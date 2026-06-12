# Feature Memory: Tablet Robot Face

Status: implemented, awaiting Raspberry Pi tablet validation

Last updated: 2026-06-08

Last validated: 2026-06-08 local browser and smoke tests, not yet validated on Samsung tablet hardware

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
SYS-005
SYS-006
SYS-008
SYS-011
SYS-012
WEB-001
WEB-004
WEB-005
WEB-009
WEB-013
WEB-014
WEB-015
WEB-024
WEB-025
WEB-TIME-001
WEB-SAFE-001
```

Verification tests:

```text
tools/web_shell_smoke.py
tools/validate_features.py
local tablet-sized browser inspection
```

## Design Intent

Give Pluto a large, lively web face for a tablet mounted in the robot head while
keeping the page passive and safe. The face should express the active mode
without owning mode transitions or motion decisions.

## Design Decision

The tablet face is served by the existing dependency-light web shell at `/face`.
It reads `/api/status`, maps the mode manager state and substate into a visual
expression, and never changes state directly. The only active control on the
page is a visible STOP button that calls `/api/emergency-stop`, matching the
website safety requirement that emergency stop is visible from every view.

The face uses CSS and small JavaScript animation instead of images or a new
frontend framework. This keeps deployment simple on Raspberry Pi and makes the
page suitable for a Samsung tablet screen.

## Interfaces

Inputs:

- `GET /api/status` from the Pluto web shell.
- Mode manager fields: `current_state`, `current_substate`, `fault_reason`, and
  `mode_manager.return_lock`.
- STM32 runtime fields including `imu_orientation` when IMU telemetry is live.

Outputs:

- HTML tablet face at `/face`.
- Visible state/substate label.
- Visible filtered IMU attitude when available.
- `POST /api/emergency-stop` when the face STOP button is pressed.

External dependencies:

- Browser on the tablet.
- Existing Pluto web shell.
- Optional STM32 IMU telemetry for attitude display.

## Configuration

Configuration values, defaults, limits, and files:

| Name | Default | Allowed Range | Reason |
| --- | --- | --- | --- |
| Face route | `/face` | fixed route | Stable tablet URL |
| Status poll | 500 ms | fixed in page script | Matches website state update timing requirement |
| STOP endpoint | `/api/emergency-stop` | fixed route | Reuses existing safe stop path |
| Full-screen trigger | tap page | browser dependent | Simple tablet mounting behavior |

## Runtime Behavior

The page maps states to expressions:

- `BOOTSTRAP`: calm waking/self-check face.
- `IDLE`: playful happy face with gentle glances and sparkles.
- `MANUAL`: focused attentive face.
- `WELCOME`: warm greeting face.
- `WELCOME_TALK`: speaking mouth animation.
- `WELCOME_RETURN`: careful yellow return-lock face.
- `DANCE`: high-energy joyful face.
- `ERROR`: red serious safe-stop face with fault text.
- `GAME_LATER`: polite unavailable expression if ever displayed.

The page does not expose mode buttons, manual drive controls, arm controls, or
raw motor endpoints.

## How To Run

Run the web shell:

```bash
python3 -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

Open on the tablet:

```text
http://<pi-ip>:8080/face
```

Run local smoke tests:

```bash
python3 tools/web_shell_smoke.py
python3 tools/validate_features.py
```

## How To Debug

Checklist:

1. Confirm `/healthz` returns `{"ok": true}`.
2. Confirm `/api/status` returns current state and substate.
3. Open `/face` and check that `PLUTO <STATE>` appears in the lower status bar.
4. Press the face STOP button and confirm the web shell enters `ERROR`.
5. If the face shows `STM32 offline`, run `python3 tools/stm32_probe.py`.
6. If the tablet layout clips, test landscape and portrait browser sizes.

Useful commands:

```bash
python3 -m pluto_runtime.web_shell --host 127.0.0.1 --port 8080 --wave-pose-disabled
python3 tools/web_shell_smoke.py
```

## Expected Evidence

Smoke test:

```text
WEB_SHELL_SMOKE PASS
```

Face page:

```text
GET /face -> 200
PLUTO Face title exists
faceStop button exists
No raw drive route is exposed
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-FACE-001 | Open `/face` | Face page loads with PLUTO identity | local browser pass |
| VER-FACE-002 | Inspect mode mapping | State/substate maps to one face expression | local code review pass |
| VER-FACE-003 | Run smoke test | `/face` exists and STOP button exists | local smoke pass |
| VER-FACE-004 | Run full validator | Software feature gate passes | local validator pass except hardware skip |
| VER-FACE-005 | Press STOP on tablet | Emergency stop endpoint fires and state becomes ERROR | not yet run on hardware |
| VER-FACE-006 | Open on Samsung tablet | No clipping or overflow in mounted orientation | not yet run on tablet |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Face does not load | Web shell not running or wrong Pi IP | Check `/healthz` | Restart web shell, verify network |
| Face stuck in ERROR | STM32 missing or fault active | Check `/api/status` fault reason | Fix hardware/fault, reset to IDLE |
| IMU text says waiting | No filtered IMU telemetry yet | Check `stm32_runtime.imu_orientation` | Keep robot still during calibration, inspect IMU lines |
| STOP button fails | Server unreachable or API failure | Browser status and web shell events | Use physical stop, then debug web shell |
| Tablet layout clips | Browser too old or wrong orientation | Compare with laptop viewport | Use Chrome if available, rotate tablet, reduce browser zoom |

## Safety Notes

The tablet face is not a control surface for movement. It only observes status
and exposes emergency stop. All motion state changes remain owned by the mode
manager, and raw motor routes remain unavailable outside validated paths.

The playful IDLE animation is visual only. It does not imply autonomous motion,
arm motion, or mode transition.

## Open Questions

- Which exact browser will run on the Samsung tablet 3, and does it support the
  current CSS feature set well enough for final mounting?
- Should the final tablet deployment hide browser chrome through kiosk mode?

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-06-08 | Added tablet face memory | New `/face` feature and requirement trace |
