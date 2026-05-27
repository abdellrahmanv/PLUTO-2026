# Feature Memory: WELCOME_TALK v1 Offline Answer Engine

Status: implemented, local smoke validated

Last updated: 2026-05-27

Last validated: 2026-05-27 local smoke test, not yet validated on Raspberry Pi microphone/speaker

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
TIME-009
AUD-013
AUD-014
AUD-015
AUD-016
AUD-018
AUD-019
STATE-3.33
STATE-3.33.1
STATE-3.33.2
STATE-3.33.3
STATE-3.33.4
STATE-3.33.5
STATE-3.33.6
STATE-3.35
STATE-3.37
```

Verification tests:

```text
tools/welcome_talk_smoke.py
tools/web_shell_smoke.py
```

## Design Intent

Make WELCOME_TALK fast, offline, and good enough for a welcoming robot. Pluto
answers short visitor questions using a deterministic local response bank
instead of waiting for an LLM.

## Design Decision

v1 uses a local keyword/fuzzy intent engine in:

```text
pluto_runtime/welcome_talk.py
```

This was chosen because Pluto needs small latency more than perfect language
understanding. Ollama/Qwen remains a v1.5 fallback candidate only after a
benchmark gate.

## Interfaces

Inputs:

- Website text fallback through `POST /api/welcome/talk`.
- Future STT text from microphone path.

Outputs:

- Short response text.
- Response source: `keyword`, `fuzzy`, `fallback`, or `blocked`.
- Intent name, score, input word count, output word count, latency.
- Web status under `status.talk`.

External dependencies:

- None for v1 answer selection.

## Configuration

| Name | Default | Allowed Range | Reason |
| --- | --- | --- | --- |
| `version` | `v1` | `v1` | Locks offline deterministic behavior |
| `primary_engine` | `keyword` | `keyword` | Keeps response path traceable |
| `enable_ollama_fallback` | `false` | bool | v1.5 only after benchmark |
| `max_input_words` | 9 | 1-12 | Keeps questions tiny |
| `max_output_words` | 9 | 1-12 | Keeps answers quick |
| `fuzzy_threshold` | 0.68 | 0.0-1.0 | Allows small STT mistakes |

## Runtime Behavior

The web API only answers while the mode manager is in `WELCOME`. Before
answering, the Pi sends a stop guard to STM32 so wheel motion stays zero during
talk.

Normal flow:

```text
POST /api/welcome/talk
  -> require current_state == WELCOME
  -> send CMD:STOP
  -> set substate WELCOME_TALK
  -> normalize text
  -> enforce <= 9 input words
  -> keyword/fuzzy match
  -> return <= 9 output words
  -> log response source and latency
```

## How To Run

Local smoke:

```bash
python tools/welcome_talk_smoke.py
```

With an already running Pi web server:

```bash
python tools/welcome_talk_smoke.py --host 192.168.137.2 --port 8080 --external-server --hardware-flow
```

Manual API test:

```bash
curl -X POST http://127.0.0.1:8080/api/welcome/talk \
  -H "Content-Type: application/json" \
  -d '{"text":"what is your name"}'
```

## How To Debug

Checklist:

1. Check `/api/status` and confirm `talk.version` is `v1`.
2. Confirm current state is `WELCOME`; otherwise talk is rejected.
3. Confirm `stop_guard.ok` is true before trusting TALK output.
4. Check `talk.last_result.response_source`.
5. If the response is wrong, add a trigger to `INTENT_RULES`.
6. If input is blocked, check `input_words`.

Useful commands:

```bash
python tools/welcome_talk_smoke.py
curl http://127.0.0.1:8080/api/status
```

## Expected Evidence

Known keyword:

```text
response_source=keyword
intent=name
response="I am Pluto."
response_words<=9
```

Long question:

```text
accepted=false
reason=input_too_long
response="Short question please."
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-TALK-001 | Known keyword question | `keyword`, answer <= 9 words | local pass |
| VER-TALK-002 | 10-word question | blocked with short-question response | local pass |
| VER-TALK-003 | Response bank audit | all responses <= 9 words | local pass |
| VER-TALK-005 | No internet/API keys | engine imports no cloud dependency | local pass |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Talk rejected | Not in WELCOME | Check `current_state` | Enter WELCOME first |
| Stop guard fails | STM32 disconnected or no ACK | Check `stop_guard` and STM32 runtime | Fix STM32 link before TALK |
| Wrong answer | Missing trigger or STT error | Check `normalized_text` and `score` | Add trigger or response |
| Long input blocked | More than 9 words | Check `input_words` | Ask shorter question |

## Safety Notes

WELCOME_TALK v1 sends no wheel or arm movement. It requires WELCOME state and
uses a `CMD:STOP` guard before answering.

## Open Questions

- Which microphone/STT path will feed this engine first?
- Which answers should be expanded for the actual demo location?
- Should common TTS lines be cached as audio files in the next phase?

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-27 | Initial implementation memory | WELCOME_TALK v1 answer engine added |
