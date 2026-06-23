from __future__ import annotations

import json
import os
from pathlib import Path

import click
from dotenv import load_dotenv

from src.persona import BASELINE_SCENARIO_IDS, infer_suite
from src.settings import RECORDINGS_DIR, ROOT_DIR, TRANSCRIPTS_DIR, ensure_dirs
from src.transcript_utils import publish_transcript

load_dotenv(ROOT_DIR / ".env")


def _llm_client():
    from openai import OpenAI

    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing LLM_API_KEY in .env (required for Whisper transcription)")
    base_url = os.getenv("LLM_BASE_URL", "").strip() or None
    return OpenAI(api_key=api_key, base_url=base_url)


def transcribe_file(audio_path: Path) -> str:
    client = _llm_client()
    with audio_path.open("rb") as audio_file:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json",
        )

    lines = [f"File: {audio_path.name}", ""]
    if hasattr(result, "text") and result.text:
        lines.append("Full transcript:")
        lines.append(result.text.strip())
        lines.append("")

    segments = getattr(result, "segments", None)
    if segments:
        lines.append("Segments:")
        for segment in segments:
            start = getattr(segment, "start", 0)
            text = getattr(segment, "text", "").strip()
            if text:
                lines.append(f"[{start:.1f}s] {text}")

    return "\n".join(lines) + "\n"


def _find_meta_for_audio(audio_path: Path) -> dict | None:
    stem = audio_path.stem
    search_roots = [
        TRANSCRIPTS_DIR,
        TRANSCRIPTS_DIR / "_raw",
        *(TRANSCRIPTS_DIR.glob("*/meta")),
    ]

    for root in search_roots:
        if not root.exists():
            continue
        direct = root / f"{stem}.meta.json"
        if direct.exists():
            return json.loads(direct.read_text(encoding="utf-8"))

    for root in search_roots:
        if not root.exists():
            continue
        for meta_path in root.rglob("*.meta.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("call_sid") == stem or meta.get("scenario_id") == stem:
                return meta

    if stem in BASELINE_SCENARIO_IDS or (ROOT_DIR / "scenarios" / f"{stem}.yaml").exists():
        return {
            "scenario_id": stem,
            "suite": infer_suite(stem),
            "call_sid": stem,
        }
    return None


def transcribe_audio(audio_path: Path) -> Path:
    """Transcribe one mp3 and publish to organized transcript folders."""
    ensure_dirs()
    meta = _find_meta_for_audio(audio_path)
    text = transcribe_file(audio_path)

    if meta and meta.get("call_sid", "").startswith("CA"):
        out_path = TRANSCRIPTS_DIR / f"{meta['call_sid']}-whisper.txt"
    else:
        out_path = TRANSCRIPTS_DIR / f"{audio_path.stem}-whisper.txt"
    out_path.write_text(text, encoding="utf-8")

    if meta and meta.get("scenario_id"):
        publish_transcript(
            meta.get("call_sid", audio_path.stem),
            meta["scenario_id"],
            meta=meta,
        )
    return out_path


def transcribe_call(call_sid: str) -> Path:
    ensure_dirs()
    audio_path = RECORDINGS_DIR / f"{call_sid}.mp3"
    if not audio_path.exists():
        raise FileNotFoundError(
            f"Recording not found: {audio_path}. Run call_runner download-recording first."
        )
    return transcribe_audio(audio_path)


@click.group()
def cli() -> None:
    """Post-call transcription with Whisper."""


@cli.command("call")
@click.argument("call_sid")
def call_cmd(call_sid: str) -> None:
    """Transcribe a recording by call SID."""
    path = transcribe_call(call_sid)
    click.echo(f"Saved {path}")


@cli.command("all")
def all_cmd() -> None:
    """Transcribe all mp3 recordings in recordings/."""
    ensure_dirs()
    files = sorted(RECORDINGS_DIR.glob("*.mp3"))
    if not files:
        click.echo("No recordings found.")
        return
    for audio_path in files:
        path = transcribe_audio(audio_path)
        click.echo(f"Saved {path} ({audio_path.name})")


@cli.command("all-runs")
def all_runs_cmd() -> None:
    """Alias for transcribe all recordings in recordings/."""
    all_cmd()


@cli.command("file")
@click.argument("audio_path", type=click.Path(exists=True, path_type=Path))
def file_cmd(audio_path: Path) -> None:
    """Transcribe a local audio file."""
    text = transcribe_file(audio_path)
    out_path = TRANSCRIPTS_DIR / f"{audio_path.stem}-whisper.txt"
    out_path.write_text(text, encoding="utf-8")
    click.echo(f"Saved {out_path}")


if __name__ == "__main__":
    cli()
