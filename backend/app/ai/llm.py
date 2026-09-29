"""AI layer (owner: P5): form pre-fill, VMS text, public notice.

Principle: AI writes words, rules compute numbers. Every number shown to the public comes from
the computed results; LLM output containing any number not present in those facts is rejected
and the deterministic template is used instead.
"""
from __future__ import annotations

import json
import os
import re
from datetime import timedelta

from jinja2 import Template

from .. import config
from ..schemas import ClosureTarget, Comms, CommsRequest, ParseResult, TimeWindow

DEFAULT_MODEL = os.getenv("LLM_MODEL", "gemini-3.8-flash")


def llm_available() -> bool:
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    return bool(os.getenv("GEMINI_API_KEY")) and provider != "none"


def _complete(system: str, user: str, max_tokens: int = 800) -> str:
    from google import genai  # imported lazily so template-only mode works without the SDK
    from google.genai import types

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text or ""


# ---------- facts: the only numbers allowed in public text ----------
def build_facts(req: CommsRequest) -> dict:
    s = req.scenario
    end = s.start_date + timedelta(days=s.duration_days - 1)
    hours = {"day": "9:30am to 3:30pm", "night": "8pm to 5am"}.get(s.time_window.value)
    if s.time_window == TimeWindow.custom and s.custom_hours:
        hours = f"{s.custom_hours[0]}:00 to {s.custom_hours[1]}:00"
    facts = {
        "road": s.location.road_name or "the work site",
        "start": s.start_date.strftime("%A %-d %B %Y"),
        "end": end.strftime("%A %-d %B %Y"),
        "hours": hours,
        "duration_days": s.duration_days,
        "closures": [t.value.replace("_", " ") for t in s.targets],
        "direction": s.direction,
    }
    if req.network:
        facts["avg_extra_min"] = round(req.network.avg_extra_min)
        facts["detour_streets"] = sorted({l.road_name for l in req.network.load_increase[:3] if l.road_name})
    if req.transit:
        facts["routes"] = [r.short_name for r in req.transit.routes]
        facts["replacement_needed"] = any(r.needs_replacement for r in req.transit.routes)
    if req.equipment:
        facts["equipment"] = {
            "items": [
                {
                    "item_id": item.item_id,
                    "name": item.name,
                    "qty": item.qty,
                    "reason": item.reason,
                    "stock": item.stock,
                    "in_stock": item.in_stock,
                    "daily_rate_aud": item.daily_rate_aud,
                    "cost_aud": item.cost_aud,
                }
                for item in req.equipment.items
            ],
            "total_cost_aud": req.equipment.total_cost_aud,
            "shortages": list(req.equipment.shortages),
            "rules_verified": req.equipment.rules_verified,
            "disclaimer": req.equipment.disclaimer,
        }
    return facts


def public_notice_facts(facts: dict) -> dict:
    """Remove internal-only facts before rendering public notices or calling the LLM."""
    return {key: value for key, value in facts.items() if key != "equipment"}


def _money(value: float) -> str:
    return f"A${value:,.2f}"


def equipment_explanation(req: CommsRequest) -> str:
    """Explain P4-provided equipment results for internal planner review."""
    if not req.equipment:
        return ""

    lines = ["## Equipment explanation"]
    shortages = set(req.equipment.shortages)
    for item in req.equipment.items:
        lines.append(f"- **{item.qty} x {item.name}**")
        lines.append(f"  Reason: {item.reason}.")
        if item.in_stock:
            lines.append(f"  Availability: in stock ({item.stock} available).")
        else:
            lines.append(f"  Availability: shortage ({item.stock} available).")
        if item.name in shortages or item.item_id in shortages:
            lines.append("  Shortage: listed by the equipment rules.")
        lines.append(
            f"  Cost: {_money(item.cost_aud)}"
            f" ({_money(item.daily_rate_aud)} daily rate)."
        )

    lines.append(f"Total estimated equipment cost: {_money(req.equipment.total_cost_aud)}.")
    lines.append(f"Rules verified: {'yes' if req.equipment.rules_verified else 'no'}.")
    if req.equipment.disclaimer:
        lines.append(req.equipment.disclaimer)
    return "\n".join(lines)


