"""Traffic and pedestrian impact engine (owner: P2).

Method: synthetic origin-destination trips + all-or-nothing shortest-path assignment,
run before and after the closure. Output is a RELATIVE impact index, not measured volume.
"""
from __future__ import annotations

import json
import math
import random
from collections import Counter
from functools import lru_cache

import networkx as nx

from .. import config
from ..graph import best_edge, edge_info, edge_lanes, is_demo, load_graph, path_geometry
from ..geo import haversine_m, point_segment_distance_m
from ..schemas import ClosureTarget, EdgeLoad, Facility, NetworkImpact, NetworkRequest, SegmentTraffic, TimeWindow

Edge = tuple[int, int, int]


# ---------- trips ----------
def sample_od_pairs(G: nx.MultiDiGraph, n: int = config.OD_SAMPLE_SIZE, seed: int = config.OD_SEED):
    """Origins/destinations biased to the network boundary (through traffic) and main roads."""
    rng = random.Random(seed)
    ys = [d["y"] for _, d in G.nodes(data=True)]
    xs = [d["x"] for _, d in G.nodes(data=True)]
    y0, y1, x0, x1 = min(ys), max(ys), min(xs), max(xs)
    margin_y, margin_x = (y1 - y0) * 0.15, (x1 - x0) * 0.15

    nodes, weights = [], []
    for node, d in G.nodes(data=True):
        boundary = d["y"] < y0 + margin_y or d["y"] > y1 - margin_y or d["x"] < x0 + margin_x or d["x"] > x1 - margin_x
        main = any(edge_info(G, (node, v, k))["road_class"] in ("primary", "secondary")
                   for _, v, k in G.out_edges(node, keys=True))
        nodes.append(node)
        weights.append(1.0 + 3.0 * boundary + 2.0 * main)

    pairs = []
    while len(pairs) < n:
        o, dst = rng.choices(nodes, weights, k=2)
        if o != dst:
            pairs.append((o, dst))
    return pairs


def assign(G: nx.MultiDiGraph, pairs) -> tuple[dict, Counter, dict]:
    """All-or-nothing assignment. Returns {pair: travel_time_s}, edge usage counts and {pair: node path}."""
    by_origin: dict[int, list[int]] = {}
    for o, d in pairs:
        by_origin.setdefault(o, []).append(d)
    times, usage, routes = {}, Counter(), {}
    for o, dests in by_origin.items():
        dist, paths = nx.single_source_dijkstra(G, o, weight="travel_time")
        for d in dests:
            if d not in dist:
                times[(o, d)] = math.inf
                continue
            times[(o, d)] = dist[d]
            path = routes[(o, d)] = paths[d]
            for a, b in zip(path, path[1:]):
                usage[best_edge(G, a, b)] += 1
    return times, usage, routes


def _usage(G: nx.MultiDiGraph, routes: dict, pairs) -> Counter:
    usage = Counter()
    for p in pairs:
        path = routes.get(p) or []
        for a, b in zip(path, path[1:]):
            usage[best_edge(G, a, b)] += 1
    return usage


# ---------- study area ----------
def study_area(G: nx.MultiDiGraph, edges: list[Edge]) -> frozenset[int]:
    """Nodes to route on: within STUDY_RADIUS_M of the works, plus however far the works themselves spread.
    On the small demo grid this is every node."""
    nodes = {n for e in edges for n in e[:2]}
    lat = sum(G.nodes[n]["y"] for n in nodes) / len(nodes)
    lng = sum(G.nodes[n]["x"] for n in nodes) / len(nodes)
    step_lat = config.STUDY_GRID_M / 111_320
    step_lng = step_lat / math.cos(math.radians(lat))
    lat, lng = round(round(lat / step_lat) * step_lat, 6), round(round(lng / step_lng) * step_lng, 6)
    reach = max(haversine_m(lat, lng, G.nodes[n]["y"], G.nodes[n]["x"]) for n in nodes)
    radius = config.STUDY_RADIUS_M + math.ceil(reach / config.STUDY_GRID_M) * config.STUDY_GRID_M
    return _area_nodes(lat, lng, radius)


@lru_cache(maxsize=16)
def _area_nodes(lat: float, lng: float, radius_m: float) -> frozenset[int]:
    G = load_graph()
    near = [n for n, d in G.nodes(data=True) if haversine_m(lat, lng, d["y"], d["x"]) <= radius_m]
    # Largest strongly connected part, so every sampled trip has a route before the closure.
    return frozenset(max(nx.strongly_connected_components(G.subgraph(near)), key=len))


@lru_cache(maxsize=8)
def _baseline(area: frozenset[int]):
    A = load_graph().subgraph(area).copy()
    pairs = sample_od_pairs(A)
    return A, pairs, *assign(A, pairs)


# ---------- closure ----------
def _closed_edges(G: nx.MultiDiGraph, edges: list[Edge], direction: str) -> list[Edge]:
    closed = list(edges)
    if direction == "both":
        for u, v, _ in edges:
            if G.has_edge(v, u) and (rev := best_edge(G, v, u)) not in closed:
                closed.append(rev)
    return closed


