"""Road network loading and snapping.

Real data: run scripts/fetch_osm.py once to write data/graph_drive.graphml.
Without it, a small demo grid is generated so the whole app runs end to end.
"""
from __future__ import annotations

import math
from functools import lru_cache

import networkx as nx

from . import config
from .geo import haversine_m, point_segment_distance_m

GRAPH_FILE = config.DATA_DIR / "graph_drive.graphml"

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


def snap(lat: float, lng: float) -> tuple[int, int, int]:
    """Nearest directed edge to a clicked point (brute force; fine for a ~1.5 km graph)."""
    G = load_graph()
    best, best_d = None, math.inf
    for u, v, k, d in G.edges(keys=True, data=True):
        pts = _edge_geometry(G, u, v, d)
        for a, b in zip(pts, pts[1:]):
            dist = point_segment_distance_m(lat, lng, a, b)
            if dist < best_d:
                best, best_d = (u, v, k), dist
    if best is None:
        raise ValueError("Graph has no edges")
    return best
