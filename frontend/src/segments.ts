import type { ScenarioParams, Segment, TimeWindow, WorkType } from "./types";

/** Segments with a line on the map (two or more points). Only these go to the impact modules. */
export const drawnSegments = (s: ScenarioParams) => s.segments.filter((g) => g.edges.length > 0);

export function newSegment(s: ScenarioParams): Segment {
  const last = s.segments[s.segments.length - 1];
  const id = String(Math.max(0, ...s.segments.map((g) => Number(g.id) || 0)) + 1);
  return {
    id, name: null, waypoints: [], edges: [], geometry: [], length_m: 0, road_name: null, road_class: null, speed_limit_kmh: null,
    // Start from the previous segment's settings: consecutive segments are usually the same kind of works.
    targets: last ? [...last.targets] : ["traffic_lane"],
    direction: last?.direction ?? "citybound",
    lanes_closed: last?.lanes_closed ?? 1,
    ...timing(last ?? null, s), // same dates and hours as the previous segment until the user changes them
  };
}

// ---------- timing: each segment has its own dates and hours ----------
export interface Timing {
  start_date: string; duration_days: number; time_window: TimeWindow; custom_hours: [number, number] | null; work_type: WorkType;
}

/** A segment's own timing, falling back to the plan's for anything it does not set. */
export function timing(g: Segment | null, s: ScenarioParams): Timing {
  return {
    start_date: g?.start_date ?? s.start_date,
    duration_days: g?.duration_days ?? s.duration_days,
    time_window: g?.time_window ?? s.time_window,
    custom_hours: g?.time_window ? g.custom_hours ?? null : s.custom_hours,
    work_type: g?.work_type ?? s.work_type,
  };
}

const MS_DAY = 86_400_000;
const toUtc = (d: string) => Date.parse(`${d}T00:00:00Z`);
export const addDays = (d: string, n: number) => new Date(toUtc(d) + n * MS_DAY).toISOString().slice(0, 10);
export const daysBetween = (a: string, b: string) => Math.round((toUtc(b) - toUtc(a)) / MS_DAY);
export const lastDay = (t: Timing) => addDays(t.start_date, t.duration_days - 1);

/** Is this segment's work on site on `day`? */
export function worksOn(g: Segment, s: ScenarioParams, day: string): boolean {
  const t = timing(g, s);
  return t.start_date <= day && day <= lastDay(t);
}

/** The plan-level timing implied by its segments: first day to last day, and the hours the modules
 *  that read one plan (equipment, messages, other works) should assume. Mixed hours count as night,
 *  so lighting is never left off the equipment list. */
export function envelope(s: ScenarioParams): Pick<ScenarioParams, "start_date" | "duration_days" | "time_window" | "custom_hours" | "work_type"> | null {
  if (s.segments.length === 0) return null;
  const ts = s.segments.map((g) => timing(g, s));
  const start = ts.map((t) => t.start_date).sort()[0];
  const end = ts.map(lastDay).sort().reverse()[0];
  const windows = [...new Set(ts.map((t) => t.time_window))];
  const time_window: TimeWindow = windows.length === 1 ? windows[0] : windows.includes("night") ? "night" : windows[0];
  return {
    start_date: start,
    duration_days: daysBetween(start, end) + 1,
    time_window,
    custom_hours: time_window === "custom" ? ts.find((t) => t.time_window === "custom")!.custom_hours ?? [10, 14] : null,
    work_type: ts.some((t) => t.work_type === "excavation") ? "excavation" : "non_excavation",
  };
}

/** Fill in every segment's timing from the plan, e.g. for a scenario that came from the API. */
export const withSegmentTiming = (s: ScenarioParams): ScenarioParams =>
  ({ ...s, segments: s.segments.map((g) => ({ ...g, ...timing(g, s) })) });

/** Which day (and, if segments on it run different hours, which hours) the map is showing. null = the whole plan. */
export interface DayView { day: string; window: TimeWindow | null }

/** The segments on site on the viewed day and hours: what the traffic model should see. */
export function onSite(s: ScenarioParams, view: DayView | null): Segment[] {
  const segs = drawnSegments(s);
  if (!view) return segs;
  const today = segs.filter((g) => worksOn(g, s, view.day));
  return view.window ? today.filter((g) => timing(g, s).time_window === view.window) : today;
}

/** The automatic name: what the segment is called until the user types one. */
export const autoName = (g: Segment) => `Segment ${g.id}${g.road_name ? ` · ${g.road_name}` : ""}`;

/** What to call a segment everywhere in the UI: the user's name if they typed one. */
export const segmentLabel = (g: Segment) => g.name?.trim() || autoName(g);

/** The plan's segments as the impact modules want them: one entry per drawn segment, each with ONLY
 *  the fields that module depends on, normalised so equal plans give equal request keys. The backend
 *  merges them (stronger effect wins where they overlap). */
export function toModuleRequests(s: ScenarioParams, view: DayView | null = null) {
  const segs = drawnSegments(s);
  if (segs.length === 0) return { network: null, transit: null, equipment: null, layout: null, disruptions: null };
  // Traffic and transit see only what is on site on the viewed day: a different set of segments is just
  // another cached request, so stepping through days never recomputes a day already seen.
  const live = onSite(s, view);
  const hours = view && live.length > 0 ? timing(live[0], s) : { time_window: s.time_window, custom_hours: s.custom_hours };
  const targets = (g: Segment) => [...g.targets].sort();
  const equipmentSeg = (g: Segment) => ({
    id: g.id, edges: g.edges, targets: targets(g), direction: g.direction, lanes_closed: g.lanes_closed,
    length_m: Math.max(1, Math.round(g.length_m)), speed_limit_kmh: g.speed_limit_kmh, road_class: g.road_class,
  });
  const plan = {
    duration_days: s.duration_days, time_window: s.time_window, work_type: s.work_type,
    custom_hours: s.time_window === "custom" ? s.custom_hours : null,  // night lighting for custom hours
  };
  return {
    network: live.length === 0 ? null : {
      segments: live.map((g) => ({ id: g.id, edges: g.edges, targets: targets(g), direction: g.direction, lanes_closed: g.lanes_closed })),
      time_window: hours.time_window,
      // Only when custom: hours that touch a peak pick the peak volumes. Re-runs the volume lookup, never routing.
      custom_hours: hours.time_window === "custom" ? hours.custom_hours : null,
    },
    transit: live.length === 0 ? null : { segments: live.map((g) => ({ edges: g.edges, targets: targets(g) })) },
    equipment: { segments: segs.map(equipmentSeg), ...plan },
    // Same inputs plus where each segment is: moving a line re-places items without recounting them.
    layout: { segments: segs.map((g) => ({ ...equipmentSeg(g), geometry: g.geometry })), ...plan },
    // Where and when only: other permits do not depend on lanes or targets. A cheap lookup, never routing.
    disruptions: {
      works: segs.flatMap((g) => g.geometry),
      start_date: s.start_date, duration_days: s.duration_days, time_window: s.time_window,
      custom_hours: s.time_window === "custom" ? s.custom_hours : null,
    },
  };
}
