"""Road network loading and snapping.

Real data: run scripts/fetch_osm.py once to write data/graph_drive.graphml.
Without it, a small demo grid is generated so the whole app runs end to end.
"""
from __future__ import annotations

import ast
import math
from functools import lru_cache
from pathlib import Path

import networkx as nx
from shapely import wkt as shapely_wkt

from . import config
from .geo import haversine_m, point_segment_distance_m

GRAPH_FILE = config.DATA_DIR / "graph_drive.graphml"
WALK_FILE = config.DATA_DIR / "graph_walk.graphml"

DEFAULT_SPEED_KMH = {"primary": 60, "secondary": 60, "tertiary": 50, "residential": 40}

# GraphML stores every attribute as a string, and it is osmnx's load_graphml that normally converts
# them back. We read with plain networkx so the API never imports osmnx (it is a data-script-only
# dependency), which means doing that conversion here.
_FLOAT_ATTRS = ("length", "travel_time", "speed_kph", "bearing")


def _maybe_list(value):
    """OSM tags can be multi-valued; graphml renders those as the literal string "['a', 'b']"."""
    if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    return value


def _coerce_edge(data: dict) -> None:
    for key in _FLOAT_ATTRS:
        if key in data and not isinstance(data[key], float):
            try:
                data[key] = float(data[key])
            except (TypeError, ValueError):
                data.pop(key)
    for key in ("name", "highway", "maxspeed", "lanes", "ref"):
        if key in data:
            data[key] = _maybe_list(data[key])
    geom = data.get("geometry")
    if isinstance(geom, str):  # WKT, e.g. "LINESTRING (144.94 -37.79, ...)"
        try:
            data["geometry"] = shapely_wkt.loads(geom)
        except Exception:
            data.pop("geometry")


def _read_graphml(path: Path) -> nx.MultiDiGraph:
    G = nx.read_graphml(path, node_type=int, force_multigraph=True)
    if not G.is_directed():
        G = G.to_directed()
    G = nx.MultiDiGraph(G)
    for _, d in G.nodes(data=True):
        for key in ("x", "y"):
            if key in d:
                d[key] = float(d[key])
    for u, v, d in G.edges(data=True):
        _coerce_edge(d)
        if "length" not in d:
            d["length"] = haversine_m(G.nodes[u]["y"], G.nodes[u]["x"], G.nodes[v]["y"], G.nodes[v]["x"])
        if "travel_time" not in d:
            d["travel_time"] = d["length"] / (_speed_kmh(d) / 3.6)
    return G


def _edge_geometry(G: nx.MultiDiGraph, u: int, v: int, data: dict) -> list[tuple[float, float]]:
    geom = data.get("geometry")
    if geom is not None:  # shapely LineString (x=lng, y=lat)
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
        return _read_graphml(GRAPH_FILE)
    return _build_demo_graph()


@lru_cache(maxsize=1)
def load_walk_graph() -> nx.Graph:
    """Undirected walk network for pedestrian detours.

    Falls back to the drive graph collapsed to undirected, which is what P2 did before real data
    existed — pedestrians then cannot use footways or laneways, so `ped_detour_basis` reports
    "street_centreline" and the UI says the number is an over-estimate.
    """
    if WALK_FILE.exists():
        return nx.Graph(_read_graphml(WALK_FILE))
    G = load_graph()
    W = nx.Graph()
    for a, b, d in G.edges(data=True):
        if a == b:
            continue
        if not W.has_edge(a, b) or d["length"] < W[a][b]["length"]:
            W.add_edge(a, b, length=d["length"], highway=d.get("highway"))
    for n, d in G.nodes(data=True):
        if n in W:
            W.nodes[n].update(x=d["x"], y=d["y"])
    return W


def has_walk_graph() -> bool:
    return WALK_FILE.exists()


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
