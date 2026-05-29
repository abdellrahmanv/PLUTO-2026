# Pluto Tools

This folder contains standalone validation tools. Tools must prove one feature
at a time and must stay safe by default.

## Phase 1 - STM32 Serial Validation

Run from the repository root on the Raspberry Pi or development laptop:

```bash
python3 tools/stm32_probe.py
```

If the auto-scan finds the wrong port, run with an explicit port:

```bash
python3 tools/stm32_probe.py --port /dev/ttyACM0
```

Expected pass evidence:

```text
PHASE 1 RESULT: PASS
ACK:PING latency <= 100 ms
STOP ACK: PASS
TEL line present
OBS line present
```

The tool never sends `CMD:DRIVE`, `CMD:ARM`, `CMD:RETURN`, or any other motion
command. It sends only `CMD:PING` and `CMD:STOP`.

## Phase 2 - Uno LCD Serial Validation

Run after the Uno LCD controller firmware is flashed and the Uno is connected
by USB:

```bash
python3 tools/uno_probe.py
```

If the auto-scan finds the wrong port, run with an explicit port:

```bash
python3 tools/uno_probe.py --port /dev/ttyACM1
```

Expected pass evidence:

```text
PHASE 2 RESULT: PASS
ID:UNO_LCD present
MODE commands acknowledged
FACE commands acknowledged
TEXT command acknowledged
LCD visibly changes
```

The tool never sends motor commands. It only validates Pluto face/display
commands.

## Phase 3 - Operator Website Shell

Run the PLUTO operator console shell:

```bash
python3 -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

Smoke test:

```bash
python3 tools/web_shell_smoke.py
```

Expected pass evidence:

```text
WEB_SHELL_SMOKE PASS
```

The website shell displays system state and hardware status, blocks unavailable
motion states, and exposes emergency stop. It does not expose raw motor routes.

## Phase 4 - Camera Feed And Human Detection

Run the operator console with camera dependencies on the Raspberry Pi:

```bash
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

Useful endpoints:

```text
/api/camera/status
/camera.jpg
/camera.mjpg
```

The camera service uses threaded capture, frame skipping, MJPG, low resolution,
YOLOv8n float16 TFLite human detection, and warmup-frame suppression.

## Phase 9 - WELCOME Audio And Simple Talk

Run the local deterministic answer and website talk smoke test:

```bash
python3 tools/welcome_talk_smoke.py
```

The smoke test also audits the offline MSA University knowledge bank. Example
questions include:

```text
what means msa
who founded msa
how many faculties
msa address
msa hotline
```

Run the audio detector. On the Raspberry Pi with the webcam connected, require
the camera microphone and record one second:

```bash
/home/pi/yolo/env/bin/python tools/audio_io_smoke.py --require-microphone --record-probe
```

To test a headphone/headset microphone, plug it in, refresh audio, then run:

```bash
/home/pi/yolo/env/bin/python tools/audio_io_smoke.py --require-microphone --record-probe --microphone-device headset
```

If ALSA shows a specific id, use it directly:

```bash
arecord -l
/home/pi/yolo/env/bin/python tools/audio_io_smoke.py --require-microphone --record-probe --microphone-device plughw:CARD=camera,DEV=0
```

Useful endpoints:

```text
/api/audio/status
/api/audio/refresh
/api/audio/select-microphone
/api/audio/select-speaker
/api/audio/speak
/api/welcome/talk
/api/welcome/listen
```

Expected Pi evidence:

```text
selected_microphone = plughw:CARD=camera,DEV=0
stt_backend = faster-whisper
tts_backend = piper
AUDIO_IO_SMOKE PASS
```

## Phase 9B - WELCOME Wave Trigger

Run the lightweight wave-trigger smoke test:

```bash
python3 tools/welcome_wave_smoke.py
```

With the Pi website and STM32 already running:

```bash
/home/pi/yolo/env/bin/python tools/welcome_wave_smoke.py --host 127.0.0.1 --port 8080 --external-server --hardware-flow
```

Useful endpoint:

```text
/api/welcome/wave-trigger
```

The v1 detector uses existing camera human boxes. It does not load MediaPipe or
PyTorch and it never sends motor commands directly.

## Phase 10 - WELCOME_APPROACH Dry Run

Run the planner smoke test:

```bash
python3 tools/welcome_approach_smoke.py
```

With the Pi website open, trigger WELCOME with a real wave and review the
`Welcome Approach` panel. Phase 10 computes target lock, center offset,
distance class, obstacle status, and proposed motion, but it is dry-run only.

Expected evidence:

```text
WELCOME_APPROACH_SMOKE PASS
welcome_approach.dry_run = true
No CMD:DRIVE is sent by WELCOME_APPROACH
STOP guard remains active while approach is evaluated
```
