"""Shortest-path assignment for the network impact engine (owner: P2).

Method: synthetic origin-destination trips, all-or-nothing assignment on shortest travel time,
run before and after the closure. The result is a RELATIVE impact index, not measured volume.

The one piece of real cleverness here is `assign_incremental`. See its docstring for why it is
exact rather than an approximation.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import networkx as nx

Edge = tuple[int, int, int]
NodePair = tuple[int, int]

# A modification table maps an edge to its new travel time, or to None meaning "unusable".
Mods = dict[Edge, "float | None"]


def resolve_edge(G: nx.MultiDiGraph, u: int, v: int, mods: Mods | None = None) -> Edge | None:
    """Pick which parallel edge a u->v step actually uses, under `mods`.

    Ties are broken by key so the answer is deterministic. The original code re-derived this
    separately on the baseline and closed graphs with no tie-break, so a closure that changed which
    parallel edge was cheapest made the before/after usage counters disagree about the same step
    and manufacture phantom load.
    """
    best, best_cost = None, math.inf
    for key, attr in G[u][v].items():
        cost = attr["travel_time"]
        if mods is not None and (u, v, key) in mods:
            cost = mods[(u, v, key)]
            if cost is None:
                continue
        if cost < best_cost or (cost == best_cost and best is not None and key < best[2]):
            best, best_cost = (u, v, key), cost
    return best


def make_weight(mods: Mods):
    """NetworkX edge-weight callable over a MultiDiGraph.

    NetworkX hands the whole parallel-edge dict for multigraphs; returning None means "no usable
    edge here", which is how a closure is expressed without copying the graph. The previous
    implementation deep-copied an 8000-edge MultiDiGraph on every uncached request.
    """
    if not mods:
        def plain(u, v, keydict):
            return min(a["travel_time"] for a in keydict.values())
        return plain

    def weight(u, v, keydict):
        best = None
        for key, attr in keydict.items():
            cost = mods.get((u, v, key), attr["travel_time"]) if (u, v, key) in mods else attr["travel_time"]
            if cost is None:
                continue
            if best is None or cost < best:
                best = cost
        return best

    return weight


def path_edges(G: nx.MultiDiGraph, nodes: list[int], mods: Mods | None = None) -> tuple[Edge, ...]:
    out = []
    for a, b in zip(nodes, nodes[1:]):
        e = resolve_edge(G, a, b, mods)
        if e is not None:
            out.append(e)
    return tuple(out)


@dataclass(frozen=True)
class Baseline:
    """Everything about the no-closure state, indexed by trip position.

    `trips_by_edge` is the inverted index that makes `assign_incremental` cheap: it answers
    "which trips would notice if this edge changed?" without touching the graph.
    """

    pairs: tuple[NodePair, ...]
    times: tuple[float, ...]
    paths: tuple[tuple[Edge, ...], ...]
    usage: Counter
    trips_by_edge: dict[Edge, tuple[int, ...]]

    @property
    def n(self) -> int:
        return len(self.pairs)


def build_baseline(G: nx.MultiDiGraph, pairs) -> Baseline:
    """Full all-or-nothing assignment, recording each trip's path so closures can be diffed."""
    by_origin: dict[int, list[int]] = {}
    for i, (o, d) in enumerate(pairs):
        by_origin.setdefault(o, []).append(i)

    times: list[float] = [math.inf] * len(pairs)
    paths: list[tuple[Edge, ...]] = [()] * len(pairs)
    usage: Counter = Counter()
    index: dict[Edge, list[int]] = {}

    for o, trip_ids in by_origin.items():
        dist, node_paths = nx.single_source_dijkstra(G, o, weight=make_weight({}))
        for i in trip_ids:
            d = pairs[i][1]
            if d not in dist:
                continue
            times[i] = dist[d]
            edges = path_edges(G, node_paths[d])
            paths[i] = edges
            for e in edges:
                usage[e] += 1
                index.setdefault(e, []).append(i)

    return Baseline(
        pairs=tuple(pairs),
        times=tuple(times),
        paths=tuple(paths),
        usage=usage,
        trips_by_edge={e: tuple(v) for e, v in index.items()},
    )


