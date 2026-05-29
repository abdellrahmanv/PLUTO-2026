# STATE-3.29 WELCOME_APPROACH Dry Run Memory

## Purpose

Phase 10 introduces WELCOME_APPROACH as a verified dry-run before Pluto is
allowed to move toward a person. The robot computes target alignment, distance
class, obstacle safety, and proposed motion, while the STM32 remains guarded by
STOP commands.

## Requirements Covered

- STATE-3.20 through STATE-3.29.5: baseline approach and safety requirements.
- STATE-3.29.6: approach remains dry-run until reviewed.
- STATE-3.29.7: no `CMD:DRIVE` from WELCOME_APPROACH in Phase 10.
- STATE-3.29.8: use locked wave target ID; do not retarget silently.
- STATE-3.29.9: expose approach evidence on the website.
- STATE-3.29.10: propose STOP on missing target, degraded vision, arrival, or blocked path.
- STATE-3.29.11: keep STOP guard active while evaluating approach.

## Design

`pluto_runtime/welcome_approach.py` is a pure planner. It accepts:

- camera status from the threaded camera service,
- STM32 runtime telemetry,
- WELCOME wave-lock status,
- current mode/substate.

It returns an `ApproachStatus` object. In Phase 10 this object is evidence, not
a motor command. `dry_run` is always true by default.

The planner chooses one target by locked wave track ID. If that target is not in
the current detections, the output stays STOP with `locked target not visible`.
This prevents the two-person failure where the red lock jumps to another human.

Distance is estimated by bounding-box height ratio until true range fusion is
added:

- `far`: target box height below greeting threshold.
- `good`: greeting distance reached.
- `too_close`: target is too near.

Obstacle telemetry uses STM32 `OBS` values:

- `F < 60 cm` blocks.
- `FL/FR < 50 cm` blocks.
- any front value below `80 cm` enters slow proposal.

The website exposes the dry-run result in the `Welcome Approach` panel and
`/api/status` under `welcome_approach`.

## Safety Behavior

- No WELCOME_APPROACH path sends `CMD:DRIVE` in Phase 10.
- While WELCOME_APPROACH is active, the web runtime sends periodic `CMD:STOP`
  guard commands through the existing STM32 link.
- If STOP cannot be verified while STM32 is connected, the mode manager enters
  ERROR.
- `WELCOME_TALK` is not treated as approach. The planner becomes inactive once
  talking begins.

## Debugging Checklist

1. Open `/api/status` and confirm `welcome_approach.dry_run` is `true`.
2. Confirm `current_state` is `WELCOME` after a real wave.
3. Confirm `welcome_approach.target_id` matches the red wave-locked box.
4. If proposal is STOP, inspect `welcome_approach.reason`.
5. If reason is `locked target not visible`, check camera lock and lighting.
6. If reason is `vision quality degraded`, improve lighting before testing.
7. If reason is `obstacle blocked`, inspect STM32 `OBS:F/FL/FR`.
8. Confirm `stm32_runtime.drive_count` does not increase during approach dry-run.

## Verification

Run:

```bash
python3 tools/welcome_approach_smoke.py
python3 tools/web_shell_smoke.py
```

Expected:

```text
WELCOME_APPROACH_SMOKE PASS
WEB_SHELL_SMOKE PASS
```

Live Pi evidence should include:

- Website opens.
- Wave lock enters WELCOME.
- Welcome Approach panel updates.
- STOP guard detail appears.
- No physical motion occurs.
