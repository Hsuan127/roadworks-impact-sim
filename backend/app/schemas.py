"""Shared data contract between all modules (the single source of truth).

The frontend mirrors these models in frontend/src/types.ts; keep both in sync.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ClosureTarget(str, Enum):
    traffic_lane = "traffic_lane"
    bike_lane = "bike_lane"
    footpath = "footpath"
    full = "full"  # every traffic lane in the chosen direction(s)


class TimeWindow(str, Enum):
    day = "day"
    night = "night"
    custom = "custom"


class WorkType(str, Enum):
    excavation = "excavation"
    non_excavation = "non_excavation"


EdgeKey = tuple[int, int, int]  # OSM edge (u, v, key)
LatLng = tuple[float, float]


class Location(BaseModel):
    lat: float
    lng: float
    edge: EdgeKey | None = None
    road_name: str | None = None
    road_class: str | None = None


class ScenarioParams(BaseModel):
    """Everything the planner sets in the form. One scenario = one column in A/B compare."""

    name: str = "A"
    location: Location
    targets: list[ClosureTarget] = Field(default_factory=lambda: [ClosureTarget.traffic_lane])
    direction: Literal["citybound", "outbound", "both"] = "citybound"
    lanes_closed: int = Field(1, ge=1, le=4)
    work_length_m: float = Field(30, gt=0, le=2000)
    start_date: date
    duration_days: int = Field(3, ge=1, le=365)
    time_window: TimeWindow = TimeWindow.day
    custom_hours: tuple[int, int] | None = None
    speed_limit_kmh: int | None = Field(None, ge=10, le=110)
    work_type: WorkType = WorkType.excavation


# ---------- snap ----------
class SnapRequest(BaseModel):
    lat: float
    lng: float


class SnapResult(BaseModel):
    edge: EdgeKey
    road_name: str | None
    lat: float
    lng: float
    speed_limit_kmh: int | None
    road_class: str | None
    geometry: list[LatLng]


# ---------- network impact (P2) ----------
class NetworkRequest(BaseModel):
    """Only the fields that change routing. Duration, work length etc. are deliberately absent,
    so editing them never triggers a network recompute."""

    edge: EdgeKey
    targets: list[ClosureTarget]
    direction: Literal["citybound", "outbound", "both"]
    lanes_closed: int = 1
    time_window: TimeWindow = TimeWindow.day


class EdgeLoad(BaseModel):
    edge: EdgeKey
    road_name: str | None
    delta: float  # relative change in usage, e.g. 0.35 = +35 %
    geometry: list[LatLng]


class Facility(BaseModel):
    name: str
    kind: str  # hospital | school | fire_station | ...
    lat: float
    lng: float


class NetworkImpact(BaseModel):
    affected_trips_pct: float
    avg_extra_min: float
    max_extra_min: float
    time_factor: float
    closed_geometry: list[LatLng]
    load_increase: list[EdgeLoad]
    ped_detour_m: float | None
    sensitive_facilities: list[Facility]
    is_demo_data: bool
    note: str = "Relative impact index from synthetic trips, not measured traffic volume."


# ---------- transit (P3) ----------
class TransitRequest(BaseModel):
    edge: EdgeKey
    targets: list[ClosureTarget]


class AffectedRoute(BaseModel):
    route_id: str
    short_name: str
    mode: Literal["tram", "bus", "train", "other"]
    needs_replacement: bool


class NearbyStop(BaseModel):
    stop_id: str
    name: str
    lat: float
    lng: float
    distance_m: float


class TransitImpact(BaseModel):
    routes: list[AffectedRoute]
    stops: list[NearbyStop]
    is_demo_data: bool


# ---------- equipment (P4) ----------
class EquipmentRequest(BaseModel):
    targets: list[ClosureTarget]
    direction: Literal["citybound", "outbound", "both"]
    lanes_closed: int = 1
    work_length_m: float
    duration_days: int
    time_window: TimeWindow
    speed_limit_kmh: int | None
    road_class: str | None = None
    work_type: WorkType


class EquipmentItem(BaseModel):
    item_id: str
    name: str
    qty: int
    reason: str
    stock: int
    in_stock: bool
    daily_rate_aud: float
    cost_aud: float


class EquipmentResult(BaseModel):
    items: list[EquipmentItem]
    total_cost_aud: float
    shortages: list[str]
    rules_verified: bool
    disclaimer: str


# ---------- comms (P5) ----------
class CommsRequest(BaseModel):
    scenario: ScenarioParams
    network: NetworkImpact | None = None
    transit: TransitImpact | None = None
    equipment: EquipmentResult | None = None


class Comms(BaseModel):
    vms_messages: list[list[str]]
    public_notice_md: str
    generated_by: Literal["template", "llm"]
    disclaimer: str = "Draft only. Must be reviewed by a qualified traffic management practitioner."


class ParseRequest(BaseModel):
    text: str


class ParseResult(BaseModel):
    fields: dict  # partial ScenarioParams, used only to pre-fill the form
    missing: list[str]