def assign_incremental(G: nx.MultiDiGraph, base: Baseline, mods: Mods):
    """Re-route only the trips whose baseline path touched a modified edge.

    Why this is EXACT, not an approximation. A closure only ever increases an edge's cost or makes
    it unusable (cost -> infinity); no cost ever falls. Take a trip whose baseline shortest path P
    uses none of the modified edges. Then cost_new(P) == cost_base(P), and for every alternative
    path Q, cost_new(Q) >= cost_base(Q) >= cost_base(P) == cost_new(P). So P is still a shortest
    path and still costs the same: the trip's travel time and its edge usage are unchanged.

    Only trips that actually used a modified edge can change, and `trips_by_edge` lists exactly
    those. On a real graph this turns ~400 shortest-path searches into a few dozen.

    Returns (times, paths, usage_delta, dirty) where times/paths are full trip-indexed tuples and
    usage_delta is the change in edge usage relative to the baseline.
    """
    dirty: set[int] = set()
    for e in mods:
        dirty.update(base.trips_by_edge.get(e, ()))

    times = list(base.times)
    paths = list(base.paths)
    delta: Counter = Counter()

    if not dirty:
        return tuple(times), tuple(paths), delta, dirty

    weight = make_weight(mods)
    by_origin: dict[int, list[int]] = {}
    for i in dirty:
        by_origin.setdefault(base.pairs[i][0], []).append(i)

    for o, trip_ids in by_origin.items():
        # One full tree is worth it when several trips share an origin; otherwise a bidirectional
        # search explores a fraction of the graph.
        if len(trip_ids) >= 4:
            dist, node_paths = nx.single_source_dijkstra(G, o, weight=weight)
            for i in trip_ids:
                d = base.pairs[i][1]
                _apply(G, base, mods, times, paths, delta, i,
                       dist.get(d, math.inf), node_paths.get(d))
        else:
            for i in trip_ids:
                d = base.pairs[i][1]
                try:
                    cost, nodes = nx.bidirectional_dijkstra(G, o, d, weight=weight)
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    cost, nodes = math.inf, None
                _apply(G, base, mods, times, paths, delta, i, cost, nodes)

    return tuple(times), tuple(paths), delta, dirty


def _apply(G, base: Baseline, mods: Mods, times, paths, delta, i, cost, nodes) -> None:
    for e in base.paths[i]:
        delta[e] -= 1
    if nodes is None or cost == math.inf:
        times[i] = math.inf
        paths[i] = ()
        return
    times[i] = cost
    edges = path_edges(G, nodes, mods)
    paths[i] = edges
    for e in edges:
        delta[e] += 1


def assign_full(G: nx.MultiDiGraph, base: Baseline, mods: Mods):
    """Reference implementation: re-route every trip. Kept as the oracle for the equivalence test
    and as an escape hatch (config.USE_INCREMENTAL_ASSIGNMENT)."""
    weight = make_weight(mods)
    times = [math.inf] * base.n
    paths: list[tuple[Edge, ...]] = [()] * base.n
    delta: Counter = Counter(base.usage)
    delta.subtract(base.usage)  # zeroed, keeps the same key space

    by_origin: dict[int, list[int]] = {}
    for i, (o, _) in enumerate(base.pairs):
        by_origin.setdefault(o, []).append(i)

    new_usage: Counter = Counter()
    for o, trip_ids in by_origin.items():
        dist, node_paths = nx.single_source_dijkstra(G, o, weight=weight)
        for i in trip_ids:
            d = base.pairs[i][1]
            if d not in dist:
                continue
            times[i] = dist[d]
            edges = path_edges(G, node_paths[d], mods)
            paths[i] = edges
            for e in edges:
                new_usage[e] += 1

    diff: Counter = Counter()
    for e in set(new_usage) | set(base.usage):
        d = new_usage[e] - base.usage[e]
        if d:
            diff[e] = d
    dirty = {i for i in range(base.n) if paths[i] != base.paths[i]}
    return tuple(times), tuple(paths), diff, dirty
