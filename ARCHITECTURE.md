# Architecture

This bot simulates a patient calling PG AI's medical office voice agent. Twilio places an outbound call from your Twilio number to the fixed test line (`+1-805-439-8008`). When the call connects, Twilio fetches TwiML from our FastAPI server, which instructs Twilio to open a **ConversationRelay** session over WebSocket. ConversationRelay handles speech-to-text and text-to-speech on our side of the call — we never touch raw audio. Our server receives transcribed agent speech as JSON `prompt` messages, passes it to an LLM along with a scenario-specific system prompt, and sends the patient's reply back as text for ConversationRelay to speak.

Each scenario is a YAML file defining persona traits, conversational goals, and constraints. This keeps test cases declarative and easy to tune after listening to recordings. We chose ConversationRelay over building our own STT/TTS pipeline because turn-taking, interruption handling, and telephony audio quality are the hardest parts of a voice bot — outsourcing that layer lets us focus on realistic patient dialogue and bug finding. Post-call, we download Twilio's native recording and re-transcribe with Whisper for accurate deliverable transcripts, then run a separate LLM pass to flag candidate agent issues that we manually curate into `BUGS.md`.

## Key design choices

| Choice | Why |
|--------|-----|
| ConversationRelay + BYO LLM | Natural voice I/O without managing telephony audio |
| YAML scenarios | Easy iteration on persona/pacing after listening to calls |
| Live transcript + Whisper | Live log for debugging; Whisper for submission-quality transcripts |
| FastAPI | Simple async WebSocket handler, minimal boilerplate |
| ngrok for dev | Twilio requires public HTTPS/WSS URLs during local development |

## Call flow

```
call_runner.py  →  Twilio REST API  →  dials +18054398008
                         ↓
              GET /twiml?scenario=...
                         ↓
         ConversationRelay WebSocket /ws
                         ↓
    prompt (agent speech) → LLM → text (patient reply)
                         ↓
              recording + live transcript saved
```