def _lanes(G, e: Edge) -> int:
    return edge_lanes(G, e)


def _blocks_traffic(G, e: Edge, targets: list[ClosureTarget], lanes_closed: int) -> bool:
    """True when no vehicle lane is left open on this edge."""
    return ClosureTarget.full in targets or (ClosureTarget.traffic_lane in targets and lanes_closed >= _lanes(G, e))


def is_full_closure(G: nx.MultiDiGraph, edges: list[Edge], targets: list[ClosureTarget], lanes_closed: int) -> bool:
    """Full road closure = every closed edge is blocked to vehicles. Anything less is a work zone."""
    return bool(edges) and all(_blocks_traffic(G, e, targets, lanes_closed) for e in edges)


# One segment's routing inputs, hashable for the cache: (edges, targets, direction, lanes_closed).
SegmentKey = tuple[tuple[Edge, ...], tuple[ClosureTarget, ...], str, int]


def merge_segments(G: nx.MultiDiGraph, segments: tuple[SegmentKey, ...]) -> dict[Edge, float | None]:
    """Combine every segment into one effect per edge: None = removed, else a travel-time factor.
    Where segments overlap, the stronger effect wins (removed > more lanes closed)."""
    effect: dict[Edge, float | None] = {}
    for edges, targets, direction, lanes_closed in segments:
        if ClosureTarget.full not in targets and ClosureTarget.traffic_lane not in targets:
            continue  # bike lane / footpath only: no change for cars
        for e in _closed_edges(G, list(edges), direction):
            if _blocks_traffic(G, e, list(targets), lanes_closed):
                effect[e] = None
            elif e not in effect or effect[e] is not None:
                factor = config.LANE_CLOSURE_TIME_FACTOR.get(lanes_closed, 2.0)
                effect[e] = max(factor, effect.get(e) or 0.0)
    return effect


def apply_closure(G: nx.MultiDiGraph, effect: dict[Edge, float | None]):
    """Return a modified copy of G for vehicle routing."""
    H = G.copy()
    for e, factor in effect.items():
        if not H.has_edge(*e):
            continue  # outside the study area
        if factor is None:
            H.remove_edge(*e)
        else:
            H.edges[e]["travel_time"] *= factor
    return H


def pedestrian_detour_m(G: nx.MultiDiGraph, edges: list[Edge]) -> float | None:
    """Extra walking distance when the footpath along this path is closed (undirected walk graph).
    TODO(P2): use a real walk network (osmnx network_type='walk') once data is fetched."""
    start, end = edges[0][0], edges[-1][1]
    if start == end:
        return None
    W = nx.Graph()
    for a, b, d in G.edges(data=True):
        if not W.has_edge(a, b) or d["length"] < W[a][b]["length"]:
            W.add_edge(a, b, length=d["length"])
    direct = 0.0
    for u, v, _ in edges:
        if W.has_edge(u, v):
            direct += W[u][v]["length"]
            W.remove_edge(u, v)
    try:
        detour = nx.shortest_path_length(W, start, end, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):  # no other way round, or the path leaves the study area
        return None
    return round(detour - direct, 1)


def time_factor(window: TimeWindow, custom_hours: tuple[int, int] | None = None) -> float:
    if window != TimeWindow.custom or not custom_hours:
        return config.TIME_WINDOW_FACTOR.get(window.value, 1.0)
    start, end = custom_hours
    overlaps_peak = any(start < pe and end > ps for ps, pe in config.PEAK_HOURS)
    return config.PEAK_FACTOR if overlaps_peak else config.OFFPEAK_FACTOR


# ---------- facilities ----------
def load_facilities() -> list[Facility]:
    f = config.DATA_DIR / "facilities.json"  # written by scripts/fetch_osm.py
    if f.exists():
        return [Facility(**x) for x in json.loads(f.read_text())]
    lat, lng = config.DEMO_CENTER
    return [Facility(name="Demo hospital (placeholder position)", kind="hospital", lat=lat + 0.0027, lng=lng + 0.0051)]


def _near(f: Facility, geometries: list[list[tuple[float, float]]]) -> bool:
    return any(point_segment_distance_m(f.lat, f.lng, a, b) <= config.FACILITY_ALERT_RADIUS_M
               for geom in geometries for a, b in zip(geom, geom[1:]))


def facilities_near(works: list[list[tuple[float, float]]], detours: list[list[tuple[float, float]]],
                    facilities: list[Facility]) -> list[Facility]:
    """Facilities next to the works themselves (access blocked or narrowed) or on a detour street.
    'works' wins when both apply: it is the more direct impact."""
    hits = []
    for f in facilities:
        if _near(f, works):
            hits.append(f.model_copy(update={"near": "works"}))
        elif _near(f, detours):
            hits.append(f.model_copy(update={"near": "detour"}))
    return hits


