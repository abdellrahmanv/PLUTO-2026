"""Quantized pose backend for Pluto wave detection.

This uses MoveNet SinglePose Lightning INT8 through TensorFlow Lite / LiteRT.
The desktop prototype used MediaPipe Pose Landmarker. On the Raspberry Pi image
currently used by Pluto, Python 3.13 blocks MediaPipe wheels, so MoveNet gives
the same useful evidence for waving: shoulder and wrist keypoints.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MOVENET_KEYPOINTS = {
    "nose": 0,
    "left_eye": 1,
    "right_eye": 2,
    "left_ear": 3,
    "right_ear": 4,
    "left_shoulder": 5,
    "right_shoulder": 6,
    "left_elbow": 7,
    "right_elbow": 8,
    "left_wrist": 9,
    "right_wrist": 10,
    "left_hip": 11,
    "right_hip": 12,
    "left_knee": 13,
    "right_knee": 14,
    "left_ankle": 15,
    "right_ankle": 16,
}


@dataclass
class PoseBackendStatus:
    status: str = "not_loaded"
    model_path: str | None = None
    input_size: int = 192
    max_tracks: int = 2
    frame_skip: int = 1
    inference_ms: float = 0.0
    inference_fps: float = 0.0
    last_keypoints: int = 0
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class MovenetPoseEstimator:
    """Small pose estimator for cropped person boxes."""

    def __init__(self, model_path: str, num_threads: int = 2) -> None:
        self.model_path = model_path
        self.num_threads = num_threads
        self.interpreter = None
        self.input_details = None
        self.output_details = None
        self.input_size = 192
        self.status = "not_loaded"
        self.error: str | None = None
        self.inference_times: list[float] = []
        self.last_keypoints = 0

    def load(self) -> bool:
        if not Path(self.model_path).exists():
            self.status = "unavailable"
            self.error = f"pose model missing: {self.model_path}"
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
            self.status = "unavailable"
            self.error = "No LiteRT/TFLite runtime found for pose model"
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
            self.status = "error"
            self.error = f"pose model load failed: {exc}"
            return False

    def estimate(self, frame, bbox: list[int] | list[float], pad_ratio: float = 0.35) -> dict[str, Any] | None:
        """Return shoulder/elbow/wrist keypoints in full-frame pixel coords.

        `frame` is expected to be RGB because Pluto's camera service stores RGB
        frames. Returned values are `[x, y, confidence]` lists so they can be
        serialized directly into the website status JSON.
        """
        if self.interpreter is None or self.input_details is None or self.output_details is None:
            return None

        import cv2  # type: ignore
        import numpy as np

        h, w = frame.shape[:2]
        x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
        box_w = max(1.0, x2 - x1)
        box_h = max(1.0, y2 - y1)
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        side = max(box_w, box_h) * (1.0 + pad_ratio)
        crop_x1 = max(0, int(cx - side / 2.0))
        crop_y1 = max(0, int(cy - side / 2.0))
        crop_x2 = min(w, int(cx + side / 2.0))
        crop_y2 = min(h, int(cy + side / 2.0))
        if crop_x2 - crop_x1 < 32 or crop_y2 - crop_y1 < 32:
            return None

        crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
        resized = cv2.resize(crop, (self.input_size, self.input_size), interpolation=cv2.INTER_LINEAR)
        input_tensor = self._prepare_input(resized, np)

        start = time.monotonic()
        try:
            self.interpreter.set_tensor(self.input_details["index"], input_tensor)
            self.interpreter.invoke()
            raw = self.interpreter.get_tensor(self.output_details["index"])
        except Exception as exc:
            self.status = "error"
            self.error = f"pose inference failed: {exc}"
            return None

        self.inference_times.append(time.monotonic() - start)
        if len(self.inference_times) > 30:
            self.inference_times = self.inference_times[-30:]

        keypoints = self._decode_output(raw, np)
        if keypoints is None or len(keypoints) < 17:
            self.last_keypoints = 0
            return None

        crop_w = max(1, crop_x2 - crop_x1)
        crop_h = max(1, crop_y2 - crop_y1)

        def point(name: str) -> list[float]:
            y_norm, x_norm, score = keypoints[MOVENET_KEYPOINTS[name]]
            return [
                float(crop_x1 + x_norm * crop_w),
                float(crop_y1 + y_norm * crop_h),
                float(score),
            ]

        result = {
            "left_shoulder": point("left_shoulder"),
            "right_shoulder": point("right_shoulder"),
            "left_elbow": point("left_elbow"),
            "right_elbow": point("right_elbow"),
            "left_wrist": point("left_wrist"),
            "right_wrist": point("right_wrist"),
        }
        self.last_keypoints = sum(1 for item in result.values() if item[2] >= 0.20)
        return result

    def _prepare_input(self, resized, np):
        dtype = self.input_details["dtype"]
        data = resized
        if dtype == np.float32:
            data = data.astype(np.float32) / 255.0
        elif dtype == np.uint8:
            data = data.astype(np.uint8)
        elif dtype == np.int8:
            scale, zero_point = self.input_details.get("quantization", (0.0, 0))
            if scale and scale > 0:
                data = (data.astype(np.float32) / scale + zero_point).round()
            data = np.clip(data, -128, 127).astype(np.int8)
        else:
            data = data.astype(dtype)
        return np.expand_dims(data, axis=0)

    def _decode_output(self, raw, np):
        output = raw
        dtype = self.output_details["dtype"]
        if dtype != np.float32:
            scale, zero_point = self.output_details.get("quantization", (0.0, 0))
            if scale and scale > 0:
                output = (output.astype(np.float32) - zero_point) * scale
            else:
                output = output.astype(np.float32)
        output = np.asarray(output, dtype=np.float32).reshape(-1, 3)
        if output.shape[0] < 17:
            return None
        return output[:17]

    def average_inference_ms(self) -> float:
        if not self.inference_times:
            return 0.0
        return (sum(self.inference_times) / len(self.inference_times)) * 1000.0

    def inference_fps(self) -> float:
        avg = self.average_inference_ms()
        return 1000.0 / avg if avg > 0 else 0.0

    def status_dict(self, max_tracks: int = 2, frame_skip: int = 1) -> dict[str, Any]:
        return PoseBackendStatus(
            status=self.status,
            model_path=self.model_path,
            input_size=self.input_size,
            max_tracks=max_tracks,
            frame_skip=frame_skip,
            inference_ms=self.average_inference_ms(),
            inference_fps=self.inference_fps(),
            last_keypoints=self.last_keypoints,
            error=self.error,
            details={
                "backend": "movenet_singlepose_lightning_int8",
                "keypoints": "shoulders_elbows_wrists",
            },
        ).__dict__
