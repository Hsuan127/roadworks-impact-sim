from datetime import date

from app.ai import llm
from app.ai.llm import build_facts, generate_comms, public_notice_facts
from app.schemas import (
    CommsRequest,
    EquipmentItem,
    EquipmentResult,
    Location,
    ScenarioParams,
)


def scenario() -> ScenarioParams:
    return ScenarioParams(
        location=Location(lat=-37.7938, lng=144.9484, road_name="Flemington Road"),
        start_date=date(2026, 10, 6),
        duration_days=3,
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
