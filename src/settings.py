from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = ROOT_DIR / "scenarios"
RECORDINGS_DIR = ROOT_DIR / "recordings"
TRANSCRIPTS_DIR = ROOT_DIR / "transcripts"

load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str
    test_line_number: str
    public_base_url: str
    llm_api_key: str
    llm_model: str
    llm_base_url: str | None
    port: int

    @property
    def ws_url(self) -> str:
        host = self.public_base_url.removeprefix("https://").removeprefix("http://")
        return f"wss://{host}/ws"

    @property
    def webhook_base(self) -> str:
        url = self.public_base_url.rstrip("/")
        if not url.startswith("http"):
            return f"https://{url}"
        return url


def get_settings() -> Settings:
    missing = []
    required = {
        "TWILIO_ACCOUNT_SID": "twilio_account_sid",
        "TWILIO_AUTH_TOKEN": "twilio_auth_token",
        "TWILIO_PHONE_NUMBER": "twilio_phone_number",
        "PUBLIC_BASE_URL": "public_base_url",
        "LLM_API_KEY": "llm_api_key",
    }
    values = {}
    for env_key, field in required.items():
        value = os.getenv(env_key, "").strip()
        if not value:
            missing.append(env_key)
        values[field] = value

    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return Settings(
        twilio_account_sid=values["twilio_account_sid"],
        twilio_auth_token=values["twilio_auth_token"],
        twilio_phone_number=values["twilio_phone_number"],
        test_line_number=os.getenv("TEST_LINE_NUMBER", "+18054398008").strip(),
        public_base_url=values["public_base_url"],
        llm_api_key=values["llm_api_key"],
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini").strip(),
        llm_base_url=os.getenv("LLM_BASE_URL", "").strip() or None,
        port=int(os.getenv("PORT", "8000")),
    )


def ensure_dirs() -> None:
    RECORDINGS_DIR.mkdir(exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
