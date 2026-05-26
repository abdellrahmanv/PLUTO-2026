# Feature Memory: Operator Console Shell

Status: implemented, awaiting Raspberry Pi browser validation

Last updated: 2026-05-26

Last validated: not yet validated on Raspberry Pi browser

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
SYS-007
SYS-011
WEB-001
WEB-004
WEB-006
WEB-007
WEB-008
WEB-009
WEB-010
WEB-013
WEB-014
WEB-015
WEB-019
WEB-020
WEB-021
WEB-022
WEB-024
WEB-025
WEB-SAFE-001
WEB-SAFE-002
WEB-TIME-004
```

Verification tests:

```text
VER-WEB-001
VER-WEB-005
VER-WEB-006
VER-WEB-008
VER-WEB-009
VER-WEB-010
Phase 3 web shell smoke test
```

## Design Intent

Create Pluto's first operator website without adding motion behavior. The
website must make system state visible, show hardware readiness, expose useful
debug events, and provide a visible emergency stop path.

## Design Decision

The implementation is a dependency-light Python HTTP server in
`pluto_runtime/web_shell.py`. It uses the Python standard library for the web
server so Phase 3 does not depend on Flask, Node, or deployment tooling.

The shell scans serial devices directly for STM32 and Uno status. Motion states
are displayed but blocked because the Phase 5 mode manager and later behavior
phases are not implemented yet.

## Interfaces

Inputs:

- Browser requests to the website.
- Optional STM32 USB CDC serial device.
- Optional Uno USB serial device.

Outputs:

- HTML operator console at `/`.
- JSON status at `/api/status`.
- Hardware refresh at `/api/refresh-hardware`.
- Emergency stop at `/api/emergency-stop`.
- State request path at `/api/request-state`.
- Dry-run shutdown shell at `/api/shutdown`.

External dependencies:

- Python 3.
- `pyserial` when serial hardware is present.
- STM32 Phase 1 firmware/protocol for emergency stop.

## Configuration

Configuration values, defaults, limits, and files:

| Name | Default | Allowed Range | Reason |
| --- | --- | --- | --- |
| `--host` | `127.0.0.1` | valid bind address | Safe local default |
| `--port` | `8080` | valid TCP port | Operator console port |
| `--baud` | `115200` | serial baud accepted by controllers | Matches Pluto serial tools |

## Runtime Behavior

Normal behavior:

1. Start PLUTO web shell.
2. Probe serial ports for STM32 and Uno.
3. If STM32 is found, send `CMD:STOP` during detection and display IDLE shell.
4. If STM32 is missing, display ERROR shell and block motion states.
5. Show current state, substate, hardware status, bootstrap report, and events.
6. Poll `/api/status` every second from the browser.
7. If operator presses emergency stop, send `CMD:STOP` when STM32 is available
   and move shell state to ERROR.

Blocked behavior:

- No raw motor endpoint exists.
- MANUAL, WELCOME, and DANCE requests are logged but not accepted.
- Shutdown command requires confirmation but real shutdown is disabled in
  Phase 3.
- Camera feed is shown as Phase 4 unavailable.

## How To Run

Run locally:

```bash
python3 -m pluto_runtime.web_shell
```

Run on Raspberry Pi for network access:

```bash
python3 -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

Open:

```text
http://<raspberry-pi-ip>:8080
```

Run smoke test:

```bash
python3 tools/web_shell_smoke.py
```

## How To Debug

Checklist:

1. Run `python3 -m py_compile pluto_runtime/web_shell.py`.
2. Run `python3 tools/web_shell_smoke.py`.
3. Confirm `http://127.0.0.1:8080/healthz` returns JSON.
4. Confirm `/api/status` includes `project: PLUTO`.
5. Confirm `/api/drive` returns `404`.
6. Confirm emergency stop logs an event.
7. If STM32 status is missing, run `python3 tools/stm32_probe.py`.
8. If Uno status is missing, run `python3 tools/uno_probe.py` after hardware arrives.

Useful commands:

```bash
python3 -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
curl http://127.0.0.1:8080/api/status
curl -X POST http://127.0.0.1:8080/api/emergency-stop
curl -X POST http://127.0.0.1:8080/api/drive
```

## Expected Evidence

Smoke test:

```text
WEB_SHELL_SMOKE PASS
```

Website home:

```text
PLUTO visible as the main project identity.
Current state visible.
Emergency Stop visible.
Hardware status visible.
Bootstrap report visible.
Events visible.
```

API evidence:

```text
GET /api/status -> 200 with project PLUTO
POST /api/request-state MANUAL -> accepted false
POST /api/emergency-stop -> state ERROR
POST /api/drive -> 404
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-WEB-001 | Open home page | `PLUTO` visible | local smoke pass |
| VER-WEB-005 | Request MANUAL while shell blocks modes | Request rejected with reason | local smoke pass |
| VER-WEB-006 | Press emergency stop | `CMD:STOP` attempted and state becomes ERROR | local smoke pass without hardware ACK |
| VER-WEB-008 | View bootstrap report | Hardware report visible in `/api/status` and UI | local smoke pass |
| VER-WEB-009 | Open on phone viewport | Layout stacks without overlap | not yet browser-validated |
| VER-WEB-010 | Attempt raw drive route | `/api/drive` returns `404` | local smoke pass |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Website does not open | Server not running or wrong bind address | Check terminal output and port | Run with `--host 0.0.0.0 --port 8080` on Pi |
| STM32 shows missing | USB disconnected or protocol unavailable | Run Phase 1 probe | Reconnect STM32 and rerun hardware refresh |
| Emergency stop lacks ACK | STM32 unavailable or serial busy | Event log and API serial detail | Use physical stop / STM32 safety, then debug serial |
| State request blocked | Expected in Phase 3 | Event log says mode manager missing | Implement Phase 5 before accepting transitions |
| Raw drive unavailable | Expected safety behavior | `/api/drive` returns 404 | Use MANUAL phase later |

## Safety Notes

The website is not the only safety layer. It does not enable movement and does
not expose raw motor commands. Emergency stop attempts `CMD:STOP` when STM32 is
available, but the STM32 remains the real motor safety controller.

## Open Questions

- Should the final website use this standard-library server or move to FastAPI
  after Phase 5?
- Should shutdown become active in Phase 3.1 or wait until final setup/service
  requirements are implemented?

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-26 | Initial implementation memory | Phase 3 initiated |
