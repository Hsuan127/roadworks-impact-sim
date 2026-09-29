"""Road network loading and snapping.

Real data: run scripts/fetch_osm.py once to write data/graph_drive.graphml.
Without it, a small demo grid is generated so the whole app runs end to end.
"""
from __future__ import annotations

import math
from functools import lru_cache

import networkx as nx
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from . import config
from .geo import haversine_m, locate_on_polyline, meters_to_degrees, point_segment_distance_m, polyline_length_m, slice_polyline

GRAPH_FILE = config.DATA_DIR / "graph_drive.graphml"

Edge = tuple[int, int, int]

DEFAULT_SPEED_KMH = {"primary": 60, "secondary": 60, "tertiary": 50, "residential": 40}


def _edge_geometry(G: nx.MultiDiGraph, u: int, v: int, data: dict) -> list[tuple[float, float]]:
    geom = data.get("geometry")
    if geom is not None:  # shapely LineString from osmnx (x=lng, y=lat)
        return [(y, x) for x, y in geom.coords]
    return [(G.nodes[u]["y"], G.nodes[u]["x"]), (G.nodes[v]["y"], G.nodes[v]["x"])]


def _speed_kmh(data: dict) -> int:
    ms = data.get("maxspeed")
    if isinstance(ms, list):
        ms = ms[0]
    try:
        return int(float(ms))
    except (TypeError, ValueError):
        hw = data.get("highway")
        hw = hw[0] if isinstance(hw, list) else hw
        return DEFAULT_SPEED_KMH.get(hw, 50)


def _build_demo_graph() -> nx.MultiDiGraph:
    """7x7 grid around the demo site. Row 3 plays 'Flemington Road', column 3 'Racecourse Road'."""
    G = nx.MultiDiGraph(name="demo-grid", crs="epsg:4326")
    lat0, lng0 = config.DEMO_CENTER
    step_lat, step_lng = 0.0027, 0.0034  # ~300 m
    n = 7
    nid = lambda r, c: r * n + c  # noqa: E731
    for r in range(n):
        for c in range(n):
            G.add_node(nid(r, c), y=lat0 + (r - 3) * step_lat, x=lng0 + (c - 3) * step_lng)

    def road(r1, c1, r2, c2, name, highway, speed, lanes):
        a, b = nid(r1, c1), nid(r2, c2)
        length = haversine_m(G.nodes[a]["y"], G.nodes[a]["x"], G.nodes[b]["y"], G.nodes[b]["x"])
        for s, t in ((a, b), (b, a)):
            G.add_edge(s, t, length=length, name=name, highway=highway, maxspeed=str(speed),
                       lanes=str(lanes), travel_time=length / (speed / 3.6))

    for r in range(n):
        for c in range(n - 1):
            if r == 3:
                road(r, c, r, c + 1, "Flemington Road", "primary", 60, 2)
            else:
                road(r, c, r, c + 1, f"Demo Street {r}", "residential", 40, 1)
    for c in range(n):
        for r in range(n - 1):
            if c == 3:
                road(r, c, r + 1, c, "Racecourse Road", "secondary", 60, 2)
            else:
                road(r, c, r + 1, c, f"Demo Avenue {c}", "tertiary", 50, 1)
    return G


@lru_cache(maxsize=1)
def load_graph() -> nx.MultiDiGraph:
    if GRAPH_FILE.exists():
        import osmnx as ox  # heavy import only when real data exists

        G = ox.load_graphml(GRAPH_FILE)
        for u, v, k, d in G.edges(keys=True, data=True):
            if "travel_time" not in d:
                d["travel_time"] = d["length"] / (_speed_kmh(d) / 3.6)
        return G
    return _build_demo_graph()


def is_demo() -> bool:
    return not GRAPH_FILE.exists()


