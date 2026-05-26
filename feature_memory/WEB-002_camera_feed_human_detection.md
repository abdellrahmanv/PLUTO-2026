# Feature Memory: Camera Feed And Human Detection

Status: implemented, awaiting full browser/FPS validation on Raspberry Pi

Last updated: 2026-05-27

Last validated: not yet validated in browser with human target

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
WEB-002
WEB-003
WEB-012
WEB-023
WEB-024
WEB-TIME-003
HW-004
STATE-0.22
STATE-1.17
```

Verification tests:

```text
VER-WEB-002
VER-WEB-003
VER-WEB-009
Phase 4 camera smoke test
Phase 4 human detection test
```

## Design Intent

Show Pluto's webcam feed inside the operator website and expose basic human
detection status without blocking the rest of the robot runtime.

The camera path must stay optional. If the webcam, OpenCV, or YOLO model is
missing, the website must still run and show a clear unavailable state.

## Design Decision

Phase 4 integrates the prior `/home/pi/yolo` project lessons into Pluto:

```text
threaded capture
frame skipping
MJPG camera format
low capture resolution
YOLOv8n float16 TFLite person detector
warmup-frame detection suppression
cached detections on skipped frames
MJPEG browser stream
```

The implementation lives in `pluto_runtime/camera.py` and is consumed by
`pluto_runtime/web_shell.py`.

The default model path is:

```text
/home/pi/yolo/model/yolov8n-fp16.tflite
```

This avoids copying the model into the main Pluto repo until the model storage
policy is decided.

## Interfaces

Inputs:

- USB webcam such as `/dev/video0`.
- Optional YOLOv8n float16 TFLite model.
- Browser request for `/camera.mjpg`.

Outputs:

- MJPEG stream at `/camera.mjpg`.
- Single JPEG snapshot at `/camera.jpg`.
- Camera/human status at `/api/camera/status`.
- Camera status included in `/api/status`.

External dependencies:

- Python 3.
- `cv2`.
- `numpy`.
- `ai_edge_litert` or compatible TFLite runtime for human detection.
- Existing `/home/pi/yolo/env` currently contains these dependencies.

## Configuration

Configuration values, defaults, limits, and files:

| Name | Default | Allowed Range | Reason |
| --- | --- | --- | --- |
| `--camera-device` | auto | `/dev/video*` or OpenCV index | Allows explicit webcam selection |
| `--camera-resolution` | `320x240` | positive WIDTHxHEIGHT | Keeps stream light for Pi 4 |
| `--camera-fps` | `30` | camera-supported FPS | Requested capture rate |
| `--camera-stream-fps` | `8` | positive integer | Browser stream target |
| `--camera-frame-skip` | `2` | positive integer | Runs detector every Nth frame |
| `--yolo-model` | `/home/pi/yolo/model/yolov8n-fp16.tflite` | existing `.tflite` file | Human detection model |
| `PLUTO_YOLO_MODEL` | unset | existing `.tflite` file | Environment override |

## Runtime Behavior

Normal behavior:

1. Website starts.
2. Camera service tries to open webcam with OpenCV.
3. Camera capture runs in a background thread.
4. Processing thread reads latest frame without waiting for camera capture.
5. Human detector loads if model and TFLite runtime are available.
6. Detector runs every `N` frames based on `--camera-frame-skip`.
7. Detections are suppressed during warmup frames.
8. Latest annotated JPEG is cached.
9. Browser reads cached frames through MJPEG stream.
10. `/api/status` reports FPS, inference time, human count, backend, and camera device.

Degraded behavior:

- Missing camera: website remains available and shows camera unavailable.
- Missing model/runtime: raw camera stream can still run, human detection shows unavailable.
- Browser disconnect: stream loop exits without stopping camera service.

## How To Run

On the Raspberry Pi with the existing YOLO environment:

```bash
cd ~/PLUTO-2026
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

Optional explicit webcam:

```bash
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell \
  --host 0.0.0.0 \
  --port 8080 \
  --camera-device /dev/video0 \
  --camera-resolution 320x240 \
  --camera-stream-fps 8 \
  --camera-frame-skip 2 \
  --yolo-model /home/pi/yolo/model/yolov8n-fp16.tflite
```

Open:

```text
http://<raspberry-pi-ip>:8080
```

## How To Debug

Checklist:

1. Check camera devices:

```bash
ls -la /dev/video*
v4l2-ctl --list-devices
```

2. Check dependencies:

```bash
/home/pi/yolo/env/bin/python - <<'PY'
import cv2, numpy
from ai_edge_litert.interpreter import Interpreter
print("camera deps ok")
PY
```

3. Check model:

```bash
ls -lh /home/pi/yolo/model/yolov8n-fp16.tflite
```

4. Check API:

```bash
curl http://127.0.0.1:8080/api/camera/status
curl -I http://127.0.0.1:8080/camera.jpg
```

5. If website works but no feed, run with explicit camera:

```bash
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --camera-device /dev/video0
```

## Expected Evidence

Website:

```text
Camera panel shows live feed.
Human count updates when a person is visible.
FPS and inference time are shown.
If unavailable, camera panel shows the exact reason.
```

API:

```text
GET /api/camera/status -> available true
GET /camera.jpg -> 200 image/jpeg
GET /camera.mjpg -> multipart MJPEG stream
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-WEB-002 | Open website with camera connected | Live feed visible | not run in browser |
| VER-WEB-003 | Start without camera or dependencies | Clear camera unavailable status | local smoke path covered |
| VER-WEB-009 | Open on phone viewport | Camera panel does not overlap controls | not run in browser |
| PHASE4-CAMERA-API | Call `/api/camera/status` | JSON contains camera availability/FPS/human count | local smoke pass |
| PHASE4-JPEG | Call `/camera.jpg` | `200 image/jpeg` when camera running, `503` when unavailable | local smoke pass for endpoint behavior |
| PHASE4-HUMAN | Stand in front of camera | `human_count >= 1` | not run with human target |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Camera unavailable | Wrong device or webcam unplugged | `/api/camera/status` error | Reconnect camera or run with `--camera-device /dev/video0` |
| `cv2` missing | Wrong Python environment | Import test fails | Run with `/home/pi/yolo/env/bin/python` or install OpenCV |
| Detector unavailable | Model or TFLite runtime missing | `detector_status` unavailable | Set `--yolo-model` and use yolo env |
| Low FPS | Resolution too high or stream FPS too high | `capture_fps`, `stream_fps`, `inference_ms` | Lower resolution, increase frame skip, reduce stream FPS |
| False detections at startup | Camera exposure settling | Early frames show humans incorrectly | Warmup suppression is enabled |
| Browser stream stalls | Client disconnect or server overloaded | Events/API status | Refresh page, lower stream FPS |

## Safety Notes

Phase 4 is perception only. It does not command motion and does not enable
WELCOME targeting yet. Human detections are displayed for operator visibility
only until the WELCOME state requirements are implemented and verified.

## Open Questions

- Should the YOLO model be copied into this repo or remain an external runtime
  asset under `/home/pi/yolo/model`?
- Should Phase 4 use a dedicated Pluto virtual environment instead of the
  existing YOLO environment?
- What minimum FPS should we accept for WELCOME trigger use later?

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-27 | Initial implementation memory | Phase 4 initiated from prior YOLO optimization repo |
