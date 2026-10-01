import type { Person } from "./types";

const PALETTE = ["#1D5FD1", "#3C8A2E", "#C8102E", "#7B3FB5", "#D9661F", "#0F8A8A"];
const KEY = "roadworks.me";
// Demo cast: whoever starts a plan is Sam, whoever opens the shared link is Luca, then the next free name.
// Fixed colours so the demo's two avatars never hash to the same one.
const CAST: Record<string, string> = { Sam: "#1D5FD1", Luca: "#C8102E", Mia: "#3C8A2E", Ravi: "#7B3FB5" };

export const colorFor = (name: string) =>
  CAST[name] ?? PALETTE[[...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % PALETTE.length];

/** Who is in this tab. Kept per tab (sessionStorage), so two tabs in one browser are two people and
 *  a reload keeps the name. `null` when this tab has not been given one yet. */
export function savedMe(): Person | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) ?? "null");
    if (saved?.name) return { name: saved.name, color: colorFor(saved.name) };
  } catch { /* storage blocked: the caller picks a demo name */ }
  return null;
}

/** The first demo name nobody in `taken` is using: Sam, then Luca, and so on. */
export const castName = (taken: string[]) =>
  Object.keys(CAST).find((n) => !taken.includes(n)) ?? `Planner ${taken.length + 1}`;

export function saveMe(name: string): Person {
  const me = { name, color: colorFor(name) };
  try { sessionStorage.setItem(KEY, JSON.stringify(me)); } catch { /* not remembered; still works */ }
  return me;
}

export const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