def edge_info(G: nx.MultiDiGraph, edge: tuple[int, int, int]) -> dict:
    u, v, k = edge
    d = G.edges[u, v, k]
    name = d.get("name")
    hw = d.get("highway")
    return {
        "road_name": name[0] if isinstance(name, list) else name,
        "road_class": hw[0] if isinstance(hw, list) else hw,
        "speed_limit_kmh": _speed_kmh(d),
        "geometry": _edge_geometry(G, u, v, d),
        "lanes": d.get("lanes"),
    }


def edge_lanes(G: nx.MultiDiGraph, e: Edge) -> int:
    try:
        return int(str(G.edges[e].get("lanes")).split(";")[0])
    except (TypeError, ValueError):
        return 1


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.atan2((b[1] - a[1]) * math.cos(math.radians(a[0])), b[0] - a[0])


def extend_line(G: nx.MultiDiGraph, edge: Edge, forward: bool, need_m: float) -> list[tuple[float, float]]:
    """Street line continuing from the end (forward) or start (backward) node of `edge`, going straight
    on where the road branches, until `need_m` metres or a dead end. Returned in travel order."""
    pts: list[tuple[float, float]] = []
    got, cur = 0.0, edge
    seen = {edge}
    while got < need_m:
        u, v, _ = cur
        geom = _edge_geometry(G, u, v, G.edges[cur])
        head = _bearing(geom[-2], geom[-1]) if forward else _bearing(geom[0], geom[1])
        options = [best_edge(G, v, w, "length") for w in G.successors(v) if w != u] if forward \
            else [best_edge(G, w, u, "length") for w in G.predecessors(u) if w != v]
        options = [e for e in options if e not in seen]
        if not options:
            break

        def turn(e: Edge) -> float:
            g = _edge_geometry(G, e[0], e[1], G.edges[e])
            b = _bearing(g[0], g[1]) if forward else _bearing(g[-2], g[-1])
            return abs((b - head + math.pi) % (2 * math.pi) - math.pi)

        cur = min(options, key=turn)
        seen.add(cur)
        g = _edge_geometry(G, cur[0], cur[1], G.edges[cur])
        pts = pts + g[1:] if forward else g[:-1] + pts
        got += polyline_length_m(g)
    return pts


def reverse_edge(G: nx.MultiDiGraph, e: Edge) -> Edge | None:
    return best_edge(G, e[1], e[0], "length") if G.has_edge(e[1], e[0]) else None


def edge_geometry(G: nx.MultiDiGraph, e: Edge) -> list[tuple[float, float]]:
    return _edge_geometry(G, e[0], e[1], G.edges[e])


SNAP_SEARCH_M = 300


@lru_cache(maxsize=1)
def _edge_index() -> tuple[STRtree, list[Edge]]:
    G = load_graph()
    edges = list(G.edges(keys=True))
    lines = [LineString([(x, y) for y, x in _edge_geometry(G, u, v, G.edges[u, v, k])]) for u, v, k in edges]
    return STRtree(lines), edges


def snap(lat: float, lng: float) -> tuple[int, int, int]:
    """Nearest directed edge to a clicked point. A spatial index picks nearby edges; exact distance decides."""
    G = load_graph()
    tree, edges = _edge_index()
    near = sorted(tree.query(Point(lng, lat).buffer(meters_to_degrees(SNAP_SEARCH_M))))
    best, best_d = None, math.inf
    for u, v, k in (edges[i] for i in near) if near else edges:  # far from every street: check them all
        pts = _edge_geometry(G, u, v, G.edges[u, v, k])
        for a, b in zip(pts, pts[1:]):
            dist = point_segment_distance_m(lat, lng, a, b)
            if dist < best_d:
                best, best_d = (u, v, k), dist
    if best is None:
        raise ValueError("Graph has no edges")
    return best


def best_edge(G: nx.MultiDiGraph, u: int, v: int, weight: str = "travel_time") -> Edge:
    k = min(G[u][v], key=lambda key: G[u][v][key].get(weight, math.inf))
    return (u, v, k)


