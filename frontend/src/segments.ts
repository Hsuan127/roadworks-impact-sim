import type { ScenarioParams, Segment } from "./types";

/** Segments with a line on the map (two or more points). Only these go to the impact modules. */
export const drawnSegments = (s: ScenarioParams) => s.segments.filter((g) => g.edges.length > 0);

export function newSegment(s: ScenarioParams): Segment {
  const last = s.segments[s.segments.length - 1];
  const id = String(Math.max(0, ...s.segments.map((g) => Number(g.id) || 0)) + 1);
  return {
    id, waypoints: [], edges: [], geometry: [], length_m: 0, road_name: null, road_class: null, speed_limit_kmh: null,
    // Start from the previous segment's settings: consecutive segments are usually the same kind of works.
    targets: last ? [...last.targets] : ["traffic_lane"],
    direction: last?.direction ?? "citybound",
    lanes_closed: last?.lanes_closed ?? 1,
  };
}

/** The plan's segments as the impact modules want them: one entry per drawn segment, each with ONLY
 *  the fields that module depends on, normalised so equal plans give equal request keys. The backend
 *  merges them (stronger effect wins where they overlap). */
export function toModuleRequests(s: ScenarioParams) {
  const segs = drawnSegments(s);
  if (segs.length === 0) return { network: null, transit: null, equipment: null, layout: null };
  const targets = (g: Segment) => [...g.targets].sort();
  const equipmentSeg = (g: Segment) => ({
    targets: targets(g), direction: g.direction, lanes_closed: g.lanes_closed,
    length_m: Math.max(1, Math.round(g.length_m)), speed_limit_kmh: g.speed_limit_kmh, road_class: g.road_class,
  });
  const plan = { duration_days: s.duration_days, time_window: s.time_window, work_type: s.work_type };
  return {
    network: {
      segments: segs.map((g) => ({ id: g.id, edges: g.edges, targets: targets(g), direction: g.direction, lanes_closed: g.lanes_closed })),
      time_window: s.time_window,
    },
    transit: { segments: segs.map((g) => ({ edges: g.edges, targets: targets(g) })) },
    equipment: { segments: segs.map(equipmentSeg), ...plan },
    // Same inputs plus where each segment is: moving a line re-places items without recounting them.
    layout: { segments: segs.map((g) => ({ ...equipmentSeg(g), id: g.id, geometry: g.geometry, edges: g.edges })), ...plan },
  };
}
