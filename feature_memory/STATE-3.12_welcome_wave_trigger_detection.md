# Feature Memory: WELCOME Wave Trigger Detection

Status: quantized pose v1 implemented, live robot validation pending

Last updated: 2026-05-29

Last validated: 2026-05-29 local smoke test

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
STATE-3.12.7
STATE-3.12.8
STATE-3.12.9
STATE-3.12.10
STATE-3.12.11
STATE-3.12.12
STATE-3.12.13
STATE-3.12.14
STATE-3.12.15
STATE-3.12.16
STATE-3.12.17
STATE-3.12.18
STATE-3.12.19
STATE-3.12.20
STATE-3.12.21
STATE-3.12.22
STATE-3.12.23
STATE-3.12.24
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
tools/welcome_wave_smoke.py
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

## Pluto v1 Implementation

Use Pluto's existing Phase 4 camera stack as the base instead of importing the
prototype unchanged.

Implemented v1 path:

1. Keep the current TFLite YOLOv8n person detector for person boxes.
2. Assign lightweight track IDs to visible people with IoU/center matching.
3. Run quantized MoveNet SinglePose Lightning INT8 on the selected tracked
   person crops when LiteRT/TFLite is available.
4. Extract shoulder, elbow, and wrist keypoints from the pose model.
5. Keep one wave buffer and confirmation streak per track.
6. Apply the desktop prototype's rules directly to pose keypoints:
   wrist above shoulder, horizontal hand amplitude, x direction changes,
   horizontal-dominates-vertical ratio, confirmation streak, and cooldown.
7. Keep optical-flow motion as debug evidence only. It must not confirm WELCOME
   or create a red lock in the current requirement baseline.
8. Prevent website polling from reusing the same camera frame as fake new wave
   history by tagging camera wave evidence with a frame index.
9. Run the wave detector from a background runtime sampler at about the camera
   stream rate. The website must not be the timing source for gesture history.
10. Publish a structured event:

```text
WELCOME_TRIGGER:WAVE
target_id=<track_id>
track_id=<integer>
side=<left|right>
score=<0.0-1.0>
confidence=<0.0-1.0>
reason=<confirmed_wave>
```

When a wave is confirmed, the camera overlay sets a temporary lock on that
track. While the lock is active, the MJPEG feed draws only the locked person
box in red with `WAVE LOCK` and suppresses other visible person boxes. This
matches the intended desktop behavior: Pluto can see multiple people, but once
one person waves, that person becomes the interaction target.

The website control is not a bypass. `Arm Wave Test` opens a short waiting
window and records that the operator is testing the WELCOME wave path. It does
not force WELCOME, does not create a fake confirmed wave, and does not set a red
lock. Only the detector's confirmed per-track wave evidence can lock the target.

False-positive fix: broad human-box movement and generic optical-flow movement
must not confirm WELCOME by themselves. Earlier versions allowed these fallback
paths to confirm a wave, which could select a person after arming even when they
did not wave. The current rule is stricter: lock requires a tracked raised-hand
candidate with enough horizontal amplitude, direction changes, and horizontal
dominance.

5. Let the mode manager accept or reject the event.

Implemented module:

```text
pluto_runtime/wave_detection.py
```

Implemented API:

```text
POST /api/welcome/wave-trigger
```

This v1 detector now uses the same meaningful evidence as the desktop
prototype: wrist and shoulder keypoints. MediaPipe is not used on the Pi because
the current Pi environment is Python 3.13 on Debian 13 and MediaPipe wheels are
not available there. The replacement is a bundled quantized MoveNet TFLite
model:

```text
models/movenet_singlepose_lightning_int8.tflite
```

The camera service runs the pose model only on selected tracked person crops
instead of the whole crowd. This keeps the computation closer to the desktop
behavior while staying realistic on Raspberry Pi. WELCOME entry still depends
on the mode manager and STM32 stop guard.

Field tuning from Raspberry Pi validation:

The desktop thresholds were designed around MediaPipe visibility at a higher
frame rate. The Pi uses MoveNet INT8 at roughly the website stream cadence, so
the active thresholds are deliberately a little more forgiving while preserving
the same gates:

| Gate | Desktop Reference | Pi Active Value | Reason |
| --- | --- | --- | --- |
| minimum samples | 6 usable pose samples | 5 usable pose samples | 8 Hz sampler needs faster confirmation |
| hand amplitude | 0.18 shoulder widths | 0.14 shoulder widths | MoveNet wrist is noisier and sometimes underestimates motion |
| direction changes | 2 | 2 | Keep real side-to-side wave requirement |
| horizontal/vertical ratio | 1.30 | 1.10 | Accept natural diagonal hand waves |
| keypoint confidence | 0.30 MediaPipe-style | 0.20 MoveNet score | MoveNet confidence scale is different |

The background wave sampler updates detector evidence continuously for website
debugging in all states. It only requests WELCOME when the robot is in IDLE.

Two-person lock behavior:

The red `WAVE LOCK` target is not allowed to jump to another person just
because the lightweight tracker briefly swaps IDs. When a wave is confirmed,
the camera service stores both the confirmed track ID and the confirmed
person's bounding box as a spatial anchor. During the lock window, the tracker
claims the detection closest to that anchor for the locked ID before assigning
other people. The anchor is updated frame by frame as the locked person moves.
This is not full face/person re-identification, but it prevents the common
two-person red-box jump seen in field testing.

