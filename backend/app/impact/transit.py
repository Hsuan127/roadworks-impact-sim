"""Public transport impact (owner: P3).

Real data: scripts/build_gtfs_subset.py writes data/gtfs/{routes,trips,shapes,stops}.txt
for the demo area only. Without it, demo routes are generated on the demo grid.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from shapely.geometry import LineString
from shapely.ops import substring

from .. import config
from ..geo import haversine_m, meters_to_degrees
from ..graph import edge_info, load_graph
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
    """Placeholder routes near the demo work site. NOT real PTV routes.

    Derived from the geometry of the work-site edge rather than from node ids: the previous version
    indexed the 7x7 demo grid directly (`G.nodes[r * 7 + c]`), which raised KeyError the moment a
    real OSM graph replaced it. One demo tram runs ALONG the work-site road, one crosses it, so the
    "runs along" vs "merely crosses" distinction stays testable on either graph.
    """
    from ..graph import snap  # local import: snap() needs the loaded graph, avoids a cycle at import

    G = load_graph()
    edge = snap(*config.DEMO_WORK_POINT)
    pts = edge_info(G, edge)["geometry"]  # [(lat, lng), ...]
    (alat, alng), (blat, blng) = pts[0], pts[-1]
    mlat, mlng = (alat + blat) / 2, (alng + blng) / 2

    # Local metres-per-degree, so "300 m" means the same thing in both axes.
    dlat = meters_to_degrees(300)
    dlng = dlat / max(math.cos(math.radians(mlat)), 1e-6)

    vlat, vlng = blat - alat, blng - alng
    norm = math.hypot(vlat, vlng / max(math.cos(math.radians(mlat)), 1e-6)) or 1e-9
    ulat, ulng = vlat / norm, vlng / norm  # unit vector along the road

    along = LineString([
        (mlng - 4 * ulng * dlng, mlat - 4 * ulat * dlat),
        (mlng + 4 * ulng * dlng, mlat + 4 * ulat * dlat),
    ])
    # Perpendicular through the edge's END (a real intersection), not its midpoint: transit_impact
    # trims the closed line to 0.15-0.85 precisely so a route that merely CROSSES at the
    # intersection is not counted as running along it. A crossing drawn through the midpoint would
    # sit inside the trimmed span and be flagged.
    across = LineString([
        (alng + 4 * ulat * dlng, alat - 4 * ulng * dlat),
        (alng - 4 * ulat * dlng, alat + 4 * ulng * dlat),
    ])
    side = LineString([  # a parallel side street, well clear of the work site
        (mlng - 4 * ulng * dlng + 3 * ulat * dlng, mlat - 4 * ulat * dlat - 3 * ulng * dlat),
        (mlng + 4 * ulng * dlng + 3 * ulat * dlng, mlat + 4 * ulat * dlat - 3 * ulng * dlat),
    ])
    routes = [
        Route("demo-tram-1", "Demo tram A", "tram", [across]),   # crosses the work site
        Route("demo-tram-2", "Demo tram B", "tram", [along]),    # runs along it
        Route("demo-bus-1", "Demo bus", "bus", [side]),
    ]
    stops = [
        Stop(f"demo-stop-{i}", f"Demo stop {i}", mlat + f * ulat * dlat, mlng + f * ulng * dlng)
        for i, f in enumerate((-1.5, 0.0, 1.5))
    ] + [
        Stop("demo-stop-3", "Demo stop 3", mlat - 1.5 * ulng * dlat, mlng + 1.5 * ulat * dlng),
        Stop("demo-stop-4", "Demo stop 4", mlat + 1.5 * ulng * dlat, mlng - 1.5 * ulat * dlng),
    ]
    return routes, stops


def transit_impact(req: TransitRequest) -> TransitImpact:
    G = load_graph()
    info = edge_info(G, tuple(req.edge))
    geom = info["geometry"]  # (lat, lng)
    closed_line = LineString([(lng, lat) for lat, lng in geom])
    # Trim the ends so a route that only CROSSES at the intersection is not counted as running along it.
    inner = substring(closed_line, 0.15, 0.85, normalized=True)
    buffer = inner.buffer(meters_to_degrees(config.TRANSIT_EDGE_BUFFER_M))
    traffic_affected = ClosureTarget.full in req.targets or ClosureTarget.traffic_lane in req.targets

    routes, stops = load_transit()
    affected = []
    if traffic_affected:
        for r in routes:
            if any(line.intersects(buffer) for line in r.lines):
                affected.append(AffectedRoute(
                    route_id=r.route_id, short_name=r.short_name, mode=r.mode,
                    # Trams cannot detour; a full closure on a tram line needs replacement buses.
                    needs_replacement=(r.mode == "tram" and ClosureTarget.full in req.targets),
                ))

    mid_lat = sum(p[0] for p in geom) / len(geom)
    mid_lng = sum(p[1] for p in geom) / len(geom)
    nearby = []
    for s in stops:
        d = haversine_m(mid_lat, mid_lng, s.lat, s.lng)
        if d <= config.NEARBY_STOP_RADIUS_M:
            nearby.append(NearbyStop(stop_id=s.stop_id, name=s.name, lat=s.lat, lng=s.lng, distance_m=round(d)))
    nearby.sort(key=lambda s: s.distance_m)
    return TransitImpact(routes=affected, stops=nearby[:15], is_demo_data=is_demo())
