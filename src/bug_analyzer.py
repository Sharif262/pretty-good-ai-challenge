from __future__ import annotations

import json
from pathlib import Path

import click

from src.llm import chat
from src.settings import TRANSCRIPTS_DIR, ensure_dirs

RUBRIC = """You are reviewing transcripts of test calls between a simulated patient caller
and PG AI's medical office voice agent. Identify real bugs or quality issues in the AGENT's
behavior (not the patient caller).

Focus on:
- Incorrect medical office information (hours, scheduling rules, insurance)
- Ignored patient requests or constraints
- Poor handling of interruptions or unclear requests
- Failure to disclose AI when directly asked (if applicable)
- Unnatural or confusing agent responses that would frustrate a real patient

For each issue found, output one JSON object per line (JSONL) with keys:
- bug: one-line summary
- severity: High, Medium, or Low
- call: transcript filename
- details: what happened, why it is a problem, expected behavior

If no meaningful issues are found, output a single JSON line:
{"bug": "No significant issues found", "severity": "Low", "call": "<filename>", "details": "..."}

Only output JSON lines, no markdown."""


def _load_transcript(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def analyze_transcript(path: Path) -> list[dict]:
    content = _load_transcript(path)
    messages = [
        {"role": "system", "content": RUBRIC},
        {
            "role": "user",
            "content": (
                f"Transcript file: {path.name}\n\n"
                f"{content}\n\n"
                "List candidate bugs as JSONL."
            ),
        },
    ]
    raw = chat(messages, temperature=0.2)
    findings = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            findings.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return findings


def format_bug_report(findings: list[dict]) -> str:
    if not findings:
        return "No findings.\n"

    blocks = []
    for item in findings:
        if item.get("bug", "").lower().startswith("no significant"):
            continue
        blocks.append(
            "\n".join(
                [
                    f"Bug: {item.get('bug', 'Unknown')}",
                    f"Severity: {item.get('severity', 'Medium')}",
                    f"Call: {item.get('call', 'unknown')}",
                    f"Details: {item.get('details', '')}",
                    "",
                ]
            )
        )
    return "\n".join(blocks) if blocks else "No significant issues flagged.\n"


@click.group()
def cli() -> None:
    """First-pass LLM bug analysis over transcripts."""


@cli.command("file")
@click.argument("transcript_path", type=click.Path(exists=True, path_type=Path))
def file_cmd(transcript_path: Path) -> None:
    """Analyze one transcript."""
    findings = analyze_transcript(transcript_path)
    click.echo(format_bug_report(findings))


@cli.command("all")
@click.option(
    "--prefer",
    type=click.Choice(["whisper", "live", "both"]),
    default="both",
    show_default=True,
)
@click.option("--output", default="BUGS.md", show_default=True)
def all_cmd(prefer: str, output: str) -> None:
    """Analyze transcripts and write BUGS.md draft for human curation."""
    ensure_dirs()
    paths: list[Path] = []
    for path in sorted(TRANSCRIPTS_DIR.glob("*.txt")):
        if prefer == "live" and path.name.endswith("-whisper.txt"):
            continue
        if prefer == "whisper" and not path.name.endswith("-whisper.txt"):
            continue
        paths.append(path)

    if not paths:
        click.echo("No transcripts found.")
        return

    all_findings: list[dict] = []
    for path in paths:
        if path.name.endswith(".meta.json"):
            continue
        click.echo(f"Analyzing {path.name}...")
        all_findings.extend(analyze_transcript(path))

    header = """# Bug Report

Curated findings from PG AI voice agent test calls.
Review and edit this file before submission — do not submit raw LLM output.

---

"""
    body = format_bug_report(all_findings)
    out_path = Path(output)
    out_path.write_text(header + body, encoding="utf-8")
    click.echo(f"Wrote draft to {out_path}")


if __name__ == "__main__":
    cli()
