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

export interface EdgeLoad { edge: EdgeKey; road_name: string | null; delta: number; geometry: LatLng[] }
export interface Facility { name: string; kind: string; lat: number; lng: number }

export interface NetworkImpact {
  affected_trips_pct: number;
  avg_extra_min: number;
  max_extra_min: number;
  time_factor: number;
  closed_geometry: LatLng[];
  load_increase: EdgeLoad[];
  ped_detour_m: number | null;
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
