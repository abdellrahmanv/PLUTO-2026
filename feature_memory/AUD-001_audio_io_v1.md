# Feature Memory: Audio I/O v1 For WELCOME Talk

Status: implemented

Last updated: 2026-05-27

Last validated: 2026-05-27 Raspberry Pi probe for camera microphone, Piper, and faster-whisper

Owner: Pluto software

## Requirement Trace

Implemented requirements:

```text
AUD-001
AUD-002
AUD-006
AUD-010
AUD-012
AUD-013
AUD-014
AUD-015
AUD-019
AUD-022
AUD-023
AUD-024
STATE-3.33
STATE-3.36
STATE-3.37
STATE-3.33.1
STATE-3.33.2
STATE-3.33.3
STATE-3.33.6
STATE-3.33.9
STATE-3.33.10
MEM-001
MEM-011
```

Verification tests:

```text
VER-AUD-001
VER-AUD-002
VER-AUD-003
VER-WELCOME-013
```

## Design Intent

Make Pluto's first speech path useful without making it heavy. The robot should
find the webcam microphone, accept short questions, answer from a large local
keyword bank, and optionally speak the answer through local Piper TTS.

## Design Decision

Use ALSA command-line tools for hardware I/O:

- `arecord` records from the selected microphone.
- `aplay` plays generated speech.
- `faster-whisper` is used only when already installed with a local model.
- Piper is used only when the local binary and model are present.

The answer layer remains deterministic keyword/fuzzy matching. Ollama/Qwen is
not enabled in v1 because the latency risk is too high for a welcoming robot.

## Interfaces

Inputs:

- Website text input through `/api/welcome/talk`.
- Webcam microphone audio through `/api/welcome/listen`.
- Optional headset microphone selected by website, API, CLI, or environment.
- Optional `speak=true` flag to generate TTS.

Outputs:

- Website-visible transcript.
- Website-visible response.
- Piper WAV playback through the selected ALSA speaker.
- Audio status in `/api/status` and `/api/audio/status`.
- Requested microphone/speaker override in audio status.

External dependencies:

- Linux ALSA tools: `arecord`, `aplay`.
- Optional `faster_whisper` Python package.
- Optional local faster-whisper model.
- Optional local Piper binary and model.

## Configuration

| Name | Default | Allowed Range | Reason |
| --- | --- | --- | --- |
| sample_rate | 16000 | 16000 recommended | Whisper-friendly speech input |
| channels | 1 | 1 | Keeps CPU and file size low |
| listen_duration_s | 3.0 | 0.5-8.0 | Short social questions |
| min_rms | 0.03 | tune per room | Skip STT for camera-mic noise floor |
| max_input_words | 9 | 1-9 in v1 | Keeps response path bounded |
| max_output_words | 9 | 1-9 in v1 | Keeps TTS fast and clear |
| PLUTO_WHISPER_MODEL | unset | local model path | Override model discovery |
| PLUTO_PIPER_BIN | unset | local binary path | Override Piper binary |
| PLUTO_PIPER_MODEL | unset | local model path | Override Piper voice |
| PLUTO_MIC_DEVICE | unset | ALSA id/name token | Prefer a specific mic, such as a headset |
| PLUTO_SPEAKER_DEVICE | unset | ALSA id/name token | Prefer a specific playback device |

## Runtime Behavior

At web startup, `AudioRuntime` probes ALSA capture and playback devices. Capture
selection first honors an explicit microphone override, then prefers headset or
headphone microphones, then camera, webcam, USB, mic, or microphone devices.
Playback selection first honors an explicit speaker override, then prefers
headphones, then speaker/USB/audio devices.

On the Raspberry Pi probe, the webcam appeared as:

```text
card 3: camera [HD camera], device 0: USB Audio [USB Audio]
selected_microphone = plughw:CARD=camera,DEV=0
```

The website exposes three WELCOME_TALK controls:

- `Ask`: text answer only.
- `Ask+Speak`: text answer plus Piper TTS.
- `Listen 3s`: record from selected mic, transcribe, answer, and speak.

The website also exposes microphone controls:

- `Use Mic`: select a specific ALSA microphone id/name/token.
- `Auto Mic`: clear the override and return to automatic selection.
- `Audio Refresh`: reprobe ALSA devices after plugging in a headset.

Before Whisper runs, Pluto measures WAV RMS/peak. If the signal is below
`min_rms`, it skips STT and returns the normal empty-input response. The Pi
camera mic showed an idle RMS near `0.018`, so v1 defaults to `0.03` to avoid
wasting CPU on room noise.

