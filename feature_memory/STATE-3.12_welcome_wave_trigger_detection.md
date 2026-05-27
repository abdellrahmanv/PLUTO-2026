# Feature Memory: WELCOME Wave Trigger Detection

Status: design studied, merged into Phase 9 WELCOME design, implementation pending

Last updated: 2026-05-27

Last validated: not implemented in Pluto runtime yet

Owner: Pluto systems engineering

## Requirement Trace

Primary requirements:

```text
STATE-3.2
STATE-3.10
STATE-3.11
STATE-3.12
STATE-3.12.1
STATE-3.12.2
STATE-3.12.3
STATE-3.12.4
STATE-3.12.5
STATE-3.12.6
STATE-3.13
STATE-3.15
STATE-3.16
STATE-3.18
STATE-3.19
TIME-008
```

Verification tests:

```text
VER-WELCOME-001
VER-WELCOME-008
VER-WELCOME-012
WELCOME-WAVE-001 no-wave stability test
WELCOME-WAVE-002 single-person wave trigger test
WELCOME-WAVE-003 multi-person target selection test
WELCOME-WAVE-004 missing dependency fallback test
```

## Design Intent

Detect a deliberate human wave and convert it into a safe WELCOME trigger.

This is not a standalone Pluto mode. A wave is an input event inside
`WELCOME_DETECT`. If the event is confirmed and the mode manager safety gates
allow it, the robot transitions into WELCOME and continues through target
selection, approach, talk, and return.

This feature must not move Pluto by itself. It only produces a confirmed
intent event for the mode manager. The mode manager then decides whether
WELCOME is allowed based on safety gates, STM32 availability, battery state,
return lock state, and current mode.

## Studied Source

Local study path:

```text
C:\Users\Asus\Desktop\wave_detection
```

Files inspected:

```text
main.py
sort.py
requirements.txt
pose_landmarker_lite.task
yolov5n.pt
```

The current wave project is a good research prototype. It combines:

```text
YOLOv5n person boxes
SORT tracking
MediaPipe Pose Landmarker
wrist/shoulder wave rules
OpenCV debug display
```

## Engineering Decision

Do not include wave detection inside Phase 4.

Phase 4 is closed as camera feed plus human presence. Wave detection belongs
to WELCOME because it can trigger a state transition that later enables
approach motion. That means it needs its own requirements, safety gate,
debug evidence, and verification tests.

Wave detection is also not a separate `FOLLOW_WAVE` mode in v1. The old
follow-wave idea is merged into WELCOME so the visitor experience is one clean
loop:

```text
wave -> WELCOME_DETECT -> WELCOME_APPROACH -> WELCOME_TALK -> WELCOME_RETURN
```

## Current Prototype Algorithm

The studied prototype works like this:

1. Capture frames from OpenCV.
2. Run YOLOv5n person detection.
3. Track people with SORT so each person has a stable track ID.
4. Crop the largest or most relevant person boxes.
5. Run MediaPipe Pose Landmarker on each selected crop.
6. Extract shoulder and wrist keypoints.
7. Normalize wrist motion relative to shoulder width.
8. Require wrist above shoulder.
9. Require side-to-side x motion above threshold.
10. Require enough direction changes across a short frame buffer.
11. Confirm wave after a short streak.
12. Apply cooldown so the same wave does not repeatedly retrigger.

Useful prototype constants found during study:

| Name | Prototype Value | Meaning |
| --- | --- | --- |
| `YOLO_IMG_SIZE` | `416` | YOLO input size, can be lowered for speed |
| `YOLO_CONF_THRESH` | `0.30` | Person confidence threshold |
| `YOLO_SKIP_FRAMES` | `2` | Detector runs every second frame |
| `WAVE_RAISED_MARGIN` | `0.0` | Wrist must be above shoulder |
| `WAVE_COOLDOWN` | `20` frames | Keep wave state briefly after detection |

## Proposed Pluto Implementation

Use Pluto's existing Phase 4 camera stack as the base instead of importing the
prototype unchanged.

Preferred path:

1. Keep the current TFLite YOLOv8n person detector for person boxes.
2. Add pose estimation only for the top one or two candidate people.
3. Reuse the prototype wrist/shoulder wave logic after adapting it into a
   headless module.
4. Publish a structured event:

```text
WELCOME_TRIGGER:WAVE
target_id=<track_id>
side=<left|right>
score=<0.0-1.0>
confidence=<0.0-1.0>
reason=<confirmed_wave>
```

5. Let the mode manager accept or reject the event.

Avoid in the first Pluto implementation:

- `cv2.imshow`, because Pluto runs headless through the website.
- PyTorch YOLOv5n on the Raspberry Pi, because Phase 4 already uses TFLite.
- Direct motion commands from the wave detector.
- Entering WELCOME while WELCOME_RETURN is active.

## Dependency Risk

The prototype requirements are:

```text
opencv-python
numpy
mediapipe
filterpy
scikit-image
lap
torch
torchvision
scipy
```

This is heavier than the current Pluto camera runtime. The Raspberry Pi
currently runs Phase 4 through `/home/pi/yolo/env`, which is optimized around
OpenCV, NumPy, and TFLite. Before implementation, verify whether MediaPipe is
available and whether CPU load remains acceptable.

## Interfaces

Inputs:

- Camera frames from `pluto_runtime.camera`.
- Human detection boxes from Phase 4.
- Optional target lock state from the mode manager.

Outputs:

- Confirmed WELCOME trigger candidate.
- WELCOME_DETECT substate debug details.
- Debug status for website and logs.
- No motor commands.

Website impact:

- Show wave detector state when enabled.
- Show selected target ID and confidence.
- Show unavailable reason if pose dependencies are missing.
- Show whether the latest WELCOME trigger came from operator request or wave.

## Verification Plan

| Test ID | Method | Expected Result |
| --- | --- | --- |
| WELCOME-WAVE-001 | Stand still in front of camera for 2 minutes | No WELCOME trigger |
| WELCOME-WAVE-002 | One person waves clearly | Trigger within `TIME-008` limit |
| WELCOME-WAVE-003 | Two people wave | Closest or selected waver becomes one locked target |
| WELCOME-WAVE-004 | Run without pose dependency | Website reports unavailable and operator trigger still works |
| WELCOME-WAVE-005 | Move arm randomly below shoulder | No trigger |
| WELCOME-WAVE-006 | Trigger while WELCOME_RETURN is active | Trigger rejected by mode manager |

## Debug Checklist

1. Confirm Phase 4 camera works:

```bash
curl http://127.0.0.1:8080/api/camera/status
```

2. Confirm person boxes are stable before testing wave.

3. Confirm pose dependency import:

```bash
/home/pi/yolo/env/bin/python - <<'PY'
import mediapipe
print("mediapipe ok")
PY
```

4. Log every rejected wave candidate with reason:

```text
no_person
pose_unavailable
wrist_not_visible
wrist_not_raised
amplitude_too_low
not_enough_direction_changes
cooldown_active
mode_gate_rejected
```

5. Only after trigger logs are stable, connect it to WELCOME entry.

## Safety Notes

Wave detection is an intent sensor, not a motion controller.

Even a perfect wave detection shall not move Pluto unless the mode manager,
STM32 heartbeat, obstacle telemetry, battery gate, and current state all allow
WELCOME.

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-27 | Created feature memory from local wave detection study | Preserve design and defer implementation to WELCOME feature gate |
| 2026-05-27 | Merged follow-wave into WELCOME | Keep wave as WELCOME_DETECT trigger, not a separate robot mode |
