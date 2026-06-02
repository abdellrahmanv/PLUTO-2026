# Feature Memory: Phase 7 MANUAL Control

Status: implemented baseline, local smoke validated, awaiting wheels-lifted reviewer validation

Last updated: 2026-05-27

Last validated: 2026-05-27 local smoke test

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
SAFE-004
SAFE-005
STATE-2.1
STATE-2.2
STATE-2.3
STATE-2.5
STATE-2.10
STATE-2.11
STATE-2.12
STATE-2.13
STATE-2.14
STATE-2.16
STATE-2.17
STATE-2.12.1
STATE-2.12.2
STATE-2.12.3
STATE-2.12.4
STATE-2.12.5
STATE-2.12.6
STATE-2.12.7
STATE-2.12.8
STATE-2.20
STATE-2.21
STATE-2.23
STATE-2.24
STATE-2.30
STATE-2.32
STATE-2.33
STATE-2.40
STATE-2.42
IF-STM32-001
IF-STM32-002
IF-STM32-003
IF-STM32-004
IF-STM32-006
TIME-007
WEB-022
WEB-SAFE-002
```

Prepared but not hardware-validated:

```text
STATE-2.4
STATE-2.15
STATE-2.41
```

The Uno/LCD path is still optional because Uno/LCD hardware is not installed.

Verification tests:

```text
VER-MANUAL-001
VER-MANUAL-003
VER-MANUAL-004
VER-MANUAL-007
VER-MANUAL-008
Phase 7 manual state smoke test
```

Wheels-lifted tests still required:

```text
VER-MANUAL-002
VER-MANUAL-005
VER-MANUAL-006
```

## Design Intent

Allow deliberate operator movement while STM32 remains the final motion safety
layer.

Manual control must be hold-to-move. Releasing input sends `CMD:STOP`.
Movement commands must be bounded and visible in logs.

## Design Decision

Manual control is implemented in the web runtime:

```text
pluto_runtime/web_shell.py
```

STM32 command support is added to:

```text
pluto_runtime/stm32_link.py
```

Validation tooling:

```text
tools/manual_state_smoke.py
```

The raw `/api/drive` route remains intentionally missing. Manual movement uses:

```text
POST /api/manual/drive
POST /api/manual/arm
POST /api/manual/stop
```

## Runtime Behavior

Normal MANUAL entry:

1. Operator requests `MANUAL` from website.
2. Mode manager validates transition from `IDLE`.
3. STM32 must be available.
4. Stop guard sends `CMD:STOP`.
5. Manual intent initializes to zero.
6. Manual controls become enabled.

Hold-to-move behavior:

1. Operator presses and holds a direction button.
2. Browser sends repeated `/api/manual/drive` requests every 150 ms.
3. Browser reads the current base speed and steer sliders before each repeat.
4. Server clamps speed and steer to configured limits.
5. Server sends `CMD:DRIVE:<speed>,<steer>` to STM32.
6. STM32 replies `ACK:DRIVE`.
7. Releasing pointer/touch sends `/api/manual/stop`.
8. Server sends `CMD:STOP`.

Arm click-to-step behavior:

1. Operator selects arm steps and arm speed.
2. Operator clicks Arm1 +, Arm1 -, Arm2 +, or Arm2 -.
3. Browser sends one `/api/manual/arm` request.
4. Server clamps steps to `max_arm_steps` and speed to `max_arm_speed`.
5. Server sends `CMD:ARM:<steps>,<speed>` or `CMD:ARM2:<steps>,<speed>`.
6. Arm commands do not auto-repeat while held.
7. Website records the last arm command for debugging.

Blocked behavior:

- `/api/manual/drive` outside MANUAL is rejected.
- `/api/manual/arm` outside MANUAL is rejected.
- Raw `/api/drive` stays unavailable.
- Manual drive is rejected if STM32 is unavailable.
- Manual arm is rejected if STM32 is unavailable.
- Forward intent is clamped to zero if obstacle telemetry is below stop threshold.
- Emergency stop enters `ERROR`.

## Configuration

| Name | Default | Reason |
| --- | --- | --- |
| Manual max speed | `150` | Operator-tunable base speed limit for MANUAL |
| Manual max steer | `80` | Low turn rate for first validation |
| Base speed slider | `0..150` | Operator can tune base motion without code edits |
| Base steer slider | `0..80` | Operator can tune turn motion without code edits |
| Arm step setting | `100` default, `1200` max | Bounded click-to-step arm testing |
| Arm speed setting | `200` default, `1000` max | Variable NEMA speed testing |
| Command repeat period | `150 ms` | Meets manual latency target while avoiding serial spam |
| Obstacle forward block | `< 60 cm` | Matches STM32 obstacle stop baseline |

## Interfaces

Inputs:

- Website hold buttons:
  - Forward.
  - Back.
  - Left.
  - Right.
  - Stop.
- Website variable controls:
  - Base speed slider.
  - Base steer slider.
  - Arm steps input.
  - Arm speed input.
  - Arm1 + / Arm1 -.
  - Arm2 + / Arm2 -.

Outputs:

- `CMD:DRIVE:<speed>,<steer>`.
- `CMD:ARM:<steps>,<speed>`.
- `CMD:ARM2:<steps>,<speed>`.
- `CMD:STOP`.
- Manual status in `/api/status.manual`.
- STM32 drive counters in `/api/status.stm32_runtime`.

## Website Impact

The website now includes a `Manual Control` panel showing:

- enabled flag.
- speed/steer intent.
- configured limits.
- blocked reason.
- variable base speed and steer controls.
- hold-to-move direction buttons.
- bounded arm 1 and arm 2 step/speed controls.
- last arm command.
- stop button.

## How To Run

Local smoke tests:

```bash
python3 tools/manual_state_smoke.py
python3 tools/web_shell_smoke.py
python3 tools/mode_manager_smoke.py
```

Raspberry Pi safe validation without moving wheels:

```bash
cd ~/PLUTO-2026
/home/pi/yolo/env/bin/python tools/manual_state_smoke.py
/home/pi/yolo/env/bin/python tools/web_shell_smoke.py
```

Wheels-lifted validation:

```text
1. Lift hoverboard wheels off the ground.
2. Open website.
3. Enter MANUAL.
4. Hold Forward briefly.
5. Release.
6. Confirm `CMD:STOP` and no continued movement.
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| PHASE7-MANUAL-001 | Request raw `/api/drive` | `404` | local pass |
| PHASE7-MANUAL-002 | Request manual drive outside MANUAL | rejected | local pass |
| PHASE7-MANUAL-003 | Request manual arm outside MANUAL | rejected | local pass |
| PHASE7-MANUAL-004 | Inspect `/api/status.manual` | base and arm limits visible | local pass |
| PHASE7-MANUAL-005 | Enter MANUAL with STM32 | stop guard sent and manual enabled | awaiting Pi validation |
| PHASE7-MANUAL-006 | Send zero manual drive in MANUAL | `ACK:DRIVE`, no movement intent | awaiting Pi validation |
| PHASE7-MANUAL-007 | Hold forward with wheels lifted | repeated `CMD:DRIVE`, release sends `CMD:STOP` | not run |
| PHASE7-MANUAL-008 | Click Arm1/Arm2 with wheels and arms isolated | one bounded `CMD:ARM` or `CMD:ARM2` per click | not run |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Manual buttons disabled | State is not MANUAL | `/api/status.current_state` | Select MANUAL from IDLE |
| Drive rejected | STM32 missing or wrong state | `/api/status.manual.blocked_reason` | Reconnect STM32 or reset to IDLE |
| No `ACK:DRIVE` | STM32 firmware not accepting command | `stm32_runtime.last_line` | Run Phase 1 probe and firmware check |
| Robot keeps moving after release | Stop route failed or browser event lost | event log and `ACK:STOP` count | Press Emergency Stop |
| Forward blocked | Obstacle telemetry under 60 cm | manual blocked reason | Clear obstacle or test reverse/turn only |

## Safety Notes

Do not perform nonzero MANUAL movement with wheels on the ground during first
validation.

The first real motion test must follow `SAFE-006`: wheels lifted off ground.

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-27 | Created MANUAL control memory | Phase 7 initiated after ERROR state validation |
