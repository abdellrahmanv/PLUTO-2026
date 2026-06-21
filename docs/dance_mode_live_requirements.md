# Dance Mode Live Sequence Requirements

## Scope

This document defines the simplified live Dance Mode target for Pluto.

Dance Mode has one fixed movement sequence. The cut Billie Jean audio starts
first, then Pluto drives the sequence. Arm movement is not included in this
version and will be added later.

When Dance Mode is stopped or completed, Pluto stays where the current/final
movement leaves it. There is no base pose and no return-to-base behavior.

## Operator Option

Dance Mode has one operator option:

- `careful`: use ultrasonic obstacle checks.
- `free`: do not use ultrasonic obstacle checks.

In `careful` mode, if the ultrasonic distance is below the configured stop
distance, Pluto shall stop the dance and stay where it is.

## Motion Constants

| Name | Value | Use |
| --- | ---: | --- |
| `MIN_SPEED` | `100` | Backward movement |
| `MIN_STEER` | `150` | Rotation |
| `MAX_SPEED` | `150` | Forward movement |
| `MAX_STEER` | `200` | Reserved from manual control |
| `TARGET_DISTANCE_M` | `2.0` | Forward/backward segment distance |
| `TARGET_TURN_DEG` | `180.0` | Rotation segment angle |
| `DISTANCE_TOLERANCE_M` | `0.10` | Distance acceptance tolerance |
| `TURN_TOLERANCE_DEG` | `5.0` | Turn acceptance tolerance |

## Sequence

```text
1. Start Billie Jean cut audio.
2. Forward 2 meters at MAX_SPEED = 150.
3. Backward 2 meters at MIN_SPEED = 100.
4. Rotate 180 degrees at MIN_STEER = 150.
5. Forward 2 meters at MAX_SPEED = 150.
6. Backward 2 meters at MIN_SPEED = 100.
7. Rotate 180 degrees at MIN_STEER = 150.
8. Stop motors and remain in final position.
```

## Sensor Fusion

The live controller shall use simple sensor fusion:

- Encoders are the primary source for forward/backward distance.
- IMU yaw is the primary source for turn angle.
- IMU yaw is also used to correct heading drift during straight movement.
- Encoders sanity-check that rotation actually produced wheel movement.

## Audio File

The song file should be copied to the Raspberry Pi outside Git, then configured
with `PLUTO_DANCE_AUDIO`. Recommended path:

```text
/home/pi/PLUTO-2026/audio/billie-jean-cut.mp3
```

The repo should not store the song file itself.

## Subrequirements

- `STATE-4-LIVE-001`: DANCE live sequence shall start audio before movement.
- `STATE-4-LIVE-002`: DANCE live sequence shall provide only `careful` and
  `free` ultrasonic modes.
- `STATE-4-LIVE-003`: Forward segments shall drive 2 meters at speed `150`.
- `STATE-4-LIVE-004`: Backward segments shall drive 2 meters at speed `100`.
- `STATE-4-LIVE-005`: Rotation segments shall turn 180 degrees at steer `150`.
- `STATE-4-LIVE-006`: The forward/backward/rotate pattern shall run twice.
- `STATE-4-LIVE-007`: Distance completion shall be measured from encoders.
- `STATE-4-LIVE-008`: Rotation completion shall be measured from IMU yaw.
- `STATE-4-LIVE-009`: Straight movement shall correct heading drift with IMU
  yaw feedback.
- `STATE-4-LIVE-010`: Careful mode shall stop if ultrasonic distance is unsafe.
- `STATE-4-LIVE-011`: Stop/completion shall not return Pluto to a base pose.
- `STATE-4-LIVE-012`: Arm movement shall remain disabled in this version.
