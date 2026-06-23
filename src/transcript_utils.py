from __future__ import annotations

import json
import shutil
from pathlib import Path

from src.persona import BASELINE_SCENARIO_IDS
from src.settings import TRANSCRIPTS_DIR

RUN_BY_SUITE = {
    "default": "edge-case-batch",
    "baseline": "baseline-test-scenarios",
}


def run_name_for_meta(meta: dict) -> str:
    suite = meta.get("suite", "default")
    if suite in RUN_BY_SUITE:
        return RUN_BY_SUITE[suite]
    scenario_id = meta.get("scenario_id", "")
    if scenario_id in BASELINE_SCENARIO_IDS:
        return "baseline-test-scenarios"
    return "edge-case-batch"


def organized_dir(run_name: str, kind: str) -> Path:
    return TRANSCRIPTS_DIR / run_name / kind


def _copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def publish_transcript(
    call_sid: str,
    scenario_id: str,
    *,
    run_name: str | None = None,
    meta: dict | None = None,
) -> None:
    """Copy live transcript, meta, and whisper files to organized run folders."""
    if meta is None:
        meta_path = TRANSCRIPTS_DIR / f"{call_sid}.meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            meta = {"scenario_id": scenario_id, "call_sid": call_sid, "suite": "default"}
    if run_name is None:
        run_name = run_name_for_meta(meta)

    live_src = TRANSCRIPTS_DIR / f"{call_sid}.txt"
    meta_src = TRANSCRIPTS_DIR / f"{call_sid}.meta.json"
    whisper_src = TRANSCRIPTS_DIR / f"{call_sid}-whisper.txt"

    for kind, src, name in (
        ("live", live_src, f"{scenario_id}.txt"),
        ("meta", meta_src, f"{scenario_id}.meta.json"),
        ("whisper", whisper_src, f"{scenario_id}-whisper.txt"),
    ):
        _copy_if_exists(src, organized_dir(run_name, kind) / name)


def organize_transcripts_dir() -> int:
    """Reorganize flat call-SID files in transcripts/ into run subfolders."""
    count = 0
    for meta_path in TRANSCRIPTS_DIR.glob("CA*.meta.json"):
        call_sid = meta_path.name.removesuffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        scenario_id = meta.get("scenario_id")
        if not scenario_id:
            continue
        publish_transcript(call_sid, scenario_id, meta=meta)
        count += 1

    for whisper_path in TRANSCRIPTS_DIR.glob("CA*-whisper.txt"):
        call_sid = whisper_path.name.replace("-whisper.txt", "")
        meta_path = TRANSCRIPTS_DIR / f"{call_sid}.meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        scenario_id = meta.get("scenario_id")
        if scenario_id:
            publish_transcript(call_sid, scenario_id, meta=meta)

    return count
