import type { Person } from "./types";

const PALETTE = ["#1D5FD1", "#3C8A2E", "#C8102E", "#7B3FB5", "#D9661F", "#0F8A8A"];
const KEY = "roadworks.me";

export const colorFor = (name: string) =>
  PALETTE[[...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % PALETTE.length];

/** Who is at this browser, for shared plans. Remembered per browser; falls back to a plain name. */
export function loadMe(): Person {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (saved?.name) return { name: saved.name, color: colorFor(saved.name) };
  } catch { /* storage blocked: use the default */ }
  return { name: "Planner", color: colorFor("Planner") };
}

export function saveMe(name: string): Person {
  const me = { name, color: colorFor(name) };
  try { localStorage.setItem(KEY, JSON.stringify(me)); } catch { /* not remembered; still works */ }
  return me;
}

export const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
