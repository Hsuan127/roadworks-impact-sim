"""P4 equipment rules: each test names the table or clause the rule comes from (see rules.yaml)."""
from collections import Counter

from fastapi.testclient import TestClient

from app.equipment.rules import by_speed, load_rules
from app.main import app

client = TestClient(app)


def demo_segment(**changes):
    """The demo closure: 30 m on Flemington Road (60 km/h, 2 lanes each way), kerb lane + bike lane."""
    g = client.get("/api/demo-scenario").json()["segments"][0]
    seg = {k: g[k] for k in ("id", "edges", "geometry", "targets", "direction", "lanes_closed", "length_m",
                             "speed_limit_kmh", "road_class")}
    return {**seg, **changes}


def equipment(seg, time_window="day", work_type="excavation", **plan):
    body = {"segments": [seg], "duration_days": 3, "time_window": time_window, "work_type": work_type, **plan}
    result = client.post("/api/equipment", json=body).json()
    qty = Counter()
    for i in result["items"]:
        qty[i["item_id"]] += i["qty"]
    return result, qty


def test_speed_tables_follow_agttm():
    r = load_rules()
    assert by_speed(r, "taper_length_m", 60) == 60  # Table 5.7, merge taper, 56-65 km/h
    assert by_speed(r, "taper_gap_m", 80) == 120  # Table 5.8: > 65 km/h is 1.5 x speed
    assert by_speed(r, "sign_spacing_m", 60) == 45  # Table 2.2
    assert by_speed(r, "sign_spacing_m", 80) == 80  # Table 2.2: >= 66 km/h equals the speed
    assert by_speed(r, "cone_spacing_m", 60) == 12  # Table 5.3


def test_lane_closure_at_60_kmh():
    _, qty = equipment(demo_segment())
    assert qty["sign_lane_status"] == 2, "Lane Status sign on both sides of a multilane road (AS 4.10.1, 4.3.2)"
    assert "sign_lane_closed" not in qty, "AS 1742.3 has no LANE CLOSED sign for traffic lanes"
    assert qty["arrow_board"] == 1, "AGTTM 5.8: arrow board at 60 km/h"
    # 60 m merge taper every 12 m -> 6 cones; 30 m buffer + 30 m work zone every 12 m -> 6 cones
    assert qty["cone"] == 12
    assert qty["sign_bike_lane_closed_ahead"] == qty["sign_bicycle_ahead"] == 1


def test_excavation_barrier_runs_past_the_work_zone():
    _, qty = equipment(demo_segment())
    assert qty["barrier_water_filled"] == 40, "24 m lead-in + 30 m + 26 m lead-out, 2 m units (ArmorZone manual)"
    assert qty["barrier_end_treatment"] == 2
    _, qty = equipment(demo_segment(), work_type="non_excavation")
    assert "barrier_water_filled" not in qty


def test_too_few_lanes_for_daytime_traffic():
    day, _ = equipment(demo_segment(), "day")
    night, _ = equipment(demo_segment(), "night")
    assert any("Table 2.4" in w for w in day["warnings"]), "1,436 veh/h near signals needs 3 open lanes"
    assert not any("Table 2.4" in w for w in night["warnings"])


def test_water_filled_barrier_is_not_used_above_its_rating():
    result, qty = equipment(demo_segment(speed_limit_kmh=70))
    assert "barrier_water_filled" not in qty
    assert any("only approved up to 60 km/h" in w for w in result["warnings"])


def test_closing_every_lane_is_signed_as_a_road_closure():
    result, qty = equipment(demo_segment(lanes_closed=2))
    assert qty["sign_road_closed"] == 2 and qty["sign_detour"] == 2 and qty["barrier_board"] > 0
    assert "sign_lane_status" not in qty and "arrow_board" not in qty, "nothing merges past a closed road"
    assert any("road closure" in w for w in result["warnings"])


def test_custom_hours_at_night_need_lighting():
    _, late = equipment(demo_segment(), "custom", custom_hours=[22, 4])
    _, midday = equipment(demo_segment(), "custom", custom_hours=[10, 14])
    assert late["light_tower"] == 1 and "light_tower" not in midday


def test_footpath_signs_stand_at_both_ends():
    _, qty = equipment(demo_segment(targets=["footpath"]))
    assert qty["sign_footpath_closed"] == 2


def test_every_item_is_in_the_inventory():
    from app.equipment.rules import load_inventory
    inventory = load_inventory()
    for seg, tw in ((demo_segment(targets=["traffic_lane", "bike_lane", "footpath"]), "night"),
                    (demo_segment(lanes_closed=2), "day")):
        _, qty = equipment(seg, tw)
        assert set(qty) <= set(inventory), set(qty) - set(inventory)
    assert {i["supplier"] for i in inventory.values()} == {"RPM", "other"}


def test_map_places_every_listed_item():
    for seg, tw in ((demo_segment(), "night"), (demo_segment(lanes_closed=2), "day"),
                    (demo_segment(targets=["footpath"]), "day")):
        body = {"segments": [seg], "duration_days": 3, "time_window": tw, "work_type": "excavation"}
        _, listed = equipment(seg, tw)
        placed = Counter(p["item_id"] for p in client.post("/api/equipment/layout", json=body).json()["placements"])
        assert placed == listed, seg["targets"]


def test_each_segment_is_hired_for_its_own_days_and_hours():
    """Segments rarely run on the same days: a 2-night segment and a 5-day segment are charged apart,
    and only the night one gets lighting."""
    night = demo_segment(id="1", duration_days=2, time_window="night")
    day = demo_segment(id="2", duration_days=5, time_window="day")
    body = {"segments": [night, day], "duration_days": 9, "time_window": "day", "work_type": "excavation"}
    r = client.post("/api/equipment", json=body).json()
    by_seg = {"1": [i for i in r["items"] if i["segment_id"] == "1"], "2": [i for i in r["items"] if i["segment_id"] == "2"]}
    assert {i["days"] for i in by_seg["1"]} == {2} and {i["days"] for i in by_seg["2"]} == {5}
    assert any(i["item_id"] == "light_tower" for i in by_seg["1"])
    assert not any(i["item_id"] == "light_tower" for i in by_seg["2"])
    for i in r["items"]:
        assert i["cost_aud"] == round(i["qty"] * i["daily_rate_aud"] * i["days"], 2)


def test_segment_without_timing_falls_back_to_the_plan():
    body = {"segments": [demo_segment()], "duration_days": 4, "time_window": "day", "work_type": "excavation"}
    r = client.post("/api/equipment", json=body).json()
    assert {i["days"] for i in r["items"]} == {4}
