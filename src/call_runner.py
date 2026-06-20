from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import click
from twilio.rest import Client

from src.persona import list_scenarios, load_scenario
from src.server import register_pending_call
from src.settings import RECORDINGS_DIR, TRANSCRIPTS_DIR, ensure_dirs, get_settings


def _twilio_client() -> Client:
    settings = get_settings()
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def place_call(scenario_id: str) -> str:
    settings = get_settings()
    ensure_dirs()
    scenario = load_scenario(scenario_id)
    client = _twilio_client()

    twiml_url = (
        f"{settings.webhook_base}/twiml"
        f"?scenario={scenario.id}"
    )
    recording_callback = f"{settings.webhook_base}/recording-status"

    call = client.calls.create(
        to=settings.test_line_number,
        from_=settings.twilio_phone_number,
        url=twiml_url,
        method="GET",
        record=True,
        recording_status_callback=recording_callback,
        recording_status_callback_method="POST",
    )

    register_pending_call(call.sid, scenario.id)

    meta = {
        "call_sid": call.sid,
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "placed_at": datetime.now(timezone.utc).isoformat(),
        "test_line": settings.test_line_number,
        "from_number": settings.twilio_phone_number,
    }
    meta_path = TRANSCRIPTS_DIR / f"{call.sid}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    click.echo(f"Placed call {call.sid} for scenario '{scenario.name}'")
    click.echo(f"  TwiML: {twiml_url}")
    return call.sid


def download_recording(call_sid: str, *, wait_seconds: int = 120) -> Path | None:
    settings = get_settings()
    client = _twilio_client()
    meta_path = TRANSCRIPTS_DIR / f"{call_sid}.meta.json"

    deadline = time.time() + wait_seconds
    recording_sid = None
    while time.time() < deadline:
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("recording_url"):
                recordings = client.recordings.list(call_sid=call_sid, limit=1)
                if recordings:
                    recording_sid = recordings[0].sid
                    break
        time.sleep(5)

    if not recording_sid:
        recordings = client.recordings.list(call_sid=call_sid, limit=1)
        if not recordings:
            click.echo(f"No recording found for {call_sid}")
            return None
        recording_sid = recordings[0].sid

    uri = client.recordings(recording_sid).fetch().uri.replace(".json", ".mp3")
    url = f"https://api.twilio.com{uri}"

    import httpx

    response = httpx.get(
        url,
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        timeout=60,
    )
    response.raise_for_status()

    out_path = RECORDINGS_DIR / f"{call_sid}.mp3"
    out_path.write_bytes(response.content)
    click.echo(f"Saved recording {out_path}")
    return out_path


@click.group()
def cli() -> None:
    """Place outbound test calls to the PG AI test line."""


@cli.command("list")
def list_cmd() -> None:
    """List available scenarios."""
    for scenario in list_scenarios():
        click.echo(f"  {scenario.id:30} {scenario.name}")


@cli.command("place")
@click.argument("scenario_id")
@click.option("--wait/--no-wait", default=False, help="Wait and download recording.")
def place_cmd(scenario_id: str, wait: bool) -> None:
    """Place a single outbound call for a scenario."""
    call_sid = place_call(scenario_id)
    if wait:
        click.echo("Waiting for recording...")
        download_recording(call_sid)


@cli.command("batch")
@click.option("--delay", default=90, show_default=True, help="Seconds between calls.")
@click.option("--wait/--no-wait", default=True, help="Download recordings after each call.")
def batch_cmd(delay: int, wait: bool) -> None:
    """Run all scenarios sequentially."""
    scenarios = list_scenarios()
    click.echo(f"Running {len(scenarios)} scenarios...")
    for index, scenario in enumerate(scenarios, start=1):
        click.echo(f"\n[{index}/{len(scenarios)}] {scenario.name}")
        call_sid = place_call(scenario.id)
        if wait:
            click.echo("Waiting for call to finish and recording to be ready...")
            time.sleep(delay)
            download_recording(call_sid, wait_seconds=60)
        else:
            time.sleep(delay)


@cli.command("download-recording")
@click.argument("call_sid")
def download_cmd(call_sid: str) -> None:
    """Download the mp3 recording for a call SID."""
    download_recording(call_sid)


if __name__ == "__main__":
    cli()
