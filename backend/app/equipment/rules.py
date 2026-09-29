"""Rule-based equipment calculator (owner: P4).

Quantities come ONLY from rules.yaml + deterministic code. The LLM never decides a quantity.
Each rule names the table or clause it follows; see the source list at the top of rules.yaml.
"""
from __future__ import annotations

import csv
import math
from functools import lru_cache
from pathlib import Path

import yaml

from ..graph import edge_lanes, is_two_way, load_graph
from ..schemas import (ClosureTarget, EquipmentItem, EquipmentRequest, EquipmentResult, EquipmentSegment,
                       TimeWindow, WorkType)

HERE = Path(__file__).parent


@lru_cache(maxsize=1)
def load_rules() -> dict:
    return yaml.safe_load((HERE / "rules.yaml").read_text())


@lru_cache(maxsize=1)
def load_inventory() -> dict[str, dict]:
    with open(HERE / "inventory.csv", newline="") as f:
        return {r["item_id"]: {"name": r["name"], "supplier": r["supplier"], "stock": int(r["stock"]),
                               "rate": float(r["daily_rate_aud"])}
                for r in csv.DictReader(f)}


@lru_cache(maxsize=1)
def load_volumes() -> list[dict]:
    return yaml.safe_load((HERE / "traffic_volumes.yaml").read_text())["sites"]


def band(table: dict, x: float):
    """Value of the band `x` falls in. Keys are each band's upper bound; None above the last band."""
    return next((v for top, v in sorted((float(k), v) for k, v in table.items()) if x <= top), None)


def by_speed(rules: dict, name: str, speed: float) -> float:
    """A speed table from rules.yaml; above its last band, `<name>_above_factor` x speed."""
    value = band(rules[name], speed)
    return value if value is not None else rules[f"{name}_above_factor"] * speed


def taper_length(rules: dict, speed: int) -> float:
    """One merge taper (AGTTM Part 3 Table 5.7)."""
    return by_speed(rules, "taper_length_m", speed)


def speed_of(seg: EquipmentSegment) -> int:
    return seg.speed_limit_kmh or load_rules()["default_speed_kmh"]


def lanes_each_way(seg: EquipmentSegment) -> int:
    """Lanes on the carriageway being worked on, in the segment's direction of travel."""
    return edge_lanes(load_graph(), tuple(seg.edges[0]))


def approach_count(seg: EquipmentSegment) -> int:
    """Directions of traffic driving into the works. A one-way street has one, even when marked "both"."""
    return 2 if seg.direction == "both" and is_two_way(load_graph(), [tuple(e) for e in seg.edges]) else 1


def closes_direction(seg: EquipmentSegment) -> bool:
    """No lane left open for traffic. Signed as a road closure, as the network model treats it."""
    return ClosureTarget.full in seg.targets or (
        ClosureTarget.traffic_lane in seg.targets and seg.lanes_closed >= lanes_each_way(seg))


def traffic_alongside(seg: EquipmentSegment) -> bool:
    """Traffic still drives past the works: in an open lane, or the other way on a two-way street."""
    return not closes_direction(seg) or (
        seg.direction != "both" and is_two_way(load_graph(), [tuple(e) for e in seg.edges]))


def transition(seg: EquipmentSegment) -> tuple[float, float]:
    """(taper_m, buffer_m) upstream of the work area on each approach. One merge taper per closed lane,
    with a gap between tapers (AGTTM Tables 5.7, 5.8), then the safety buffer (AGTTM 5.6)."""
    r = load_rules()
    if ClosureTarget.traffic_lane not in seg.targets or closes_direction(seg):
        return 0.0, 0.0
    speed, n = speed_of(seg), seg.lanes_closed
    taper = n * taper_length(r, speed) + (n - 1) * by_speed(r, "taper_gap_m", speed)
    buffer = r["safety_buffer_m"] if speed >= r["safety_buffer_min_speed_kmh"] else 0.0
    return taper, buffer


