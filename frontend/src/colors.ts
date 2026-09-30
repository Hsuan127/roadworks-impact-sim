// Map colours (Leaflet sets SVG attributes, which cannot read CSS variables). Keep in sync with styles.css.
export const COLORS = {
  asphalt: "#2B3034",
  works: "#E8631A", // full road closure
  workZone: "#F2B705", // partial: traffic still passes
  detour: "#1D5FD1",
  tram: "#3C8A2E",
  alert: "#C8102E",
};

// Other planned works by relevance level (0 = not at the same time ... 3 = same time and close).
// Greys, so they sit behind the closure and detours and never read as our own results.
export const OTHER_WORKS = [
  { color: "#8E959B", weight: 3, opacity: 0.85, dashArray: "5 5" },
  { color: "#6B7278", weight: 5, opacity: 0.9 },
  { color: "#3A3F43", weight: 6, opacity: 0.95 },
  { color: "#0B0D0E", weight: 7, opacity: 1 },
] as const;
