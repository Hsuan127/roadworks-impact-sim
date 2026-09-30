"""Traffic and pedestrian impact engine (owner: P2).

Method: synthetic origin-destination trips + all-or-nothing shortest-path assignment, run before and
after the closure, inside a study area around the works. Which trips go where is invented; how much
traffic a road carries is not: delay comes from published VicRoads volumes through a BPR capacity
curve (impact/capacity.py), one pass, only on roads with a published count.
"""
from __future__ import annotations

import json
import math
import random
from collections import Counter
from functools import lru_cache

import networkx as nx

from .. import config
from ..graph import (
    centreline_walk_graph, edge_info, edge_lanes, has_walk_graph, is_demo, load_graph, load_walk_graph,
    path_geometry,
)
from ..geo import haversine_m, point_segment_distance_m
from ..schemas import (
    AadtRef, ClosureTarget, DelaySummary, EdgeLoad, Facility, NetworkImpact, NetworkRequest, SegmentTraffic, TimeWindow,
)
from . import capacity, routing

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
def _baseline(area: frozenset[int]) -> tuple[nx.MultiDiGraph, routing.Baseline]:
    A = load_graph().subgraph(area).copy()
    return A, routing.build_baseline(A, sample_od_pairs(A))


def demo_area() -> frozenset[int]:
    """The study area of the demo work site, so its baseline can be built before the first click."""
    from ..graph import snap
    return study_area(load_graph(), [snap(*config.DEMO_WORK_POINT)])


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


def _closed_edges(G: nx.MultiDiGraph, edges: list[Edge], direction: str) -> list[Edge]:
    closed = [tuple(e) for e in edges]
    if direction == "both":
        for e in list(closed):
            if (other := opposite_carriageway(e)) is not None and other not in closed:
                closed.append(other)
    return closed


def _lanes(G, e: Edge) -> int:
    return edge_lanes(G, e)


def _blocks_traffic(G, e: Edge, targets: list[ClosureTarget], lanes_closed: int) -> bool:
    """True when no vehicle lane is left open on this edge."""
    return ClosureTarget.full in targets or (ClosureTarget.traffic_lane in targets and lanes_closed >= _lanes(G, e))


def is_full_closure(G: nx.MultiDiGraph, edges: list[Edge], targets: list[ClosureTarget], lanes_closed: int) -> bool:
    """Full road closure = every closed edge is blocked to vehicles. Anything less is a work zone."""
    return bool(edges) and all(_blocks_traffic(G, e, targets, lanes_closed) for e in edges)


def _closes_traffic(targets) -> bool:
    return ClosureTarget.full in targets or ClosureTarget.traffic_lane in targets


# One segment's routing inputs, hashable for the cache: (edges, targets, direction, lanes_closed).
SegmentKey = tuple[tuple[Edge, ...], tuple[ClosureTarget, ...], str, int]


def merge_segments(G: nx.MultiDiGraph, segments: tuple[SegmentKey, ...]) -> dict[Edge, float | None]:
    """Combine every segment into one effect per edge: None = removed, else a travel-time factor.
    Where segments overlap, the stronger effect wins (removed > more lanes closed)."""
    effect: dict[Edge, float | None] = {}
    for edges, targets, direction, lanes_closed in segments:
        if not _closes_traffic(targets):
            continue  # bike lane / footpath only: no change for cars
        for e in _closed_edges(G, list(edges), direction):
            if _blocks_traffic(G, e, list(targets), lanes_closed):
                effect[e] = None
            elif e not in effect or effect[e] is not None:
                factor = config.LANE_CLOSURE_TIME_FACTOR.get(lanes_closed, 4.5)
                effect[e] = max(factor, effect.get(e) or 0.0)
    return effect


def closure_mods(A: nx.MultiDiGraph, effect: dict[Edge, float | None]) -> routing.Mods:
    """The effect as an edge -> new-cost table for routing (None = unusable), without copying the graph.
    Edges outside the study area are dropped: they change no route inside it."""
    return {e: None if f is None else A.edges[e]["travel_time"] * f for e, f in effect.items() if A.has_edge(*e)}


# ---------- pedestrians ----------
WALK_SNAP_MAX_M = 50  # further than this from a walk network = the works are outside it


def _nearest_walk_node(W: nx.Graph, lat: float, lng: float) -> tuple[int | None, float]:
    best, best_d = None, math.inf
    for n, d in W.nodes(data=True):
        if "y" not in d:
            continue
        dist = haversine_m(lat, lng, d["y"], d["x"])
        if dist < best_d:
            best, best_d = n, dist
    return best, best_d


