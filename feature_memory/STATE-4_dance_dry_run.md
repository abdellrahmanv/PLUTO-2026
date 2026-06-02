# STATE-4 DANCE Dry Run Memory

## Purpose

This phase starts DANCE safely. Pluto may enter the DANCE state from the
website, but the runtime only computes the bounded dance step that would be
commanded later. It does not send wheel or arm motion commands.

The intended final DANCE behavior is a Michael Jackson moonwalk-inspired
performance inside a configured 3 m x 3 m floor envelope with 3 m vertical
clearance. Pluto may glide backward/forward, change direction in 90 degree
increments, and move its arms, but it must never intentionally leave the
envelope.

The 60 cm backward and 45 cm forward segment defaults are not sacred
choreography values. They are conservative engineering placeholders: visible
enough for a 110 cm robot to look alive, but small enough to keep Pluto far
inside a 300 cm dance envelope during early validation. These values can be
tuned after dry-run evidence and wheels-lifted tests.

## Requirements Covered

- STATE-4.1 through STATE-4.5: DANCE entry and STOP guard baseline.
- STATE-4.10 through STATE-4.19.2: audio, bounded movement, 3 m x 3 m envelope,
  encoder odometry, 90 degree heading changes, arm gate.
- STATE-4.20 through STATE-4.28: obstacle and vision-assisted dance safety.
- STATE-4.28.1: dry-run until evidence is reviewed.
- STATE-4.28.2: no `CMD:DRIVE` or `CMD:ARM` in dry-run.
- STATE-4.28.3: website evidence panel.
- STATE-4.28.4: STOP proposal on missing/blocked safety data.
- STATE-4.28.5: bounded glide and 90 degree direction-change proposals.
- STATE-4.28.6: periodic STOP guard while DANCE is active.
- STATE-4.28.7: stop or avoid motion toward a detected obstacle.
- STATE-4.28.8: stop or remain dry-run when odometry is unavailable or invalid.

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

The current dry-run sequence is deliberately small:

```text
pose_north
moonwalk_back_north
return_forward_north
turn_right_90
moonwalk_back_east
return_forward_east
turn_right_90
arm_sway_left
arm_sway_right
```

Future live DANCE should expand this into an envelope-aware sequence:

```text
1. Save dance origin and heading using encoder odometry.
2. Treat origin +/- 150 cm on X/Y as the 3 m x 3 m dance box.
3. Moonwalk backward and forward inside that box.
4. Change direction only in slow 90 degree increments.
5. Before each segment, predict whether odometry would leave the box.
6. If the segment would leave the box, clamp it, rotate, or stop.
7. If an obstacle is in the movement direction, stop that direction.
8. Arm motions remain disabled until hardware validation passes.
```

Wheel proposals must never intentionally leave the envelope. Arm motion is
reported as `disabled_until_arm_validated` until the stepper hardware and
limits are proven.

Implementation update:

`DanceDryRunPlanner` now exposes envelope and odometry evidence directly in
`DanceStatus`:

```text
envelope_size_cm
vertical_clearance_cm
envelope_margin_cm
odometry_status
odometry_reason
odometry_confidence
estimated_x_cm / estimated_y_cm
predicted_x_cm / predicted_y_cm
heading_deg / heading_quadrant
direction_safety
segment_distance_cm
stage_assumption
```

If STM32 telemetry later exposes X/Y/heading fields, the planner uses those.
Until then, dry-run uses a low-confidence simulated sequence estimate. Live
DANCE must not use this simulated estimate as proof that physical motion is
safe.

Audio lookup order:

```text
1. PLUTO_DANCE_AUDIO environment variable.
2. C:\Users\Asus\Downloads\Michael_Jackson_-_Billie_Jean_This_is_it_2009_(mp3.pm).mp3
3. /home/pi/PLUTO-2026/audio/Michael_Jackson_-_Billie_Jean_This_is_it_2009_(mp3.pm).mp3
4. /home/pi/Downloads/Michael_Jackson_-_Billie_Jean_This_is_it_2009_(mp3.pm).mp3
```

The repository does not store the song file. The Pi should receive a local copy
or set `PLUTO_DANCE_AUDIO` to the actual file path.

## Safety Behavior

- No dry-run path sends `CMD:DRIVE`.
- No dry-run path sends `CMD:ARM`.
- While DANCE is active, the web runtime periodically sends `CMD:STOP`.
- If STOP cannot be verified while STM32 is connected, Pluto enters ERROR.
- Missing obstacle telemetry results in STOP proposal.
- Obstacle values below stop threshold result in STOP proposal.
- Obstacles in the direction of the next movement block that movement.
- Human boxes clipped by the camera frame or too large in the frame result in
  STOP proposal.
- Low-light/degraded vision blocks dance motion proposal.
- Encoder odometry must be available and trusted before live dance can use the
  3 m x 3 m boundary. If odometry is invalid, live DANCE must stop or remain
  dry-run.
- Backward moonwalk motion in v1 depends on a pre-cleared 3 m x 3 m stage
  because the ultrasonic sensors are mostly front-facing. The website stage
  drawing is required evidence that Pluto is staying inside that agreed box.

## Debugging Checklist

1. Open `/api/status` and confirm `dance.dry_run` is `true`.
2. Start DANCE from IDLE using the website.
3. Confirm substate becomes `DANCE_DRY_RUN`.
4. Confirm `stm32_runtime.drive_count` does not increase.
5. Confirm `dance.stop_guard.detail` reports a STOP result.
6. If `dance.reason` is obstacle-related, inspect `stm32_runtime.obstacles`.
7. If `dance.reason` is boundary-related, inspect odometry origin, estimated
   X/Y, heading quadrant, and envelope margin.
8. If `dance.reason` is vision-related, inspect `camera.vision_quality` and
   whether a human box is too large or clipped.
9. If `dance.audio_status` is `silent_dry_run`, add/configure a preloaded dance
   audio file before live DANCE.
10. If `dance.direction_safety` is `stage_clear_assumed_backward`, remember
    that the backward segment is allowed only because the operator has provided
    an empty 3 m x 3 m dance stage and the odometry envelope remains valid.
11. Inspect the website dance-stage drawing. Current pose, predicted next pose,
    heading arrow, and margin must look reasonable before any future live test.

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
