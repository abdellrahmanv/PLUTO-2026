# Feature Memory: WELCOME Talk Strategy Study

Status: study draft

Last updated: 2026-05-27

Last validated: not yet validated on Raspberry Pi audio hardware

Owner: Pluto systems engineering

## Requirement Trace

Study covers requirements:

```text
SYS-013
TIME-009
AUD-001
AUD-003
AUD-004
AUD-005
AUD-006
AUD-010
AUD-013
AUD-014
AUD-015
AUD-016
AUD-017
AUD-018
AUD-019
AUD-020
AUD-021
STATE-3.33
STATE-3.33.1
STATE-3.33.2
STATE-3.33.3
STATE-3.33.4
STATE-3.33.5
STATE-3.33.6
STATE-3.33.7
STATE-3.33.8
STATE-3.34
STATE-3.35
STATE-3.36
STATE-3.37
STATE-3.52
```

Verification tests:

```text
VER-WELCOME-013
VER-AUD-001
VER-AUD-003
VER-AUD-004
future VER-TALK-001
future VER-TALK-002
future VER-TALK-003
future VER-TALK-004
```

## Design Intent

WELCOME_TALK must feel quick, simple, and social. Pluto is not trying to be a
full chatbot in v1. The target experience is that a visitor asks a tiny
question, Pluto answers almost immediately, and the robot stays physically safe.

The hard interaction constraints are:

- Recognized question text passed to the answer layer shall be no more than 9 words.
- Spoken answer text shall be no more than 9 words in v1.
- Wheels shall remain stopped during TALK.
- Keyword/intent matching shall be the primary answer path.
- Ollama/LLM shall be fallback only after measured latency proves it is acceptable.
- v1 shall be fully offline and require no API keys.
- v1.5 may add local Ollama/Qwen fallback, but keyword matching remains first.

## Repos And Notes Studied

Studied local files:

```text
C:\Users\Asus\Desktop\uni\grad\welcoming robot\pluto\modules\speech_in.py
C:\Users\Asus\Desktop\uni\grad\welcoming robot\pluto\modules\speech_out.py
C:\Users\Asus\Desktop\uni\grad\welcoming robot\pluto\modules\voice.py
C:\Users\Asus\Desktop\uni\grad\welcoming robot\pluto\modules\llm_groq.py
C:\Users\Asus\Desktop\uni\grad\welcoming robot\pluto\allinone.py
C:\Users\Asus\Desktop\Obsidian_Vault\02_Knowledge\Engineering\Baseline_Measure_Before_Setting_Targets.md
C:\Users\Asus\Desktop\Obsidian_Vault\02_Knowledge\Engineering\Component_Choice_Beats_Architecture_Optimization.md
```

Findings:

| Source | Good Part | Problem For Pluto v1 |
| --- | --- | --- |
| `speech_in.py` | Uses WebRTC VAD to stop listening after silence | Loads Whisper `base`, too heavy for tiny talk latency |
| `speech_out.py` | Edge-TTS voice quality is good | Network/service dependency and mp3 generation delay |
| `voice.py` | Simple structure with `pyttsx3` local TTS | Google STT needs network and phrase limit is 8 seconds |
| `llm_groq.py` / `allinone.py` | Full AI answers are expressive | Network/API path is not deterministic enough for robot welcome |
| Prior benchmark note | Measured pipeline on Raspberry Pi 4 | STT ~4.5s, Qwen 0.5B ~4.3s, Piper ~4.1s, total ~13s |

## Decision

Chosen roadmap:

```text
v1:
  fully offline
  keyword/fuzzy intent matching first
  max 9 input words
  max 9 output words
  canned/local responses
  no API keys
  no cloud calls

v1.5:
  keep v1 path as primary
  add local Ollama/Qwen fallback only behind config
  require benchmark evidence before enabling
  enforce timeout and word limits
```

Chosen v1 runtime strategy:

```text
STT result
  -> normalize text
  -> reject or shorten to max 9 words
  -> deterministic local keyword/intent matcher
  -> canned response max 9 words
  -> speak/display response
  -> log latency and response source
```

Ollama/Qwen is not rejected forever. It becomes the v1.5 fallback candidate.
It is rejected as the primary v1 path because previous Pluto notes show Qwen
0.5B around 4.3 seconds on Raspberry Pi 4. Even if a 9-word prompt improves
this, it must be benchmarked before it can be enabled in WELCOME_TALK.

The LLM path should be:

```text
disabled by default
enabled only with config flag
bounded by timeout
bounded by max input words
bounded by max output words
replaced by canned fallback if slow
```

## Comparison

| Path | Expected Answer Selection Latency After STT | Quality | Determinism | v1 Verdict |
| --- | ---: | --- | --- | --- |
| Keyword/intent matcher | less than 10 ms | Simple but stable | Very high | Primary |
| Fuzzy keyword matcher | 10-50 ms | Handles small STT mistakes | High | Good upgrade |
| Ollama Qwen 0.5B | must be measured; prior note says ~4.3 s | More flexible | Medium | Fallback only |
| Groq/cloud LLM | network-dependent | Strong | Low in field | Not primary |
| Hardcoded random fallback | less than 5 ms | Dumb but friendly | Very high | Required safety fallback |

## Proposed Response Bank

All responses must remain at or below 9 words.