WELCOME_TALK still requires WELCOME state. If used outside WELCOME, it is
blocked and the website shows `Enter WELCOME first.`

## How To Run

Local deterministic tests:

```bash
python tools/welcome_talk_smoke.py
python tools/audio_io_smoke.py
```

Raspberry Pi hardware probe:

```bash
/home/pi/yolo/env/bin/python tools/audio_io_smoke.py --require-microphone --record-probe
```

Headset microphone probe:

```bash
/home/pi/yolo/env/bin/python tools/audio_io_smoke.py --require-microphone --record-probe --microphone-device headset
```

Explicit ALSA device probe:

```bash
/home/pi/yolo/env/bin/python tools/audio_io_smoke.py --require-microphone --record-probe --microphone-device plughw:CARD=camera,DEV=0
```

Running server:

```bash
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

API checks:

```bash
curl http://127.0.0.1:8080/api/audio/status
curl -X POST http://127.0.0.1:8080/api/audio/refresh
curl -X POST http://127.0.0.1:8080/api/audio/select-microphone \
  -H 'Content-Type: application/json' \
  -d '{"device":"headset"}'
curl -X POST http://127.0.0.1:8080/api/audio/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"I am Pluto."}'
```

## How To Debug

Checklist:

1. Confirm the microphone exists in `arecord -l`.
2. Confirm selected microphone in `/api/audio/status`.
3. Run `tools/audio_io_smoke.py --record-probe`.
4. Confirm `faster_whisper` imports in `/home/pi/yolo/env`.
5. Confirm Piper binary and model paths exist.
6. Check `/tmp/pluto_tts_cache` for generated WAV files.

Useful commands:

```bash
arecord -l
arecord -L
arecord -D plughw:CARD=camera,DEV=0 -f S16_LE -r 16000 -c 1 -d 1 /tmp/pluto_mic_probe.wav
aplay -l
aplay -D default:CARD=Headphones /tmp/pluto_tts_probe.wav
python -c "import faster_whisper; print('ok')"
```

## Expected Evidence

```text
microphone_available = true
selected_microphone = plughw:CARD=camera,DEV=0
requested_microphone = null or headset override
speaker_available = true
stt_backend = faster-whisper
tts_backend = piper
AUDIO_IO_SMOKE PASS
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-AUD-001 | `/api/audio/status` | camera mic and speaker status visible | implemented |
| VER-AUD-002 | `tools/audio_io_smoke.py --record-probe` | one-second WAV recorded | Pi probe passed manually |
| VER-AUD-003 | `/api/audio/speak` | Piper TTS starts through speaker device | Piper/aplay command passed manually |
| VER-WELCOME-013 | `/api/welcome/listen` in WELCOME | transcript, keyword answer, optional speech | pending live voice review |
| VER-AUD-004 | Silence listen | STT skipped by RMS gate | implemented |
| VER-AUD-005 | Headset mic override | selected microphone follows requested headset/device token | implemented, Pi hardware check required |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| No microphone | Webcam missing or ALSA card changed | `arecord -l` | Replug camera, refresh audio |
| Wrong microphone | ALSA name did not match preferred tokens | `/api/audio/status` | Use website mic override, CLI flag, or `PLUTO_MIC_DEVICE` |
| STT unavailable | `faster_whisper` or model missing | `stt_backend` is unavailable | Install/copy local model |
| TTS unavailable | Piper binary/model missing | `tts_backend` is unavailable | Restore `/home/pi/pluto-v2` Piper files |
| Listen is slow | Tiny Whisper still CPU-bound | `last_transcript.elapsed_ms` | Keep v1 short, use text fallback |
| No sound heard | Wrong playback device or volume | `aplay -l`, mixer settings | Select headphones/speaker, adjust volume |

## Safety Notes

Audio code never sends drive or arm motion commands. WELCOME_TALK sends a stop
guard before answering, and audio failures do not affect STM32 heartbeat or
emergency stop behavior.

## Open Questions

- Should v1 cache the most common spoken answers during startup?
- Should Pluto add a push-to-talk mode to avoid motor noise?
- Should audio output volume be controlled from the website?

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-27 | Initial implementation memory | Add camera mic, local STT/TTS, and larger talk bank |
| 2026-05-27 | Added headset microphone override | Allow testing speech through a headphone microphone without code changes |
