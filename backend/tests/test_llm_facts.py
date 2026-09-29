from datetime import date

from app import config
from app.ai import llm
from app.ai.llm import build_facts, equipment_explanation, generate_comms, public_notice_facts
from app.schemas import (
    AffectedRoute,
    AadtRef,
    ClosureTarget,
    CommsRequest,
    EdgeLoad,
    EquipmentItem,
    EquipmentResult,
    NetworkImpact,
    ScenarioParams,
    Segment,
    SegmentTraffic,
    TransitImpact,
)


def scenario(
    *,
    road_name: str | None = "Flemington Road",
    targets: list[ClosureTarget] | None = None,
    duration_days: int = 3,
) -> ScenarioParams:
    return ScenarioParams(
        name="A",
        segments=[
            Segment(
                id="1",
                waypoints=[(-37.7938, 144.9484), (-37.7937, 144.9488)],
                edges=[(1, 2, 0)],
                geometry=[(-37.7938, 144.9484), (-37.7937, 144.9488)],
                length_m=30,
                road_name=road_name,
                road_class="primary",
                speed_limit_kmh=60,
                targets=targets or [ClosureTarget.traffic_lane],
                direction="citybound",
                lanes_closed=1,
            )
        ],
        start_date=date(2026, 10, 6),
        duration_days=duration_days,
        time_window="day",
        work_type="excavation",
    )


def multi_segment_scenario() -> ScenarioParams:
    s = scenario()
    s.segments.append(
        Segment(
            id="2",
            waypoints=[(-37.794, 144.949), (-37.795, 144.949)],
            edges=[(2, 3, 0)],
            geometry=[(-37.794, 144.949), (-37.795, 144.949)],
            length_m=45,
            road_name="Racecourse Road",
            road_class="primary",
            speed_limit_kmh=60,
            targets=[ClosureTarget.footpath],
            direction="outbound",
            lanes_closed=1,
        )
    )
    return s


def network_impact(*, full_closure: dict[str, bool] | None = None, unmodelled: list[str] | None = None) -> NetworkImpact:
    return NetworkImpact(
        affected_trips_pct=12.3,
        avg_extra_min=4.4,
        max_extra_min=9.0,
        time_factor=1.0,
        full_closure=full_closure or {"1": False},
        rerouted_trips_pct=7.0,
        slowed_trips_pct=5.3,
        unreachable_trips_pct=0.0,
        segment_traffic={"1": SegmentTraffic(through_trips_pct=30.0, slowdown_factor=1.8)},
        unmodelled_segments=unmodelled or [],
        load_increase=[EdgeLoad(edge=(4, 5, 0), road_name="Racecourse Road", delta=0.2, geometry=[], aadt=None)],
        ped_detour_m=None,
        closed_aadt={"1": AadtRef(aadt=25365, year=2019)},
        sensitive_facilities=[],
        is_demo_data=True,
    )


def equipment() -> EquipmentResult:
    return EquipmentResult(
        items=[
            EquipmentItem(
                item_id="arrow_board",
                name="Arrow board",
                supplier="RPM",
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
        warnings=["Check lane capacity"],
        rules_verified=False,
        disclaimer="Demo equipment pricing only.",
    )


def transit_replacement_needed() -> TransitImpact:
    return TransitImpact(
        routes=[
            AffectedRoute(
                route_id="tram-58",
                short_name="58",
                mode="tram",
                needs_replacement=True,
            )
        ],
        stops=[],
        is_demo_data=True,
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
                "supplier": "RPM",
                "daily_rate_aud": 55.5,
                "cost_aud": 2830.5,
            }
        ],
        "total_cost_aud": 2830.5,
        "shortages": ["Arrow board"],
        "warnings": ["Check lane capacity"],
        "rules_verified": False,
        "disclaimer": "Demo equipment pricing only.",
    }


def test_public_notice_facts_excludes_internal_equipment_facts():
    facts = build_facts(CommsRequest(scenario=scenario(), equipment=equipment()))

    public = public_notice_facts(facts)

    assert "equipment" not in public
    assert public["road"] == "Flemington Road"


def test_equipment_explanation_reflects_p4_fields_without_recomputing():
    text = equipment_explanation(CommsRequest(scenario=scenario(), equipment=equipment()))

    assert "17 x Arrow board" in text
    assert "Reason: Lane closure advance warning." in text
    assert "Supplier: RPM." in text
    assert "Availability: shortage (0 available)." in text
    assert "Shortage: listed by the equipment rules." in text
    assert "Cost: A$2,830.50 (A$55.50 daily rate)." in text
    assert "Total estimated equipment cost: A$2,830.50." in text
    assert "Warning: Check lane capacity." in text
    assert "Rules verified: no." in text


def test_equipment_explanation_is_empty_without_p4_result():
    assert equipment_explanation(CommsRequest(scenario=scenario())) == ""


