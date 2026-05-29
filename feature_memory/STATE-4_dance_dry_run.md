# STATE-4 DANCE Dry Run Memory

## Purpose

This phase starts DANCE safely. Pluto may enter the DANCE state from the
website, but the runtime only computes the bounded dance step that would be
commanded later. It does not send wheel or arm motion commands.

## Requirements Covered

- STATE-4.1 through STATE-4.5: DANCE entry and STOP guard baseline.
- STATE-4.10 through STATE-4.17: audio, bounded movement, fixed direction, arm gate.
- STATE-4.20 through STATE-4.28: obstacle and vision-assisted dance safety.
- STATE-4.28.1: dry-run until evidence is reviewed.
- STATE-4.28.2: no `CMD:DRIVE` or `CMD:ARM` in dry-run.
- STATE-4.28.3: website evidence panel.
- STATE-4.28.4: STOP proposal on missing/blocked safety data.
- STATE-4.28.5: zero steer for fixed-facing wheel proposals.
- STATE-4.28.6: periodic STOP guard while DANCE is active.

## Design

`pluto_runtime/dance.py` contains `DanceDryRunPlanner`. It evaluates:

- current mode/substate,
- STM32 obstacle telemetry,
- camera vision envelope,
- speaker/audio readiness,
- optional configured preloaded audio file,
- elapsed dance time.

The planner outputs `DanceStatus`, which is displayed under `/api/status` as
`dance` and shown in the website `Dance` panel.

The dry-run sequence is deliberately small:

```text
pose
moonwalk_back
hold
return_forward
hold
arm_sway_left
arm_sway_right
```

Wheel proposals use forward/backward speed only and `steer = 0` so Pluto keeps
fixed facing direction in v1. Arm motion is reported as
`disabled_until_arm_validated`.

## Safety Behavior

- No dry-run path sends `CMD:DRIVE`.
- No dry-run path sends `CMD:ARM`.
- While DANCE is active, the web runtime periodically sends `CMD:STOP`.
- If STOP cannot be verified while STM32 is connected, Pluto enters ERROR.
- Missing obstacle telemetry results in STOP proposal.
- Obstacle values below stop threshold result in STOP proposal.
- Human boxes clipped by the camera frame or too large in the frame result in
  STOP proposal.
- Low-light/degraded vision blocks dance motion proposal.

## Debugging Checklist

1. Open `/api/status` and confirm `dance.dry_run` is `true`.
2. Start DANCE from IDLE using the website.
3. Confirm substate becomes `DANCE_DRY_RUN`.
4. Confirm `stm32_runtime.drive_count` does not increase.
5. Confirm `dance.stop_guard.detail` reports a STOP result.
6. If `dance.reason` is obstacle-related, inspect `stm32_runtime.obstacles`.
7. If `dance.reason` is vision-related, inspect `camera.vision_quality` and
   whether a human box is too large or clipped.
8. If `dance.audio_status` is `silent_dry_run`, add/configure a preloaded dance
   audio file before live DANCE.

## Verification

Run:

```bash
python3 tools/dance_smoke.py
python3 tools/web_shell_smoke.py
```

Expected:

```text
DANCE_SMOKE PASS
WEB_SHELL_SMOKE PASS
```

Live Pi evidence should include:

- Website opens.
- DANCE can be selected explicitly from IDLE.
- Dance panel updates.
- STOP guard remains active.
- No physical motion occurs.