def sign_spacing(seg: EquipmentSegment) -> float:
    return by_speed(load_rules(), "sign_spacing_m", speed_of(seg))  # AGTTM Table 2.2


def sign_sides(seg: EquipmentSegment) -> int:
    """AS 1742.3 4.3.2: signs on both sides of the roadway on multilane roads."""
    return 2 if load_rules()["signs_both_sides_multilane"] and lanes_each_way(seg) >= 2 else 1


def barrier_run(seg: EquipmentSegment) -> tuple[float, float, int]:
    """(start_m, end_m, units) of the water-filled barrier's standard units, in metres from the start of
    the work zone: ArmorZone lead-in and lead-out, stretched evenly to the minimum length of need."""
    r = load_rules()
    start, end = -r["barrier_lead_in_m"], seg.length_m + r["barrier_lead_out_m"]
    short = r["barrier_min_length_m"] - (end - start)
    if short > 0:
        start, end = start - short / 2, end + short / 2
    return start, end, math.ceil((end - start) / r["barrier_segment_length_m"])


def site_volumes(seg: EquipmentSegment) -> list[dict]:
    """Measured volumes (traffic_volumes.yaml) for the segment's road, in each direction it closes."""
    d = load_graph().edges[tuple(seg.edges[0])]
    name = d.get("name")
    name = name[0] if isinstance(name, list) else name
    directions = ("citybound", "outbound") if seg.direction == "both" else (seg.direction,)
    return [s for s in load_volumes() if s["road_name"] == name and s["direction"] in directions]


def excavation_option(seg: EquipmentSegment) -> int:
    """AGTTM Part 3 Table 6.1: 1 = cones at normal spacing, 2 = cones at 4 m, 3 = road safety barrier."""
    r = load_rules()
    table, speed = r["excavation_protection"], speed_of(seg)
    if speed <= table["low_speed"]["max_speed_kmh"]:
        rows = table["low_speed"]["rows"]
    else:
        vpd = max((s.get("veh_per_day", 0) for s in site_volumes(seg)), default=None)
        low = vpd is not None and vpd <= table["high_speed_low_volume"]["max_vpd"]  # unknown volume: assume high
        rows = table["high_speed_low_volume" if low else "high_speed_high_volume"]["rows"]
    depth = r["excavation_depth_mm"]
    col = 0 if depth <= 250 else 1 if depth <= 500 else 2
    return next(options[col] for top, options in rows if top is None or r["excavation_clearance_m"] <= top)


def is_night(req: EquipmentRequest) -> bool:
    """Night works, or custom hours reaching into the night window."""
    if req.time_window == TimeWindow.night:
        return True
    if req.time_window != TimeWindow.custom or not req.custom_hours:
        return False
    start, end = load_rules()["night_hours"]
    night = set(range(start, 24)) | set(range(0, end))
    a, b = req.custom_hours
    return bool(night & (set(range(a, b)) if a < b else set(range(a, 24)) | set(range(0, b))))


def compute(req: EquipmentRequest) -> list[tuple[str, int, str]]:
    """Return (item_id, qty, reason) lines for the whole plan. Each segment is set up on its own
    (own signs, taper and work zone), so lines are prefixed with the segment id when there are several:
    the same label the map uses, even after other segments were deleted."""
    many = len(req.segments) > 1
    return [(item, qty, f"Segment {seg.id}: {reason}" if many else reason)
            for seg in req.segments for item, qty, reason, _ in compute_segment(seg, req)]