def _street_positions(G: nx.MultiDiGraph, lat: float, lng: float) -> list[tuple[Edge, float]]:
    """Where a click lands on the street: (directed edge, metres from its start), one per driving direction."""
    u, v, k = snap(lat, lng)
    geom = _edge_geometry(G, u, v, G.edges[u, v, k])
    off = locate_on_polyline(geom, lat, lng)
    out = [((u, v, k), off)]
    if G.has_edge(v, u):
        out.append((best_edge(G, v, u, "length"), polyline_length_m(geom) - off))
    return out


def _geom_len(G: nx.MultiDiGraph, e: Edge) -> float:
    return polyline_length_m(_edge_geometry(G, *e[:2], G.edges[e]))


def _leg(G: nx.MultiDiGraph, a: tuple[Edge, float], b: tuple[Edge, float]) -> tuple[float, list[Edge], float, float]:
    """Drive from position a to position b. Returns (length, edges, start offset, end offset along those edges)."""
    (e1, o1), (e2, o2) = a, b
    if e1 == e2 and o2 >= o1:
        return o2 - o1, [e1], o1, o2
    try:
        mid = nx.shortest_path(G, e1[1], e2[0], weight="length")
    except nx.NetworkXNoPath:
        return math.inf, [], 0.0, 0.0
    edges = [e1] + [best_edge(G, x, y, "length") for x, y in zip(mid, mid[1:])] + [e2]
    total = sum(_geom_len(G, e) for e in edges)
    return total - o1 - (_geom_len(G, e2) - o2), edges, o1, total - (_geom_len(G, e2) - o2)


def plan_path(points: list[tuple[float, float]]):
    """Clicks anywhere along streets → (street positions, edges touched, drawn line).

    The drawn line starts and ends exactly where the user clicked; the edges are the whole
    street segments it touches, which is what the impact engines compute on."""
    G = load_graph()
    cands = [_street_positions(G, lat, lng) for lat, lng in points]
    # Pick a driving direction at every click so the whole path is shortest (Viterbi over ≤2 options each).
    best = [(0.0, None)] * len(cands[0])
    back: list[list[tuple[int, tuple]]] = []
    for i in range(1, len(cands)):
        row, ptr = [], []
        for b in cands[i]:
            options = [(best[j][0] + _leg(G, a, b)[0], j) for j, a in enumerate(cands[i - 1])]
            cost, j = min(options)
            row.append((cost, j))
        back.append([j for _, j in row])
        best = row
    choice = [min(range(len(best)), key=lambda j: best[j][0])]
    for ptr in reversed(back):
        choice.append(ptr[choice[-1]])
    chosen = [cands[i][j] for i, j in enumerate(reversed(choice))]
    if math.isinf(min(c for c, _ in best)):
        raise ValueError("No drivable path between two of the points.")

    edges: list[Edge] = []
    line: list[tuple[float, float]] = []
    for (a, b), p, q in zip(zip(chosen, chosen[1:]), points, points[1:]):
        length, leg_edges, start, end = _leg(G, a, b)
        # Much longer than the straight line = it went around the block to avoid a one-way street.
        if length > 1.6 * haversine_m(*p, *q) + 60:
            raise ValueError("That goes against a one-way street. Click the points in the direction of traffic.")
        piece = slice_polyline(path_geometry(G, leg_edges), start, end)
        line.extend(piece if not line else piece[1:])
        edges += [e for e in leg_edges if e not in edges]

    snapped = [slice_polyline(_edge_geometry(G, *e[:2], G.edges[e]), o, o)[0] for e, o in chosen]
    return snapped, edges, line


def path_geometry(G: nx.MultiDiGraph, edges: list[Edge]) -> list[tuple[float, float]]:
    """One continuous polyline for consecutive edges."""
    pts: list[tuple[float, float]] = []
    for u, v, k in edges:
        g = _edge_geometry(G, u, v, G.edges[u, v, k])
        pts.extend(g if not pts else g[1:])
    return pts