def test_generate_comms_does_not_send_equipment_facts_to_llm(monkeypatch):
    captured = {}

    def fake_complete(system: str, user: str, max_tokens: int = 800) -> str:
        captured["user"] = user
        return "# Roadworks notice: Flemington Road"

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm, "_complete", fake_complete)

    comms = generate_comms(CommsRequest(scenario=scenario(), equipment=equipment()))

    assert comms.generated_by == "llm"
    assert "Arrow board" not in captured["user"]
    assert "2830.5" not in captured["user"]
    assert "shortages" not in captured["user"]


def test_equipment_explanation_stays_out_of_public_notice_and_llm_prompt(monkeypatch):
    captured = {}

    def fake_complete(system: str, user: str, max_tokens: int = 800) -> str:
        captured["user"] = user
        return "# Roadworks notice: Flemington Road"

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm, "_complete", fake_complete)

    req = CommsRequest(scenario=scenario(), equipment=equipment())
    explanation = equipment_explanation(req)
    comms = generate_comms(req)

    assert "Arrow board" in explanation
    assert "Lane closure advance warning" in explanation
    assert "Arrow board" not in comms.public_notice_md
    assert "Lane closure advance warning" not in comms.public_notice_md
    assert "Arrow board" not in captured["user"]
    assert "Lane closure advance warning" not in captured["user"]


def test_equipment_numbers_are_not_allowed_in_public_llm_notice(monkeypatch):
    def fake_complete(system: str, user: str, max_tokens: int = 800) -> str:
        return "Works require 17 arrow boards."

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm, "_complete", fake_complete)

    comms = generate_comms(CommsRequest(scenario=scenario(), equipment=equipment()))

    assert comms.generated_by == "template"
    assert "17 arrow boards" not in comms.public_notice_md


def test_template_uses_cautious_replacement_wording_and_omits_access_claim(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    comms = generate_comms(
        CommsRequest(
            scenario=scenario(),
            transit=transit_replacement_needed(),
        )
    )

    assert "Replacement services may be required." in comms.public_notice_md
    assert "Replacement buses will be arranged." not in comms.public_notice_md
    assert "Access to homes and businesses will be maintained." not in comms.public_notice_md


def test_llm_fallback_preserves_cautious_template_wording(monkeypatch):
    def fake_complete(system: str, user: str, max_tokens: int = 800) -> str:
        raise RuntimeError("LLM unavailable")

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm, "_complete", fake_complete)

    comms = generate_comms(
        CommsRequest(
            scenario=scenario(),
            transit=transit_replacement_needed(),
        )
    )

    assert comms.generated_by == "template"
    assert "Replacement services may be required." in comms.public_notice_md
    assert "Replacement buses will be arranged." not in comms.public_notice_md
    assert "Access to homes and businesses will be maintained." not in comms.public_notice_md


def test_provider_none_forces_template_even_with_gemini_key(monkeypatch):
    def fail_if_called(system: str, user: str, max_tokens: int = 800) -> str:
        raise AssertionError("LLM should not be called when provider is none")

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setattr(llm, "_complete", fail_if_called)

    comms = generate_comms(CommsRequest(scenario=scenario()))

    assert comms.generated_by == "template"


def test_build_facts_preserves_multi_segment_identity_and_public_limits():
    facts = build_facts(
        CommsRequest(
            scenario=multi_segment_scenario(),
            network=network_impact(unmodelled=["2"]),
            equipment=equipment(),
        )
    )

    assert facts["closures"] == [
        {"segment_id": "1", "road": "Flemington Road", "closed": ["traffic lane"], "direction": "citybound"},
        {"segment_id": "2", "road": "Racecourse Road", "closed": ["footpath"], "direction": "outbound"},
    ]
    assert facts["unmodelled_segments"] == ["2"]
    assert facts["closed_aadt"]["1"]["aadt"] == 25365

    public = public_notice_facts(facts)
    assert "equipment" not in public
    assert "closed_aadt" not in public
    assert "unreachable_trips_pct" not in public
    assert "unmodelled_segments" not in public
    assert public["has_unmodelled_segments"] is True
    assert public["closures"] == [
        {"road": "Flemington Road", "closed": ["traffic lane"], "direction": "citybound"},
        {"road": "Racecourse Road", "closed": ["footpath"], "direction": "outbound"},
    ]


def test_segment_ids_do_not_let_unsupported_llm_numbers_pass(monkeypatch):
    def fake_complete(system: str, user: str, max_tokens: int = 800) -> str:
        return "2 lanes will be closed on Racecourse Road."

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm, "_complete", fake_complete)

    comms = generate_comms(
        CommsRequest(
            scenario=multi_segment_scenario(),
            network=network_impact(unmodelled=["2"]),
        )
    )

    assert comms.generated_by == "template"
    assert "2 lanes will be closed" not in comms.public_notice_md
    assert "Some closed segment effects are outside the routed study area" in comms.public_notice_md


def flatten(messages: list[list[str]]) -> str:
    return " ".join(line for message in messages for line in message)


def screen_word_count(message: list[str]) -> int:
    return len(" ".join(message).split())