# ---------- entry point ----------
@lru_cache(maxsize=128)
def _routing_impact(segments: tuple[SegmentKey, ...], area: frozenset[int]):
    """Expensive part, cached by the routing-relevant fields only."""
    A, pairs, base_times, base_usage, base_routes = _baseline(area)
    effect = merge_segments(load_graph(), segments)
    H = apply_closure(A, effect)

    # Affected = the route used a closed or slowed street. Closures only make streets slower or remove them,
    # so every other trip's route is still its shortest: only affected trips are re-routed.
    def uses_works(p) -> bool:
        path = base_routes.get(p) or []
        return any(best_edge(A, a, b) in effect for a, b in zip(path, path[1:]))
    affected = [p for p in pairs if uses_works(p)]
    times, _, routes = assign(H, affected)
    new_times, new_routes = {**base_times, **times}, {**base_routes, **routes}

    # Same node path but slower = stayed in the work zone; anything else took (or has no) other route.
    slowed = sum(1 for p in affected if new_routes.get(p) == base_routes.get(p))
    extras = [min(new_times[p] - base_times[p], 3600) for p in affected]
    base_aff, new_aff = _usage(A, base_routes, affected), _usage(H, new_routes, affected)
    new_usage = base_usage - base_aff + new_aff
    loads = []
    for e, cnt in new_aff.items():
        diff = cnt - base_aff.get(e, 0)
        share = diff / len(affected)
        if diff > 0 and share >= config.LOAD_REPORT_THRESHOLD and e not in effect:
            info = edge_info(A, e)
            loads.append(EdgeLoad(edge=e, road_name=info["road_name"], delta=round(share, 3), geometry=info["geometry"]))
    loads.sort(key=lambda x: x.delta, reverse=True)
    return {
        "affected_pct": len(affected) / len(pairs),
        "rerouted_pct": (len(affected) - slowed) / len(pairs),
        "slowed_pct": slowed / len(pairs),
        "usage": new_usage,  # read-only: this dict is cached
        "n_trips": len(pairs),
        "area": A,
        "avg_extra_s": sum(extras) / len(extras) if extras else 0.0,
        "max_extra_s": max(extras) if extras else 0.0,
        "loads": loads[:25],
    }


def _segment_traffic(G, key: SegmentKey, closed: list[Edge], usage: Counter, n_trips: int) -> SegmentTraffic:
    """How many trips still drive through this segment, and how much slower (its own settings only)."""
    own = merge_segments(G, (key,))
    factors = [own.get(e, 1.0) for e in closed]
    if factors and all(f is None for f in factors):
        return SegmentTraffic(through_trips_pct=0.0, slowdown_factor=None)
    through = max((usage.get(e, 0) for e in closed), default=0)  # busiest edge: trips on any part of the segment
    return SegmentTraffic(through_trips_pct=round(through / n_trips, 3),
                          slowdown_factor=max((f for f in factors if f is not None), default=1.0))


def network_impact(req: NetworkRequest, custom_hours: tuple[int, int] | None = None) -> NetworkImpact:
    G = load_graph()
    keys = {
        seg.id: (tuple(tuple(e) for e in seg.edges), tuple(sorted(set(seg.targets), key=lambda t: t.value)),
                 seg.direction, seg.lanes_closed)
        for seg in req.segments
    }
    area = study_area(G, [tuple(e) for seg in req.segments for e in seg.edges])
    r = _routing_impact(tuple(sorted(keys.values())), area)  # segment order and ids don't change routing
    tf = time_factor(req.time_window, custom_hours)  # cheap: applied after the cached routing
    detours = [d for edges, targets, _, _ in keys.values() if ClosureTarget.footpath in targets
               if (d := pedestrian_detour_m(r["area"], list(edges))) is not None]
    works = [path_geometry(G, list(k[0])) for k in keys.values()]
    facilities = facilities_near(works, [l.geometry for l in r["loads"]], load_facilities())
    closed = {sid: _closed_edges(G, list(k[0]), k[2]) for sid, k in keys.items()}
    return NetworkImpact(
        affected_trips_pct=round(r["affected_pct"], 3),
        avg_extra_min=round(r["avg_extra_s"] / 60 * tf, 2),
        max_extra_min=round(r["max_extra_s"] / 60 * tf, 2),
        time_factor=tf,
        full_closure={sid: is_full_closure(G, closed[sid], list(k[1]), k[3]) for sid, k in keys.items()},
        rerouted_trips_pct=round(r["rerouted_pct"], 3),
        slowed_trips_pct=round(r["slowed_pct"], 3),
        segment_traffic={sid: _segment_traffic(G, k, closed[sid], r["usage"], r["n_trips"])
                         for sid, k in keys.items()},
        load_increase=r["loads"],
        ped_detour_m=max(detours) if detours else None,  # the longest walking detour of any closed footpath
        sensitive_facilities=facilities,
        is_demo_data=is_demo(),
    )
