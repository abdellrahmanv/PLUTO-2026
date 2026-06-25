"""Camera feed and human detection service for Pluto Phase 4."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_MODEL_PATHS = (
    "/home/pi/yolo/model/yolov8n-fp16.tflite",
    "models/yolov8n-fp16.tflite",
)

DEFAULT_POSE_MODEL_PATHS = (
    "/home/pi/yolo/model/movenet_singlepose_lightning_int8.tflite",
    "models/movenet_singlepose_lightning_int8.tflite",
)


@dataclass
class HumanDetection:
    bbox: list[int]
    confidence: float
    class_name: str = "human"
    track_id: int | None = None


@dataclass
class CameraStatus:
    available: bool = False
    running: bool = False
    backend: str = "none"
    device: str | int | None = None
    resolution: list[int] = field(default_factory=lambda: [0, 0])
    configured_resolution: list[int] = field(default_factory=lambda: [320, 320])
    model_input_size: int = 224
    capture_fps: float = 0.0
    stream_fps: float = 0.0
    inference_fps: float = 0.0
    inference_ms: float = 0.0
    frame_skip: int = 1
    detection_hold_s: float = 2.0
    warmup_remaining: int = 0
    detections: list[HumanDetection] = field(default_factory=list)
    human_count: int = 0
    wave_motion: dict[str, Any] = field(default_factory=dict)
    detector_status: str = "not_started"
    model_path: str | None = None
    pose_status: str = "not_started"
    pose_model_path: str | None = None
    pose_inference_ms: float = 0.0
    pose_inference_fps: float = 0.0
    image_brightness: float = 0.0
    image_contrast: float = 0.0
    vision_quality: str = "unknown"
    perception_mode: str = "NORMAL"
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def find_model_path() -> str | None:
    env_path = os.environ.get("PLUTO_YOLO_MODEL")
    candidates = [env_path] if env_path else []
    candidates.extend(DEFAULT_MODEL_PATHS)
    for item in candidates:
        if not item:
            continue
        path = Path(item)
        if path.exists():
            return str(path)
    return None


def find_pose_model_path() -> str | None:
    env_path = os.environ.get("PLUTO_POSE_MODEL")
    candidates = [env_path] if env_path else []
    candidates.extend(DEFAULT_POSE_MODEL_PATHS)
    for item in candidates:
        if not item:
            continue
        path = Path(item)
        if path.exists():
            return str(path)
    return None


def list_video_devices() -> list[str]:
    devices = sorted(str(path) for path in Path("/dev").glob("video*"))
    usable = [item for item in devices if item.startswith("/dev/video")]
    return usable


def v4l2_summary() -> str:
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--list-devices"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def box_area(bbox: list[int] | list[float]) -> float:
    x1, y1, x2, y2 = [float(value) for value in bbox]
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def bbox_iou(a: list[int] | list[float], b: list[int] | list[float]) -> float:
    ax1, ay1, ax2, ay2 = [float(value) for value in a]
    bx1, by1, bx2, by2 = [float(value) for value in b]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = box_area(a) + box_area(b) - inter
    return inter / union if union > 1e-6 else 0.0


def normalized_center_distance(a: list[int] | list[float], b: list[int] | list[float]) -> float:
    ax1, ay1, ax2, ay2 = [float(value) for value in a]
    bx1, by1, bx2, by2 = [float(value) for value in b]
    acx, acy = (ax1 + ax2) / 2.0, (ay1 + ay2) / 2.0
    bcx, bcy = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
    scale = max(ax2 - ax1, ay2 - ay1, bx2 - bx1, by2 - by1, 1.0)
    return (((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5) / scale


class ThreadedCamera:
    """Background camera capture using OpenCV with low-latency settings."""

    def __init__(
        self,
        device: str | int | None = None,
        resolution: tuple[int, int] = (320, 320),
        framerate: int = 30,
        use_mjpg: bool = True,
    ) -> None:
        self.device = device
        self.resolution = resolution
        self.framerate = framerate
        self.use_mjpg = use_mjpg
        self.cv2 = None
        self.camera = None
        self.running = False
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_frame_time = 0.0
        self.capture_fps = 0.0
        self.frame_counter = 0
        self.last_fps_time = time.monotonic()
        self.backend = "opencv"
        self.opened_device: str | int | None = None
        self.actual_resolution = [0, 0]
        self.error: str | None = None

    def start(self) -> bool:
        try:
            import cv2  # type: ignore

            self.cv2 = cv2
        except Exception as exc:
            self.error = f"OpenCV unavailable: {exc}"
            return False

        if not self._open_camera():
            return False

        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, name="pluto-camera-capture", daemon=True)
        self.thread.start()

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with self.lock:
                if self.latest_frame is not None:
                    return True
            time.sleep(0.02)

        self.error = "camera opened but no frame arrived"
        self.stop()
        return False

    def _open_camera(self) -> bool:
        assert self.cv2 is not None
        candidates: list[str | int] = []
        if self.device is not None:
            candidates.append(self.device)
        else:
            env_device = os.environ.get("PLUTO_CAMERA_DEVICE")
            if env_device:
                candidates.append(env_device)
            # Raspberry Pi exposes many /dev/video* nodes that are not capture
            # devices. Some block for several seconds when opened, so the
            # automatic path only tries the normal primary camera endpoints.
            candidates.extend(["/dev/video0", "/dev/video1", 0, 1])

        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)

            cam = self.cv2.VideoCapture(candidate)
            if not cam.isOpened():
                cam.release()
                continue

            if self.use_mjpg:
                cam.set(self.cv2.CAP_PROP_FOURCC, self.cv2.VideoWriter_fourcc(*"MJPG"))
            cam.set(self.cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
            cam.set(self.cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
            cam.set(self.cv2.CAP_PROP_FPS, self.framerate)
            cam.set(self.cv2.CAP_PROP_BUFFERSIZE, 1)

            ok, frame = cam.read()
            if ok and frame is not None:
                self.camera = cam
                self.opened_device = candidate
                self.actual_resolution = [int(frame.shape[1]), int(frame.shape[0])]
                return True

            cam.release()

        self.error = "no usable camera device found"
        return False

    def _capture_loop(self) -> None:
        assert self.cv2 is not None
        while self.running:
            try:
                ok, frame = self.camera.read() if self.camera is not None else (False, None)
                if not ok or frame is None:
                    time.sleep(0.01)
                    continue

                frame_rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
                frame_rgb = self.cv2.rotate(frame_rgb, self.cv2.ROTATE_180)
                now = time.monotonic()
                with self.lock:
                    self.latest_frame = frame_rgb
                    self.latest_frame_time = time.time()
                    self.frame_counter += 1
                    elapsed = now - self.last_fps_time
                    if elapsed >= 1.0:
                        self.capture_fps = self.frame_counter / elapsed
                        self.frame_counter = 0
                        self.last_fps_time = now
            except Exception as exc:
                self.error = str(exc)
                time.sleep(0.05)

    def get_frame(self):
        with self.lock:
            if self.latest_frame is None:
                return None
            return self.latest_frame.copy()

    def stop(self) -> None:
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.camera is not None:
            self.camera.release()
        self.camera = None


class YoloHumanDetector:
    """YOLOv8n TFLite person detector adapted from the prior yolo repo."""

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.40,
        iou_threshold: float = 0.45,
        num_threads: int = 4,
    ) -> None:
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.num_threads = num_threads
        self.interpreter = None
        self.input_details = None
        self.output_details = None
        self.input_size = 224
        self.inference_times: list[float] = []
        self.status = "not_loaded"
        self.error: str | None = None

    def load(self) -> bool:
        try:
            import cv2  # type: ignore
            import numpy as np  # noqa: F401

            self.cv2 = cv2
        except Exception as exc:
            self.error = f"OpenCV/numpy unavailable: {exc}"
            self.status = "unavailable"
            return False

        if not Path(self.model_path).exists():
            self.error = f"model missing: {self.model_path}"
            self.status = "unavailable"
            return False

        Interpreter = None
        try:
            from ai_edge_litert.interpreter import Interpreter  # type: ignore
        except Exception:
            try:
                from tflite_runtime.interpreter import Interpreter  # type: ignore
            except Exception:
                try:
                    from tensorflow.lite.python.interpreter import Interpreter  # type: ignore
                except Exception:
                    Interpreter = None

        if Interpreter is None:
            self.error = "No TFLite runtime found"
            self.status = "unavailable"
            return False

        try:
            self.interpreter = Interpreter(model_path=self.model_path, num_threads=self.num_threads)
            self.interpreter.allocate_tensors()
            self.input_details = self.interpreter.get_input_details()[0]
            self.output_details = self.interpreter.get_output_details()[0]
            shape = self.input_details["shape"]
            if len(shape) >= 3:
                self.input_size = int(shape[1])
            self.status = "loaded"
            return True
        except Exception as exc:
            self.error = f"model load failed: {exc}"
            self.status = "error"
            return False

    def detect(self, frame) -> list[HumanDetection]:
        if self.interpreter is None:
            return []

        import numpy as np

        start = time.monotonic()
        h, w = frame.shape[:2]
        resized = self.cv2.resize(frame, (self.input_size, self.input_size))
        input_data = resized.astype(np.float32) / 255.0
        input_data = np.expand_dims(input_data, axis=0)

        self.interpreter.set_tensor(self.input_details["index"], input_data)
        self.interpreter.invoke()
        output_data = self.interpreter.get_tensor(self.output_details["index"])

        output = output_data[0].T
        detections = self._parse_output(output, (h, w))
        detections = self._apply_nms(detections)

        self.inference_times.append(time.monotonic() - start)
        if len(self.inference_times) > 30:
            self.inference_times = self.inference_times[-30:]
        return detections

    def _parse_output(self, output, original_size: tuple[int, int]) -> list[HumanDetection]:
        import numpy as np

        original_h, original_w = original_size
        x_center = output[:, 0]
        y_center = output[:, 1]
        width = output[:, 2]
        height = output[:, 3]
        class_scores = output[:, 4:84]
        person_score = class_scores[:, 0]
        best_class = np.argmax(class_scores, axis=1)

        valid = (
            (best_class == 0)
            & (person_score >= self.confidence_threshold)
            & (width > 0.001)
            & (height > 0.001)
        )
        if not np.any(valid):
            return []

        x_center = x_center[valid]
        y_center = y_center[valid]
        width = width[valid]
        height = height[valid]
        confidence = person_score[valid]

        x1 = ((x_center - width / 2) * original_w).astype(np.int32)
        y1 = ((y_center - height / 2) * original_h).astype(np.int32)
        x2 = ((x_center + width / 2) * original_w).astype(np.int32)
        y2 = ((y_center + height / 2) * original_h).astype(np.int32)

        x1 = np.clip(x1, 0, original_w)
        y1 = np.clip(y1, 0, original_h)
        x2 = np.clip(x2, 0, original_w)
        y2 = np.clip(y2, 0, original_h)
        box_valid = (x2 > x1) & (y2 > y1) & ((x2 - x1) >= 15) & ((y2 - y1) >= 15)

        return [
            HumanDetection(
                bbox=[int(x1[i]), int(y1[i]), int(x2[i]), int(y2[i])],
                confidence=float(confidence[i]),
            )
            for i in np.where(box_valid)[0]
        ]

    def _apply_nms(self, detections: list[HumanDetection]) -> list[HumanDetection]:
        if not detections:
            return []

        boxes_xyxy = [det.bbox for det in detections]
        boxes_xywh = [
            [x1, y1, x2 - x1, y2 - y1]
            for x1, y1, x2, y2 in boxes_xyxy
        ]
        scores = [det.confidence for det in detections]
        indices = self.cv2.dnn.NMSBoxes(boxes_xywh, scores, self.confidence_threshold, self.iou_threshold)
        if len(indices) == 0:
            return []
        return [detections[int(i)] for i in indices.flatten()]

    def average_inference_ms(self) -> float:
        if not self.inference_times:
            return 0.0
        return (sum(self.inference_times) / len(self.inference_times)) * 1000.0

    def inference_fps(self) -> float:
        avg = self.average_inference_ms()
        return 1000.0 / avg if avg > 0 else 0.0


class CameraService:
    """Owns camera capture, optional human detection, and MJPEG frames."""

    def __init__(
        self,
        device: str | int | None = None,
        resolution: tuple[int, int] = (320, 320),
        framerate: int = 30,
        stream_fps: int = 8,
        frame_skip: int = 1,
        detection_hold_s: float = 2.0,
        warmup_frames: int = 5,
        model_path: str | None = None,
        pose_model_path: str | None = None,
        pose_enabled: bool = True,
        pose_frame_skip: int = 1,
        pose_max_tracks: int = 2,
        confidence_threshold: float = 0.30,
    ) -> None:
        self.device = device
        self.resolution = resolution
        self.framerate = framerate
        self.target_stream_fps = stream_fps
        self.frame_skip = max(1, frame_skip)
        self.detection_hold_s = max(0.0, detection_hold_s)
        self.warmup_frames = max(0, warmup_frames)
        self.model_path = model_path or find_model_path()
        self.pose_model_path = pose_model_path or find_pose_model_path()
        self.pose_enabled = pose_enabled
        self.pose_frame_skip = max(1, pose_frame_skip)
        self.pose_max_tracks = max(1, pose_max_tracks)
        self.confidence_threshold = confidence_threshold
        self.camera: ThreadedCamera | None = None
        self.detector: YoloHumanDetector | None = None
        self.pose_estimator: Any | None = None
        self.pose_error: str | None = None
        self.running = False
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.latest_jpeg: bytes | None = None
        self.latest_detections: list[HumanDetection] = []
        self.latest_wave_motion: dict[str, Any] = {"available": False, "reason": "not_started"}
        self.previous_wave_rois: dict[int, Any] = {}
        self.tracks: dict[int, dict[str, Any]] = {}
        self.next_track_id = 1
        self.wave_lock_until = 0.0
        self.wave_lock_label = "WAVE LOCK"
        self.wave_lock_track_id: int | None = None
        self.wave_lock_anchor_bbox: list[int] | None = None
        self.wave_lock_anchor_updated_at = 0.0
        self.lock_match_min_iou = 0.12
        self.lock_match_max_center_distance = 0.45
        self.image_brightness = 0.0
        self.image_contrast = 0.0
        self.vision_quality = "unknown"
        self.last_positive_detection_time = 0.0
        self.status = CameraStatus(configured_resolution=[resolution[0], resolution[1]], frame_skip=self.frame_skip)
        self.stream_frame_count = 0
        self.stream_fps_value = 0.0
        self.last_stream_fps_time = time.monotonic()
        self.error: str | None = None
        self.perception_mode = "NORMAL"

    def set_perception_mode(self, mode: str) -> bool:
        clean = str(mode or "NORMAL").upper()
        if clean not in {"NORMAL", "REDUCED", "PAUSED"}:
            clean = "NORMAL"
        if clean == self.perception_mode:
            return False
        self.perception_mode = clean
        if clean != "NORMAL":
            self.previous_wave_rois.clear()
            self.latest_wave_motion = {
                "available": False,
                "reason": f"perception_{clean.lower()}",
                "timestamp": time.time(),
            }
        return True

    def start(self) -> bool:
        if self.running:
            return True

        self.camera = ThreadedCamera(self.device, self.resolution, self.framerate)
        if not self.camera.start():
            self.error = self.camera.error or "camera failed to start"
            self.status = self._build_status(available=False, running=False, error=self.error)
            return False

        self.detector = None
        if self.model_path:
            detector = YoloHumanDetector(self.model_path)
            detector.confidence_threshold = self.confidence_threshold
            if detector.load():
                self.detector = detector
            else:
                self.error = detector.error

        if self.pose_enabled:
            if self.pose_model_path:
                try:
                    from .pose_wave import MovenetPoseEstimator

                    pose = MovenetPoseEstimator(self.pose_model_path)
                    if pose.load():
                        self.pose_estimator = pose
                    else:
                        self.pose_error = pose.error
                except Exception as exc:
                    self.pose_error = f"pose backend unavailable: {exc}"
            else:
                self.pose_error = "pose model missing"

        self.running = True
        self.thread = threading.Thread(target=self._processing_loop, name="pluto-camera-processing", daemon=True)
        self.thread.start()
        return True

    def stop(self) -> None:
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.camera:
            self.camera.stop()

    def _processing_loop(self) -> None:
        assert self.camera is not None
        import cv2  # type: ignore

        frame_index = 0
        warmup_remaining = self.warmup_frames
        next_frame_time = 0.0

        while self.running:
            now = time.monotonic()
            if now < next_frame_time:
                time.sleep(0.005)
                continue
            next_frame_time = now + (1.0 / max(1, self.target_stream_fps))

            frame = self.camera.get_frame()
            if frame is None:
                continue

            frame_index += 1
            self._update_image_quality(frame)
            mode = self.perception_mode
            effective_frame_skip = self.frame_skip
            if mode == "REDUCED":
                effective_frame_skip = max(self.frame_skip, 4)
            if self.detector and mode != "PAUSED" and frame_index % effective_frame_skip == 0:
                detections = self.detector.detect(frame)
                if warmup_remaining > 0:
                    detections = []
                    warmup_remaining -= 1
                if detections:
                    detections = self._assign_tracks(detections, time.monotonic())
                    self.latest_detections = detections
                    self.last_positive_detection_time = time.monotonic()
                elif time.monotonic() - self.last_positive_detection_time > self.detection_hold_s:
                    self.latest_detections = []
                    self._cleanup_tracks(time.monotonic())

            if mode == "NORMAL":
                wave_motion = self._estimate_wave_motion(cv2, frame, self.latest_detections, frame_index)
            else:
                self.previous_wave_rois.clear()
                wave_motion = {
                    "available": False,
                    "reason": f"perception_{mode.lower()}",
                    "frame_index": frame_index,
                    "timestamp": time.time(),
                }

            annotated = frame.copy()
            self._draw_overlay(cv2, annotated, self.latest_detections, wave_motion)
            ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ok:
                with self.lock:
                    self.latest_jpeg = encoded.tobytes()
                    self.stream_frame_count += 1
                    elapsed = time.monotonic() - self.last_stream_fps_time
                    if elapsed >= 1.0:
                        self.stream_fps_value = self.stream_frame_count / elapsed
                        self.stream_frame_count = 0
                        self.last_stream_fps_time = time.monotonic()
                    self.latest_wave_motion = wave_motion
                    self.status = self._build_status(available=True, running=True, warmup_remaining=warmup_remaining)

    def _assign_tracks(self, detections: list[HumanDetection], now: float) -> list[HumanDetection]:
        self._cleanup_tracks(now)
        available_ids = set(self.tracks.keys())
        assigned: list[HumanDetection] = []

        remaining = sorted(detections, key=lambda item: box_area(item.bbox), reverse=True)
        locked_det = self._claim_locked_detection(remaining, now)
        if locked_det is not None and self.wave_lock_track_id is not None:
            locked_det.track_id = self.wave_lock_track_id
            self.tracks[self.wave_lock_track_id] = {
                "bbox": list(locked_det.bbox),
                "last_seen": now,
                "confidence": locked_det.confidence,
                "locked": True,
            }
            self.wave_lock_anchor_bbox = list(locked_det.bbox)
            self.wave_lock_anchor_updated_at = now
            available_ids.discard(self.wave_lock_track_id)
            assigned.append(locked_det)

        for det in remaining:
            best_id: int | None = None
            best_score = 0.0
            for track_id in list(available_ids):
                track = self.tracks.get(track_id)
                if not track:
                    continue
                iou = bbox_iou(det.bbox, track["bbox"])
                dist = normalized_center_distance(det.bbox, track["bbox"])
                score = max(iou, 1.0 - dist)
                if (iou >= 0.12 or dist <= 0.55) and score > best_score:
                    best_score = score
                    best_id = track_id
            if best_id is None:
                best_id = self.next_track_id
                self.next_track_id += 1
            available_ids.discard(best_id)
            det.track_id = best_id
            self.tracks[best_id] = {"bbox": list(det.bbox), "last_seen": now, "confidence": det.confidence}
            assigned.append(det)
        return assigned

    def _claim_locked_detection(self, detections: list[HumanDetection], now: float) -> HumanDetection | None:
        if not detections or self.wave_lock_track_id is None or now >= self.wave_lock_until:
            return None
        anchor = self.wave_lock_anchor_bbox
        if anchor is None:
            track = self.tracks.get(self.wave_lock_track_id)
            anchor = list(track["bbox"]) if track and track.get("bbox") else None
        if anchor is None:
            return None

        best_index: int | None = None
        best_score = -999.0
        for index, det in enumerate(detections):
            iou = bbox_iou(det.bbox, anchor)
            dist = normalized_center_distance(det.bbox, anchor)
            score = (iou * 2.0) + (1.0 - dist)
            if score > best_score:
                best_score = score
                best_index = index

        if best_index is None:
            return None

        candidate = detections[best_index]
        if not self._lock_match_ok(candidate.bbox, anchor):
            self.clear_wave_lock()
            return None
        return detections.pop(best_index)

    def _lock_match_ok(self, bbox: list[int] | list[float], anchor: list[int] | list[float]) -> bool:
        return (
            bbox_iou(bbox, anchor) >= self.lock_match_min_iou
            or normalized_center_distance(bbox, anchor) <= self.lock_match_max_center_distance
        )

    def _update_image_quality(self, frame) -> None:
        try:
            import numpy as np

            gray = (
                0.299 * frame[:, :, 0].astype(np.float32)
                + 0.587 * frame[:, :, 1].astype(np.float32)
                + 0.114 * frame[:, :, 2].astype(np.float32)
            )
            brightness = float(gray.mean())
            contrast = float(gray.std())
        except Exception:
            return

        self.image_brightness = brightness
        self.image_contrast = contrast
        if brightness < 35.0 or contrast < 18.0:
            self.vision_quality = "low_light"
        elif brightness < 55.0 or contrast < 24.0:
            self.vision_quality = "dim"
        else:
            self.vision_quality = "ok"

    def _cleanup_tracks(self, now: float) -> None:
        stale = [track_id for track_id, item in self.tracks.items() if now - float(item.get("last_seen", 0.0)) > 2.0]
        active_ids = set(self.tracks.keys()) - set(stale)
        for track_id in stale:
            self.tracks.pop(track_id, None)
            self.previous_wave_rois.pop(track_id, None)
        if self.wave_lock_track_id is not None and self.wave_lock_track_id not in active_ids and now >= self.wave_lock_until:
            self.wave_lock_track_id = None
            self.wave_lock_anchor_bbox = None

    def _estimate_wave_motion(self, cv2, frame, detections: list[HumanDetection], frame_index: int) -> dict[str, Any]:
        if not detections:
            self.previous_wave_rois.clear()
            return {"available": False, "reason": "no_person", "frame_index": frame_index, "timestamp": time.time()}

        if self.vision_quality == "low_light":
            return {
                "available": False,
                "reason": "low_light",
                "candidates": [],
                "flow_candidates": [],
                "frame_index": frame_index,
                "timestamp": time.time(),
                "image_brightness": self.image_brightness,
                "image_contrast": self.image_contrast,
            }

        pose_candidates: list[dict[str, Any]] = []
        flow_candidates: list[dict[str, Any]] = []
        lock_active = time.monotonic() < self.wave_lock_until and self.wave_lock_track_id is not None
        ordered = sorted(detections, key=lambda item: box_area(item.bbox), reverse=True)
        if lock_active:
            locked = [item for item in ordered if item.track_id == self.wave_lock_track_id]
            ordered = locked or ordered[:1]
        else:
            ordered = ordered[: max(1, self.pose_max_tracks)]

        if self.pose_estimator is not None and frame_index % self.pose_frame_skip == 0:
            for det in ordered:
                candidate = self._estimate_detection_pose_wave(frame, det, frame_index)
                if candidate.get("available"):
                    pose_candidates.append(candidate)

        for det in ordered[:3]:
            candidate = self._estimate_detection_wave_motion(cv2, frame, det)
            if candidate.get("available"):
                candidate["frame_index"] = frame_index
                candidate["timestamp"] = time.time()
                flow_candidates.append(candidate)

        if pose_candidates:
            best = max(pose_candidates, key=lambda item: float(item.get("pose_score") or item.get("confidence") or 0.0))
            return {
                **best,
                "available": True,
                "reason": "movenet_pose",
                "candidates": pose_candidates,
                "flow_candidates": flow_candidates,
                "locked_track_id": self.wave_lock_track_id if lock_active else None,
                "frame_index": frame_index,
                "timestamp": time.time(),
            }

        if self.pose_estimator is not None:
            return {
                "available": False,
                "reason": "pose_no_keypoints",
                "candidates": [],
                "flow_candidates": flow_candidates,
                "locked_track_id": self.wave_lock_track_id if lock_active else None,
                "frame_index": frame_index,
                "timestamp": time.time(),
                "image_brightness": self.image_brightness,
                "image_contrast": self.image_contrast,
            }

        if not flow_candidates:
            return {
                "available": False,
                "reason": self.pose_error or "pose_unavailable",
                "candidates": [],
                "flow_candidates": [],
                "frame_index": frame_index,
                "timestamp": time.time(),
            }

        best = max(flow_candidates, key=lambda item: float(item.get("motion_norm") or 0.0))
        return {
            **best,
            "available": True,
            "reason": "optical_flow_debug_only",
            "candidates": [],
            "flow_candidates": flow_candidates,
            "locked_track_id": self.wave_lock_track_id if lock_active else None,
            "frame_index": frame_index,
            "timestamp": time.time(),
            "image_brightness": self.image_brightness,
            "image_contrast": self.image_contrast,
        }

    def _estimate_detection_pose_wave(self, frame, det: HumanDetection, frame_index: int) -> dict[str, Any]:
        track_id = int(det.track_id or 0)
        if self.pose_estimator is None:
            return {"available": False, "reason": "pose_unavailable", "track_id": track_id}

        keypoints = self.pose_estimator.estimate(frame, det.bbox)
        if not keypoints:
            return {"available": False, "reason": "pose_no_keypoints", "track_id": track_id}

        scores = [
            float(keypoints[name][2])
            for name in ("left_shoulder", "right_shoulder", "left_wrist", "right_wrist")
            if name in keypoints
        ]
        pose_score = sum(scores) / max(len(scores), 1)
        return {
            "available": True,
            "reason": "movenet_pose",
            "track_id": track_id,
            "bbox": det.bbox,
            "confidence": det.confidence,
            "pose_score": pose_score,
            "pose_keypoints": keypoints,
            "frame_index": frame_index,
            "timestamp": time.time(),
        }

    def _estimate_detection_wave_motion(self, cv2, frame, det: HumanDetection) -> dict[str, Any]:
        track_id = int(det.track_id or 0)
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = det.bbox
        box_w = max(1, x2 - x1)
        box_h = max(1, y2 - y1)
        pad_x = int(box_w * 0.35)
        top = max(0, y1 - int(box_h * 0.10))
        bottom = min(height, y1 + int(box_h * 0.78))
        left = max(0, x1 - pad_x)
        right = min(width, x2 + pad_x)
        if right - left < 16 or bottom - top < 16:
            self.previous_wave_rois.pop(track_id, None)
            return {"available": False, "reason": "roi_too_small", "track_id": track_id}

        import numpy as np

        crop = frame[top:bottom, left:right]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        roi = cv2.resize(gray, (80, 80), interpolation=cv2.INTER_AREA)
        roi = cv2.GaussianBlur(roi, (5, 5), 0)
        previous_roi = self.previous_wave_rois.get(track_id)
        if previous_roi is None:
            self.previous_wave_rois[track_id] = roi
            return {
                "available": True,
                "reason": "priming",
                "track_id": track_id,
                "motion_norm": 0.0,
                "balance": 0.0,
                "bbox": det.bbox,
                "confidence": det.confidence,
            }

        flow = cv2.calcOpticalFlowFarneback(
            previous_roi,
            roi,
            None,
            0.5,
            2,
            11,
            2,
            5,
            1.1,
            0,
        )
        diff = cv2.absdiff(roi, previous_roi)
        self.previous_wave_rois[track_id] = roi

        # Remove global crop motion first. The remaining residual flow is much
        # closer to "arm/hand moving while the person stays mostly still".
        fx = flow[..., 0]
        fy = flow[..., 1]
        fx = fx - float(np.median(fx))
        fy = fy - float(np.median(fy))
        mag = np.sqrt((fx * fx) + (fy * fy))
        adaptive_thresh = max(0.16, float(np.percentile(mag, 72)))
        active_flow = mag > adaptive_thresh
        active_diff = diff > 14
        active = active_flow & active_diff
        if active.mean() < 0.006:
            active = active_flow

        weights = mag * active
        weight_sum = float(weights.sum())
        motion_norm = float(active.mean())
        flow_dx = float((fx * weights).sum() / weight_sum) if weight_sum > 1e-6 else 0.0
        flow_dy = float((fy * weights).sum() / weight_sum) if weight_sum > 1e-6 else 0.0
        flow_dx_dy = abs(flow_dx) / (abs(flow_dy) + 1e-6)
        hand_valid = motion_norm >= 0.006 and weight_sum > 1e-6
        hand_x_norm = 0.0
        hand_y_norm = 1.0
        raised_region = False
        if hand_valid:
            yy, xx = np.indices(active.shape)
            cx_roi = float((xx * weights).sum() / weight_sum) / 79.0
            cy_roi = float((yy * weights).sum() / weight_sum) / 79.0
            hand_x = left + cx_roi * max(1, right - left)
            hand_y = top + cy_roi * max(1, bottom - top)
            hand_x_norm = float((hand_x - ((x1 + x2) / 2.0)) / box_w)
            hand_y_norm = float((hand_y - y1) / box_h)
            raised_region = hand_y_norm <= 0.82
        left_motion = float(weights[:, :40].sum())
        right_motion = float(weights[:, 40:].sum())
        total = left_motion + right_motion
        balance = (right_motion - left_motion) / total if total > 0 else 0.0
        return {
            "available": True,
            "reason": "optical_flow",
            "track_id": track_id,
            "motion_norm": motion_norm,
            "balance": balance,
            "left_motion": left_motion,
            "right_motion": right_motion,
            "flow_dx": flow_dx,
            "flow_dy": flow_dy,
            "flow_dx_dy": flow_dx_dy,
            "hand_valid": hand_valid,
            "hand_x_norm": hand_x_norm,
            "hand_y_norm": hand_y_norm,
            "raised_region": raised_region,
            "bbox": det.bbox,
            "confidence": det.confidence,
        }

    def set_wave_lock(
        self,
        duration_s: float = 3.0,
        label: str = "WAVE LOCK",
        track_id: int | None = None,
        bbox: list[int] | None = None,
    ) -> None:
        with self.lock:
            self.wave_lock_until = time.monotonic() + max(0.5, duration_s)
            self.wave_lock_label = label
            self.wave_lock_track_id = track_id
            if bbox is None and track_id is not None:
                match = next((item for item in self.latest_detections if item.track_id == track_id), None)
                bbox = list(match.bbox) if match else None
            if bbox is not None:
                self.wave_lock_anchor_bbox = [int(value) for value in bbox]
                self.wave_lock_anchor_updated_at = time.monotonic()

    def clear_wave_lock(self) -> None:
        with self.lock:
            self.wave_lock_until = 0.0
            self.wave_lock_track_id = None
            self.wave_lock_anchor_bbox = None

    def _draw_overlay(self, cv2, frame, detections: list[HumanDetection], wave_motion: dict[str, Any] | None = None) -> None:
        lock_active = time.monotonic() < self.wave_lock_until
        locked_det = None
        if detections:
            if lock_active and self.wave_lock_track_id is not None:
                locked_det = self._locked_detection_for_overlay(detections)
            if locked_det is None:
                locked_det = max(detections, key=lambda item: box_area(item.bbox))
        visible_detections = [locked_det] if lock_active and locked_det is not None else detections
        for det in visible_detections:
            if det is None:
                continue
            x1, y1, x2, y2 = det.bbox
            is_locked = lock_active and locked_det is det
            color = (255, 0, 0) if is_locked else (0, 255, 0)
            thickness = 3 if is_locked else 2
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
            label_id = f"ID {det.track_id} " if det.track_id is not None else ""
            label = f"{self.wave_lock_label} {label_id}{det.confidence:.2f}" if is_locked else f"{label_id}human {det.confidence:.2f}"
            cv2.putText(frame, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        for candidate in (wave_motion or {}).get("candidates", []) or []:
            if not isinstance(candidate, dict):
                continue
            if lock_active and self.wave_lock_track_id is not None and candidate.get("track_id") != self.wave_lock_track_id:
                continue
            self._draw_pose_keypoints(cv2, frame, candidate.get("pose_keypoints") or {})

        fps = self.stream_fps_value
        inf_ms = self.detector.average_inference_ms() if self.detector else 0.0
        pose_ms = self.pose_estimator.average_inference_ms() if self.pose_estimator else 0.0
        text = f"FPS {fps:.1f} | Humans {len(detections)} | Y {inf_ms:.0f}ms | P {pose_ms:.0f}ms"
        cv2.rectangle(frame, (5, 5), (310, 34), (0, 0, 0), -1)
        cv2.putText(frame, text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 0), 1)

    def _locked_detection_for_overlay(self, detections: list[HumanDetection]) -> HumanDetection | None:
        if self.wave_lock_track_id is None:
            return None
        direct = next((item for item in detections if item.track_id == self.wave_lock_track_id), None)
        if direct is not None:
            self.wave_lock_anchor_bbox = list(direct.bbox)
            self.wave_lock_anchor_updated_at = time.monotonic()
            return direct
        if self.wave_lock_anchor_bbox is None:
            return None
        best = min(detections, key=lambda item: normalized_center_distance(item.bbox, self.wave_lock_anchor_bbox))
        if self._lock_match_ok(best.bbox, self.wave_lock_anchor_bbox):
            return best
        self.clear_wave_lock()
        return None

    def _draw_pose_keypoints(self, cv2, frame, keypoints: dict[str, Any]) -> None:
        if not keypoints:
            return
        pairs = [
            ("left_shoulder", "left_elbow"),
            ("left_elbow", "left_wrist"),
            ("right_shoulder", "right_elbow"),
            ("right_elbow", "right_wrist"),
            ("left_shoulder", "right_shoulder"),
        ]
        for first, second in pairs:
            a = keypoints.get(first)
            b = keypoints.get(second)
            if not a or not b or float(a[2]) < 0.20 or float(b[2]) < 0.20:
                continue
            cv2.line(frame, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), (255, 255, 0), 2)
        for point in keypoints.values():
            if not point or float(point[2]) < 0.20:
                continue
            cv2.circle(frame, (int(point[0]), int(point[1])), 3, (255, 0, 255), -1)

    def _build_status(self, available: bool, running: bool, error: str | None = None, warmup_remaining: int = 0) -> CameraStatus:
        camera = self.camera
        detector = self.detector
        detections = list(self.latest_detections)
        pose_status = self.pose_estimator.status_dict(self.pose_max_tracks, self.pose_frame_skip) if self.pose_estimator else {
            "status": "unavailable" if self.pose_enabled else "disabled",
            "model_path": self.pose_model_path,
            "inference_ms": 0.0,
            "inference_fps": 0.0,
            "error": self.pose_error,
        }
        return CameraStatus(
            available=available,
            running=running,
            backend=camera.backend if camera else "none",
            device=camera.opened_device if camera else self.device,
            resolution=camera.actual_resolution if camera else [0, 0],
            configured_resolution=[self.resolution[0], self.resolution[1]],
            model_input_size=detector.input_size if detector else 0,
            capture_fps=camera.capture_fps if camera else 0.0,
            stream_fps=self.stream_fps_value,
            inference_fps=detector.inference_fps() if detector else 0.0,
            inference_ms=detector.average_inference_ms() if detector else 0.0,
            frame_skip=self.frame_skip,
            detection_hold_s=self.detection_hold_s,
            warmup_remaining=warmup_remaining,
            detections=detections,
            human_count=len(detections),
            wave_motion=dict(self.latest_wave_motion),
            detector_status=detector.status if detector else "unavailable",
            model_path=self.model_path,
            pose_status=str(pose_status.get("status", "unknown")),
            pose_model_path=self.pose_model_path,
            pose_inference_ms=float(pose_status.get("inference_ms") or 0.0),
            pose_inference_fps=float(pose_status.get("inference_fps") or 0.0),
            image_brightness=self.image_brightness,
            image_contrast=self.image_contrast,
            vision_quality=self.vision_quality,
            perception_mode=self.perception_mode,
            error=error or self.error,
            details={
                "video_devices": list_video_devices(),
                "v4l2": v4l2_summary(),
                "optimizations": [
                    "threaded_capture",
                    "frame_skip",
                    "mjpg",
                    "low_resolution",
                    "warmup_suppression",
                    "movenet_int8_pose_crops",
                ],
                "wave_lock_active": time.monotonic() < self.wave_lock_until,
                "wave_locked_track_id": self.wave_lock_track_id,
                "wave_lock_anchor_bbox": self.wave_lock_anchor_bbox,
                "wave_lock_anchor_age_s": time.monotonic() - self.wave_lock_anchor_updated_at if self.wave_lock_anchor_updated_at else None,
                "wave_lock_match_min_iou": self.lock_match_min_iou,
                "wave_lock_match_max_center_distance": self.lock_match_max_center_distance,
                "active_track_ids": sorted(self.tracks.keys()),
                "image_brightness": self.image_brightness,
                "image_contrast": self.image_contrast,
                "vision_quality": self.vision_quality,
                "perception_mode": self.perception_mode,
                "pose": pose_status,
            },
        )

    def get_status(self) -> CameraStatus:
        with self.lock:
            return self.status

    def get_jpeg(self) -> bytes | None:
        with self.lock:
            return self.latest_jpeg

    def stream_frames(self):
        while self.running:
            frame = self.get_jpeg()
            if frame:
                yield frame
            time.sleep(1.0 / max(1, self.target_stream_fps))


def status_to_dict(status: CameraStatus) -> dict[str, Any]:
    return asdict(status)
