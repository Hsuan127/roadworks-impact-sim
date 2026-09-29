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
from ..graph import edge_info, is_demo, load_graph
from ..geo import haversine_m, point_segment_distance_m
from ..schemas import ClosureTarget, EdgeLoad, Facility, NetworkImpact, NetworkRequest, TimeWindow

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


def _best_edge(G: nx.MultiDiGraph, u: int, v: int, weight: str = "travel_time") -> Edge:
    k = min(G[u][v], key=lambda key: G[u][v][key].get(weight, math.inf))
    return (u, v, k)


def assign(G: nx.MultiDiGraph, pairs) -> tuple[dict, Counter]:
    """All-or-nothing assignment. Returns {pair: travel_time_s} and edge usage counts."""
    by_origin: dict[int, list[int]] = {}
    for o, d in pairs:
        by_origin.setdefault(o, []).append(d)
    times, usage = {}, Counter()
    for o, dests in by_origin.items():
        dist, paths = nx.single_source_dijkstra(G, o, weight="travel_time")
        for d in dests:
            if d not in dist:
                times[(o, d)] = math.inf
                continue
            times[(o, d)] = dist[d]
            path = paths[d]
            for a, b in zip(path, path[1:]):
                usage[_best_edge(G, a, b)] += 1
    return times, usage


@lru_cache(maxsize=1)
def _baseline():
    G = load_graph()
    pairs = sample_od_pairs(G)
    times, usage = assign(G, pairs)
    return pairs, times, usage


# ---------- closure ----------
def _closed_edges(G: nx.MultiDiGraph, edge: Edge, direction: str) -> list[Edge]:
    u, v, k = edge
    edges = [edge]
    if direction == "both" and G.has_edge(v, u):
        edges.append(_best_edge(G, v, u))
    return edges


def _lanes(G, e: Edge) -> int:
    try:
        return int(str(edge_info(G, e)["lanes"]).split(";")[0])
    except (TypeError, ValueError):
        return 1


def apply_closure(G: nx.MultiDiGraph, edges: list[Edge], targets: list[ClosureTarget], lanes_closed: int):
    """Return a modified copy of G for vehicle routing."""
    H = G.copy()
    traffic_affected = ClosureTarget.full in targets or ClosureTarget.traffic_lane in targets
    if not traffic_affected:
        return H  # bike lane / footpath only: no change for cars
    for e in edges:
        if ClosureTarget.full in targets or lanes_closed >= _lanes(G, e):
            H.remove_edge(*e)
        else:
            factor = config.LANE_CLOSURE_TIME_FACTOR.get(lanes_closed, 2.0)
            H.edges[e]["travel_time"] *= factor
    return H


def pedestrian_detour_m(G: nx.MultiDiGraph, edge: Edge) -> float | None:
    """Extra walking distance when the footpath along this edge is closed (undirected walk graph).
    TODO(P2): use a real walk network (osmnx network_type='walk') once data is fetched."""
    u, v, _ = edge
    W = nx.Graph()
    for a, b, d in G.edges(data=True):
        if not W.has_edge(a, b) or d["length"] < W[a][b]["length"]:
            W.add_edge(a, b, length=d["length"])
    direct = W[u][v]["length"]
    W.remove_edge(u, v)
    try:
        detour = nx.shortest_path_length(W, u, v, weight="length")
    except nx.NetworkXNoPath:
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


def facilities_near(geometries: list[list[tuple[float, float]]], facilities: list[Facility]) -> list[Facility]:
    hits = []
    for f in facilities:
        for geom in geometries:
            if any(point_segment_distance_m(f.lat, f.lng, a, b) <= config.FACILITY_ALERT_RADIUS_M
                   for a, b in zip(geom, geom[1:])):
                hits.append(f)
                break
    return hits


# ---------- entry point ----------
@lru_cache(maxsize=128)
def _routing_impact(edge: Edge, targets: tuple[ClosureTarget, ...], direction: str, lanes_closed: int):
    """Expensive part, cached by the routing-relevant fields only."""
    G = load_graph()
    pairs, base_times, base_usage = _baseline()
    closed = _closed_edges(G, edge, direction)
    H = apply_closure(G, closed, list(targets), lanes_closed)
    new_times, new_usage = assign(H, pairs)

    affected = [p for p in pairs if new_times[p] - base_times[p] > 1.0]
    extras = [min(new_times[p] - base_times[p], 3600) for p in affected]
    n_aff = max(len(affected), 1)
    loads = []
    for e, cnt in new_usage.items():
        diff = cnt - base_usage.get(e, 0)
        share = diff / n_aff
        if diff > 0 and share >= config.LOAD_REPORT_THRESHOLD and e not in closed:
            info = edge_info(G, e)
            loads.append(EdgeLoad(edge=e, road_name=info["road_name"], delta=round(share, 3), geometry=info["geometry"]))
    loads.sort(key=lambda x: x.delta, reverse=True)
    return {
        "affected_pct": len(affected) / len(pairs),
        "avg_extra_s": sum(extras) / len(extras) if extras else 0.0,
        "max_extra_s": max(extras) if extras else 0.0,
        "loads": loads[:25],
        "closed_geometry": edge_info(G, edge)["geometry"],
    }


def network_impact(req: NetworkRequest, custom_hours: tuple[int, int] | None = None) -> NetworkImpact:
    G = load_graph()
    edge = tuple(req.edge)
    r = _routing_impact(edge, tuple(sorted(req.targets, key=lambda t: t.value)), req.direction, req.lanes_closed)
    tf = time_factor(req.time_window, custom_hours)  # cheap: applied after the cached routing
    ped = pedestrian_detour_m(G, edge) if ClosureTarget.footpath in req.targets else None
    facilities = facilities_near([l.geometry for l in r["loads"]], load_facilities())
    return NetworkImpact(
        affected_trips_pct=round(r["affected_pct"], 3),
        avg_extra_min=round(r["avg_extra_s"] / 60 * tf, 2),
        max_extra_min=round(r["max_extra_s"] / 60 * tf, 2),
        time_factor=tf,
        closed_geometry=r["closed_geometry"],
        load_increase=r["loads"],
        ped_detour_m=ped,
        sensitive_facilities=facilities,
        is_demo_data=is_demo(),
    )
