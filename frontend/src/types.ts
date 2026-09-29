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

export interface EdgeLoad { edge: EdgeKey; road_name: string | null; delta: number; geometry: LatLng[] }
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
  slowed_trips_pct: number; // of all trips: kept their route, slower through a work zone
  segment_traffic: Record<string, SegmentTraffic>; // per segment id
  unmodelled_segments: string[]; // segment ids off the routed study area: not in these numbers
  load_increase: EdgeLoad[];
  ped_detour_m: number | null;
  sensitive_facilities: Facility[];
  is_demo_data: boolean;
  note: string;
}

export interface AffectedRoute { route_id: string; short_name: string; mode: "tram" | "bus" | "train" | "other"; needs_replacement: boolean }
export interface NearbyStop { stop_id: string; name: string; lat: number; lng: number; distance_m: number }
export interface TransitImpact { routes: AffectedRoute[]; stops: NearbyStop[]; is_demo_data: boolean; note: string | null }

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
