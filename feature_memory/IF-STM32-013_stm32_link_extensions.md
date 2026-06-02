# Feature Memory: STM32 Link Extensions

Status: draft
Last updated: 2026-05-30
Last validated: 2026-05-30, dry-run simulated via stm32_link_extensions_smoke.py
Owner: Antigravity

## Requirement Trace
- [IF-STM32-013](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L370) (RETURN tracking)
- [IF-STM32-014](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L371) (RESET_HOME tracking)
- [IF-STM32-015](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L372) (ARM tracking)
- [STATE-3.5](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L650) (save home coordinate)
- [STATE-3.42](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L710) (odometry-guided return)
- [STATE-4.14](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L830) (NEMA stepper arm commands)

## Design Intent
Wiring Pi-side persistent serial link to support existing STM32 firmware commands for home return, home reset, and arm motion, while keeping actual movement dry-run and ensuring maximum physical safety.

## Design Decision
Implemented a robust serial command transmission structure with direct command logging, synchronous ACK tracking, and asynchronous completion status indicators (such as `return_active`, `return_complete` and `arm_done`) inside the persistent serial link `stm32_link.py`. All methods default to `wait_ack=True` with short timeouts to avoid thread blocking, and return comprehensive diagnostic dicts.

## Interfaces
- Commands: `CMD:RETURN`, `CMD:RESET_HOME`, `CMD:ARM:<steps>,<speed>`, `CMD:STOP`, `CMD:DRIVE:<speed>,<steer>`
- ACKs: `ACK:RETURN`, `ACK:RETURN_COMPLETE`, `ACK:RESET_HOME`, `ACK:ARM`, `ACK:ARM_DONE`
- Telemetry: `TEL:BAT,SPD,DIST,TEMP,X,Y,H,HOME,RET`
- Pi Runtime API: `Stm32SerialLink` exposes methods `send_return()`, `send_reset_home()`, and `send_arm()`.

## Runtime Behavior
- `send_return()` resets `return_complete = False` and sets `return_active = True`.
- On receipt of `ACK:RETURN_COMPLETE`, `return_active` transitions to `False` and `return_complete` becomes `True`.
- Interruption: `send_stop()` or `send_drive()` sets `return_active` to `False` to signal the return process was preempted.
- `send_arm()` resets `arm_done = False`. When NEMA stepper finishes motion, `ACK:ARM_DONE` transitions `arm_done` to `True`.
- STM32 telemetry now exposes odometry fields:
  - `X`, `Y`: current estimated position in centimeters.
  - `H`: heading in degrees.
  - `HOME`: distance to saved home in centimeters.
  - `RET`: `1` when STM32 return-to-home is active, otherwise `0`.
- STM32 return speed is bounded by `RETURN_SPEED = -25` instead of the previous hardcoded `-150`, matching the requirement that return speed shall be less than or equal to approach speed.

## Configuration
None.

## How To Run
The extensions are run and verified via the dedicated smoke test suite:
```bash
python tools/stm32_link_extensions_smoke.py
```

## How To Debug
1. Open the `/api/status` endpoint to inspect the current state of `Stm32RuntimeStatus` fields.
2. In the operator console, send serial commands and observe the incoming ACK responses.
3. Validate that `return_active` correctly shifts to `False` under completion or command preemptions.

## Expected Evidence
Logs or state changes including `ACK:RETURN`, `ACK:RETURN_COMPLETE`, `ACK:RESET_HOME`, `ACK:ARM`, and `ACK:ARM_DONE` in serial link telemetry output.

Example telemetry:

```text
TEL:BAT:36.2,SPD:0.0,DIST:0,TEMP:28.5,X:12.5,Y:-4.0,H:90.0,HOME:15.2,RET:1
```

## Verification Tests
Verified via:
- [tools/stm32_link_extensions_smoke.py](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/tools/stm32_link_extensions_smoke.py) (15 test cases verifying `FakeSerial` formatting, status defaults, and return_active state transitions)
- [tools/welcome_approach_smoke.py](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/tools/welcome_approach_smoke.py) (no regression)
- [tools/dance_smoke.py](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/tools/dance_smoke.py) (no regression)
- [tools/mode_manager_smoke.py](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/tools/mode_manager_smoke.py) (no regression)

## Failure Modes
- Serial transmission error: `Stm32SerialLink.error` is populated and `available` is set to `False`.
- Missing immediate ACK: commands time out after 450 ms and return `{"ok": False, "detail": "..."}`.
- Unbounded ARM motion: Calling `send_arm()` without safety limits may crash stepper. MUST NOT be called without strict bounds checks.

## Safety Notes
`send_arm()` has an explicit, high-priority safety warning in its docstring and must only be called after mechanical bounds and physical limit switches are verified. Odometry-guided `send_return()` represents a potential hazard because STM32 odometry can drift; thus, it is kept behind dry-run controls and only exercised after thorough wheels-lifted verification.

## Open Questions
None for Phase 1.

## Change History
- 2026-05-30: Refactored stm32_link_extensions feature memory to use the official SYSTEM_REQUIREMENTS template and correct requirement IDs IF-STM32-013 through IF-STM32-015 by Antigravity.
- 2026-05-30: Added STM32 odometry telemetry fields and bounded firmware return speed for return/dance planning evidence.
