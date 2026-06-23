from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
import shutil

import click

from src.persona import list_scenarios, load_scenario
from src.server import register_pending_call
from src.settings import RECORDINGS_DIR, TRANSCRIPTS_DIR, ensure_dirs, get_settings
from src.transcript_utils import RUN_BY_SUITE, publish_transcript


def _twilio_client():
    from twilio.rest import Client

    settings = get_settings()
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def place_call(scenario_id: str, *, suite: str = "default") -> str:
    settings = get_settings()
    ensure_dirs()
    scenario = load_scenario(scenario_id, suite=suite)
    client = _twilio_client()

    twiml_url = (
        f"{settings.webhook_base}/twiml"
        f"?scenario={scenario.id}&suite={suite}"
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

    register_pending_call(call.sid, scenario.id, suite=suite)

    meta = {
        "call_sid": call.sid,
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "suite": suite,
        "placed_at": datetime.now(timezone.utc).isoformat(),
        "test_line": settings.test_line_number,
        "from_number": settings.twilio_phone_number,
    }
    meta_path = TRANSCRIPTS_DIR / f"{call.sid}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    click.echo(f"Placed call {call.sid} for scenario '{scenario.name}'")
    click.echo(f"  TwiML: {twiml_url}")
    return call.sid


def download_recording(
    call_sid: str,
    *,
    wait_seconds: int = 120,
    output_dir: Path | None = None,
    scenario_id: str | None = None,
) -> Path | None:
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

    out_path = (output_dir or RECORDINGS_DIR) / f"{call_sid}.mp3"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    download_deadline = time.time() + wait_seconds
    while time.time() < download_deadline:
        response = httpx.get(
            url,
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=60,
        )
        if response.status_code == 200:
            out_path.write_bytes(response.content)
            click.echo(f"Saved recording {out_path}")
            if scenario_id:
                named = out_path.parent / f"{scenario_id}.mp3"
                if named != out_path:
                    named.write_bytes(response.content)
                    click.echo(f"Saved recording {named}")
            return out_path
        if response.status_code == 404:
            click.echo("Recording not ready yet, retrying...")
            time.sleep(5)
            continue
        response.raise_for_status()

    click.echo(f"Recording not available for {call_sid} after {wait_seconds}s")
    return None


def _collect_meta_by_call_sid() -> dict[str, dict]:
    meta_by_sid: dict[str, dict] = {}
    roots = [
        TRANSCRIPTS_DIR,
        *(p for p in TRANSCRIPTS_DIR.glob("*/meta") if p.is_dir()),
    ]
    for root in roots:
        for meta_path in root.glob("*.meta.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            call_sid = str(meta.get("call_sid", "")).strip()
            scenario_id = str(meta.get("scenario_id", "")).strip()
            if call_sid.startswith("CA") and scenario_id:
                meta_by_sid[call_sid] = meta
    return meta_by_sid


def _rename_file(src: Path, dst: Path) -> bool:
    if src == dst:
        return False
    if dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return True


def rename_artifacts_to_scenario_ids() -> tuple[int, int]:
    """Rename CA* recordings/transcripts to scenario_id names using metadata."""
    renamed = 0
    skipped = 0
    meta_by_sid = _collect_meta_by_call_sid()

    for rec_path in sorted(RECORDINGS_DIR.glob("CA*.mp3")):
        call_sid = rec_path.stem
        meta = meta_by_sid.get(call_sid)
        if not meta:
            click.echo(f"Skip recording (no meta): {rec_path.name}")
            skipped += 1
            continue
        scenario_id = str(meta.get("scenario_id", "")).strip()
        if not scenario_id:
            click.echo(f"Skip recording (no scenario_id): {rec_path.name}")
            skipped += 1
            continue
        target = rec_path.with_name(f"{scenario_id}.mp3")
        if _rename_file(rec_path, target):
            click.echo(f"Renamed recording: {rec_path.name} -> {target.name}")
            renamed += 1
        else:
            click.echo(f"Skip recording (target exists): {target.name}")
            skipped += 1

    for pattern, suffix in (
        ("CA*.txt", ".txt"),
        ("CA*.meta.json", ".meta.json"),
        ("CA*-whisper.txt", "-whisper.txt"),
    ):
        for path in sorted(TRANSCRIPTS_DIR.glob(pattern)):
            if pattern == "CA*-whisper.txt":
                call_sid = path.name.replace("-whisper.txt", "")
            elif pattern == "CA*.meta.json":
                call_sid = path.name.removesuffix(".meta.json")
            else:
                call_sid = path.stem
            meta = meta_by_sid.get(call_sid)
            if not meta:
                click.echo(f"Skip transcript (no meta): {path.name}")
                skipped += 1
                continue
            scenario_id = str(meta.get("scenario_id", "")).strip()
            if not scenario_id:
                click.echo(f"Skip transcript (no scenario_id): {path.name}")
                skipped += 1
                continue
            target = path.with_name(f"{scenario_id}{suffix}")
            if _rename_file(path, target):
                click.echo(f"Renamed transcript: {path.name} -> {target.name}")
                renamed += 1
            else:
                click.echo(f"Skip transcript (target exists): {target.name}")
                skipped += 1

    return renamed, skipped


@click.group()
def cli() -> None:
    """Place outbound test calls to the PG AI test line."""


@cli.command("list")
@click.option(
    "--suite",
    type=click.Choice(["default", "baseline"]),
    default="default",
    show_default=True,
)
def list_cmd(suite: str) -> None:
    """List available scenarios."""
    for scenario in list_scenarios(suite=None if suite == "default" else suite):
        click.echo(f"  {scenario.id:30} {scenario.name}")


@cli.command("place")
@click.argument("scenario_id")
@click.option("--wait/--no-wait", default=False, help="Wait and download recording.")
@click.option(
    "--suite",
    type=click.Choice(["default", "baseline"]),
    default="default",
    show_default=True,
)
@click.option("--recordings-dir", type=click.Path(path_type=Path), default=None)
def place_cmd(scenario_id: str, wait: bool, suite: str, recordings_dir: Path | None) -> None:
    """Place a single outbound call for a scenario."""
    call_sid = place_call(scenario_id, suite=suite)
    if wait:
        click.echo("Waiting for recording...")
        download_recording(
            call_sid,
            output_dir=recordings_dir,
            scenario_id=scenario_id if recordings_dir else None,
        )
        if recordings_dir:
            run_name = RUN_BY_SUITE.get(suite, "edge-case-batch")
            publish_transcript(call_sid, scenario_id, run_name=run_name)


@cli.command("batch")
@click.option("--delay", default=90, show_default=True, help="Seconds between calls.")
@click.option("--wait/--no-wait", default=True, help="Download recordings after each call.")
@click.option(
    "--suite",
    type=click.Choice(["default", "baseline"]),
    default="default",
    show_default=True,
)
@click.option("--recordings-dir", type=click.Path(path_type=Path), default=None)
def batch_cmd(
    delay: int,
    wait: bool,
    suite: str,
    recordings_dir: Path | None,
) -> None:
    """Run all scenarios sequentially."""
    scenarios = list_scenarios(suite=None if suite == "default" else suite)
    click.echo(f"Running {len(scenarios)} scenarios (suite={suite})...")
    for index, scenario in enumerate(scenarios, start=1):
        click.echo(f"\n[{index}/{len(scenarios)}] {scenario.name}")
        call_sid = place_call(scenario.id, suite=suite)
        if wait:
            click.echo("Waiting for call to finish and recording to be ready...")
            time.sleep(delay)
            download_recording(
                call_sid,
                wait_seconds=120,
                output_dir=recordings_dir,
                scenario_id=scenario.id if recordings_dir else None,
            )
            if recordings_dir:
                run_name = RUN_BY_SUITE.get(suite, "edge-case-batch")
                publish_transcript(call_sid, scenario.id, run_name=run_name)
        else:
            time.sleep(delay)


@cli.command("download-recording")
@click.argument("call_sid")
def download_cmd(call_sid: str) -> None:
    """Download the mp3 recording for a call SID."""
    download_recording(call_sid)


@cli.command("rename-artifacts")
def rename_artifacts_cmd() -> None:
    """Rename CA* recordings/transcripts to scenario_id-based filenames."""
    ensure_dirs()
    renamed, skipped = rename_artifacts_to_scenario_ids()
    click.echo(f"Done. Renamed {renamed} file(s); skipped {skipped}.")


if __name__ == "__main__":
    cli()
