# Feature Memory: Vision-Assisted Obstacle Safety

Status: requirement/design added, implementation pending

Last updated: 2026-05-27

Last validated: not implemented yet

Owner: Pluto systems engineering

## Requirement Trace

Primary requirements:

```text
SAFE-009
SAFE-010
STATE-3.29.3
STATE-3.29.4
STATE-3.29.5
STATE-4.26
STATE-4.27
STATE-4.28
```

Verification tests:

```text
VER-WELCOME-015
VER-DANCE-008
```

## Design Intent

Use the Raspberry Pi camera as a secondary safety layer during WELCOME and
DANCE. The STM32 ultrasonic/hoverboard safety remains the primary stop layer.
Vision only makes Pi motion commands more conservative before the STM32 has to
react.

## Design Decision

Reuse the Phase 4 optimized camera stack:

```text
threaded capture
320x320 input
frame skipping
detection hold
tracked person boxes
YOLOv8n TFLite
```

Do not add a heavier vision pipeline until this safety path is proven. The
first implementation should prefer stable, low-latency human/obstacle presence
over perfect classification.

## Runtime Behavior

WELCOME:

```text
camera sees person/obstacle in approach envelope
  -> reduce approach speed
  -> stop if box enters unsafe central zone
  -> ask for space if blocked long enough
```

DANCE:

```text
camera sees person/obstacle in dance envelope
  -> shrink dance movement
  -> pause or stop if envelope is occupied
```

Conflict rule:

```text
if vision and ultrasonic disagree, choose the slower or stopped command
```

## Interfaces

Inputs:

- Human/object boxes from `pluto_runtime.camera`.
- Current state/substate from `mode_manager`.
- STM32 ultrasonic telemetry from the existing runtime.

Outputs:

- Conservative motion scale: `1.0`, `0.5`, `0.25`, or `0.0`.
- Website-visible safety reason.
- Logs for reduced/stopped motion.

No direct raw motor route is allowed from the vision code.

## How To Debug

Checklist:

1. Confirm camera feed and detection are stable:

```bash
curl http://127.0.0.1:8080/api/camera/status
```

2. Confirm detections hold instead of flickering at 0/1 every frame.
3. Check current state is `WELCOME` or `DANCE`.
4. Confirm the safety reason appears in website logs.
5. Confirm STM32 obstacle telemetry is still active.

## Verification Plan

| Test ID | Method | Expected Result |
| --- | --- | --- |
| VER-WELCOME-015 | Put a person in the approach path | Pi slows/stops before sending unsafe approach command |
| VER-DANCE-008 | Step into dance envelope | dance range shrinks, pauses, or stops |
| VIS-SAFE-001 | Disable camera | STM32 ultrasonic safety still works |
| VIS-SAFE-002 | Flickering detection | detection hold prevents command oscillation |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Vision unavailable | Camera missing or model missing | `/api/camera/status` | Degrade to STM32 ultrasonic safety |
| Flicker 0/1 detections | Resolution/FPS too low or confidence too high | camera status and overlay | Lower confidence or increase hold time |
| Robot overreacts | Envelope too wide | safety logs | Tune WELCOME/DANCE envelopes |
| Robot underreacts | Envelope too narrow | live test with wheels lifted | Tune thresholds before ground motion |

## Safety Notes

This feature must never weaken STM32 safety. Any error in the vision safety
path shall fail conservative: reduced speed or stop.

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-27 | Created design memory | Add optimized computer vision as secondary obstacle safety for WELCOME and DANCE |
