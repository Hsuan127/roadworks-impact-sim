// Mirrors backend/app/schemas.py — keep in sync.
export type ClosureTarget = "traffic_lane" | "bike_lane" | "footpath" | "full";
export type TimeWindow = "day" | "night" | "custom";
export type WorkType = "excavation" | "non_excavation";
export type Direction = "citybound" | "outbound" | "both";
export type EdgeKey = [number, number, number];
export type LatLng = [number, number];

export interface Location {
  lat: number;
  lng: number;
  edge: EdgeKey | null;
  road_name: string | null;
  road_class: string | null;
}

export interface ScenarioParams {
  name: string;
  location: Location;
  targets: ClosureTarget[];
  direction: Direction;
  lanes_closed: number;
  work_length_m: number;
  start_date: string; // YYYY-MM-DD
  duration_days: number;
  time_window: TimeWindow;
  custom_hours: [number, number] | null;
  /** Where the work zone starts along the snapped road, metres from the edge's u end. */
  closure_offset_m?: number;
  speed_limit_kmh: number | null;
  work_type: WorkType;
}

export interface SnapResult {
  edge: EdgeKey;
  road_name: string | null;
  lat: number;
  lng: number;
  speed_limit_kmh: number | null;
  road_class: string | null;
  geometry: LatLng[];
}

/** A published traffic count. Looked up, never computed. */
export interface AadtRef {
  aadt: number;
  heavy: number | null;
  year: number;
  direction: string | null;
  both_directions: boolean;
  section: string | null;
  method: string | null; // "Actual" (measured) or "Estimated"
  match_confidence: number | null;
  source: string | null;
}

export interface EdgeLoad {
  edge: EdgeKey;
  road_name: string | null;
  /** Share of REROUTED trips that use this street, e.g. 0.35 = 35 % of them. */
  delta: number;
  geometry: LatLng[];
  aadt: AadtRef | null;
}
export interface Facility { name: string; kind: string; lat: number; lng: number }

export interface NetworkImpact {
  /** Share of routable trips that reroute OR get slower. */
  affected_trips_pct: number;
  /** Share that must take a different route. */
  rerouted_trips_pct: number;
  /** Had a route before the closure, has none after. Excluded from the delay stats. */
  unreachable_trips_pct: number;
  avg_extra_min: number;
  max_extra_min: number;
  time_factor: number;
  /** The whole edges routing actually removed or penalised. */
  closed_geometry: LatLng[];
  /** The physical dig, clipped to offset_m..+length_m. Narrower than closed_geometry. */
  work_zone_geometry: LatLng[];
  closed_edges: EdgeKey[];
  /** The run of road the work zone can be dragged along. */
  corridor_geometry: LatLng[];
  /** Where the corridor starts relative to the anchor edge; negative means it begins before it. */
  corridor_start_m: number;
  /** Grid the work zone snapped to, so the map can draw what was really modelled. */
  closure_quantum_m: number;
  closed_aadt: AadtRef | null;
  load_increase: EdgeLoad[];
  ped_detour_m: number | null;
  ped_detour_basis: string | null; // "footway" | "street_centreline"
  sensitive_facilities: Facility[];
  is_demo_data: boolean;
  note: string;
}

export interface AffectedRoute { route_id: string; short_name: string; mode: "tram" | "bus" | "train" | "other"; needs_replacement: boolean }
export interface NearbyStop { stop_id: string; name: string; lat: number; lng: number; distance_m: number }
export interface TransitImpact { routes: AffectedRoute[]; stops: NearbyStop[]; is_demo_data: boolean }

export interface EquipmentItem {
  item_id: string; name: string; qty: number; reason: string; stock: number;
  in_stock: boolean; daily_rate_aud: number; cost_aud: number;
}
export interface EquipmentResult {
  items: EquipmentItem[]; total_cost_aud: number; shortages: string[]; rules_verified: boolean; disclaimer: string;
}

export interface Comms { vms_messages: string[][]; public_notice_md: string; generated_by: "template" | "llm"; disclaimer: string }
export interface ParseResult { fields: Partial<ScenarioParams> & { road_name?: string }; missing: string[] }
