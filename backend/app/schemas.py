"""Shared data contract between all modules (the single source of truth).

The frontend mirrors these models in frontend/src/types.ts; keep both in sync.
"""
from __future__ import annotations

from datetime import date, datetime
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


class Segment(BaseModel):
    """One independently drawn closure line with its own settings. A plan can have several,
    and they may share streets or intersections (e.g. A-B and A-C)."""

    id: str
    name: str | None = Field(None, max_length=80)  # typed by the user; None = automatic. Display only, no module reads it
    waypoints: list[LatLng] = Field(default_factory=list)  # user's clicks, moved onto the street, in order
    edges: list[EdgeKey] = Field(default_factory=list)  # whole street segments the line touches (what impacts compute on)
    geometry: list[LatLng] = Field(default_factory=list)  # the line as drawn: starts and ends exactly at the clicks
    length_m: float = 0  # of the drawn line
    road_name: str | None = None
    road_class: str | None = None
    speed_limit_kmh: int | None = Field(None, ge=10, le=110)
    targets: list[ClosureTarget] = Field(default_factory=lambda: [ClosureTarget.traffic_lane])
    direction: Literal["citybound", "outbound", "both"] = "citybound"
    lanes_closed: int = Field(1, ge=1, le=4)
    # When this segment's works run. None = the plan's values. No module reads these yet: the UI keeps the
    # plan-level fields below equal to the span of all segments, and every module reads those.
    start_date: date | None = None
    duration_days: int | None = Field(None, ge=1, le=365)
    time_window: TimeWindow | None = None
    custom_hours: tuple[int, int] | None = None
    work_type: WorkType | None = None


class ScenarioParams(BaseModel):
    """Everything the planner sets. One scenario = one column in A/B compare.
    Where, what and when live on each segment. The plan-level timing is the span of all segments
    (first day to last day; mixed hours count as night), kept in sync by the UI."""

    name: str = "A"
    segments: list[Segment] = Field(default_factory=list)
    start_date: date
    duration_days: int = Field(3, ge=1, le=365)
    time_window: TimeWindow = TimeWindow.day
    custom_hours: tuple[int, int] | None = None
    work_type: WorkType = WorkType.excavation


# ---------- path ----------
class PathRequest(BaseModel):
    points: list[LatLng] = Field(min_length=1)  # map clicks, in order


class PathResult(BaseModel):
    waypoints: list[LatLng]  # each click moved onto the nearest street
    edges: list[EdgeKey]  # empty until there are two waypoints
    geometry: list[LatLng]  # the drawn line, trimmed to the clicks
    length_m: float  # of the drawn line
    road_name: str | None  # of the longest segment
    road_class: str | None
    speed_limit_kmh: int | None


# ---------- network impact (P2) ----------
class SegmentClosure(BaseModel):
    """The routing-relevant part of one segment."""

    id: str
    edges: list[EdgeKey] = Field(min_length=1)
    targets: list[ClosureTarget]
    direction: Literal["citybound", "outbound", "both"]
    lanes_closed: int = Field(1, ge=1, le=4)


class NetworkRequest(BaseModel):
    """Only the fields that change routing. Duration, dates etc. are deliberately absent,
    so editing them never triggers a network recompute."""

    segments: list[SegmentClosure] = Field(min_length=1)
    time_window: TimeWindow = TimeWindow.day
    # Only read when time_window == custom: hours that touch a peak get the peak volume profile.
    # Changing them re-runs the cheap volume lookup, never the routing.
    custom_hours: tuple[int, int] | None = None


class AadtRef(BaseModel):
    """A published traffic count attached to one edge. Never computed, only looked up."""

    aadt: int
    heavy: int | None = None
    year: int
    direction: str | None = None
    both_directions: bool = False
    section: str | None = None
    method: str | None = None  # "Actual" (measured) or "Estimated"
    match_confidence: float | None = None
    source: str | None = None


class EdgeLoad(BaseModel):
    edge: EdgeKey
    road_name: str | None
    delta: float  # share of affected trips that newly use this street, e.g. 0.35 = 35 % of them
    geometry: list[LatLng]
    aadt: AadtRef | None = None  # published volume on this street, display only


class Facility(BaseModel):
    name: str
    kind: str  # hospital | school | fire_station | ...
    lat: float
    lng: float
    near: Literal["works", "detour"] | None = None  # set in results: next to the works, or on a detour street


