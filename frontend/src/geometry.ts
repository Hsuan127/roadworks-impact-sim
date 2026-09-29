import type { LatLng } from "./types";

/** Same local equirectangular approximation as backend/app/geo.py, so both agree on "metres". */
function metres(a: LatLng, b: LatLng): number {
  const kx = 111_320 * Math.cos((((a[0] + b[0]) / 2) * Math.PI) / 180);
  const ky = 110_540;
  return Math.hypot((b[1] - a[1]) * kx, (b[0] - a[0]) * ky);
}

export function polylineLength(pts: LatLng[]): number {
  let total = 0;
  for (let i = 0; i < pts.length - 1; i++) total += metres(pts[i], pts[i + 1]);
  return total;
}

/**
 * How far along `pts` the nearest point to `p` lies, in metres from the start.
 * Lets a dragged handle be turned into a work-zone offset without a server round trip, so the
 * gesture stays smooth and only the final position is sent.
 */
export function projectOntoPolyline(p: LatLng, pts: LatLng[]): number {
  let best = 0;
  let bestDist = Infinity;
  let acc = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    const seg = metres(a, b);
    if (seg > 0) {
      const kx = 111_320 * Math.cos((a[0] * Math.PI) / 180);
      const ky = 110_540;
      const ax = 0;
      const ay = 0;
      const bx = (b[1] - a[1]) * kx;
      const by = (b[0] - a[0]) * ky;
      const px = (p[1] - a[1]) * kx;
      const py = (p[0] - a[0]) * ky;
      const dx = bx - ax;
      const dy = by - ay;
      const t = Math.max(0, Math.min(1, (px * dx + py * dy) / (dx * dx + dy * dy)));
      const dist = Math.hypot(ax + t * dx - px, ay + t * dy - py);
      if (dist < bestDist) {
        bestDist = dist;
        best = acc + t * seg;
      }
    }
    acc += seg;
  }
  return best;
}