The lock fails closed. If the confirmed waver leaves the camera and the only
remaining box is not close enough to the stored anchor, the red lock is cleared
instead of transferring to the other person. Active thresholds:

```text
anchor IoU >= 0.12 OR normalized center distance <= 0.45
```

Low-light behavior:

The camera service measures frame brightness and contrast. If the image is too
dark or flat, wave detection reports `low_light` and does not confirm new wave
targets. This is safer than letting noisy pose landmarks select the wrong
person. Active gates:

```text
low_light if brightness < 35 OR contrast < 18
dim       if brightness < 55 OR contrast < 24
ok        otherwise
```

WELCOME entry accepts the same stop-guard evidence used by WELCOME_TALK:
an explicit STM32 `ACK:STOP` is preferred. If that ACK is missed but the STM32
link is alive, recent telemetry is available, wheel speed is zero, and manual
drive intent is zero, the guard is marked as degraded-safe and the response
records `degraded=true`. If neither proof exists, the trigger is rejected and
the mode manager enters ERROR.

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

This is heavier than the Phase 4 camera runtime, but lighter than the desktop
stack. The Raspberry Pi currently runs Phase 4 through `/home/pi/yolo/env`,
which has OpenCV, NumPy, and `ai_edge_litert`. The selected deployment path is
MoveNet INT8 via LiteRT, not MediaPipe.

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
- Show detector reason, sample count, score, confidence, side, and latest event.
- Show `motion_norm`, `motion_direction_changes`, `raised`, `hand_amp`,
  `hand_sign_changes`, and `hand_dx_dy` so hand-wave tuning is visible.
- Show `track_id`, visible track IDs, and locked track ID for multi-person
  debugging.
- Show pose backend status, pose model path, and pose inference latency.
- Show active thresholds: hand amplitude, direction changes, horizontal/vertical
  ratio, keypoint confidence, and sampling rate.
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
| WELCOME-WAVE-007 | Refresh `/api/status` repeatedly on one frozen frame | Sample count does not advance as fake wave history |
| WELCOME-WAVE-008 | Stop browser polling and wave in front of camera | Background sampler still detects and locks |
| WELCOME-WAVE-009 | Two people visible after one person waves | Red box remains on the anchored waver track |
| WELCOME-WAVE-010 | Waver leaves camera while another person remains | Red lock clears instead of jumping |
| WELCOME-WAVE-011 | Low light scene | Wave detector reports low light and does not confirm |

## Debug Checklist

1. Confirm Phase 4 camera works:

```bash
curl http://127.0.0.1:8080/api/camera/status
```

2. Confirm person boxes are stable before testing wave.

3. Confirm pose dependency import and model load:

```bash
/home/pi/yolo/env/bin/python - <<'PY'
from pluto_runtime.pose_wave import MovenetPoseEstimator
p = MovenetPoseEstimator("models/movenet_singlepose_lightning_int8.tflite")
print(p.load(), p.status, p.error)
PY
```

The required smoke test is:

```bash
python tools/welcome_wave_smoke.py
```

4. Log every rejected wave candidate with reason:

```text
no_person
pose_unavailable
pose_no_keypoints
pose_not_enough_samples
wrist_not_visible
wrist_not_raised
amplitude_too_low
not_enough_direction_changes
cooldown_active
mode_gate_rejected
```

5. Only after trigger logs are stable, allow non-diagnostic wave events to
   request WELCOME entry.

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
| 2026-05-27 | Added lightweight v1 wave detector | Use existing camera boxes and avoid heavy pose dependencies |
| 2026-05-27 | Reused degraded stop guard for wave trigger | Keep hardware validation consistent with WELCOME_TALK |
| 2026-05-27 | Added upper-crop pixel motion evidence | Detect hand waves without requiring pose landmarks |
| 2026-05-27 | Ported PC wave rules into Pi-friendly detector | Keep raised/oscillating-hand behavior without YOLOv5, SORT, or MediaPipe runtime |
| 2026-05-29 | Replaced frame-diff hand estimate with optical flow | Preserve motion direction while staying light enough for Raspberry Pi |
| 2026-05-29 | Added lightweight multi-person tracking and red lock overlay | Match desktop behavior: choose one waving target and suppress other boxes |
| 2026-05-29 | Changed website wave test into an arm/wait control | Prevent fake locks before a real wave is detected |
| 2026-05-29 | Removed broad motion fallback as confirmation evidence | Prevent auto-selecting a person who did not wave |
| 2026-05-29 | Added MoveNet INT8 pose backend | Replace failing optical-flow-only wave logic with real shoulder/wrist evidence on Python 3.13 Pi |
| 2026-05-29 | Added frame-index dedupe | Prevent website polling from creating fake gesture history |
| 2026-05-29 | Added runtime wave sampler and threshold display | Match the desktop video-loop behavior and make field tuning visible |
| 2026-05-29 | Added spatially sticky wave lock anchor | Keep red target focus on the person who actually waved when two people are visible |
| 2026-05-29 | Added fail-closed lock clearing and low-light gate | Prevent red lock from moving to another person when the waver exits or vision is unreliable |
