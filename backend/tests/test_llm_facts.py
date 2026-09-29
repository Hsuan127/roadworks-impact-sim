from datetime import date

from app import config
from app.ai import llm
from app.ai.llm import build_facts, generate_comms, public_notice_facts
from app.schemas import (
    ClosureTarget,
    CommsRequest,
    EquipmentItem,
    EquipmentResult,
    Location,
    ScenarioParams,
)


def scenario(
    *,
    road_name: str | None = "Flemington Road",
    targets: list[ClosureTarget] | None = None,
    duration_days: int = 3,
) -> ScenarioParams:
    return ScenarioParams(
        location=Location(lat=-37.7938, lng=144.9484, road_name=road_name),
        targets=targets or [ClosureTarget.traffic_lane],
        start_date=date(2026, 10, 6),
        duration_days=duration_days,
    )


def equipment() -> EquipmentResult:
    return EquipmentResult(
        items=[
            EquipmentItem(
                item_id="arrow_board",
                name="Arrow board",
                qty=17,
                reason="Lane closure advance warning",
                stock=0,
                in_stock=False,
                daily_rate_aud=55.5,
                cost_aud=2830.5,
            )
        ],
        total_cost_aud=2830.5,
        shortages=["Arrow board"],
        rules_verified=False,
        disclaimer="Demo equipment pricing only.",
    )


def test_build_facts_copies_equipment_fields_without_schema_changes():
    facts = build_facts(CommsRequest(scenario=scenario(), equipment=equipment()))

    assert facts["equipment"] == {
        "items": [
            {
                "item_id": "arrow_board",
                "name": "Arrow board",
                "qty": 17,
                "reason": "Lane closure advance warning",
                "stock": 0,
                "in_stock": False,
                "daily_rate_aud": 55.5,
                "cost_aud": 2830.5,
            }
        ],
        "total_cost_aud": 2830.5,
        "shortages": ["Arrow board"],
        "rules_verified": False,
        "disclaimer": "Demo equipment pricing only.",
    }


def test_public_notice_facts_excludes_internal_equipment_facts():
    facts = build_facts(CommsRequest(scenario=scenario(), equipment=equipment()))

    public = public_notice_facts(facts)

    assert "equipment" not in public
    assert public["road"] == "Flemington Road"


def test_generate_comms_does_not_send_equipment_facts_to_llm(monkeypatch):
    captured = {}

    def fake_complete(system: str, user: str, max_tokens: int = 800) -> str:
        captured["user"] = user
        return "# Roadworks notice: Flemington Road"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_complete", fake_complete)

    comms = generate_comms(CommsRequest(scenario=scenario(), equipment=equipment()))

    assert comms.generated_by == "llm"
    assert "Arrow board" not in captured["user"]
    assert "2830.5" not in captured["user"]
    assert "shortages" not in captured["user"]


def test_equipment_numbers_are_not_allowed_in_public_llm_notice(monkeypatch):
    def fake_complete(system: str, user: str, max_tokens: int = 800) -> str:
        return "Works require 17 arrow boards."

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_complete", fake_complete)

    comms = generate_comms(CommsRequest(scenario=scenario(), equipment=equipment()))

    assert comms.generated_by == "template"
    assert "17 arrow boards" not in comms.public_notice_md


def flatten(messages: list[list[str]]) -> str:
    return " ".join(line for message in messages for line in message)


def test_vms_messages_obey_configured_line_and_character_limits():
    req = CommsRequest(
        scenario=scenario(
            road_name="Very Long Flemington Road Name",
            targets=[ClosureTarget.traffic_lane, ClosureTarget.bike_lane],
            duration_days=365,
        )
    )

    messages = llm.vms_templates(req)

    assert 2 <= len(messages) <= 3
    assert any("WORKS FROM" in message for message in messages)
    assert any("FOR 365 DAYS" in message for message in messages)
    for message in messages:
        assert len(message) <= config.VMS_LINES
        for line in message:
            assert len(line) <= config.VMS_CHARS_PER_LINE


def test_traffic_lane_vms_does_not_assume_left_or_right_lane():
    messages = llm.vms_templates(
        CommsRequest(scenario=scenario(targets=[ClosureTarget.traffic_lane]))
    )

    text = flatten(messages)

    assert "LANE CLOSED" in text
    assert "ROAD CLOSED" not in text
    assert "LEFT LANE" not in text
    assert "RIGHT LANE" not in text
    assert "MERGE RIGHT" not in text
    assert "MERGE LEFT" not in text


def test_full_closure_vms_distinguishes_road_closure_from_lane_closure():
    messages = llm.vms_templates(CommsRequest(scenario=scenario(targets=[ClosureTarget.full])))

    text = flatten(messages)

    assert "ROAD CLOSED" in text
    assert "USE DETOUR" in text
    assert "LANE CLOSED" not in text


def test_bike_lane_vms_supports_bike_lane_closure():
    messages = llm.vms_templates(
        CommsRequest(scenario=scenario(targets=[ClosureTarget.bike_lane]))
    )

    text = flatten(messages)
    bike_lane_messages = [
        message
        for message in messages
        if message[:3] == ["BIKE LANE", "CLOSED", "USE CAUTION"]
    ]

    assert "BIKE LANE" in text
    assert "CLOSED" in text
    assert "USE CAUTION" in text
    assert len(bike_lane_messages) == 1


def test_footpath_vms_supports_explicit_footpath_closure():
    messages = llm.vms_templates(
        CommsRequest(scenario=scenario(road_name=None, targets=[ClosureTarget.footpath]))
    )

    text = flatten(messages)

    assert "FOOTPATH" in text
    assert "CLOSED" in text
    assert "USE CAUTION" in text
    assert "ROADWORKS" not in text
