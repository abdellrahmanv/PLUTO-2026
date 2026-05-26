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


@dataclass
class HumanDetection:
    bbox: list[int]
    confidence: float
    class_name: str = "human"


@dataclass
class CameraStatus:
    available: bool = False
    running: bool = False
    backend: str = "none"
    device: str | int | None = None
    resolution: list[int] = field(default_factory=lambda: [0, 0])
    configured_resolution: list[int] = field(default_factory=lambda: [320, 240])
    model_input_size: int = 224
    capture_fps: float = 0.0
    stream_fps: float = 0.0
    inference_fps: float = 0.0
    inference_ms: float = 0.0
    frame_skip: int = 2
    warmup_remaining: int = 0
    detections: list[HumanDetection] = field(default_factory=list)
    human_count: int = 0
    detector_status: str = "not_started"
    model_path: str | None = None
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


class ThreadedCamera:
    """Background camera capture using OpenCV with low-latency settings."""

    def __init__(
        self,
        device: str | int | None = None,
        resolution: tuple[int, int] = (320, 240),
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
        candidates.extend(list_video_devices())
        candidates.extend([0, 1])

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
        resolution: tuple[int, int] = (320, 240),
        framerate: int = 30,
        stream_fps: int = 8,
        frame_skip: int = 2,
        warmup_frames: int = 5,
        model_path: str | None = None,
    ) -> None:
        self.device = device
        self.resolution = resolution
        self.framerate = framerate
        self.target_stream_fps = stream_fps
        self.frame_skip = max(1, frame_skip)
        self.warmup_frames = max(0, warmup_frames)
        self.model_path = model_path or find_model_path()
        self.camera: ThreadedCamera | None = None
        self.detector: YoloHumanDetector | None = None
        self.running = False
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.latest_jpeg: bytes | None = None
        self.latest_detections: list[HumanDetection] = []
        self.status = CameraStatus(configured_resolution=[resolution[0], resolution[1]], frame_skip=self.frame_skip)
        self.stream_frame_count = 0
        self.stream_fps_value = 0.0
        self.last_stream_fps_time = time.monotonic()
        self.error: str | None = None

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
            if detector.load():
                self.detector = detector
            else:
                self.error = detector.error

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
            if self.detector and frame_index % self.frame_skip == 0:
                detections = self.detector.detect(frame)
                if warmup_remaining > 0:
                    detections = []
                    warmup_remaining -= 1
                self.latest_detections = detections

            annotated = frame.copy()
            self._draw_overlay(cv2, annotated, self.latest_detections)
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
                    self.status = self._build_status(available=True, running=True, warmup_remaining=warmup_remaining)

    def _draw_overlay(self, cv2, frame, detections: list[HumanDetection]) -> None:
        for det in detections:
            x1, y1, x2, y2 = det.bbox
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"human {det.confidence:.2f}"
            cv2.putText(frame, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        fps = self.stream_fps_value
        inf_ms = self.detector.average_inference_ms() if self.detector else 0.0
        text = f"FPS {fps:.1f} | Humans {len(detections)} | Inf {inf_ms:.0f}ms"
        cv2.rectangle(frame, (5, 5), (310, 34), (0, 0, 0), -1)
        cv2.putText(frame, text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 0), 1)

    def _build_status(self, available: bool, running: bool, error: str | None = None, warmup_remaining: int = 0) -> CameraStatus:
        camera = self.camera
        detector = self.detector
        detections = list(self.latest_detections)
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
            warmup_remaining=warmup_remaining,
            detections=detections,
            human_count=len(detections),
            detector_status=detector.status if detector else "unavailable",
            model_path=self.model_path,
            error=error or self.error,
            details={
                "video_devices": list_video_devices(),
                "v4l2": v4l2_summary(),
                "optimizations": ["threaded_capture", "frame_skip", "mjpg", "low_resolution", "warmup_suppression"],
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
