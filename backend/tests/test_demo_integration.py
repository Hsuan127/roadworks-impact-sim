from fastapi.testclient import TestClient

from app import config
from app.demo_scenarios import demo_scenarios
from app.main import app

client = TestClient(app)


def _equipment_request(scenario: dict) -> dict:
    return {
        "targets": scenario["targets"],
        "direction": scenario["direction"],
        "lanes_closed": scenario["lanes_closed"],
        "work_length_m": scenario["work_length_m"],
        "duration_days": scenario["duration_days"],
        "time_window": scenario["time_window"],
        "speed_limit_kmh": scenario["speed_limit_kmh"],
        "road_class": scenario["location"]["road_class"],
        "work_type": scenario["work_type"],
    }


def test_fixed_demo_scenarios_end_to_end_template_mode(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-be-used")

    for key, scenario_model in demo_scenarios().items():
        scenario = scenario_model.model_dump(mode="json")

        network = client.post(
            "/api/impact/network",
            json={
                "edge": scenario["location"]["edge"],
                "targets": scenario["targets"],
                "direction": scenario["direction"],
                "lanes_closed": scenario["lanes_closed"],
                "time_window": scenario["time_window"],
            },
        ).json()
        transit = client.post(
            "/api/impact/transit",
            json={"edge": scenario["location"]["edge"], "targets": scenario["targets"]},
        ).json()
        equipment = client.post("/api/equipment", json=_equipment_request(scenario)).json()

        payload = {
            "scenario": scenario,
            "network": network,
            "transit": transit,
            "equipment": equipment,
        }
        comms_response = client.post("/api/comms", json=payload)
        facts_response = client.post("/api/comms/facts", json=payload)

        assert comms_response.status_code == 200, key
        assert facts_response.status_code == 200, key
        comms = comms_response.json()
        facts = facts_response.json()

        assert comms["generated_by"] == "template", key
        assert comms["public_notice_md"].strip(), key
        assert comms["vms_messages"], key
        assert all(len(message) <= config.VMS_LINES for message in comms["vms_messages"]), key
        assert all(
            len(line) <= config.VMS_CHARS_PER_LINE
            for message in comms["vms_messages"]
            for line in message
        ), key

        public_notice = comms["public_notice_md"]
        assert "Equipment explanation" not in public_notice, key
        assert "Arrow board" not in public_notice, key
        assert "Light tower" not in public_notice, key
        assert "Pedestrian fence panel" not in public_notice, key
        assert str(equipment["total_cost_aud"]) not in public_notice, key

        assert facts["road"] == scenario["location"]["road_name"], key
        assert facts["duration_days"] == scenario["duration_days"], key
        assert facts["closures"] == [target.replace("_", " ") for target in scenario["targets"]], key
        assert facts["direction"] == scenario["direction"], key
        assert facts["avg_extra_min"] == round(network["avg_extra_min"]), key
        assert "detour_streets" in facts, key
        assert facts["routes"] == [route["short_name"] for route in transit["routes"]], key
        assert facts["replacement_needed"] == any(route["needs_replacement"] for route in transit["routes"]), key
        assert facts["equipment"]["items"] == equipment["items"], key
        assert facts["equipment"]["total_cost_aud"] == equipment["total_cost_aud"], key
        assert facts["equipment"]["shortages"] == equipment["shortages"], key
        assert facts["equipment"]["rules_verified"] == equipment["rules_verified"], key

        if key == "B":
            assert "full" in scenario["targets"], key
            assert scenario["direction"] == "both", key
            assert any(route["needs_replacement"] for route in transit["routes"]), key
            assert facts["replacement_needed"] is True, key

        if key == "C":
            equipment_names = {item["name"] for item in equipment["items"]}
            assert scenario["time_window"] == "night", key
            assert "footpath" in scenario["targets"], key
            assert "Portable light tower" in equipment_names, key
            assert "Arrow board" in equipment_names, key
            assert "Pedestrian fence panel" in equipment_names, key
