from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, ConversationRelay, VoiceResponse

from src.llm import chat
from src.persona import build_system_prompt, infer_suite, load_scenario, should_end_call
from src.settings import TRANSCRIPTS_DIR, ensure_dirs, get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PG AI Voice Bot")
ensure_dirs()

# call_sid -> session state
sessions: dict[str, "CallSession"] = {}
# call_sid -> scenario_id
pending_scenarios: dict[str, str] = {}
# call_sid -> scenario suite (default | baseline)
pending_suites: dict[str, str] = {}


@dataclass
class CallSession:
    scenario_id: str
    suite: str = "default"
    messages: list[dict[str, str]] = field(default_factory=list)
    turn_count: int = 0
    transcript_lines: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add_line(self, speaker: str, text: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{stamp}] {speaker}: {text}"
        self.transcript_lines.append(line)
        logger.info(line)


def _get_scenario_id(request: Request, call_sid: str | None) -> str:
    scenario_id = request.query_params.get("scenario")
    if scenario_id:
        return scenario_id
    if call_sid and call_sid in pending_scenarios:
        return pending_scenarios[call_sid]
    return "01_simple_scheduling"


def _get_suite(request: Request, call_sid: str | None) -> str:
    suite = request.query_params.get("suite")
    if suite:
        return suite
    if call_sid and call_sid in pending_suites:
        return pending_suites[call_sid]
    return "default"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/twiml", methods=["GET", "POST"])
async def twiml(request: Request) -> Response:
    settings = get_settings()
    call_sid = request.query_params.get("CallSid", "")
    scenario_id = _get_scenario_id(request, call_sid or None)
    suite = _get_suite(request, call_sid or None)

    try:
        scenario = load_scenario(scenario_id, suite=suite)
        greeting = scenario.opening_line
    except FileNotFoundError:
        greeting = "Hello, I'm calling about an appointment."

    response = VoiceResponse()
    connect = Connect()
    relay = ConversationRelay(
        url=settings.ws_url,
        welcome_greeting=greeting,
        welcome_greeting_interruptible="speech",
        interruptible="speech",
        report_input_during_agent_speech="speech",
    )
    relay.parameter(name="scenario_id", value=scenario_id)
    relay.parameter(name="suite", value=suite)
    connect.append(relay)
    response.append(connect)

    logger.info("TwiML for call %s scenario=%s", call_sid, scenario_id)
    return Response(content=str(response), media_type="application/xml")


@app.post("/recording-status")
async def recording_status(request: Request) -> dict[str, str]:
    form = await request.form()
    call_sid = form.get("CallSid", "")
    recording_url = form.get("RecordingUrl", "")
    recording_sid = form.get("RecordingSid", "")
    logger.info(
        "Recording ready call=%s sid=%s url=%s",
        call_sid,
        recording_sid,
        recording_url,
    )
    meta_path = TRANSCRIPTS_DIR / f"{call_sid}.meta.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "recording_sid": recording_sid,
            "recording_url": recording_url,
            "recording_status": form.get("RecordingStatus", ""),
        }
    )
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"status": "received"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    call_sid: str | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            msg_type = message.get("type")

            if msg_type == "setup":
                call_sid = message.get("callSid", "")
                custom = message.get("customParameters") or {}
                scenario_id = custom.get("scenario_id") or pending_scenarios.get(
                    call_sid, "01_simple_scheduling"
                )
                suite = infer_suite(
                    scenario_id,
                    custom.get("suite") or pending_suites.get(call_sid),
                )
                scenario = load_scenario(scenario_id, suite=suite)
                session = CallSession(
                    scenario_id=scenario_id,
                    suite=suite,
                    messages=[{"role": "system", "content": build_system_prompt(scenario)}],
                )
                sessions[call_sid] = session
                session.add_line("Patient", scenario.opening_line)
                logger.info("Setup call=%s scenario=%s", call_sid, scenario_id)

            elif msg_type == "prompt":
                if not call_sid or call_sid not in sessions:
                    continue
                session = sessions[call_sid]
                agent_text = (message.get("voicePrompt") or "").strip()
                if not agent_text:
                    continue

                session.add_line("Agent", agent_text)
                session.messages.append({"role": "user", "content": agent_text})
                session.turn_count += 1

                reply = chat(session.messages)
                session.messages.append({"role": "assistant", "content": reply})
                session.add_line("Patient", reply)

                await websocket.send_text(
                    json.dumps({"type": "text", "token": reply, "last": True})
                )

                scenario = load_scenario(session.scenario_id, suite=session.suite)
                if should_end_call(scenario, session.turn_count, reply):
                    logger.info("Ending call %s after %s turns", call_sid, session.turn_count)
                    _hangup_call(call_sid)

            elif msg_type == "interrupt":
                logger.info("Interrupt on call %s", call_sid)

            elif msg_type in {"error", "dtmf"}:
                logger.warning("Message type %s on call %s: %s", msg_type, call_sid, message)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected call=%s", call_sid)
    finally:
        if call_sid and call_sid in sessions:
            _persist_transcript(call_sid, sessions.pop(call_sid))
            pending_scenarios.pop(call_sid, None)
            pending_suites.pop(call_sid, None)


def _persist_transcript(call_sid: str, session: CallSession) -> None:
    ensure_dirs()
    path = TRANSCRIPTS_DIR / f"{call_sid}.txt"
    header = (
        f"Scenario: {session.scenario_id}\n"
        f"Call SID: {call_sid}\n"
        f"Started: {session.started_at.isoformat()}\n"
        f"Turns: {session.turn_count}\n\n"
    )
    path.write_text(header + "\n".join(session.transcript_lines) + "\n", encoding="utf-8")
    logger.info("Saved live transcript %s", path)


def register_pending_call(call_sid: str, scenario_id: str, *, suite: str = "default") -> None:
    pending_scenarios[call_sid] = scenario_id
    pending_suites[call_sid] = suite


def _hangup_call(call_sid: str) -> None:
    try:
        from twilio.rest import Client

        settings = get_settings()
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.calls(call_sid).update(status="completed")
    except Exception as exc:
        logger.warning("Failed to hang up call %s: %s", call_sid, exc)
