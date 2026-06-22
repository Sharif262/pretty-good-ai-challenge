from __future__ import annotations

import os
from pathlib import Path

import click
from dotenv import load_dotenv

from src.settings import RECORDINGS_DIR, ROOT_DIR, TRANSCRIPTS_DIR, ensure_dirs

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


def transcribe_call(call_sid: str) -> Path:
    ensure_dirs()
    audio_path = RECORDINGS_DIR / f"{call_sid}.mp3"
    if not audio_path.exists():
        raise FileNotFoundError(
            f"Recording not found: {audio_path}. Run call_runner download-recording first."
        )

    text = transcribe_file(audio_path)
    out_path = TRANSCRIPTS_DIR / f"{call_sid}-whisper.txt"
    out_path.write_text(text, encoding="utf-8")
    return out_path


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
    """Transcribe all recordings in recordings/."""
    ensure_dirs()
    files = sorted(RECORDINGS_DIR.glob("*.mp3"))
    if not files:
        click.echo("No recordings found.")
        return
    for audio_path in files:
        call_sid = audio_path.stem
        path = transcribe_call(call_sid)
        click.echo(f"Saved {path}")


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
