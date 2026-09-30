// Mirrors backend/app/schemas.py — keep in sync.
export type ClosureTarget = "traffic_lane" | "bike_lane" | "footpath" | "full";
export type TimeWindow = "day" | "night" | "custom";
export type WorkType = "excavation" | "non_excavation";
export type Direction = "citybound" | "outbound" | "both";
export type EdgeKey = [number, number, number];
export type LatLng = [number, number];

/** One independently drawn closure line with its own settings. Segments may share streets or points. */
export interface Segment {
  id: string;
  waypoints: LatLng[];
  edges: EdgeKey[]; // whole street segments touched: what impacts compute on
  geometry: LatLng[]; // the line as drawn, trimmed to the clicks
  length_m: number;
  road_name: string | null;
  road_class: string | null;
  speed_limit_kmh: number | null;
  targets: ClosureTarget[];
  direction: Direction;
  lanes_closed: number;
}

/** Where and what is closed lives on each segment; when and how the works run is shared by the plan. */
export interface ScenarioParams {
  name: string;
  segments: Segment[];
  start_date: string; // YYYY-MM-DD
  duration_days: number;
  time_window: TimeWindow;
  custom_hours: [number, number] | null;
  work_type: WorkType;
}

export interface PathResult {
  waypoints: LatLng[];
  edges: EdgeKey[];
  geometry: LatLng[];
  length_m: number; // of the drawn line
  road_name: string | null;
  road_class: string | null;
  speed_limit_kmh: number | null;
}

/** A published VicRoads count on one edge. Looked up, never computed; display only. */
export interface AadtRef {
  aadt: number; heavy: number | null; year: number; direction: string | null; both_directions: boolean;
  section: string | null; method: string | null; match_confidence: number | null; source: string | null;
}
export interface EdgeLoad { edge: EdgeKey; road_name: string | null; delta: number; geometry: LatLng[]; aadt: AadtRef | null }
// near: next to the works themselves, or on a street taking detour traffic
export interface Facility { name: string; kind: string; lat: number; lng: number; near: "works" | "detour" | null }
// through_trips_pct: share of all trips still driving through; slowdown_factor: travel-time multiplier, null = closed to vehicles
export interface SegmentTraffic { through_trips_pct: number; slowdown_factor: number | null }

export interface NetworkImpact {
  affected_trips_pct: number;
  avg_extra_min: number;
  max_extra_min: number;
  time_factor: number;
  full_closure: Record<string, boolean>; // per segment id. true: road closure, false: work zone
  rerouted_trips_pct: number; // of all trips: took another route
  slowed_trips_pct: number; // of all trips: kept their route, slower through a work zone or on a busier street
  unreachable_trips_pct: number; // had a route before the closure, none after; not in the delay stats
  segment_traffic: Record<string, SegmentTraffic>; // per segment id
  unmodelled_segments: string[]; // segment ids off the routed study area: not in these numbers
  load_increase: EdgeLoad[];
  ped_detour_m: number | null;
  ped_detour_basis: "footway" | "street_centreline" | null; // centreline = an over-estimate
  closed_aadt: Record<string, AadtRef>; // per segment id; absent where the road has no published count
  sensitive_facilities: Facility[];
  is_demo_data: boolean;
  note: string;
}

export interface AffectedRoute { route_id: string; short_name: string; mode: "tram" | "bus" | "train" | "other"; needs_replacement: boolean }
export interface NearbyStop { stop_id: string; name: string; lat: number; lng: number; distance_m: number; routes: string[] }
export interface TransitImpact { routes: AffectedRoute[]; stops: NearbyStop[]; is_demo_data: boolean; note: string | null }

/** Other permitted works from the DTP feed (a snapshot). Display only: nothing here enters a calculation. */
export interface Shift { weekday: number; start_h: number; hours: number } // weekday 0 = Monday; hours may pass midnight
export interface Disruption {
  id: string; permit: string; road_name: string | null; cross_street: string | null; cause: string | null;
  impact_type: string | null; direction: string | null; lanes_impacted: string | null; description: string | null;
  start: string; end: string; // ISO, Melbourne local time
  shifts: Shift[] | null; // null: the feed gives no daily hours
  lines: LatLng[][];
  edges: EdgeKey[]; // drive edges it lies on; empty if it did not match our streets
  distance_m: number; // nearest approach to the drawn works
  overlap: number; // share of our working hours inside its permitted hours, 0-1
  relevance: number; // overlap x closeness, a ranking only
  level: 0 | 1 | 2 | 3; // 0 = not at the same time; 3 = same time and close
}
export interface DisruptionsResult {
  available: boolean; // false: no snapshot on this machine, nothing shown
  fetched_at: string | null; source: string | null; disruptions: Disruption[]; note: string;
}

export interface EquipmentItem {
  item_id: string; name: string; supplier: string | null; qty: number; reason: string; stock: number;
  in_stock: boolean; daily_rate_aud: number; cost_aud: number;
}
export interface EquipmentResult {
  items: EquipmentItem[]; total_cost_aud: number; shortages: string[]; warnings: string[]; rules_verified: boolean; disclaimer: string;
}

export interface Placement {
  item_id: string; name: string; segment_id: string; lat: number; lng: number; reason: string; in_stock: boolean;
}
export interface EquipmentLayout { placements: Placement[]; note: string }

export interface Comms { vms_messages: string[][]; public_notice_md: string; generated_by: "template" | "llm"; disclaimer: string }
/** The only fields a description may pre-fill; null = not found. Location and speed are never pre-filled. */
export interface ParsedFields {
  road_name: string | null; // shown, not applied
  targets: ClosureTarget[] | null; // these three go to the segment being edited
  direction: Direction | null;
  lanes_closed: number | null;
  start_date: string | null; // the rest go to the plan
  duration_days: number | null;
  time_window: TimeWindow | null;
  work_type: WorkType | null;
}
export interface ParseResult { fields: ParsedFields; missing: string[] }
