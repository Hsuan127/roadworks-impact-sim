import type { Disruption, EdgeKey, NetworkImpact, Segment } from "./types";

const clock = (h: number) => {
  const m = Math.round((((h % 24) + 24) % 24) * 60);
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};

/** "21:00–05:00", or the most common shift plus "and other hours" when a permit lists several. */
export function permitHours(d: Disruption): string {
  if (!d.shifts) return "hours not published";
  if (d.shifts.some((s) => s.hours >= 24)) return "all day";
  const counts = new Map<string, number>();
  for (const s of d.shifts) {
    const k = `${clock(s.start_h)}–${clock(s.start_h + s.hours)}`;
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const [top] = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  return counts.size > 1 ? `${top[0]} and other hours` : top[0];
}

export const permitDates = (d: Disruption) => {
  const f = (iso: string) => new Date(iso).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
  return `${f(d.start)} – ${f(d.end)}`;
};

export const LEVEL_LABEL = ["Not at the same time", "Same time, further away", "Same time, nearby", "Same time, close"] as const;

// Undirected: a permit on one side of a two-way street and our detour on the other still share the street.
const street = ([u, v]: EdgeKey) => (u < v ? `${u}-${v}` : `${v}-${u}`);

/** One entry per permit (a permit has many sections), most relevant section first. */
function byPermit(ds: Disruption[]): Disruption[] {
  const seen = new Set<string>();
  return ds.filter((d) => !seen.has(d.permit) && seen.add(d.permit));
}

/** Concurrent permits on the streets we close, and on streets our detour loads. Set intersection on
 *  edges, no modelling: a permit only says works may run then, so these are prompts to check, not facts. */
export function conflicts(ds: Disruption[], segments: Segment[], net: NetworkImpact | null) {
  const concurrent = ds.filter((d) => d.level > 0);
  const works = new Set(segments.flatMap((g) => g.edges.map(street)));
  const detour = new Set((net?.load_increase ?? []).map((l) => street(l.edge)));
  return {
    onWorks: byPermit(concurrent.filter((d) => d.edges.some((e) => works.has(street(e))))),
    onDetour: byPermit(concurrent.filter((d) => d.edges.some((e) => detour.has(street(e))))),
    concurrentPermits: byPermit(concurrent).length,
  };
}
