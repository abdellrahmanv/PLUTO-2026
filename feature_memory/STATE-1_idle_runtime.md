# Feature Memory: Phase 6 IDLE Runtime

Status: implemented, local smoke validated, awaiting Raspberry Pi hardware validation

Last updated: 2026-05-27

Last validated: 2026-05-27 local smoke test

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
STATE-1.1
STATE-1.2
STATE-1.4
STATE-1.10
STATE-1.11
STATE-1.12
STATE-1.13
STATE-1.16
STATE-1.17
STATE-1.18
STATE-1.40
STATE-1.41
STATE-1.42
STATE-1.43
STATE-1.50
STATE-1.51
STATE-1.52
STATE-1.53
IF-STM32-002
IF-STM32-007
IF-STM32-008
IF-STM32-010
TIME-001
TIME-002
PWR-002
WEB-TIME-001
WEB-TIME-003
```

Partially implemented or prepared:

```text
STATE-1.3
STATE-1.14
STATE-1.14.1
STATE-1.14.2
STATE-1.14.3
```

These Uno/LCD requirements are prepared but not hardware-validated because the
Uno and LCD are not installed yet.

Verification tests:

```text
VER-IDLE-001
VER-IDLE-003
VER-IDLE-006
VER-IDLE-008
VER-IDLE-009
Phase 6 idle runtime smoke test
Phase 6 web shell smoke test
```

## Design Intent

Make IDLE a real safe runtime, not just a label on the website.

In IDLE, Pluto must be awake, connected to STM32, sending heartbeat, reading
telemetry, reading obstacle reports, and keeping wheel intent at zero.

## Design Decision

Persistent STM32 runtime communication lives in:

```text
pluto_runtime/stm32_link.py
```

The operator website consumes the runtime link through:

```text
pluto_runtime/web_shell.py
```

The runtime link opens the STM32 serial port once and keeps it open. This avoids
repeated connect/disconnect behavior and gives the Pi a stable heartbeat loop.

## Runtime Behavior

Normal behavior:

1. Website starts.
2. Hardware probe identifies STM32.
3. Mode manager enters `IDLE`.
4. `Stm32SerialLink` opens the STM32 port.
5. Runtime sends `CMD:STOP` once as an IDLE stop guard.
6. Runtime sends `CMD:PING` every 0.4 seconds.
7. Runtime records `ACK:PING`, `ACK:STOP`, `TEL:`, `OBS:`, and `ALERT:` lines.
8. Website shows heartbeat counts, ping latency, telemetry, obstacles, and last line.

Degraded behavior:

- If STM32 is missing, mode manager enters `ERROR` and motion states are blocked.
- If Uno is missing, IDLE continues because Uno is optional in current hardware.
- If camera fails, IDLE keeps STM32 heartbeat and shows camera warning.

## Interfaces

Inputs:

- STM32 USB CDC serial port.
- STM32 lines:
  - `ACK:PING`
  - `ACK:STOP`
  - `TEL:...`
  - `OBS:...`
  - `ALERT:...`

Outputs:

- `CMD:STOP` on IDLE runtime start and transition stop guards.
- `CMD:PING` every 0.4 seconds.
- `stm32_runtime` block in `/api/status`.

Website impact:

- Adds an `STM32 Runtime` panel.
- Shows heartbeat count.
- Shows last ping latency.
- Shows telemetry dictionary.
- Shows obstacle dictionary.
- Shows last received STM32 line.

## How To Run

Run local smoke tests:

```bash
python3 tools/idle_runtime_smoke.py
python3 tools/web_shell_smoke.py
```

Run Raspberry Pi hardware validation:

```bash
cd ~/PLUTO-2026
/home/pi/yolo/env/bin/python tools/idle_runtime_smoke.py --require-hardware
```

Run website:

```bash
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

Check status:

```bash
curl http://127.0.0.1:8080/api/status
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| PHASE6-IDLE-001 | Parser smoke test | `TEL` and `OBS` lines parse into dictionaries | local pass |
| PHASE6-IDLE-002 | Run without STM32 | Smoke skips or reports missing hardware without crash | local pass |
| PHASE6-IDLE-003 | Run with STM32 | `CMD:PING` loop gets `ACK:PING` | awaiting Pi validation |
| PHASE6-IDLE-004 | Start website with STM32 | `/api/status.stm32_runtime.running == true` | awaiting Pi validation |
| PHASE6-IDLE-005 | Leave in IDLE | Ping count increases and no drive commands are sent | awaiting Pi validation |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Heartbeat not running | STM32 missing or serial busy | `stm32_runtime.running` false | Stop other Pluto process and refresh hardware |
| No `ACK:PING` | Wrong serial device or firmware not responding | `ack_ping_count` remains zero | Run Phase 1 STM32 probe |
| Serial busy | Another process owns `/dev/ttyACM0` | runtime error text | Stop duplicate web shell |
| No telemetry | STM32 firmware not sending `TEL:` | `last_line` but empty telemetry | Check STM32 firmware output |
| No obstacle data | Ultrasonics not wired or firmware not reporting `OBS:` | empty obstacle dictionary | Validate ultrasonic wiring |

## Safety Notes

IDLE shall not command motion. The persistent link only sends `CMD:STOP` and
`CMD:PING` in this phase.

Future MANUAL, WELCOME, and DANCE phases must reuse this link instead of
opening separate serial connections for movement commands.

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-27 | Created IDLE runtime memory | Phase 6 initiated after Phase 5 mode manager |
