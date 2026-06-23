# CURSOR.md — Agent & Contributor Guide

**Canonical project documentation for AI coding agents and human contributors.**

> **Maintenance rule:** Any change to application code, CLI commands, directory layout, environment variables, scenario format, or workflows **must** update this file in the same PR/commit. See [Keeping this file current](#keeping-this-file-current).

Other AI tools: [AGENTS.md](./AGENTS.md) and [CLAUDE.md](./CLAUDE.md) point here.

---

## What this project does

This is a **Python voice bot test caller** for evaluating phone-based AI agents (built for the [Pretty Good AI Engineering Challenge](https://github.com/Sharif262/pretty-good-ai-challenge)).

It:

1. Places **outbound Twilio calls** from your number to a target test line (default: `+1-805-439-8008`)
2. Simulates a **patient caller** using an LLM driven by YAML scenario configs
3. Uses **Twilio ConversationRelay** for speech-to-text / text-to-speech over a WebSocket
4. **Records** the call, saves a **live transcript** during the call, and optionally **re-transcribes** with Whisper
5. Runs an optional **bug analyzer** LLM pass to draft findings for `BUGS.md`

You can fork this repo and point it at **your own test line**, **your own scenarios**, and **your own agent** — the architecture is generic beyond the PG AI challenge defaults.

---

## Manual setup (required before first run)

### 1. Prerequisites

| Requirement | Why |
|-------------|-----|
| Python 3.9+ | Runtime |
| [Twilio account](https://www.twilio.com/try-twilio) + voice-capable phone number | Outbound calls + recording |
| [OpenAI API key](https://platform.openai.com/) (or compatible provider) | Patient dialogue + Whisper transcription |
| [ngrok](https://ngrok.com/) or similar | Twilio needs public HTTPS/WSS URLs to reach your local server |

### 2. Install

```bash
git clone <your-fork-url>
cd pretty-good-ai-challenge
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

### 3. Configure `.env` (you must fill these in)

Copy `.env.example` → `.env`. **Never commit `.env`.**

| Variable | Required | Description |
|----------|----------|-------------|
| `TWILIO_ACCOUNT_SID` | Yes | Twilio Console → Account SID |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio Console → Auth Token |
| `TWILIO_PHONE_NUMBER` | Yes | Your Twilio number in E.164 (e.g. `+15551234567`) |
| `PUBLIC_BASE_URL` | Yes | ngrok hostname **only** — no `https://`, no trailing slash (e.g. `abc123.ngrok-free.app`) |
| `LLM_API_KEY` | Yes | OpenAI or compatible API key (also used for Whisper) |
| `TEST_LINE_NUMBER` | No | Number to dial (default `+18054398008`) — change for your own agent |
| `LLM_MODEL` | No | Chat model (default `gpt-4o-mini`) |
| `LLM_BASE_URL` | No | OpenAI-compatible base URL if not using OpenAI directly |
| `PORT` | No | Server port (default `8000`) |

### 4. Start services (three terminals)

**Terminal 1 — FastAPI server:**

```bash
python run_server.py
```

**Terminal 2 — expose to the internet:**

```bash
ngrok http 8000
```

Copy the ngrok hostname into `PUBLIC_BASE_URL` in `.env`, then **restart the server**.

**Terminal 3 — place calls:**

```bash
python -m src.call_runner list
python -m src.call_runner place 01_emergency_escalation --wait
```

### 5. Verify health

```bash
curl https://<your-ngrok-host>/health
# {"status":"ok"}
```

---

## Architecture

```
call_runner.py  →  Twilio REST API  →  dials TEST_LINE_NUMBER
                         ↓
              GET /twiml?scenario=...&suite=...
                         ↓
         ConversationRelay WebSocket /ws
                         ↓
    prompt (agent speech) → LLM → text (patient reply) → TTS
                         ↓
              recording + live transcript saved
                         ↓
         transcribe.py (Whisper) + bug_analyzer.py (optional)
```

### Design choices

| Choice | Rationale |
|--------|-----------|
| ConversationRelay + BYO LLM | Telephony STT/TTS/turn-taking without managing raw audio |
| YAML scenarios | Declarative personas; easy to tune after listening to recordings |
| Live + Whisper transcripts | Live log for debugging; Whisper for submission-quality text |
| FastAPI | Async WebSocket handler with minimal boilerplate |
| ngrok for dev | Twilio requires public HTTPS/WSS during local development |

See also [ARCHITECTURE.md](./ARCHITECTURE.md) for a shorter design summary.

---

## Repository layout

```
pretty-good-ai-challenge/
├── CURSOR.md                 # This file — canonical agent guide (keep updated!)
├── AGENTS.md / CLAUDE.md     # Pointers for other AI tools
├── README.md                 # Human-facing quick start
├── ARCHITECTURE.md           # Short architecture summary
├── BUGS.md                   # Curated bug report (human-edited after analysis)
├── run_server.py             # Uvicorn entrypoint
├── requirements.txt
├── .env.example              # Template — copy to .env
│
├── src/
│   ├── server.py             # FastAPI: TwiML, WebSocket, recording webhook
│   ├── call_runner.py        # CLI: place calls, batch runs, download recordings
│   ├── persona.py            # Load YAML scenarios, build patient system prompts
│   ├── llm.py                # OpenAI-compatible chat client
│   ├── transcribe.py         # Whisper post-call transcription CLI
│   ├── transcript_utils.py   # Organize/publish transcripts to run folders
│   ├── organize_transcripts.py  # CLI wrapper for transcript_utils
│   ├── bug_analyzer.py       # LLM pass over transcripts → BUGS.md draft
│   └── settings.py           # Paths, env loading, get_settings()
│
├── scenarios/                # All YAML scenarios (edge-case + baseline)
├── recordings/               # Downloaded mp3s (scenario_id filenames)
└── transcripts/              # Organized run folders (plus optional .gitkeep)
    ├── edge-case-batch/      # Organized run folder
    │   ├── live/             # Final call text by scenario_id
    │   ├── meta/             # Call metadata JSON by scenario_id
    │   └── whisper/          # Whisper transcripts by scenario_id
    └── baseline-test-scenarios/
        ├── live/
        ├── meta/
        └── whisper/
```

---

## Transcript folder rules

Use `transcripts/` as organized run output only.

- Create one run folder per suite/run name under `transcripts/` (for example `edge-case-batch` or `baseline-test-scenarios`).
- Inside each run folder, always create exactly three subfolders: `live/`, `meta/`, and `whisper/`.
- Store outputs by `scenario_id`:
  - `live/<scenario_id>.txt`
  - `meta/<scenario_id>.meta.json`
  - `whisper/<scenario_id>-whisper.txt`
- Avoid leaving loose `CA<sid>*` files at the root of `transcripts/`; treat root-level files as temporary artifacts to clean up.

---

## Module reference

### `run_server.py`

Starts Uvicorn with `src.server:app` on `PORT` from settings.

### `src/settings.py`

- **Paths:** `ROOT_DIR`, `SCENARIOS_DIR`, `RECORDINGS_DIR`, `TRANSCRIPTS_DIR`
- **`resolve_scenarios_dir()`** — always returns `scenarios/` (suite filtering happens in `persona.py`)
- **`get_settings()`** — loads required env vars; raises if missing
- **`ensure_dirs()`** — creates `recordings/` and `transcripts/`

### `src/server.py`

FastAPI app with four responsibilities:

| Route | Purpose |
|-------|---------|
| `GET /health` | Liveness check |
| `GET/POST /twiml` | Returns TwiML with ConversationRelay pointing at `wss://<PUBLIC_BASE_URL>/ws` |
| `POST /recording-status` | Twilio callback when recording is ready; updates `CA<sid>.meta.json` |
| `WebSocket /ws` | ConversationRelay session handler |

**WebSocket message flow:**

1. `setup` — reads `scenario_id` and `suite` from custom parameters; creates `CallSession` with LLM system prompt
2. `prompt` — agent speech arrives as `voicePrompt`; LLM generates patient reply; sent back as `text`
3. `interrupt` — logged (agent or patient interrupted)
4. On disconnect — persists live transcript to `transcripts/CA<sid>.txt`

**Important:** `CallSession.suite` is stored at setup time. The server process does **not** share memory with `call_runner` — suite must come from TwiML query params or ConversationRelay custom parameters, not `pending_suites` alone on the server.

**Exports:** `register_pending_call(call_sid, scenario_id, suite)` — used by `call_runner` (same process only when co-located; not reliable cross-process).

### `src/call_runner.py`

Click CLI for outbound calls.

| Command | Description |
|---------|-------------|
| `list [--suite default\|baseline]` | List scenarios |
| `place <scenario_id> [--wait] [--suite] [--recordings-dir]` | Place one call |
| `batch [--delay 90] [--wait] [--suite] [--recordings-dir]` | Run all scenarios sequentially |
| `download-recording <call_sid>` | Download mp3 from Twilio |
| `rename-artifacts` | Rename root `recordings/CA*.mp3` and `transcripts/CA*` files to `scenario_id` names using metadata |

**`place_call()`** creates Twilio call with `record=True`, writes `CA<sid>.meta.json`, registers pending scenario.

**`download_recording()`** polls for recording readiness (404 retry), saves `CA<sid>.mp3`, optionally copies to `<scenario_id>.mp3` when using `--recordings-dir`.

**`rename-artifacts`** is a cleanup helper for existing flat artifacts; it renames root `recordings/` and `transcripts/` call-SID files to scenario-id filenames when matching metadata is available.

### `src/persona.py`

- **`Scenario`** dataclass — parsed from YAML
- **`load_scenario(id, suite)`** — loads from `scenarios/`
- **`infer_suite(scenario_id, suite)`** — maps baseline scenario IDs to suite `baseline`
- **`build_system_prompt(scenario)`** — patient role-play instructions for the LLM
- **`should_end_call(scenario, turn_count, reply)`** — ends on max turns or farewell phrases after turn 4
- **`list_scenarios(suite)`** — enumerate scenarios for a suite

### `src/llm.py`

Thin OpenAI client wrapper: `chat(messages, temperature=0.7)` using `LLM_API_KEY`, `LLM_MODEL`, optional `LLM_BASE_URL`.

### `src/transcribe.py`

Whisper transcription via OpenAI-compatible API (`whisper-1`).

| Command | Description |
|---------|-------------|
| `call <call_sid>` | Transcribe `recordings/CA<sid>.mp3` |
| `all` | Transcribe all `*.mp3` in `recordings/` |
| `all-runs` | Alias for `all` |
| `file <audio_path>` | Transcribe any local mp3 |

Writes whisper output and calls `publish_transcript()` to sync organized transcript folders.

### `src/transcript_utils.py`

- **`publish_transcript(call_sid, scenario_id, meta)`** — copies live, meta, whisper files to:
  - `transcripts/<run_name>/{live,whisper,meta}/<scenario_id>.*`
- **`organize_transcripts_dir()`** — re-publishes all flat `CA*.meta.json` files
- **Run mapping:** `default` suite → `edge-case-batch`, `baseline` → `baseline-test-scenarios`

### `src/organize_transcripts.py`

CLI: `python -m src.organize_transcripts` — runs `organize_transcripts_dir()`.

### `src/bug_analyzer.py`

LLM rubric-based review of agent behavior in transcripts.

Analysis is **sentence-level** (ignores conversational filler), uses scenario YAML context for edge-case detection, and includes a suggested fix per finding.

| Command | Description |
|---------|-------------|
| `file <transcript_path>` | Analyze one file |
| `all [--prefer whisper\|live\|both] [--output BUGS.md]` | Draft bug report from organized `transcripts/` run folders (deduped by scenario) |

Output fields: `bug`, `severity` (High/Medium only), `evidence`, `details`, `suggested_fix`.

---

## Scenario suites

### Edge-case scenarios (suite `default`)

Edge-case probes designed to surface agent bugs:

| ID | Focus |
|----|-------|
| `01_emergency_escalation` | Chest pain mentioned casually — agent should escalate |
| `02_privacy_hipaa_boundary` | HIPAA / PHI boundary testing |
| `03_prompt_injection_probe` | Adversarial prompt injection |
| `04_multi_intent_overload` | Multiple requests in one call |
| `05_self_contradiction` | Caller contradicts themselves |
| `06_silent_unresponsive_caller` | Minimal / delayed responses |
| `07_out_of_scope_request` | Requests outside medical office scope |
| `08_emotionally_frustrated_caller` | Angry / frustrated caller |
| `09_elderly_confused_caller` | Confused elderly patient |
| `10_impossible_appointment_request` | Scheduling constraints agent cannot satisfy |

### Baseline scenarios (suite `baseline`)

Standard coverage scenarios also live in `scenarios/`. Filter with `--suite baseline`:

| ID | Focus |
|----|-------|
| `01_simple_scheduling` | Basic appointment scheduling |
| `05_hours_location` | Office hours and location |
| `06_insurance_question` | Insurance coverage question |
| `10_language_support_probe` | Non-English language support |

Other baseline IDs (`02_reschedule`, `03_cancel_appointment`, etc.) are recognized when their YAML files are added to `scenarios/`.

Run with: `python -m src.call_runner batch --suite baseline`

### YAML scenario format

```yaml
id: "01_emergency_escalation"
name: "Emergency escalation test"
persona:
  name: "David Chen"
  age: 52
  tone: "casual, matter-of-fact"
  speaking_style: "conversational, concise"
goal: |
  Multi-line description of what the patient should accomplish.
constraints:
  - "Behavior rule 1"
  - "Behavior rule 2"
opening_line: "Hi, I'd like to schedule..."
max_turns: 20
notes: "Internal notes for evaluators (not sent to LLM as primary instruction)"
```

**To add your own scenario:** create a new `.yaml` in `scenarios/`, then `python -m src.call_runner place <id> --wait`.

---

## Typical workflows

### Single test call

```bash
python run_server.py          # terminal 1
ngrok http 8000                 # terminal 2 — update PUBLIC_BASE_URL
python -m src.call_runner place 01_emergency_escalation --wait
```

### Full edge-case batch (10 calls)

```bash
python -m src.call_runner batch
```

### Baseline batch

```bash
python -m src.call_runner batch --suite baseline
```

### Post-call: re-transcribe + organize (no new calls)

```bash
python -m src.transcribe all
python -m src.organize_transcripts
```

### Bug analysis draft

```bash
python -m src.bug_analyzer all --prefer whisper --output BUGS.md
# Edit BUGS.md manually before submitting
```

## Adapting for your own use case

| Goal | What to change |
|------|----------------|
| Call your own agent | Set `TEST_LINE_NUMBER` in `.env` |
| New patient personas | Add YAML files under `scenarios/` |
| Different evaluation rubric | Edit `RUBRIC` in `src/bug_analyzer.py` |
| New scenario suite | Add scenario YAML files + extend `BASELINE_SCENARIO_IDS` / `RUN_BY_SUITE` in `persona.py` / `transcript_utils.py` |
| Longer/shorter calls | Adjust `max_turns` and `should_end_call()` logic |
| Non-medical domain | Rewrite scenario goals/constraints; keep ConversationRelay flow |

**Do not** commit API keys, Twilio tokens, or `.env`.

---

## Dependencies

From `requirements.txt`:

- `fastapi`, `uvicorn` — HTTP + WebSocket server
- `twilio` — outbound calls, TwiML, recording fetch
- `openai` — LLM chat + Whisper API
- `python-dotenv` — `.env` loading
- `pyyaml` — scenario parsing
- `httpx` — recording download
- `click` — CLI interfaces
- `python-multipart` — required for Twilio `POST /recording-status` form parsing

---

## Known pitfalls

1. **`PUBLIC_BASE_URL` must match ngrok** — restart server after changing it
2. **Server and call_runner are separate processes** — `pending_suites` in server memory is only populated in-process; suite must flow via TwiML URL query string (`?suite=baseline`)
3. **Recording download 404** — Twilio may need seconds after call ends; `download_recording` retries automatically
4. **Short calls (~7s)** — usually means WebSocket crash (e.g. scenario not found); check server logs
5. **Whisper costs** — `all-runs` transcribes every mp3; re-run only when needed

---

## Keeping this file current

**Strict requirement for all contributors and AI agents:**

When you change any of the following, update **CURSOR.md** in the same change set:

- New/moved/renamed modules, routes, or CLI commands
- Environment variables or setup steps
- Directory layout or transcript organization
- Scenario format or suite behavior
- Dependencies
- Workflows or known pitfalls

If unsure whether a change affects this doc, update it.

**Enforcement:**

- **Cursor:** `.cursor/rules/maintain-cursor-md.mdc` (`alwaysApply: true`)
- **Claude Code / other tools:** read [CLAUDE.md](./CLAUDE.md) or [AGENTS.md](./AGENTS.md), which point here

---

## Related docs

| File | Audience |
|------|----------|
| [README.md](./README.md) | Quick human onboarding |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Short design rationale |
| [BUGS.md](./BUGS.md) | Submission bug report template |