def _walk_detour(W: nx.Graph, line: list[tuple[float, float]]) -> float | None:
    (a, da), (b, db) = _nearest_walk_node(W, *line[0]), _nearest_walk_node(W, *line[-1])
    if a is None or b is None or a == b or max(da, db) > WALK_SNAP_MAX_M:
        return None
    try:
        direct = nx.shortest_path_length(W, a, b, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    # Remove the walk links that run alongside the closed footpath.
    doomed = [(x, y) for x, y in W.edges()
              if any(point_segment_distance_m(W.nodes[x]["y"], W.nodes[x]["x"], p, q) <= config.WALK_BUFFER_M
                     and point_segment_distance_m(W.nodes[y]["y"], W.nodes[y]["x"], p, q) <= config.WALK_BUFFER_M
                     for p, q in zip(line, line[1:]))]
    if not doomed:
        return None
    W2 = W.copy()
    W2.remove_edges_from(doomed)
    try:
        detour = nx.shortest_path_length(W2, a, b, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):  # no other way round
        return None
    return round(max(detour - direct, 0.0), 1)


def pedestrian_detour_m(G: nx.MultiDiGraph, edges: list[Edge]) -> tuple[float, str] | None:
    """Extra walking distance when the footpath along these edges is closed, and what it was measured on.

    Uses the real walk network (footways, laneways, crossings) where the works are inside it. Outside
    it, or without it, falls back to road centrelines, where the answer is an over-estimate."""
    line = path_geometry(G, [tuple(e) for e in edges])
    if has_walk_graph() and (d := _walk_detour(load_walk_graph(), line)) is not None:
        return d, "footway"
    d = _walk_detour(centreline_walk_graph(), line)
    return (d, "street_centreline") if d is not None else None


# ---------- time of day ----------
def volume_window(window: TimeWindow, custom_hours: tuple[int, int] | None = None) -> str:
    """Which hourly-volume profile applies. This is how time of day reaches the model.

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
    if any(s < pe and e > ps for s, e in spans for ps, pe in config.PEAK_HOURS):
        # ASSUMPTION: the only measured peak is the AM one (toward the CBD); PM hours reuse it.
        return "peak"
    ns, ne = config.NIGHT_HOURS  # wraps past midnight
    if all(s >= ns or e <= ne for s, e in spans):
        return "night"  # night hours typed by hand get the measured night volumes
    return "custom"


def time_factor(window: TimeWindow, custom_hours: tuple[int, int] | None = None) -> float:
    """Transparency only: how busy this window is relative to a normal daytime hour.

    Reported so the UI can explain why a night plan looks milder. It is NOT multiplied into the
    delay -- the volume it describes has already been fed through the capacity curve.
    """
    key = volume_window(window, custom_hours)
    day = config.AADT_HOURLY_FRACTION["day"]
    return round(config.AADT_HOURLY_FRACTION.get(key, day) / day, 3)


@lru_cache(maxsize=4096)
def toward_cbd(edge: Edge) -> bool:
    """Does this directed edge point at the city? Picks the directional peak volume."""
    G = load_graph()
    pts = edge_info(G, edge)["geometry"]
    (alat, alng), (blat, blng) = pts[0], pts[-1]
    return haversine_m(blat, blng, *config.CBD_POINT) < haversine_m(alat, alng, *config.CBD_POINT)


def _aadt_ref(edge: Edge) -> AadtRef | None:
    rec = capacity.aadt_for(edge)
    return AadtRef(**rec) if rec else None


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


# ---------- routing (cached) ----------
@lru_cache(maxsize=128)
def _routing_impact(segments: tuple[SegmentKey, ...], area: frozenset[int]):
    """Expensive part, cached by the routing-relevant fields only: never by time of day.

    Every trip whose route used a closed or narrowed street lands in exactly one bucket:
      * unreachable - had a route before, has none now
      * rerouted    - still reachable, takes a different path
      * slowed      - same path, through the work zone
    """
    A, base = _baseline(area)
    effect = merge_segments(load_graph(), segments)
    mods = closure_mods(A, effect)
    assign_fn = routing.assign_incremental if config.USE_INCREMENTAL_ASSIGNMENT else routing.assign_full
    times, paths, usage_delta, _ = assign_fn(A, base, mods)

    # Closures only make streets slower or remove them, so only trips over a modified edge can change.
    affected = sorted({i for e in mods for i in base.trips_by_edge.get(e, ())})
    unreachable = [i for i in affected if math.isinf(times[i])]
    rerouted = [i for i in affected if not math.isinf(times[i]) and paths[i] != base.paths[i]]
    slowed = [i for i in affected if not math.isinf(times[i]) and paths[i] == base.paths[i]]
    # "The longer way round" at free-flow speed. The lane-closure factor only steers route choice;
    # the delay of driving through a narrowed street comes from the capacity curve, per time window.
    detour_s = {i: min(sum(A.edges[e]["travel_time"] for e in paths[i]) - base.times[i], 3600) for i in rerouted}

    n_aff, n_rer = max(len(affected), 1), max(len(rerouted), 1)
    loads, gained = [], {}
    for e, diff in usage_delta.items():
        if diff > 0 and e not in effect:
            gained[e] = diff / n_rer  # share of the diverted traffic that lands here
            if diff / n_aff >= config.LOAD_REPORT_THRESHOLD:
                info = edge_info(A, e)
                loads.append(EdgeLoad(edge=e, road_name=info["road_name"], delta=round(diff / n_aff, 3),
                                      geometry=info["geometry"], aadt=_aadt_ref(e)))
    loads.sort(key=lambda x: x.delta, reverse=True)
    usage = Counter(base.usage)
    usage.update(usage_delta)
    return {
        "area": A, "n_trips": base.n, "paths": paths, "effect": effect,
        "unreachable": unreachable, "rerouted": rerouted, "slowed": slowed, "detour_s": detour_s,
        "gained": gained, "usage": usage,  # read-only: this dict is cached
        "loads": loads[:25],
    }


# ---------- congestion (per time window, cheap) ----------
def _congestion_delays(r: dict, segments: tuple[SegmentKey, ...], window: str, formula: str = "bpr") -> dict[int, float]:
    """Extra seconds per trip caused by streets getting busier, not by taking a longer way round.

    Applies the chosen volume-delay curve (BPR or Conical) per edge (see impact/capacity.py) and charges each trip for the
    edges its post-closure path actually uses. A trip which did NOT reroute still pays if its route
    runs along a street the diverted traffic landed on -- usually who suffers most, and invisible to
    a pure shortest-path diff. Roads with no published count stay free-flow (under-stated, not invented).
    """
    G, A, effect = load_graph(), r["area"], r["effect"]
    lanes_closed_on: dict[Edge, int] = {}  # edge still open to traffic -> most lanes any segment closes there
    diverted = 0.0  # vehicles per hour that no longer fit through the works
    for edges, targets, direction, lanes_closed in segments:
        if not _closes_traffic(targets):
            continue
        closed = _closed_edges(G, list(edges), direction)
        forward = set(edges)
        # The same vehicles drive every edge of one carriageway in turn: count each carriageway once.
        for side in ([e for e in closed if e in forward], [e for e in closed if e not in forward]):
            excess = []
            for e in side:
                shut = _blocks_traffic(G, e, list(targets), lanes_closed)
                if not shut:
                    lanes_closed_on[e] = max(lanes_closed_on.get(e, 0), lanes_closed)
                if (rec := capacity.aadt_for(e)) is not None:
                    v = capacity.hourly_volume(rec["aadt"], window, toward_cbd(e))
                    left = 0 if shut else _lanes(G, e) - lanes_closed
                    excess.append(max(v - capacity.capacity_vph(left), 0.0))
            diverted += max(excess, default=0.0)

    per_edge: dict[Edge, float] = {}
    for e, lc in lanes_closed_on.items():
        if A.has_edge(*e) and effect.get(e) is not None:  # still open: a stronger overlapping closure didn't shut it
            per_edge[e] = capacity.edge_delay_delta_s(e, A.edges[e]["travel_time"], _lanes(G, e), window,
                                                      lanes_closed=lc, toward_cbd=toward_cbd(e), formula=formula)
    for e, share in r["gained"].items():
        per_edge[e] = per_edge.get(e, 0.0) + capacity.edge_delay_delta_s(
            e, A.edges[e]["travel_time"], _lanes(G, e), window, added_vehicles_ph=diverted * share,
            toward_cbd=toward_cbd(e), formula=formula)
    per_edge = {e: s for e, s in per_edge.items() if s > 0}
    if not per_edge:
        return {}
    out: dict[int, float] = {}
    for i, path in enumerate(r["paths"]):
        if extra := sum(per_edge.get(e, 0.0) for e in path):
            out[i] = extra
    return out


def _segment_traffic(G, key: SegmentKey, closed: list[Edge], usage: Counter, n_trips: int) -> SegmentTraffic:
    """How many trips still drive through this segment, and how much slower (its own settings only)."""
    own = merge_segments(G, (key,))
    factors = [own.get(e, 1.0) for e in closed]
    if factors and all(f is None for f in factors):
        return SegmentTraffic(through_trips_pct=0.0, slowdown_factor=None)
    through = max((usage.get(e, 0) for e in closed), default=0)  # busiest edge: trips on any part of the segment
    return SegmentTraffic(through_trips_pct=round(through / n_trips, 3),
                          slowdown_factor=max((f for f in factors if f is not None), default=1.0))


# ---------- entry point ----------
def network_impact(req: NetworkRequest) -> NetworkImpact:
    G = load_graph()
    keys = {
        seg.id: (tuple(tuple(e) for e in seg.edges), tuple(sorted(set(seg.targets), key=lambda t: t.value)),
                 seg.direction, seg.lanes_closed)
        for seg in req.segments
    }
    segments = tuple(sorted(keys.values()))  # segment order and ids don't change routing
    area = study_area(G, [tuple(e) for seg in req.segments for e in seg.edges])
    r = _routing_impact(segments, area)
    window = volume_window(req.time_window, req.custom_hours)  # cheap: applied after the cached routing
    # Every curve is one cheap pass over the cached routing: compute all three so the planner sees how
    # much the answer depends on the curve, and headline the one they chose.
    by_formula = {f: _congestion_delays(r, segments, window, f) for f in capacity.FORMULAS}
    congestion = by_formula[req.delay_formula]

    # Trips that kept their route but drive slower: through the work zone, or on a street that took
    # diverted traffic. Cut-off trips are affected too, but have no delay to report.
    unreachable, rerouted = set(r["unreachable"]), set(r["rerouted"])
    slowed = (set(r["slowed"]) | set(congestion)) - rerouted - unreachable

    def delays(c: dict[int, float]) -> list[float]:
        return [r["detour_s"].get(i, 0.0) + c.get(i, 0.0) for i in rerouted | slowed]

    def summary(d: list[float]) -> DelaySummary:
        return DelaySummary(avg_extra_min=round(sum(d) / len(d) / 60, 2) if d else 0.0,
                            max_extra_min=round(max(d) / 60, 2) if d else 0.0)

    delayed = delays(congestion)
    n = r["n_trips"]

    detours = [d for edges, targets, _, _ in keys.values() if ClosureTarget.footpath in targets
               if (d := pedestrian_detour_m(G, list(edges))) is not None]
    longest = max(detours, default=None)  # the longest walking detour of any closed footpath
    works = [path_geometry(G, list(k[0])) for k in keys.values()]
    facilities = facilities_near(works, [l.geometry for l in r["loads"]], load_facilities())
    closed = {sid: _closed_edges(G, list(k[0]), k[2]) for sid, k in keys.items()}
    # The study area is one strongly connected part of the network; a closure off it changes no route here.
    changes_routing = {sid for sid, k in keys.items() if merge_segments(G, (k,))}
    unmodelled = [sid for sid in keys if sid in changes_routing and not all(r["area"].has_edge(*e) for e in closed[sid])]
    counts = {sid: max(filter(None, map(_aadt_ref, closed[sid])), key=lambda a: a.aadt, default=None) for sid in keys}
    return NetworkImpact(
        affected_trips_pct=round((len(rerouted) + len(slowed) + len(unreachable)) / n, 3),
        avg_extra_min=summary(delayed).avg_extra_min,
        max_extra_min=summary(delayed).max_extra_min,
        delay_formula=req.delay_formula,
        delay_by_formula={f: summary(delays(c)) for f, c in by_formula.items()},
        time_factor=time_factor(req.time_window, req.custom_hours),  # reported, not multiplied in
        full_closure={sid: is_full_closure(G, closed[sid], list(k[1]), k[3]) for sid, k in keys.items()},
        rerouted_trips_pct=round(len(rerouted) / n, 3),
        slowed_trips_pct=round(len(slowed) / n, 3),
        unreachable_trips_pct=round(len(unreachable) / n, 3),
        segment_traffic={sid: _segment_traffic(G, k, closed[sid], r["usage"], n) for sid, k in keys.items()},
        unmodelled_segments=unmodelled,
        load_increase=r["loads"],
        ped_detour_m=longest[0] if longest else None,
        ped_detour_basis=longest[1] if longest else None,
        closed_aadt={sid: a for sid, a in counts.items() if a is not None},
        sensitive_facilities=facilities,
        is_demo_data=is_demo(),
    )