| Intent | Example Triggers | Response |
| --- | --- | --- |
| greeting | hi, hello, hey | Hello. I am Pluto. |
| name | your name, who are you | I am Pluto. |
| creator | who made you, built you | Abdelrahman and the team built me. |
| feeling | how are you | I feel ready to meet people. |
| age | how old are you | I am still very new. |
| dance | can you dance | Yes, choose dance from the website. |
| purpose | what do you do | I welcome people and answer simply. |
| help | help, what can I ask | Ask me short simple questions. |
| goodbye | bye, goodbye | Goodbye. Come back soon. |
| unknown | no match | Ask me something simpler, please. |

## Input And Output Rules

Input rule:

```text
If STT result is 1-9 words, process normally.
If STT result is more than 9 words, answer:
"Short question please."
```

Output rule:

```text
All canned responses are checked by test.
If an LLM response exceeds 9 words, it is rejected or trimmed safely.
```

Prompt rule for optional Ollama:

```text
Answer in 9 words or fewer.
Be Pluto, a welcoming robot.
Question: <max 9 words>
```

## Interfaces

Inputs:

- Recognized text from STT.
- Optional confidence or quality score from STT.
- Website/manual text fallback for testing.
- Config flag for LLM fallback.

Outputs:

- Response text.
- Response source: `keyword`, `fuzzy`, `llm`, `fallback`, or `blocked`.
- Response latency.
- Word counts.
- Optional TTS request.
- Optional Uno face/text update.

External dependencies:

- Microphone for real speech.
- Speaker or text fallback for output.
- Optional Ollama local service for fallback experiments.

## Configuration

| Name | Default | Allowed Range | Reason |
| --- | --- | --- | --- |
| `talk_max_input_words` | 9 | 1-12 | Keeps STT/LLM scope tiny |
| `talk_max_output_words` | 9 | 1-12 | Keeps response fast and social |
| `talk_primary_engine` | `keyword` | `keyword` | Deterministic v1 |
| `talk_enable_ollama_fallback` | `false` | bool | LLM must not slow v1 |
| `talk_ollama_timeout_ms` | 1000 | 250-3000 | Must respect TIME-009 if enabled |
| `talk_unknown_response` | `Ask me something simpler, please.` | text <= 9 words | Safe fallback |
| `talk_version` | `v1` | `v1`, `v1.5` | Explicitly gates the engine set |

## Runtime Behavior

WELCOME_TALK enters only after arrival and `CMD:STOP`.

Normal path:

1. Verify TALK is allowed.
2. Verify wheels are stopped.
3. Accept a short recognized text or website text fallback.
4. Normalize text to lowercase words.
5. Enforce max 9 input words.
6. Match intent from local keyword bank.
7. Return response with max 9 words.
8. Log response path and latency.

If microphone is missing, WELCOME_TALK can still be tested through website text
input, but it must report that audio input is unavailable.

## How To Run

Study only. No runtime command yet.

Future benchmark command:

```bash
python -m tools.talk_latency_benchmark --engine keyword --trials 20
python -m tools.talk_latency_benchmark --engine ollama --model <model-name> --trials 10
```

Future web test:

```bash
curl -X POST http://127.0.0.1:8080/api/welcome/talk ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"what is your name\"}"
```

## How To Debug

Checklist:

1. Confirm WELCOME_TALK state is active.
2. Confirm wheels are stopped and STM32 heartbeat is healthy.
3. Confirm text has 9 words or fewer.
4. Check response source in logs.
5. If Ollama is enabled, check service health and timeout.
6. If TTS is slow, switch to text-only or cached audio.

Useful commands:

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
```

## Expected Evidence

Logs should show:

```text
WELCOME_TALK input_words=4 source=keyword latency_ms=<100 response="I am Pluto."
```

For long input:

```text
WELCOME_TALK blocked reason=input_too_long input_words=14 response="Short question please."
```

For LLM disabled:

```text
WELCOME_TALK source=fallback reason=llm_disabled
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-TALK-001 | Send known keyword question | response source `keyword`, latency below 100 ms | not run |
| VER-TALK-002 | Send 10+ word question | blocked with `Short question please.` | not run |
| VER-TALK-003 | Check response bank | every response <= 9 words | not run |
| VER-TALK-004 | Enable Ollama with timeout | slow LLM falls back safely | not run |
| VER-WELCOME-013 | Run TALK with motor noise | low confidence/fallback logged | not run |
| VER-TALK-005 | Run with no internet/API keys | v1 still answers with local responses | not run |
| VER-TALK-006 | Enable v1.5 without benchmark file | Ollama fallback remains disabled | not run |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Response feels slow | LLM or TTS used as primary | Check `response_source` and latency | Force keyword-only mode |
| Pluto answers nonsense | STT mistake or weak keyword bank | Review recognized text log | Add synonym or fallback |
| Long answers | LLM ignored word limit | Count output words in test | Reject LLM output |
| No speech input | Microphone missing or busy | Audio probe fails | Use website text fallback |
| Talk while moving | State sequencing bug | Check STM32 command log | Send `CMD:STOP`, enter ERROR if needed |

## Safety Notes

TALK must never command wheel movement. The robot must be stopped before
listening or answering. Audio failures must never affect STM32 heartbeat,
emergency stop, obstacle stop, or manual stop.

## Open Questions

- Which exact Ollama model name is installed on the Raspberry Pi?
- What is measured p50/p95 latency for 9-word input and 9-word output?
- Is local TTS fast enough, or should common Pluto lines be pre-recorded/cached?

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-27 | Initial study draft | Choose WELCOME_TALK v1 strategy before code |
| 2026-05-27 | Added v1/v1.5 split | Lock offline keyword-first v1 and benchmark-gated Qwen fallback |