def numbers_in(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def passes_number_guard(text: str, facts: dict) -> bool:
    return numbers_in(text) <= numbers_in(json.dumps(facts, default=str))


# ---------- VMS ----------
def _fit(line: str) -> str:
    # Draft display bounds only; TODO_VERIFY against the actual board format.
    return line.upper()


SUFFIX_ABBR = {"ROAD": "RD", "STREET": "ST", "AVENUE": "AVE", "HIGHWAY": "HWY", "PARADE": "PDE"}


def _vms_words(text: str) -> list[str]:
    return re.findall(r"[A-Z0-9]+", text.upper())


def _screen_word_count(message: list[str]) -> int:
    return sum(len(_vms_words(line)) for line in message)


def _screen_from_words(words: list[str]) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    for word in words[: config.VMS_WORDS_PER_SCREEN]:
        candidate = " ".join([*current, word])
        if current and len(candidate) > config.VMS_CHARS_PER_LINE:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return [_fit(line) for line in lines[: config.VMS_LINES]]


def _road_words(name: str | None) -> list[str]:
    if not name:
        return ["ROAD"]
    return [SUFFIX_ABBR.get(word, word) for word in _vms_words(name)]


def vms_road_name(name: str | None) -> str:
    return " ".join(_road_words(name)[: config.VMS_WORDS_PER_SCREEN])


def _closure_screens(closure_words: list[str], road_words: list[str] | None = None) -> list[list[str]]:
    road_words = road_words or []
    if road_words and len(closure_words) + len(road_words) <= config.VMS_WORDS_PER_SCREEN:
        return [_screen_from_words([*closure_words, *road_words])]
    screens = [_screen_from_words(closure_words)]
    if road_words:
        screens.append(_screen_from_words(road_words))
    return screens


def _fit_vms_messages(messages: list[list[str]]) -> list[list[str]]:
    fitted = [[_fit(line) for line in message[: config.VMS_LINES]] for message in messages]
    compliant = [
        message
        for message in fitted
        if message and _screen_word_count(message) <= config.VMS_WORDS_PER_SCREEN
    ]
    return compliant[: config.VMS_MAX_SCREENS]


def vms_templates(req: CommsRequest) -> list[list[str]]:
    s = req.scenario
    msgs: list[list[str]] = []
    has_traffic_lane = ClosureTarget.traffic_lane in s.targets
    has_bike_lane = ClosureTarget.bike_lane in s.targets
    has_footpath = ClosureTarget.footpath in s.targets
    road_words = _road_words(s.location.road_name)
    if ClosureTarget.full in s.targets:
        msgs.extend(_closure_screens(["ROAD", "CLOSED"], road_words))
        if has_bike_lane:
            msgs.append(["BIKE LANE", "CLOSED"])
    else:
        if has_traffic_lane:
            msgs.extend(_closure_screens(["LANE", "CLOSED"], road_words))
        if has_bike_lane:
            msgs.append(["BIKE LANE", "CLOSED"])
        if has_footpath:
            msgs.append(["FOOTPATH", "CLOSED"])

    if not msgs:
        msgs.extend(_closure_screens(["ROADWORKS"], road_words))
    return _fit_vms_messages(msgs)


# ---------- public notice ----------
NOTICE_TEMPLATE = Template("""# Roadworks notice: {{ road }}

From **{{ start }}** to **{{ end }}**, {{ hours }}, works will close the {{ closures | join(', ') }} on {{ road }} ({{ direction }}).
{% if avg_extra_min is defined and avg_extra_min > 0 %}
Allow about {{ avg_extra_min }} extra minutes if you drive through the area.{% endif %}
{% if detour_streets %}Expect more traffic on {{ detour_streets | join(', ') }}.{% endif %}
{% if routes %}
Public transport: {{ routes | join(', ') }} may be affected.{% if replacement_needed %} Replacement services may be required.{% endif %}{% endif %}

We apologise for any inconvenience.
""")


def generate_comms(req: CommsRequest) -> Comms:
    facts = build_facts(req)
    notice_facts = public_notice_facts(facts)
    notice = NOTICE_TEMPLATE.render(**notice_facts).strip()
    vms = vms_templates(req)
    generated_by = "template"

    if llm_available():
        try:
            draft = _complete(
                system=("You rewrite roadworks notices for Melbourne residents in plain, friendly English. "
                        "Use ONLY the facts given. Do not add any number, date, time or route that is not in the facts. "
                        "Return markdown only."),
                user=f"Facts (JSON): {json.dumps(notice_facts, default=str)}\n\nCurrent draft:\n{notice}",
            )
            if passes_number_guard(draft, notice_facts):
                notice, generated_by = draft.strip(), "llm"
        except Exception:  # noqa: BLE001 - any LLM failure falls back to the template
            pass
    return Comms(vms_messages=vms, public_notice_md=notice, generated_by=generated_by)


# ---------- form pre-fill ----------
PARSE_SYSTEM = """Extract roadworks parameters from the user's description. Return ONLY JSON:
{"fields": {...}, "missing": [...]}
Allowed field keys: road_name, targets (list of traffic_lane|bike_lane|footpath|full),
direction (citybound|outbound|both), lanes_closed (int), work_length_m (number),
start_date (YYYY-MM-DD, resolve relative dates from TODAY), duration_days (int),
time_window (day|night|custom), work_type (excavation|non_excavation).
Put keys you cannot determine in "missing". Never guess a speed limit."""


def parse_description(text: str, today: str) -> ParseResult:
    if not llm_available():
        raise RuntimeError("Set GEMINI_API_KEY to enable one-sentence pre-fill.")
    raw = _complete(PARSE_SYSTEM, f"TODAY={today}\n{text}", max_tokens=400)
    raw = raw.replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    return ParseResult(fields=data.get("fields", {}), missing=data.get("missing", []))
