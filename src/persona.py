from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from src.settings import SCENARIOS_DIR, resolve_scenarios_dir

BASELINE_SCENARIO_IDS = {
    "01_simple_scheduling",
    "02_reschedule",
    "03_cancel_appointment",
    "04_medication_refill",
    "05_hours_location",
    "06_insurance_question",
    "07_ambiguous_request",
    "08_interruption_edge_case",
    "09_ai_disclosure_probe",
    "10_language_support_probe",
}


def infer_suite(scenario_id: str, suite: str | None = None) -> str:
    if suite and suite not in ("", "default"):
        return suite
    if scenario_id in BASELINE_SCENARIO_IDS:
        return "baseline"
    return "default"


@dataclass
class Scenario:
    id: str
    name: str
    persona_name: str
    persona_age: int | None
    tone: str
    speaking_style: str
    goal: str
    constraints: list[str]
    opening_line: str
    max_turns: int = 20
    notes: str = ""


def load_scenario(scenario_id: str, *, suite: str | None = None) -> Scenario:
    suite = infer_suite(scenario_id, suite)
    base = resolve_scenarios_dir(suite)
    path = base / f"{scenario_id}.yaml"
    if not path.exists():
        matches = sorted(base.glob(f"*{scenario_id}*.yaml"))
        if not matches:
            available = [p.stem for p in sorted(base.glob("*.yaml"))]
            raise FileNotFoundError(
                f"Scenario '{scenario_id}' not found. Available: {', '.join(available)}"
            )
        path = matches[0]

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    persona = data.get("persona", {})
    return Scenario(
        id=data["id"],
        name=data["name"],
        persona_name=persona.get("name", "Alex"),
        persona_age=persona.get("age"),
        tone=persona.get("tone", "friendly and natural"),
        speaking_style=persona.get(
            "speaking_style", "conversational, concise, like a real phone caller"
        ),
        goal=data["goal"].strip(),
        constraints=list(data.get("constraints", [])),
        opening_line=data.get("opening_line", "Hi, I'm calling about an appointment."),
        max_turns=int(data.get("max_turns", 20)),
        notes=(data.get("notes") or "").strip(),
    )


def list_scenarios(*, suite: str | None = None) -> list[Scenario]:
    paths = sorted(SCENARIOS_DIR.glob("*.yaml"))
    if suite in {"baseline", "test"}:
        paths = [path for path in paths if path.stem in BASELINE_SCENARIO_IDS]
    elif suite == "default":
        paths = [path for path in paths if path.stem not in BASELINE_SCENARIO_IDS]

    resolved = "baseline" if suite in {"baseline", "test"} else "default"
    return [load_scenario(path.stem, suite=resolved) for path in paths]


def build_system_prompt(scenario: Scenario) -> str:
    age_line = f"You are {scenario.persona_age} years old. " if scenario.persona_age else ""
    constraints = "\n".join(f"- {item}" for item in scenario.constraints)
    notes = f"\nScenario notes:\n{scenario.notes}\n" if scenario.notes else ""

    return f"""You are role-playing as a patient calling a medical office on the phone.
Your name is {scenario.persona_name}. {age_line}Your tone is {scenario.tone}.
Speaking style: {scenario.speaking_style}

Scenario: {scenario.name}
Your goal for this call:
{scenario.goal}

Behavior rules:
{constraints}
- Stay in character as the patient caller at all times.
- Keep each reply to one or three short spoken sentences.
- Sound natural on a phone call; occasional filler words are fine.
- Do not mention that you are an AI, a bot, or part of a test.
- Spell out numbers when speaking (say "ten thirty" not "10:30").
- No emojis, bullet points, markdown, or stage directions.
- Steer the conversation toward your goal without rushing.
- When your goal is complete, politely wrap up and say goodbye.
{notes}"""


def should_end_call(scenario: Scenario, turn_count: int, last_assistant_reply: str) -> bool:
    if turn_count >= scenario.max_turns:
        return True
    lowered = last_assistant_reply.lower()
    farewell_markers = ("goodbye", "bye", "have a great day", "take care", "thanks for calling")
    return any(marker in lowered for marker in farewell_markers) and turn_count >= 4
