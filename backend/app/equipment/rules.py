"""Rule-based equipment calculator (owner: P4).

Quantities come ONLY from rules.yaml + deterministic code. The LLM never decides a quantity.
"""
from __future__ import annotations

import csv
import math
from functools import lru_cache
from pathlib import Path

import yaml

from ..schemas import ClosureTarget, EquipmentItem, EquipmentRequest, EquipmentResult, TimeWindow

HERE = Path(__file__).parent


@lru_cache(maxsize=1)
def load_rules() -> dict:
    return yaml.safe_load((HERE / "rules.yaml").read_text())


@lru_cache(maxsize=1)
def load_inventory() -> dict[str, dict]:
    with open(HERE / "inventory.csv", newline="") as f:
        return {r["item_id"]: {"name": r["name"], "stock": int(r["stock"]), "rate": float(r["daily_rate_aud"])}
                for r in csv.DictReader(f)}


def _taper_length(rules: dict, speed: int) -> float:
    table = {int(k): v for k, v in rules["taper_length_m"].items()}
    eligible = [s for s in table if s >= speed]
    return table[min(eligible)] if eligible else table[max(table)]


def compute(req: EquipmentRequest) -> list[tuple[str, int, str]]:
    """Return (item_id, qty, reason) lines. Pure function: easy to unit test."""
    r = load_rules()
    speed = req.speed_limit_kmh or r["default_speed_kmh"]
    approaches = 2 if req.direction == "both" else 1
    traffic = ClosureTarget.full in req.targets or ClosureTarget.traffic_lane in req.targets
    lines: list[tuple[str, int, str]] = []
    counts: dict[str, int] = {}

    def add(item: str, qty: int, reason: str):
        if qty > 0:
            lines.append((item, qty, reason))
            counts[item] = counts.get(item, 0) + qty

    # Advance signs per approach
    for t in req.targets:
        for sign in r["advance_signs"].get(t.value, []):
            add(sign, approaches, f"{approaches} approach(es) x 1 for {t.value.replace('_', ' ')}")

    # Cones: taper + work zone
    if traffic:
        taper = _taper_length(r, speed)
        taper_cones = math.ceil(taper / r["cone_spacing_m"]["taper"]) + 1
        wz_cones = math.ceil(req.work_length_m / r["cone_spacing_m"]["work_zone"]) + 1
        add("cone", approaches * taper_cones, f"taper {taper:.0f} m at {speed} km/h, {approaches} approach(es)")
        add("cone", wz_cones, f"work zone {req.work_length_m:.0f} m")

    # Barriers for excavation
    if req.work_type.value == "excavation":
        length = req.work_length_m + 2 * r["barrier_end_buffer_m"]
        add("barrier_water_filled", math.ceil(length / r["barrier_segment_length_m"]),
            f"excavation protection over {length:.0f} m")

    # Pedestrian fencing
    if ClosureTarget.footpath in req.targets or req.work_type.value == "excavation":
        add("ped_fence", math.ceil(req.work_length_m / r["ped_fence_panel_length_m"]),
            "separate pedestrians from the work area")

    # VMS
    if traffic and (req.duration_days >= r["vms_min_duration_days"] or (req.road_class or "") in r["vms_road_classes"]):
        add("vms_board", approaches, "advance notice: multi-day works or major road")

    # Arrow board
    if ClosureTarget.traffic_lane in req.targets and (speed >= r["arrow_board_min_speed_kmh"] or req.time_window == TimeWindow.night):
        add("arrow_board", approaches, "lane closure on higher-speed road or at night")

    # Lighting
    if req.time_window == TimeWindow.night:
        add("light_tower", math.ceil(req.work_length_m / r["light_tower_coverage_m"]), "night works lighting")

    return lines


def equipment(req: EquipmentRequest) -> EquipmentResult:
    rules, inv = load_rules(), load_inventory()
    lines = compute(req)
    totals: dict[str, int] = {}
    for item, qty, _ in lines:
        totals[item] = totals.get(item, 0) + qty

    items, shortages, total = [], [], 0.0
    for item, qty, reason in lines:
        meta = inv.get(item, {"name": item, "stock": 0, "rate": 0.0})
        in_stock = totals[item] <= meta["stock"]
        cost = qty * meta["rate"] * req.duration_days
        total += cost
        items.append(EquipmentItem(item_id=item, name=meta["name"], qty=qty, reason=reason, stock=meta["stock"],
                                   in_stock=in_stock, daily_rate_aud=meta["rate"], cost_aud=round(cost, 2)))
        if not in_stock and meta["name"] not in shortages:
            shortages.append(meta["name"])

    return EquipmentResult(
        items=items, total_cost_aud=round(total, 2), shortages=shortages, rules_verified=bool(rules.get("verified")),
        disclaimer=("Rule values are placeholders pending verification against AS 1742.3 / AGTTM."
                    if not rules.get("verified") else "Quantities from verified rules; plan still needs sign-off."),
    )