class SegmentTraffic(BaseModel):
    through_trips_pct: float  # share of all trips still driving through this segment (0 for a road closure)
    slowdown_factor: float | None  # travel-time multiplier on the segment; None = closed to vehicles, 1 = no change


class NetworkImpact(BaseModel):
    affected_trips_pct: float
    avg_extra_min: float
    max_extra_min: float
    time_factor: float
    # Per segment id. True: no vehicle can pass (road closure). False: traffic still passes (work zone).
    full_closure: dict[str, bool]
    # Of all trips: took another route vs kept their route but drive slower through a work zone.
    rerouted_trips_pct: float
    slowed_trips_pct: float
    # Had a route before the closure, has none after. Counted in affected_trips_pct, not in the delay stats.
    unreachable_trips_pct: float = 0.0
    segment_traffic: dict[str, SegmentTraffic]  # per segment id
    # Segment ids whose closed streets lie (partly) outside the routed study area, e.g. a one-way street,
    # cul-de-sac or ramp cut off from the main network: their effect on traffic is not in these numbers.
    unmodelled_segments: list[str] = Field(default_factory=list)
    load_increase: list[EdgeLoad]
    ped_detour_m: float | None
    ped_detour_basis: Literal["footway", "street_centreline"] | None = None  # centreline = an over-estimate
    # Per segment id: the published VicRoads count on its busiest closed edge. Display only; segments
    # on a road with no published count are absent.
    closed_aadt: dict[str, AadtRef] = Field(default_factory=dict)
    sensitive_facilities: list[Facility]
    is_demo_data: bool
    note: str = (
        "Trip pattern is synthetic. Delays come from published VicRoads volumes through a BPR "
        "capacity curve, one pass with no route re-choice, and only on roads that have a published "
        "count. Indicative, not a calibrated traffic model."
    )


# ---------- transit (P3) ----------
class TransitSegment(BaseModel):
    edges: list[EdgeKey] = Field(min_length=1)
    targets: list[ClosureTarget]


class TransitRequest(BaseModel):
    segments: list[TransitSegment] = Field(min_length=1)


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
    routes: list[str] = Field(default_factory=list)  # short names of routes serving this stop


class TransitImpact(BaseModel):
    routes: list[AffectedRoute]
    stops: list[NearbyStop]
    is_demo_data: bool
    note: str | None = None  # e.g. why there are no routes at all


# ---------- nearby planned works (DTP Planned Disruptions) ----------
class DisruptionsRequest(BaseModel):
    """Where and when the works run: no lanes or targets, since other permits do not depend on them.
    Cheap lookup, so changing the dates re-runs only this, never the network."""

    works: list[LatLng] = Field(min_length=1)  # the drawn lines' points, all segments together
    start_date: date
    duration_days: int = Field(ge=1, le=365)
    time_window: TimeWindow
    custom_hours: tuple[int, int] | None = None  # only read when time_window == custom


class Shift(BaseModel):
    weekday: int = Field(ge=0, le=6)  # 0 = Monday
    start_h: float  # local clock hour, 20.5 = 20:30
    hours: float  # may run past midnight


class Disruption(BaseModel):
    """One permitted works section from the DTP feed. A permit allows works in this window; it does not
    say which nights the crew is actually there. Display only: nothing here enters any calculation."""

    id: str
    permit: str  # several sections share one permit
    road_name: str | None
    cross_street: str | None
    cause: str | None  # e.g. "Utility Works"
    impact_type: str | None  # "Closures" | "Lanes blocked", as the feed says
    direction: str | None
    lanes_impacted: str | None  # as published; often missing
    description: str | None
    start: str  # ISO, Melbourne local time
    end: str
    shifts: list[Shift] | None  # None: the feed gives no daily hours
    lines: list[list[LatLng]]
    edges: list[EdgeKey]  # drive edges it lies on; empty if it did not match our streets
    distance_m: float  # nearest approach to the drawn works
    overlap: float  # share of our working hours that fall inside its permitted hours, 0-1
    relevance: float  # overlap x closeness (1 at the works, 0.5 at 500 m), a ranking only
    level: Literal[0, 1, 2, 3]  # 0 = not at the same time; 3 = same time and close


class DisruptionsResult(BaseModel):
    available: bool  # False when the snapshot file is missing: nothing is invented in its place
    fetched_at: str | None
    source: str | None
    disruptions: list[Disruption]  # most relevant first
    note: str = (
        "Permitted works from the DTP feed, a snapshot, not live. A permit allows works in the listed hours; "
        "it does not say which nights a crew is on site. Relevance is a ranking by time overlap and distance, "
        "not a traffic impact."
    )


