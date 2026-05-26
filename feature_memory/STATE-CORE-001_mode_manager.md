# Feature Memory: Phase 5 Mode Manager

Status: implemented, local smoke validated

Last updated: 2026-05-27

Last validated: 2026-05-27 local smoke test

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
WEB-006
WEB-007
WEB-008
WEB-TIME-001
WEB-SAFE-002
WEB-SAFE-003
WEB-SAFE-004
TRANS-001
TRANS-002
TRANS-003
TRANS-004
TRANS-005
TRANS-006
TRANS-007
TRANS-010
STATE-0.60
STATE-0.61
STATE-0.62
STATE-1.18
STATE-1.30
STATE-1.31
STATE-1.32
STATE-1.33
STATE-2.32
STATE-3.10
STATE-3.11
STATE-3.14
STATE-3.41
STATE-3R.1
STATE-3R.2
STATE-3R.3
STATE-5.1
STATE-5.5
STATE-5.20
STATE-5.21
STATE-5.23
```

Verification tests:

```text
Phase 5 mode manager smoke test
Phase 3/4/5 web shell smoke test
```

## Design Intent

Create one runtime owner for Pluto state transitions.

Before Phase 5, the website displayed blocked state requests with local logic.
After Phase 5, all state requests pass through `ModeManager`, which produces
accepted/rejected results, blocked reasons, stop guard requirements, and
transition logs.

This phase does not implement MANUAL driving, WELCOME approach, or DANCE
motion. It only builds the state authority those features will use.

## Design Decision

The mode manager is implemented as a dependency-light pure Python module:

```text
pluto_runtime/mode_manager.py
```

The operator website consumes it through:

```text
pluto_runtime/web_shell.py
```

Pure Python was chosen so the transition logic can be tested without hardware,
camera, serial devices, or the Raspberry Pi.

## Runtime Behavior

Normal behavior:

1. Runtime starts in `BOOTSTRAP`.
2. Hardware probe reports required hardware status.
3. If STM32 is available, mode manager enters `IDLE`.
4. If STM32 is missing, mode manager enters `ERROR`.
5. Website displays current state, substate, return lock, and allowed next
   states.
6. Website state requests call the mode manager.
7. Accepted transitions that enter or leave motion states require a stop guard.
8. `ERROR` can interrupt any state.
9. `WELCOME_RETURN` blocks all normal transitions except `ERROR`.

Blocked behavior:

- `GAME_LATER` is never reachable in v1.
- Motion states are blocked if STM32 is unavailable.
- Motion states are blocked if battery is critical.
- `WELCOME` requires confirmed trigger or operator request.
- `DANCE` requires explicit operator request.
- `ERROR -> IDLE` requires explicit reset and STM32 available.

## Interfaces

Inputs:

- Requested target state.
- Safety context:
  - STM32 availability.
  - Battery critical flag.
  - Motion intent zero flag.
  - Welcome trigger confirmed flag.
  - Operator request flag.
  - Return lock flag.
  - Active fault flag.

Outputs:

- Accepted/rejected transition result.
- Current state and substate.
- Allowed next states with reasons.
- Transition log with timestamp, previous state, next state, source, reason,
  blocked reasons, and stop guard flag.

Website impact:

- `/api/status` now includes `mode_manager`.
- Allowed state buttons are generated from mode manager decisions.
- `/api/request-state` returns transition result details.
- Emergency stop records an `ERROR` transition through the mode manager.

## How To Run

Run mode manager smoke test:

```bash
python3 tools/mode_manager_smoke.py
```

Run web shell smoke test:

```bash
python3 tools/web_shell_smoke.py
```

Run website:

```bash
python3 -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| PHASE5-MODE-001 | `BOOTSTRAP -> IDLE` with required checks pass | Accepted | local smoke pass |
| PHASE5-MODE-002 | `IDLE -> MANUAL` without STM32 | Rejected by `stm32_unavailable` | local smoke pass |
| PHASE5-MODE-003 | `IDLE -> MANUAL` with STM32 | Accepted and stop guard required | local smoke pass |
| PHASE5-MODE-004 | `MANUAL -> IDLE` with nonzero motion intent | Rejected | local smoke pass |
| PHASE5-MODE-005 | `IDLE -> WELCOME` without trigger | Rejected | local smoke pass |
| PHASE5-MODE-006 | `WELCOME_RETURN -> MANUAL` | Rejected by return lock | local smoke pass |
| PHASE5-MODE-007 | `ERROR -> IDLE` without reset | Rejected | local smoke pass |
| PHASE5-MODE-008 | `GAME_LATER` request | Rejected | local smoke pass |
| PHASE5-WEB-001 | `/api/status` | Includes `mode_manager` and allowed states | local smoke pass |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Motion state unavailable | STM32 missing | `/api/status` allowed state reason | Run Phase 1 STM32 probe |
| State button disabled | Mode manager gate blocks it | Check `blocked_by` in `/api/status` | Fix missing gate input or wait for feature phase |
| Cannot leave ERROR | Reset not explicit or STM32 missing | Transition result reason | Clear fault, reconnect STM32, request IDLE reset |
| WELCOME request rejected | Missing confirmed trigger | Transition result reason | Use operator trigger in v1 or implement wave trigger later |
| Return lock blocks modes | WELCOME_RETURN active | `return_lock: true` in `/api/status` | Finish return or use emergency stop |

## Safety Notes

The mode manager is a gate, not a motor driver.

It does not send raw movement commands. It marks when a stop guard is required.
The caller must send `CMD:STOP` before enabling or leaving motion states.

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-27 | Created Phase 5 mode manager | Centralize transition logic before implementing IDLE, MANUAL, WELCOME, DANCE, and ERROR behavior |
