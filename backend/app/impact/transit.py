"""Public transport impact (owner: P3).

Real data: scripts/build_gtfs_subset.py writes data/gtfs/{routes,trips,shapes,stops}.txt
for the demo area only. Without it, demo routes are generated on the demo grid.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from shapely.geometry import LineString
from shapely.ops import substring, unary_union

from .. import config
from ..geo import meters_to_degrees, point_segment_distance_m
from ..graph import edge_info, load_graph, path_geometry
from ..graph import is_demo as is_demo_graph
from ..schemas import AffectedRoute, ClosureTarget, NearbyStop, TransitImpact, TransitRequest

GTFS_DIR = config.DATA_DIR / "gtfs"
ROUTE_TYPE_MODE = {0: "tram", 3: "bus", 2: "train", 1: "train"}


@dataclass
class Route:
    route_id: str
    short_name: str
    mode: str
    lines: list[LineString]  # lng/lat order (shapely x, y)


@dataclass
class Stop:
    stop_id: str
    name: str
    lat: float
    lng: float


def is_demo() -> bool:
    return not (GTFS_DIR / "shapes.txt").exists()


@lru_cache(maxsize=1)
def load_transit() -> tuple[list[Route], list[Stop]]:
    if is_demo():
        return _demo_transit()
    import pandas as pd

    routes = pd.read_csv(GTFS_DIR / "routes.txt", dtype=str)
    trips = pd.read_csv(GTFS_DIR / "trips.txt", dtype=str, usecols=["route_id", "shape_id"]).drop_duplicates()
    shapes = pd.read_csv(GTFS_DIR / "shapes.txt", dtype={"shape_id": str})
    stops = pd.read_csv(GTFS_DIR / "stops.txt", dtype={"stop_id": str})

    lines_by_shape = {
        sid: LineString(g.sort_values("shape_pt_sequence")[["shape_pt_lon", "shape_pt_lat"]].to_numpy())
        for sid, g in shapes.groupby("shape_id") if len(g) >= 2
    }
    out = []
    for _, r in routes.iterrows():
        sids = trips.loc[trips.route_id == r.route_id, "shape_id"]
        lines = [lines_by_shape[s] for s in sids if s in lines_by_shape]
        if lines:
            mode = ROUTE_TYPE_MODE.get(int(r.route_type), "other")
            out.append(Route(r.route_id, str(r.get("route_short_name") or r.route_id), mode, lines))
    stop_list = [Stop(s.stop_id, s.stop_name, float(s.stop_lat), float(s.stop_lon)) for s in stops.itertuples()]
    return out, stop_list


def _demo_transit() -> tuple[list[Route], list[Stop]]:
    """Placeholder routes on the demo grid. NOT real PTV routes. None on a real street network."""
    if not is_demo_graph():
        return [], []
    G = load_graph()
    xy = lambda n: (G.nodes[n]["x"], G.nodes[n]["y"])  # noqa: E731
    n = 7
    tram = LineString([xy(r * n + 3) for r in range(n)])       # along demo 'Racecourse Road'
    bus = LineString([xy(1 * n + c) for c in range(n)])         # along a side street
    tram2 = LineString([xy(3 * n + c) for c in range(n)])      # along demo 'Flemington Road'
    routes = [
        Route("demo-tram-1", "Demo tram A", "tram", [tram]),
        Route("demo-tram-2", "Demo tram B", "tram", [tram2]),
        Route("demo-bus-1", "Demo bus", "bus", [bus]),
    ]
    stops = [Stop(f"demo-stop-{i}", f"Demo stop {i}", G.nodes[node]["y"], G.nodes[node]["x"])
             for i, node in enumerate([3 * n + 2, 3 * n + 3, 3 * n + 4, 2 * n + 3, 4 * n + 3])]
    return routes, stops


def _inner_buffer(G, edges: list[tuple[int, int, int]]):
    # Trim each street segment's ends so a route that only CROSSES at an intersection is not counted as running along it.
    inner = unary_union([
        substring(LineString([(lng, lat) for lat, lng in edge_info(G, e)["geometry"]]), 0.15, 0.85, normalized=True)
        for e in edges
    ])
    return inner.buffer(meters_to_degrees(config.TRANSIT_EDGE_BUFFER_M))


def transit_impact(req: TransitRequest) -> TransitImpact:
    G = load_graph()
    routes, stops = load_transit()
    affected: dict[str, AffectedRoute] = {}
    for seg in req.segments:
        if ClosureTarget.full not in seg.targets and ClosureTarget.traffic_lane not in seg.targets:
            continue
        buffer = _inner_buffer(G, [tuple(e) for e in seg.edges])
        for r in routes:
            if any(line.intersects(buffer) for line in r.lines):
                # Trams cannot detour; a full closure on a tram line needs replacement buses.
                replace = r.mode == "tram" and ClosureTarget.full in seg.targets
                prev = affected.get(r.route_id)
                affected[r.route_id] = AffectedRoute(route_id=r.route_id, short_name=r.short_name, mode=r.mode,
                                                     needs_replacement=replace or (prev is not None and prev.needs_replacement))

    paths = [path_geometry(G, [tuple(e) for e in seg.edges]) for seg in req.segments]
    nearby = []
    for s in stops:
        d = min(point_segment_distance_m(s.lat, s.lng, a, b) for path in paths for a, b in zip(path, path[1:]))
        if d <= config.NEARBY_STOP_RADIUS_M:
            nearby.append(NearbyStop(stop_id=s.stop_id, name=s.name, lat=s.lat, lng=s.lng, distance_m=round(d)))
    nearby.sort(key=lambda s: s.distance_m)
    note = "No timetable data loaded (run scripts/build_gtfs_subset.py)." if is_demo() and not is_demo_graph() else None
    return TransitImpact(routes=list(affected.values()), stops=nearby[:15], is_demo_data=is_demo(), note=note)
