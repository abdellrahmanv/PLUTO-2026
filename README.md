# Pluto Grad 22-5

This repository is for the Pluto graduation robot project.

Current study direction:

- Raspberry Pi is the main brain and mode manager.
- STM32F401 Black Pill is the motor and safety controller.
- Arduino Uno is the LCD / face / UI controller.
- The Pi decides what Pluto should do.
- The Arduinos execute simple, bounded commands.

The architecture is still allowed to change. For now, keep the system simple,
safe, and easy to test one layer at a time.

## Engineering Method

Pluto code should be implemented with a systems-engineering workflow:

- define the interface,
- implement one layer,
- verify it on the bench,
- add telemetry and logs,
- then integrate the next layer.

See `SYSTEMS_ENGINEERING.md` before adding new robot behavior.

System requirements and state decomposition live in `SYSTEM_REQUIREMENTS.md`.

The build order and feature-by-feature workflow live in
`HOW_TO_BUILD_THE_SYSTEM_RIGHT.md`.

## Current Validation Tools

```bash
python3 tools/stm32_probe.py
python3 tools/uno_probe.py
python3 tools/web_shell_smoke.py
python3 tools/validation_center_smoke.py
python3 -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

## One-Command Website Start

From PowerShell in the repository root on the Raspberry Pi:

```powershell
.\tools\start_website.ps1
```

The launcher finds Python, runs the safe website smoke test when needed,
detects and validates the STM32 motor controller with safe `PING`/`STOP`
checks, verifies the persistent heartbeat runtime, and then starts the operator
website on port 8080.

If PowerShell blocks local scripts on Windows, use the same launcher with an
execution-policy override:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\start_website.ps1
```

For laptop UI-only checks without required robot hardware:

```powershell
.\tools\start_website.ps1 -UiOnly
```

The website includes a Stage 1 Validation Center that runs existing safe or
dry-run validation tools from the operator console. Hardware-required buttons
stay disabled until the matching device is detected.
