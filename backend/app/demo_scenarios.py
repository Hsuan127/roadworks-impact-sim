"""Fixed demo scenarios for hackathon runs and smoke tests."""
from __future__ import annotations

from datetime import date

from . import config
from .graph import edge_info, load_graph, snap
from .schemas import ClosureTarget, Location, ScenarioParams, TimeWindow, WorkType


def _scenario_location(lat: float, lng: float) -> Location:
    edge = snap(lat, lng)
    info = edge_info(load_graph(), edge)
    return Location(
        lat=lat,
        lng=lng,
        edge=edge,
        road_name=info["road_name"],
        road_class=info["road_class"],
    )


def demo_scenarios() -> dict[str, ScenarioParams]:
    """Single source of truth for fixed demo coverage scenarios."""
    lat, lng = config.DEMO_WORK_POINT
    racecourse_lat = config.DEMO_CENTER[0] + 0.0027
    racecourse_lng = config.DEMO_CENTER[1]

    return {
        "A": ScenarioParams(
            name="Scenario A - lane and bike lane closure",
            location=_scenario_location(lat, lng),
            targets=[ClosureTarget.traffic_lane, ClosureTarget.bike_lane],
            direction="citybound",
            lanes_closed=1,
            work_length_m=30,
            start_date=date(2026, 10, 6),
            duration_days=3,
            time_window=TimeWindow.day,
            speed_limit_kmh=60,
            work_type=WorkType.excavation,
        ),
        "B": ScenarioParams(
            name="Scenario B - full road closure and tram impact",
            location=_scenario_location(lat, lng),
            targets=[ClosureTarget.full],
            direction="both",
            lanes_closed=2,
            work_length_m=80,
            start_date=date(2026, 10, 11),
            duration_days=2,
            time_window=TimeWindow.day,
            speed_limit_kmh=60,
            work_type=WorkType.excavation,
        ),
        "C": ScenarioParams(
            name="Scenario C - night works with equipment and transit impact",
            location=_scenario_location(racecourse_lat, racecourse_lng),
            targets=[ClosureTarget.traffic_lane, ClosureTarget.footpath],
            direction="both",
            lanes_closed=1,
            work_length_m=140,
            start_date=date(2026, 10, 14),
            duration_days=5,
            time_window=TimeWindow.night,
            speed_limit_kmh=60,
            work_type=WorkType.excavation,
        ),
    }


def demo_scenario_a() -> ScenarioParams:
    return demo_scenarios()["A"]
