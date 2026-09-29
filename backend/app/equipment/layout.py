"""Where each piece of equipment stands on the map (owner: P4).

Quantities come from rules.compute_segment; this module only places exactly that many of each,
so the map and the equipment list always agree. The layout is schematic: kerb-side lane(s) closed,
driving on the left, lane widths assumed. It is for checking quantities, not a traffic guidance scheme.
"""
from __future__ import annotations

import math

from ..geo import locate_on_polyline, polyline_length_m, slice_polyline
from ..graph import edge_geometry, edge_lanes, extend_line, load_graph, reverse_edge
from ..schemas import ClosureTarget, EquipmentLayout, EquipmentRequest, LayoutRequest, LayoutSegment, Placement
from .rules import compute_segment, equipment, load_rules, taper_length

Pt = tuple[float, float]


class Approach:
    """One direction of traffic past the works. Chainage s is metres from the start of the work zone
    (negative = upstream); lateral offset is metres left of the road centreline."""

    def __init__(self, line: list[Pt], zone_start: float):
        self.line, self.zone_start = line, zone_start
        self.total = polyline_length_m(line)

    def at(self, s: float, left_m: float) -> Pt:
        c = min(max(self.zone_start + s, 0.0), self.total)
        piece = slice_polyline(self.line, max(0.0, c - 1), min(self.total, c + 1))
        (a_lat, a_lng), (b_lat, b_lng) = piece[0], piece[-1]
        p = slice_polyline(self.line, c, c)[0]
        kx = 111_320 * math.cos(math.radians(p[0]))
        dx, dy = (b_lng - a_lng) * kx, (b_lat - a_lat) * 110_540
        n = math.hypot(dx, dy) or 1.0
        nx_, ny = -dy / n, dx / n  # left of travel
        return (p[0] + ny * left_m / 110_540, p[1] + nx_ * left_m / kx)


def _approach(G, geometry: list[Pt], first, last, up_m: float, down_m: float) -> Approach:
    g_first, g_last = edge_geometry(G, first), edge_geometry(G, last)
    before = slice_polyline(g_first, 0, locate_on_polyline(g_first, *geometry[0]))
    after = slice_polyline(g_last, locate_on_polyline(g_last, *geometry[-1]), polyline_length_m(g_last))
    up = extend_line(G, first, forward=False, need_m=up_m) + before
    down = after + extend_line(G, last, forward=True, need_m=down_m)
    line = up + geometry[1:-1] + down if up and down else (up or [geometry[0]]) + geometry[1:-1] + (down or [geometry[-1]])
    return Approach(line, polyline_length_m(up or [geometry[0]]))


def _spread(n: int, a: float, b: float) -> list[float]:
    return [(a + b) / 2] if n == 1 else [a + (b - a) * k / (n - 1) for k in range(n)]


def layout_segment(seg: LayoutSegment, req: LayoutRequest) -> list[tuple[str, str, Pt]]:
    """(item_id, reason, position) for every single item of one segment."""
    G = load_graph()
    r = load_rules()
    lines = compute_segment(seg, req)
    edges = [tuple(e) for e in seg.edges]
    speed = seg.speed_limit_kmh or r["default_speed_kmh"]
    taper = taper_length(r, speed)
    gap, lane = r["sign_spacing_m"], r["lane_width_m"]
    before_signs = max([int(p.split(":")[3]) - 1 for _, _, _, p in lines if p.startswith("sign:")] + [3])
    vms_at = -(taper + (before_signs + 1) * gap)
    L = seg.length_m

    approaches = [_approach(G, seg.geometry, edges[0], edges[-1], -vms_at + 20, r["end_sign_gap_m"] + 20)]
    if seg.direction == "both":
        rev_first, rev_last = reverse_edge(G, edges[-1]), reverse_edge(G, edges[0])
        if rev_first and rev_last:
            approaches.append(_approach(G, seg.geometry[::-1], rev_first, rev_last, -vms_at + 20, r["end_sign_gap_m"] + 20))

    lanes = edge_lanes(G, edges[0])
    kerb = lanes * lane  # left edge of the carriageway for this direction
    full = ClosureTarget.full in seg.targets or seg.lanes_closed >= lanes
    closed_to = 0.3 if full else kerb - seg.lanes_closed * lane  # cone line between closed and open lanes

    out: list[tuple[str, str, Pt]] = []
    for item, qty, reason, where in lines:
        per = [a for a in approaches][: qty] if where in ("vms", "arrow") or where.startswith("sign:") else None
        if where.startswith("sign:"):
            _, target, i, n = where.split(":")
            i, n = int(i), int(n)
            is_end = target in ("traffic_lane", "full") and i == n - 1
            s = L + r["end_sign_gap_m"] if is_end else (
                -(taper + (n - 1 - i) * gap) if target in ("traffic_lane", "full") else -gap / 2)
            pts = [a.at(s, kerb + 1.5) for a in per]
        elif where == "vms":
            pts = [a.at(vms_at, kerb + 2) for a in per]
        elif where == "arrow":
            pts = [a.at(-5, (kerb + closed_to) / 2) for a in per]
        elif where == "taper":
            each = qty // len(approaches)
            pts = [a.at(s, kerb + (closed_to - kerb) * (s + taper) / taper)
                   for a in approaches for s in _spread(each, -taper, 0)]
        elif where == "work_zone":
            pts = [approaches[0].at(s, closed_to) for s in _spread(qty, 0, L)]
        elif where == "barrier":
            b = r["barrier_end_buffer_m"]
            pts = [approaches[0].at(s, closed_to + 0.8) for s in _spread(qty, -b, L + b)]
        elif where == "footpath":
            pts = [approaches[0].at(s, kerb + 2.5) for s in _spread(qty, 0, L)]
        else:  # lighting
            pts = [approaches[0].at(s, kerb + 1.5) for s in _spread(qty, 0, L)]
        # A one-way street marked "both" has one approach: place what exists, never invent extra.
        out += [(item, reason, p) for p in pts[:qty]]
    return out


def equipment_layout(req: LayoutRequest) -> EquipmentLayout:
    stock = {i.item_id: i for i in equipment(EquipmentRequest(**req.model_dump())).items}
    placements = []
    for seg in req.segments:
        for item, reason, (lat, lng) in layout_segment(seg, req):
            info = stock[item]
            placements.append(Placement(item_id=item, name=info.name, segment_id=seg.id, lat=lat, lng=lng,
                                        reason=reason, in_stock=info.in_stock))
    return EquipmentLayout(placements=placements)
