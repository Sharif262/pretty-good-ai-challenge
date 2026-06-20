# Pretty Good AI — Voice Bot Test Caller

Python voice bot that places outbound calls to the PG AI test line (`+1-805-439-8008`), simulates realistic patient personas, records conversations, transcribes them, and helps surface agent quality issues.

Built for the [Pretty Good AI Engineering Challenge](https://github.com/Sharif262/pretty-good-ai-challenge).

## Architecture

- **Twilio Programmable Voice** places outbound calls and records audio
- **Twilio ConversationRelay** handles STT/TTS and turn-taking over a WebSocket
- **FastAPI** serves TwiML webhooks and the ConversationRelay WebSocket handler
- **LLM** (OpenAI-compatible) generates the patient caller's dialogue from YAML scenario configs
- **Whisper** re-transcribes recordings for accurate final transcripts
- **Bug analyzer** runs an offline LLM pass; you curate results into `BUGS.md`

See [ARCHITECTURE.md](ARCHITECTURE.md) for design rationale.

## Prerequisites

1. [Twilio account](https://www.twilio.com/try-twilio) with a voice-capable phone number
2. [OpenAI API key](https://platform.openai.com/) (or compatible provider via `LLM_BASE_URL`)
3. [ngrok](https://ngrok.com/) (or similar) to expose your local server to Twilio
4. Optional: PG AI test account at [pgai.us/athena](https://pgai.us/athena) for product context

## Setup

```bash
git clone https://github.com/Sharif262/pretty-good-ai-challenge.git
cd pretty-good-ai-challenge
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

| Variable | Description |
|----------|-------------|
| `TWILIO_ACCOUNT_SID` | From Twilio Console |
| `TWILIO_AUTH_TOKEN` | From Twilio Console |
| `TWILIO_PHONE_NUMBER` | Your Twilio number (E.164) |
| `PUBLIC_BASE_URL` | ngrok host only, e.g. `abc123.ngrok-free.app` |
| `LLM_API_KEY` | OpenAI (or compatible) API key |

## Run a test call

**Terminal 1 — start the server:**

```bash
python run_server.py
```

**Terminal 2 — expose via ngrok:**

```bash
ngrok http 8000
```

Copy the ngrok hostname into `PUBLIC_BASE_URL` in `.env`, then restart the server.

**Terminal 3 — place a call:**

```bash
python -m src.call_runner list
python -m src.call_runner place 01_simple_scheduling --wait
```

## Run all 10 scenarios

With the server and ngrok running:

```bash
python -m src.call_runner batch
```

This places one call per scenario (~90s apart), downloads mp3 recordings, and saves live transcripts to `transcripts/`.

## Post-call workflow

```bash
# Re-transcribe recordings with Whisper (more accurate)
python -m src.transcribe all

# Draft bug report (review and edit before submitting!)
python -m src.bug_analyzer all --output BUGS.md
```

## Project layout

```
├── run_server.py          # Start FastAPI + WebSocket server
├── src/
│   ├── server.py          # TwiML + ConversationRelay WebSocket
│   ├── persona.py         # Scenario loading + patient system prompts
│   ├── call_runner.py     # Outbound call CLI
│   ├── transcribe.py      # Whisper post-call transcription
│   └── bug_analyzer.py    # LLM bug triage helper
├── scenarios/             # 10 patient test scenarios (YAML)
├── recordings/            # Downloaded mp3 call recordings
├── transcripts/           # Live + Whisper transcripts
├── BUGS.md                # Curated bug report (fill in after testing)
└── ARCHITECTURE.md
```

## Deliverables checklist

- [ ] 10+ calls with mp3 recordings in `recordings/`
- [ ] Matching transcripts in `transcripts/`
- [ ] Curated `BUGS.md`
- [ ] Loom walkthrough (≤5 min)
- [ ] 5-min screen recording of AI-assisted debugging
- [ ] Submit via PG AI form with GitHub + Loom links and your Twilio number

## Notes

- All test calls must go **only** to `+1-805-439-8008`
- Use a **single** Twilio number for all calls (submission requirement)
- Iterate on scenario prompts after listening to early recordings — natural pacing matters most
- Do not commit `.env` or API keys