def assert_vms_screen_limits(messages: list[list[str]]) -> None:
    assert len(messages) <= config.VMS_MAX_SCREENS
    for message in messages:
        assert len(message) <= config.VMS_LINES
        assert screen_word_count(message) <= config.VMS_WORDS_PER_SCREEN
        for line in message:
            words = line.split()
            assert len(line) <= config.VMS_CHARS_PER_LINE or (
                len(words) == 1 and len(words[0]) > config.VMS_CHARS_PER_LINE
            )


def test_vms_messages_obey_screen_word_count_and_draft_display_limits():
    req = CommsRequest(
        scenario=scenario(
            road_name="Very Long Flemington Road Name",
            targets=[ClosureTarget.traffic_lane, ClosureTarget.bike_lane],
            duration_days=365,
        )
    )

    messages = llm.vms_templates(req)

    assert len(messages) == config.VMS_MAX_SCREENS
    assert_vms_screen_limits(messages)


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
    assert "USE CAUTION" not in text
    assert "USE DETOUR" not in text
    assert_vms_screen_limits(messages)


def test_road_name_moves_to_second_vms_screen_when_needed():
    messages = llm.vms_templates(
        CommsRequest(
            scenario=scenario(
                road_name="Very Long Flemington Road",
                targets=[ClosureTarget.traffic_lane],
            )
        )
    )

    assert messages == [["LANE CLOSED"], ["VERY LONG", "FLEMINGTON", "RD"]]
    assert_vms_screen_limits(messages)


def test_vms_long_single_token_road_name_is_not_silently_truncated():
    messages = llm.vms_templates(
        CommsRequest(
            scenario=scenario(
                road_name="Alexandriaville Road",
                targets=[ClosureTarget.traffic_lane],
            )
        )
    )

    text = flatten(messages)

    assert messages == [["LANE CLOSED", "ALEXANDRIAVILLE", "RD"]]
    assert "ALEXANDRIAVILLE" in text
    assert all(line != "ALEXANDRIAVI" for message in messages for line in message)
    assert_vms_screen_limits(messages)


def test_vms_omits_road_name_screen_instead_of_dropping_tokens():
    messages = llm.vms_templates(
        CommsRequest(
            scenario=scenario(
                road_name="Longwordone Longwordtwo Longwordthree Longwordfour",
                targets=[ClosureTarget.traffic_lane],
            )
        )
    )

    text = flatten(messages)

    assert messages == [["LANE CLOSED"]]
    assert "LONGWORDONE" not in text
    assert "LONGWORDTWO" not in text
    assert "LONGWORDTHREE" not in text
    assert "LONGWORDFOUR" not in text
    assert "LANE CLOSED" in text
    assert_vms_screen_limits(messages)


def test_full_closure_vms_distinguishes_road_closure_from_lane_closure():
    messages = llm.vms_templates(CommsRequest(scenario=scenario(targets=[ClosureTarget.full])))

    text = flatten(messages)

    assert "ROAD CLOSED" in text
    assert "USE DETOUR" not in text
    assert "LANE CLOSED" not in text
    assert_vms_screen_limits(messages)


def test_network_full_closure_marks_traffic_lane_as_road_closed():
    messages = llm.vms_templates(
        CommsRequest(
            scenario=scenario(targets=[ClosureTarget.traffic_lane]),
            network=network_impact(full_closure={"1": True}),
        )
    )

    text = flatten(messages)

    assert "ROAD CLOSED" in text
    assert "LANE CLOSED" not in text
    assert "USE DETOUR" not in text
    assert_vms_screen_limits(messages)


def test_vms_multiple_segments_respects_two_screen_cap_and_banned_words():
    messages = llm.vms_templates(CommsRequest(scenario=multi_segment_scenario()))
    text = flatten(messages)

    assert len(messages) == config.VMS_MAX_SCREENS
    assert "LANE CLOSED" in text
    assert "USE CAUTION" not in text
    assert "USE DETOUR" not in text
    assert "MERGE LEFT" not in text
    assert "MERGE RIGHT" not in text
    assert_vms_screen_limits(messages)


def test_bike_lane_vms_supports_bike_lane_closure():
    messages = llm.vms_templates(
        CommsRequest(scenario=scenario(targets=[ClosureTarget.bike_lane]))
    )

    text = flatten(messages)
    bike_lane_messages = [
        message
        for message in messages
        if message[:2] == ["BIKE LANE", "CLOSED"]
    ]

    assert "BIKE LANE" in text
    assert "CLOSED" in text
    assert "USE CAUTION" not in text
    assert len(bike_lane_messages) == 1
    assert_vms_screen_limits(messages)


def test_footpath_vms_supports_explicit_footpath_closure():
    messages = llm.vms_templates(
        CommsRequest(scenario=scenario(road_name=None, targets=[ClosureTarget.footpath]))
    )

    text = flatten(messages)

    assert "FOOTPATH" in text
    assert "CLOSED" in text
    assert "USE CAUTION" not in text
    assert "ROADWORKS" not in text
    assert_vms_screen_limits(messages)
