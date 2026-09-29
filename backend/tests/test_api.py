from fastapi.testclient import TestClient

from app.ai.llm import passes_number_guard
from app.main import app

client = TestClient(app)


def scenario():
    return client.get("/api/demo-scenario").json()


def test_demo_scenario_is_snapped():
    s = scenario()
    assert s["location"]["edge"] is not None
    assert s["duration_days"] == 3


def test_full_closure_reroutes_and_hits_tram():
    s = scenario()
    net = client.post("/api/impact/network", json={
        "edge": s["location"]["edge"], "targets": ["full"], "direction": "both", "lanes_closed": 1, "time_window": "day",
    }).json()
    assert net["affected_trips_pct"] > 0
    assert net["load_increase"], "detour streets expected"
    tr = client.post("/api/impact/transit", json={"edge": s["location"]["edge"], "targets": ["full"]}).json()
    assert any(r["mode"] == "tram" and r["needs_replacement"] for r in tr["routes"])


def test_night_is_less_severe_than_day():
    s = scenario()
    body = {"edge": s["location"]["edge"], "targets": ["traffic_lane"], "direction": "citybound", "lanes_closed": 1}
    day = client.post("/api/impact/network", json={**body, "time_window": "day"}).json()
    night = client.post("/api/impact/network", json={**body, "time_window": "night"}).json()
    assert night["avg_extra_min"] <= day["avg_extra_min"]


def test_duration_changes_cost_not_quantities():
    base = {"targets": ["traffic_lane", "bike_lane"], "direction": "citybound", "lanes_closed": 1, "work_length_m": 30,
            "time_window": "day", "speed_limit_kmh": 60, "road_class": "primary", "work_type": "excavation"}
    three = client.post("/api/equipment", json={**base, "duration_days": 3}).json()
    four = client.post("/api/equipment", json={**base, "duration_days": 4}).json()
    assert [i["qty"] for i in three["items"]] == [i["qty"] for i in four["items"]]
    assert four["total_cost_aud"] > three["total_cost_aud"]
    assert "Arrow board" in three["shortages"]  # demo inventory has 0 arrow boards on purpose


def test_comms_template_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = client.post("/api/comms", json={"scenario": scenario()}).json()
    assert c["generated_by"] == "template"
    assert all(len(line) <= 12 for m in c["vms_messages"] for line in m)


def test_number_guard():
    facts = {"duration_days": 3, "avg_extra_min": 4}
    assert passes_number_guard("Works run 3 days, allow 4 minutes.", facts)
    assert not passes_number_guard("Works run 5 days.", facts)


def test_lane_closure_does_not_flag_crossing_tram():
    s = scenario()  # Flemington Rd segment; demo tram A runs along the crossing Racecourse Rd
    tr = client.post("/api/impact/transit", json={"edge": s["location"]["edge"], "targets": ["traffic_lane"]}).json()
    assert "Demo tram A" not in [r["short_name"] for r in tr["routes"]]


def test_vms_road_name_fits():
    from app.ai.llm import vms_road_name
    assert vms_road_name("Flemington Road") == "FLEMINGTON"
    assert vms_road_name("Swan Street") == "SWAN ST"
