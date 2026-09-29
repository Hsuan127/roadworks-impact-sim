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
from ..graph import edge_info, has_walk_graph, is_demo, load_graph, load_walk_graph
from ..geo import haversine_m, point_segment_distance_m
from . import capacity, routing
from ..schemas import AadtRef, ClosureTarget, EdgeLoad, Facility, NetworkImpact, NetworkRequest, TimeWindow

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


def _best_edge(G: nx.MultiDiGraph, u: int, v: int) -> Edge:
    return routing.resolve_edge(G, u, v)


@lru_cache(maxsize=1)
def _baseline() -> routing.Baseline:
    G = load_graph()
    return routing.build_baseline(G, sample_od_pairs(G))


# ---------- closure ----------
def _norm_name(value) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return value.strip().upper() if isinstance(value, str) else None


@lru_cache(maxsize=256)
def opposite_carriageway(edge: Edge) -> Edge | None:
    """The other direction of travel for a divided road.

    `G.has_edge(v, u)` is not enough. Flemington Road at the demo site is a divided arterial that
    OSM models as two separate one-way ways with different node pairs about 20 m apart, so the
    reverse lookup finds nothing and a "both directions" closure would silently shut only one
    carriageway and halve the modelled impact. Verified on the fetched graph: the demo edge has no
    (v, u) counterpart.

    Match on: same road name, roughly opposite bearing, midpoint nearby. Nearest wins.
    """
    G = load_graph()
    u, v, _ = edge
    if G.has_edge(v, u):
        return routing.resolve_edge(G, v, u)

    d = G.edges[edge]
    name = _norm_name(d.get("name"))
    if name is None:
        return None
    bearing = d.get("bearing")
    pts = edge_info(G, edge)["geometry"]
    mlat, mlng = (pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2

    best, best_dist = None, math.inf
    for a, b, k, od in G.edges(keys=True, data=True):
        if (a, b, k) == edge or _norm_name(od.get("name")) != name:
            continue
        ob = od.get("bearing")
        if bearing is not None and ob is not None:
            diff = abs((ob - bearing + 180) % 360 - 180)
            if diff < 180 - config.OPPOSITE_BEARING_TOLERANCE_DEG:
                continue
        opts = edge_info(G, (a, b, k))["geometry"]
        olat, olng = (opts[0][0] + opts[-1][0]) / 2, (opts[0][1] + opts[-1][1]) / 2
        dist = haversine_m(mlat, mlng, olat, olng)
        if dist < best_dist and dist <= config.OPPOSITE_CARRIAGEWAY_MAX_M:
            best, best_dist = (a, b, k), dist
    return best


def _closed_edges(G: nx.MultiDiGraph, edge: Edge, direction: str) -> list[Edge]:
    edges = [edge]
    if direction == "both":
        other = opposite_carriageway(edge)
        if other is not None:
            edges.append(other)
    return edges


def _lanes(G, e: Edge) -> int:
    try:
        return int(str(edge_info(G, e)["lanes"]).split(";")[0])
    except (TypeError, ValueError):
        return 1


def closure_mods(G: nx.MultiDiGraph, edges: list[Edge], targets: list[ClosureTarget],
                 lanes_closed: int) -> routing.Mods:
    """Describe the closure as an edge -> new-cost table (None = unusable).

    Replaces the old `G.copy()`, which deep-copied a 10 000-edge MultiDiGraph on every uncached
    request just to change one or two travel times.
    """
    if not (ClosureTarget.full in targets or ClosureTarget.traffic_lane in targets):
        return {}  # bike lane / footpath only: no change for cars
    mods: routing.Mods = {}
    for e in edges:
        if ClosureTarget.full in targets or lanes_closed >= _lanes(G, e):
            mods[e] = None
        else:
            factor = config.LANE_CLOSURE_TIME_FACTOR.get(lanes_closed, 4.5)
            mods[e] = G.edges[e]["travel_time"] * factor
    return mods


def _nearest_walk_node(W: nx.Graph, lat: float, lng: float) -> int | None:
    best, best_d = None, math.inf
    for n, d in W.nodes(data=True):
        if "y" not in d:
            continue
        dist = haversine_m(lat, lng, d["y"], d["x"])
        if dist < best_d:
            best, best_d = n, dist
    return best


def pedestrian_detour_m(edge: Edge) -> float | None:
    """Extra walking distance when the footpath along this edge is closed.

    Routes on the real walk network when scripts/fetch_osm.py has been run (footways, laneways and
    crossings included). Without it, falls back to the drive network collapsed to undirected, where
    pedestrians can only use road centrelines and the answer is an over-estimate -- see
    ped_detour_basis on the response.
    """
    G = load_graph()
    W = load_walk_graph()
    pts = edge_info(G, edge)["geometry"]
    (alat, alng), (blat, blng) = pts[0], pts[-1]

    a = _nearest_walk_node(W, alat, alng)
    b = _nearest_walk_node(W, blat, blng)
    if a is None or b is None or a == b or a not in W or b not in W:
        return None
    try:
        direct = nx.shortest_path_length(W, a, b, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None

    # Remove the walk links that run alongside the closed carriageway.
    doomed = [(x, y) for x, y, d in W.edges(data=True)
              if any(point_segment_distance_m(W.nodes[x]["y"], W.nodes[x]["x"], p, q) <= config.WALK_BUFFER_M
                     and point_segment_distance_m(W.nodes[y]["y"], W.nodes[y]["x"], p, q) <= config.WALK_BUFFER_M
                     for p, q in zip(pts, pts[1:]))]
    if not doomed:
        return None
    W2 = W.copy()
    W2.remove_edges_from(doomed)
    try:
        detour = nx.shortest_path_length(W2, a, b, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    return round(max(detour - direct, 0.0), 1)


def ped_detour_basis() -> str:
    return "footway" if has_walk_graph() else "street_centreline"


def volume_window(window: TimeWindow, custom_hours: tuple[int, int] | None = None) -> str:
    """Which hourly-volume profile applies. This is how time of day reaches the model now.

    A night closure is milder because fewer vehicles per hour meet the reduced capacity, not
    because the answer gets multiplied by 0.3. Custom hours that touch a peak get the peak profile.
    """
    if window != TimeWindow.custom or not custom_hours:
        return window.value
    start, end = custom_hours
    if end <= start:  # window wraps past midnight, e.g. 20:00-05:00
        spans = [(start, 24), (0, end)]
    else:
        spans = [(start, end)]
    overlaps_peak = any(s < pe and e > ps for s, e in spans for ps, pe in config.PEAK_HOURS)
    return "peak" if overlaps_peak else "custom"


def time_factor(window: TimeWindow, custom_hours: tuple[int, int] | None = None) -> float:
    """Transparency only: how busy this window is relative to a normal daytime hour.

    Reported so the UI can explain why a night plan looks milder. It is NOT multiplied into the
    delay -- the volume it describes has already been fed through the capacity curve.
    """
    key = volume_window(window, custom_hours)
    day = config.AADT_HOURLY_FRACTION["day"]
    return round(config.AADT_HOURLY_FRACTION.get(key, day) / day, 3)


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
@lru_cache(maxsize=512)
def _routing_impact(edge: Edge, targets: tuple[ClosureTarget, ...], direction: str, lanes_closed: int):
    """Expensive part, cached by the routing-relevant fields only.

    Three disjoint buckets, no clamping:
      * unreachable - had a route before, has none now
      * rerouted    - still reachable, but takes a different path
      * unchanged   - everything else

    Delay statistics are computed over REROUTED trips only. The old code counted a trip as
    "affected" only when its travel time rose by more than one second, which on a real dense
    network reported 0.0% for a full arterial closure: without a capacity constraint, diverting to
    the parallel street costs almost nothing. "Did this trip have to change route" is a claim this
    model can actually support.
    """
    G = load_graph()
    base = _baseline()
    closed = _closed_edges(G, edge, direction)
    mods = closure_mods(G, closed, list(targets), lanes_closed)

    assign_fn = routing.assign_incremental if config.USE_INCREMENTAL_ASSIGNMENT else routing.assign_full
    times, paths, usage_delta, _ = assign_fn(G, base, mods)

    routable = [i for i in range(base.n) if base.times[i] != math.inf]
    unreachable = [i for i in routable if times[i] == math.inf]
    rerouted = [i for i in routable if times[i] != math.inf and paths[i] != base.paths[i]]
    extras = [times[i] - base.times[i] for i in rerouted]

    n_base = max(len(routable), 1)
    n_rer = max(len(rerouted), 1)
    loads = []
    for e, diff in usage_delta.items():
        share = diff / n_rer
        if diff > 0 and share >= config.LOAD_REPORT_THRESHOLD and e not in closed:
            info = edge_info(G, e)
            loads.append(EdgeLoad(edge=e, road_name=info["road_name"], delta=round(share, 3),
                                  geometry=info["geometry"], aadt=_aadt_ref(e)))
    loads.sort(key=lambda x: x.delta, reverse=True)
    loads = loads[:25]
    return {
        "rerouted_pct": len(rerouted) / n_base,
        "unreachable_pct": len(unreachable) / n_base,
        "detour_extra_s": {"avg": sum(extras) / len(extras) if extras else 0.0,
                           "max": max(extras) if extras else 0.0},
        "loads": loads,
        "paths": paths,
        "base_times": base.times,
        "times": times,
        "rerouted": rerouted,
        "routable": routable,
        "closed_edges": closed,
        "closed_geometry": edge_info(G, edge)["geometry"],
    }


def _aadt_ref(edge: Edge) -> AadtRef | None:
    rec = capacity.aadt_for(edge)
    return AadtRef(**rec) if rec else None


def _congestion_delays(G, r: dict, targets: list[ClosureTarget], lanes_closed: int,
                       window: str) -> dict[int, float]:
    """Extra seconds per trip caused by streets getting busier, not by taking a longer way round.

    Applies a BPR volume-delay curve per edge (see impact/capacity.py) and charges each trip for
    the edges its post-closure path actually uses. Note that a trip which did NOT reroute still
    pays, if its route runs along a street the diverted traffic landed on -- which is usually who
    suffers most, and is invisible to a pure shortest-path diff.
    """
    if not (ClosureTarget.full in targets or ClosureTarget.traffic_lane in targets):
        return {}  # bike lane / footpath only: no vehicle capacity is lost, so no vehicle delay
    closed = r["closed_edges"]
    fully = ClosureTarget.full in targets
    lanes_here = max((_lanes(G, e) for e in closed), default=1)
    if not fully and lanes_closed >= lanes_here:
        fully = True  # closing every lane IS a full closure, whatever the target says
    diverted = capacity.diverted_vehicles_ph(closed, window, fully, lanes_here, lanes_closed)

    per_edge: dict[Edge, float] = {}
    for e in closed:
        if not fully and lanes_closed < _lanes(G, e):
            per_edge[e] = capacity.edge_delay_delta_s(
                e, G.edges[e]["travel_time"], _lanes(G, e), window, lanes_closed=lanes_closed)
    for load in r["loads"]:
        e = tuple(load.edge)
        per_edge[e] = capacity.edge_delay_delta_s(
            e, G.edges[e]["travel_time"], _lanes(G, e), window,
            added_vehicles_ph=diverted * load.delta)

    if not per_edge:
        return {}
    out: dict[int, float] = {}
    for i in r["routable"]:
        extra = sum(per_edge.get(e, 0.0) for e in r["paths"][i])
        if extra:
            out[i] = extra
    return out


def network_impact(req: NetworkRequest) -> NetworkImpact:
    G = load_graph()
    edge = tuple(req.edge)
    targets = sorted(set(req.targets), key=lambda t: t.value)
    r = _routing_impact(edge, tuple(targets), req.direction, req.lanes_closed)
    tf = time_factor(req.time_window, req.custom_hours)  # reported, not multiplied in
    window = volume_window(req.time_window, req.custom_hours)
    congestion = _congestion_delays(G, r, targets, req.lanes_closed, window)
    # Total delay per trip = longer way round + busier streets. Both in seconds.
    detour_extra = {i: r["times"][i] - r["base_times"][i] for i in r["rerouted"]}
    totals = [detour_extra.get(i, 0.0) + congestion.get(i, 0.0)
              for i in set(detour_extra) | set(congestion)]
    avg_s = sum(totals) / len(totals) if totals else 0.0
    max_s = max(totals) if totals else 0.0
    n_base = max(len(r["routable"]), 1)
    delayed_pct = len(totals) / n_base

    ped = pedestrian_detour_m(edge) if ClosureTarget.footpath in req.targets else None
    facilities = facilities_near([l.geometry for l in r["loads"]], load_facilities())
    return NetworkImpact(
        affected_trips_pct=round(max(r["rerouted_pct"], delayed_pct), 3),
        rerouted_trips_pct=round(r["rerouted_pct"], 3),
        unreachable_trips_pct=round(r["unreachable_pct"], 3),
        avg_extra_min=round(avg_s / 60, 2),
        max_extra_min=round(max_s / 60, 2),
        closed_aadt=_aadt_ref(edge),
        time_factor=tf,
        closed_geometry=r["closed_geometry"],
        closed_edges=list(r["closed_edges"]),
        load_increase=r["loads"],
        ped_detour_m=ped,
        ped_detour_basis=ped_detour_basis() if ped is not None else None,
        sensitive_facilities=facilities,
        is_demo_data=is_demo(),
    )