def compute_segment(seg: EquipmentSegment, req: EquipmentRequest) -> list[tuple[str, int, str, str]]:
    """Return (item_id, qty, reason, placement) lines for one segment.
    `placement` tells layout.py where that line's items stand, so the map and the list can't disagree."""
    r = load_rules()
    speed = speed_of(seg)
    approaches = approach_count(seg)
    closed = closes_direction(seg)
    merge = ClosureTarget.traffic_lane in seg.targets and not closed
    sides = sign_sides(seg)
    taper, buffer = transition(seg)
    lines: list[tuple[str, int, str, str]] = []

    def add(item: str, qty: int, reason: str, placement: str):
        if qty > 0:
            lines.append((item, qty, reason, placement))

    # Signs. Closing every lane is signed as a road closure.
    targets = dict.fromkeys(ClosureTarget.full if closed and t == ClosureTarget.traffic_lane else t for t in seg.targets)
    for t in targets:
        signs = r["advance_signs"].get(t.value, [])
        if t == ClosureTarget.footpath:
            per, why = 2, "one at each end of the closed footpath (AS 4.17)"
        elif t == ClosureTarget.bike_lane:
            per, why = approaches, f"{approaches} approach(es), for cyclists and drivers (AS Appendix A)"
        else:
            per = approaches * sides
            why = f"{approaches} approach(es) x {sides} side(s)" + (", multilane road (AS 4.3.2)" if sides == 2 else "")
        for i, sign in enumerate(signs):
            add(sign, per, why, f"sign:{t.value}:{i}:{len(signs)}")

    if closed:
        lanes = lanes_each_way(seg)
        boards = math.ceil(lanes * r["lane_width_m"] / r["barrier_board_length_m"])
        add("barrier_board", approaches * boards,
            f"bar all {lanes} lane(s) at ROAD CLOSED, {approaches} approach(es) (AS 4.10.1)", "road_closed")

    # Cones: merge taper(s) on each approach, then along the safety buffer and work zone
    option = excavation_option(seg) if req.work_type == WorkType.excavation and traffic_alongside(seg) else 1
    if merge:
        spacing = by_speed(r, "cone_spacing_m", speed)
        add("cone", approaches * (math.ceil(taper / spacing) + 1),
            f"{seg.lanes_closed} merge taper(s), {taper:.0f} m at {speed} km/h, every {spacing:g} m, "
            f"{approaches} approach(es) (AGTTM Tables 5.3, 5.7, 5.8)", "taper")
        if option == 2:
            spacing = r["option2_cone_spacing_m"]
        line = buffer + seg.length_m
        add("cone", math.ceil(line / spacing) + 1,
            f"{buffer:.0f} m safety buffer + {seg.length_m:.0f} m work zone, every {spacing:g} m (AGTTM 5.6, Table 5.3)",
            "work_zone")

    # Barrier where an excavation sits close to traffic (AGTTM Table 6.1, option 3)
    if option == 3 and speed <= r["barrier_max_speed_kmh"]:
        start, end, units = barrier_run(seg)
        add("barrier_water_filled", units,
            f"excavation next to traffic (AGTTM Table 6.1): {end - start:.0f} m run incl. "
            f"{r['barrier_lead_in_m']} m lead-in and {r['barrier_lead_out_m']} m lead-out (ArmorZone manual)", "barrier")
        add("barrier_end_treatment", 2 * r["barrier_end_units_per_end"],
            "end treatment at both ends of the barrier, not water-filled (ArmorZone manual 4.7)", "barrier_end")

    # Pedestrian fencing
    if ClosureTarget.footpath in seg.targets or req.work_type == WorkType.excavation:
        add("ped_fence", math.ceil(seg.length_m / r["ped_fence_panel_length_m"]),
            "separate pedestrians from the work area", "footpath")

    # VMS
    if (merge or closed) and ((seg.road_class or "") in r["vms_road_classes"] or lanes_each_way(seg) >= r["vms_min_lanes"]):
        add("vms_board", approaches, "advance warning on a major or multi-lane road (AS 4.22.2)", "vms")

    # Arrow board
    if merge and speed >= r["arrow_board_min_speed_kmh"]:
        add("arrow_board", approaches, f"lane closure at {speed} km/h (AGTTM 5.8: 60 km/h or above)", "arrow")

    # Lighting
    if is_night(req):
        lit = buffer + seg.length_m
        add("light_tower", math.ceil(lit / r["light_tower_coverage_m"]),
            f"light the whole {lit:.0f} m worksite at night (AGTTM 6.7), about {r['light_tower_coverage_m']} m per tower",
            "lighting")

    return lines


