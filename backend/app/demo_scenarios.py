"""Fixed demo scenarios for hackathon runs and smoke tests."""
from __future__ import annotations

from datetime import date
from typing import Literal

from . import config
from .geo import locate_on_polyline, polyline_length_m, slice_polyline
from .graph import edge_info, load_graph, plan_path, snap
from .schemas import ClosureTarget, ScenarioParams, Segment, TimeWindow, WorkType


def _segment(
    *,
    id: str,
    lat: float,
    lng: float,
    length_m: float,
    targets: list[ClosureTarget],
    direction: Literal["citybound", "outbound", "both"],
    lanes_closed: int,
) -> Segment:
    """Create a deterministic drawn segment around a point on the loaded graph."""
    G = load_graph()
    edge = snap(lat, lng)
    geom = edge_info(G, edge)["geometry"]
    mid = locate_on_polyline(geom, lat, lng)
    ends = slice_polyline(geom, mid - length_m / 2, mid + length_m / 2)
    waypoints, edges, line = plan_path([ends[0], ends[-1]])
    info = edge_info(G, edges[0])
    return Segment(
        id=id,
        waypoints=waypoints,
        edges=edges,
        geometry=line,
        length_m=round(polyline_length_m(line), 1),
        road_name=info.get("road_name"),
        road_class=info.get("road_class"),
        speed_limit_kmh=info.get("speed_limit_kmh"),
        targets=targets,
        direction=direction,
        lanes_closed=lanes_closed,
    )


def demo_scenarios() -> dict[str, ScenarioParams]:
    """Single source of truth for fixed demo coverage scenarios."""
    lat, lng = config.DEMO_WORK_POINT
    racecourse_lat = config.DEMO_CENTER[0] + 0.0027
    racecourse_lng = config.DEMO_CENTER[1]

    return {
        "A": ScenarioParams(
            name="Scenario A - Flemington Rd daytime one-lane closure",
            segments=[
                _segment(
                    id="1",
                    lat=lat,
                    lng=lng,
                    length_m=30,
                    targets=[ClosureTarget.traffic_lane, ClosureTarget.bike_lane],
                    direction="citybound",
                    lanes_closed=1,
                )
            ],
            start_date=date(2026, 10, 6),
            duration_days=3,
            time_window=TimeWindow.day,
            work_type=WorkType.excavation,
        ),
        "B": ScenarioParams(
            name="Scenario B - night full closure A/B comparison",
            segments=[
                _segment(
                    id="1",
                    lat=lat,
                    lng=lng,
                    length_m=80,
                    targets=[ClosureTarget.full],
                    direction="both",
                    lanes_closed=2,
                )
            ],
            start_date=date(2026, 10, 11),
            duration_days=2,
            time_window=TimeWindow.night,
            work_type=WorkType.excavation,
        ),
        "C": ScenarioParams(
            name="Scenario C - Eastern Freeway placeholder comparison",
            segments=[
                _segment(
                    id="1",
                    lat=racecourse_lat,
                    lng=racecourse_lng,
                    length_m=140,
                    targets=[ClosureTarget.traffic_lane, ClosureTarget.footpath],
                    direction="both",
                    lanes_closed=1,
                )
            ],
            start_date=date(2026, 10, 14),
            duration_days=5,
            time_window=TimeWindow.night,
            work_type=WorkType.excavation,
        ),
    }


def demo_scenario_a() -> ScenarioParams:
    return demo_scenarios()["A"]
