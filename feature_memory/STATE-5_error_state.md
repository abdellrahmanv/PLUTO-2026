# Feature Memory: Phase 8 ERROR State

Status: implemented, local smoke validated, awaiting Raspberry Pi hardware reviewer validation

Last updated: 2026-05-27

Last validated: 2026-05-27 local smoke test

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
SYS-007
WEB-013
WEB-014
WEB-015
WEB-SAFE-002
WEB-SAFE-004
STATE-5.1
STATE-5.2
STATE-5.4
STATE-5.5
STATE-5.10
STATE-5.11
STATE-5.12
STATE-5.13
STATE-5.14
STATE-5.20
STATE-5.21
STATE-5.22
STATE-5.23
TRANS-004
TIME-006
```

Prepared but not hardware-validated:

```text
STATE-5.3
```

The Uno/LCD warning path is documented and ready, but the Uno/LCD hardware is
not installed yet.

Verification tests:

```text
VER-ERROR-001
VER-ERROR-004
VER-ERROR-005
VER-ERROR-006
Phase 8 error state smoke test
```

## Design Intent

Make ERROR a controlled safe state, not a crash or mystery condition.

When Pluto enters ERROR, the operator must see the fault reason, the prior
state, recovery action, and blocked transitions. ERROR must not allow motion
states until the fault is explicitly reset.

## Design Decision

ERROR remains owned by the Phase 5 mode manager:

```text
pluto_runtime/mode_manager.py
```

Operator-facing ERROR behavior is implemented in:

```text
pluto_runtime/web_shell.py
```

Test coverage is added in:

```text
tools/error_state_smoke.py
```

The website now exposes safe diagnostic actions:

```text
POST /api/emergency-stop
POST /api/inject-fault
POST /api/reset-error
```

These actions do not expose raw motor movement.

## Runtime Behavior

Normal ERROR entry:

1. Fault or emergency stop occurs.
2. Pi sends `CMD:STOP` when STM32 is available.
3. Mode manager enters `ERROR`.
4. Fault reason is recorded.
5. Previous state is available from the transition log.
6. Website shows recovery action.
7. Motion state requests are rejected.
8. STM32 heartbeat/status reading continues if the link is available.

Reset behavior:

1. Operator presses `Reset To IDLE`.
2. Hardware is refreshed.
3. STM32 must be available.
4. Fault must be clear from the mode manager context.
5. `CMD:STOP` is sent as a reset stop guard.
6. Mode manager returns to `IDLE`.

Diagnostic behavior:

- `Inject Test Fault` places Pluto into `ERROR` without commanding motion.
- This is for validating website and mode-manager behavior before real faults.

Critical alert behavior:

- STM32 `ALERT:` lines are recorded by the runtime link.
- Alerts containing critical tokens such as `CRITICAL`, `FAULT`, `TIMEOUT`,
  `ESTOP`, `LOW_BAT`, or `DISCONNECT` escalate to `ERROR`.
- Non-critical obstacle/status alerts are recorded but do not automatically
  trigger ERROR.

## Interfaces

Inputs:

- Website emergency stop.
- Website diagnostic fault injection.
- Website reset request.
- STM32 critical `ALERT:` lines.
- Missing required STM32 hardware.

Outputs:

- `CMD:STOP` on emergency stop and ERROR reset guard.
- `ERROR` state and `ERROR_ACTIVE` substate.
- `/api/status.error` block:
  - active flag.
  - fault reason.
  - previous state.
  - recovery action.
  - STM32 availability.
  - last alert.

## Website Impact

The website now shows:

- Fault reason.
- Recovery action.
- Reset To IDLE button.
- Inject Test Fault button.
- ERROR transition events.
- Blocked state reasons while ERROR is active.

## How To Run

Local tests:

```bash
python3 tools/error_state_smoke.py
python3 tools/mode_manager_smoke.py
python3 tools/web_shell_smoke.py
```

Raspberry Pi validation:

```bash
cd ~/PLUTO-2026
/home/pi/yolo/env/bin/python tools/error_state_smoke.py
/home/pi/yolo/env/bin/python tools/mode_manager_smoke.py
/home/pi/yolo/env/bin/python tools/web_shell_smoke.py
```

Manual website validation:

```text
1. Open website.
2. Press Emergency Stop.
3. Confirm state becomes ERROR.
4. Confirm fault reason is visible.
5. Try DANCE or MANUAL and confirm it is rejected.
6. Press Reset To IDLE.
7. Confirm state returns to IDLE if STM32 is connected.
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| PHASE8-ERROR-001 | Press emergency stop | State becomes `ERROR` | local smoke pass |
| PHASE8-ERROR-002 | View `/api/status` in ERROR | `error.active == true`, fault reason visible | local smoke pass |
| PHASE8-ERROR-003 | Request DANCE while in ERROR | Rejected by reset gate | local smoke pass |
| PHASE8-ERROR-004 | Inject diagnostic fault | State remains/enters ERROR with injected reason | local smoke pass |
| PHASE8-ERROR-005 | Reset with STM32 missing | Reset rejected with `stm32_unavailable` | local smoke pass |
| PHASE8-ERROR-006 | Reset with STM32 connected | Reset accepted and `CMD:STOP` sent | awaiting Pi validation |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| ERROR will not reset | STM32 missing | `blocked_by` includes `stm32_unavailable` | Reconnect STM32 and refresh/reset |
| Fault reason missing | Fault entered without reason | Transition log review | Use `enter_error(reason)` path |
| Motion state accepted in ERROR | Mode manager bug | `tools/error_state_smoke.py` | Fix transition gate before MANUAL |
| E-stop lacks ACK | STM32 unavailable or busy | API `serial.detail` | Use physical stop, then debug serial |
| Critical alert ignored | Alert token missing | `stm32_runtime.alerts` | Add token or classifier rule |

## Safety Notes

ERROR shall not command motion. Diagnostic fault injection and reset only send
safe commands such as `CMD:STOP`.

Phase 7 MANUAL must not start until Phase 8 ERROR has been validated on the
Raspberry Pi with STM32 connected.

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-27 | Created ERROR state memory | Phase 8 initiated before MANUAL for safer motion development |
