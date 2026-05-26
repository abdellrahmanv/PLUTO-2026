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