# ---------- equipment (P4) ----------
class EquipmentSegment(BaseModel):
    """Each segment gets its own signs, taper and work-zone set-up."""

    id: str  # the segment's id in the plan: equipment lines are labelled with it
    edges: list[EdgeKey] = Field(min_length=1)  # tells a one-way street (one approach) from a two-way one
    targets: list[ClosureTarget]
    direction: Literal["citybound", "outbound", "both"]
    lanes_closed: int = 1
    length_m: float = Field(gt=0)
    speed_limit_kmh: int | None
    road_class: str | None = None


class EquipmentRequest(BaseModel):
    segments: list[EquipmentSegment] = Field(min_length=1)
    duration_days: int
    time_window: TimeWindow
    custom_hours: tuple[int, int] | None = None  # only read when time_window == custom (night lighting)
    work_type: WorkType


class LayoutSegment(EquipmentSegment):
    """An equipment segment plus where it is, for placing items on the map."""

    geometry: list[LatLng] = Field(min_length=2)  # the drawn line, in the direction of traffic


class LayoutRequest(BaseModel):
    segments: list[LayoutSegment] = Field(min_length=1)
    duration_days: int
    time_window: TimeWindow
    custom_hours: tuple[int, int] | None = None
    work_type: WorkType


class Placement(BaseModel):
    item_id: str
    name: str
    segment_id: str
    lat: float
    lng: float
    reason: str
    in_stock: bool


class EquipmentLayout(BaseModel):
    placements: list[Placement]
    note: str = "Schematic layout to check quantities, not a traffic guidance scheme. Positions need a qualified designer."


class EquipmentItem(BaseModel):
    item_id: str
    name: str
    supplier: str | None = None  # "RPM" when RPM Hire rents it, "other" for items hired elsewhere
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
    warnings: list[str] = Field(default_factory=list)  # e.g. too few lanes left for the traffic (AGTTM Table 2.4)
    rules_verified: bool
    disclaimer: str


# ---------- hire queries (contractor -> RPM Hire) ----------
# The planner never sees stock. They send a query; the depot sees every query with the stock it would
# need, including what other queries for the same dates already ask for, and decides which to take.
QueryStatus = Literal["new", "accepted", "declined", "countered"]


class QueryContact(BaseModel):
    company: str = Field(min_length=1, max_length=120)
    contact: str = Field(min_length=1, max_length=120)
    email: str | None = Field(None, max_length=200)
    note: str = Field("", max_length=1000)


class QueryRequest(BaseModel):
    scenario: ScenarioParams
    equipment: EquipmentRequest  # the body the planner's equipment list came from; recomputed server-side
    contact: QueryContact


class StockGap(BaseModel):
    """One item the depot cannot cover for this query's dates."""

    item_id: str
    name: str
    stock: int
    requested: int  # by this query
    overlapping_demand: int  # this query plus every other open query whose dates overlap it


class HireQuery(BaseModel):
    id: str
    submitted_at: datetime
    status: QueryStatus = "new"
    contact: QueryContact
    segments: list[str]  # segment labels: the user's name, else the road
    road_classes: list[str]
    start_date: date
    end_date: date  # last day of works, inclusive
    time_window: TimeWindow
    items: list[EquipmentItem]
    total_cost_aud: float
    stock_gaps: list[StockGap] = Field(default_factory=list)  # depot view only; computed on read
    overlaps_with: list[str] = Field(default_factory=list)  # ids of other open queries sharing any day


class QueryStatusUpdate(BaseModel):
    status: QueryStatus


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


class ParsedFields(BaseModel):
    """The only fields a description may pre-fill, each validated. Anything else the model returns is dropped.
    Location and speed are never pre-filled: they come from the map. road_name is shown, not applied."""

    road_name: str | None = None
    # Applied to the segment being edited
    targets: list[ClosureTarget] | None = Field(None, min_length=1)  # [] would close nothing: report it missing
    direction: Literal["citybound", "outbound", "both"] | None = None
    lanes_closed: int | None = Field(None, ge=1, le=4)
    # Applied to the plan
    start_date: date | None = None
    duration_days: int | None = Field(None, ge=1, le=365)
    time_window: TimeWindow | None = None
    work_type: WorkType | None = None


class ParseResult(BaseModel):
    fields: ParsedFields  # used only to pre-fill the form; null = not found
    missing: list[str]  # allowed keys the model could not determine, or returned an invalid value for