def segment_warnings(seg: EquipmentSegment, req: EquipmentRequest) -> list[str]:
    """Things the planner should change or check. Not quantities: those are in compute_segment."""
    r = load_rules()
    speed = speed_of(seg)
    out: list[str] = []

    if ClosureTarget.full not in seg.targets and closes_direction(seg):
        out.append(f"Closing {seg.lanes_closed} of {lanes_each_way(seg)} lane(s) leaves none open in this direction, "
                   "so it is signed as a road closure with a detour. The alternative is shuttle flow under "
                   "portable traffic signals (AGTTM 5.10.1).")

    if (req.work_type == WorkType.excavation and traffic_alongside(seg) and excavation_option(seg) == 3
            and speed > r["barrier_max_speed_kmh"]):
        out.append(f"The excavation needs a road safety barrier, but the water-filled barrier is only approved up to "
                   f"{r['barrier_max_speed_kmh']} km/h. Use a steel or concrete barrier, or lower the speed limit.")

    # Enough lanes left for the traffic in this time window? (AGTTM Table 2.4)
    if ClosureTarget.traffic_lane in seg.targets and not closes_direction(seg):
        for site in site_volumes(seg):
            vph = site["veh_per_hour"].get(req.time_window.value)
            if vph is None:
                continue
            table = r["open_lanes_near_signals" if site.get("near_signals") else "open_lanes_mid_block"]
            need = band(table, vph) or max(table.values()) + 1
            left = site["lanes"] - seg.lanes_closed
            if left < need:
                out.append(f"{site['road_name']} {site['direction']} carries about {vph:,} veh/h in this time window "
                           f"({site['statistic']}). AGTTM Table 2.4 recommends {need} open lanes; this closure "
                           f"leaves {left}. Consider night works or closing fewer lanes.")
    return out


def equipment(req: EquipmentRequest) -> EquipmentResult:
    rules, inv = load_rules(), load_inventory()
    lines = compute(req)
    totals: dict[str, int] = {}
    for item, qty, _ in lines:
        totals[item] = totals.get(item, 0) + qty

    items, shortages, total = [], [], 0.0
    for item, qty, reason in lines:
        meta = inv.get(item, {"name": item, "supplier": None, "stock": 0, "rate": 0.0})
        in_stock = totals[item] <= meta["stock"]
        cost = qty * meta["rate"] * req.duration_days
        total += cost
        items.append(EquipmentItem(item_id=item, name=meta["name"], supplier=meta["supplier"], qty=qty, reason=reason,
                                   stock=meta["stock"], in_stock=in_stock, daily_rate_aud=meta["rate"],
                                   cost_aud=round(cost, 2)))
        if not in_stock and meta["name"] not in shortages:
            shortages.append(meta["name"])

    many = len(req.segments) > 1
    warnings = [f"Segment {seg.id}: {w}" if many else w for seg in req.segments for w in segment_warnings(seg, req)]
    return EquipmentResult(
        items=items, total_cost_aud=round(total, 2), shortages=shortages, warnings=warnings,
        rules_verified=bool(rules.get("verified")),
        disclaimer=("Quantities follow AGTTM Part 3, AS 1742.3 and the barrier maker's manual. Values marked as "
                    "assumptions (product sizes, excavation depth) still need confirming. Depot stock is simulated "
                    "and hire rates are estimates from public Australian listings, not RPM Hire prices."
                    if not rules.get("verified") else "Quantities from verified rules; plan still needs sign-off."),
    )
