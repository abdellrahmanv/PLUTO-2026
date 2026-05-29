"""WELCOME wave detector using tracked pose keypoints.

The desktop reference pipeline is:

YOLO person boxes -> SORT track IDs -> MediaPipe pose -> wrist/shoulder wave
rules.

Pluto keeps the same engineering shape but swaps the heavy pieces:

- Existing TFLite YOLO boxes provide the people.
- CameraService assigns lightweight track IDs.
- MoveNet Lightning INT8 provides shoulder/wrist keypoints.
- This module applies the desktop wave gates per track:
  raised wrist, horizontal amplitude, x direction changes,
  horizontal-dominates-vertical, confirmation streak, cooldown.

Optical-flow evidence is still surfaced by the camera for debugging, but broad
pixel motion is not allowed to confirm a wave by default.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class WaveSample:
    timestamp: float
    frame_key: Any
    track_id: int
    center_x: float
    width: float
    confidence: float


@dataclass
class WaveStatus:
    available: bool = True
    confirmed: bool = False
    reason: str = "not_enough_samples"
    score: float = 0.0
    confidence: float = 0.0
    side: str = "unknown"
    sample_count: int = 0
    direction_changes: int = 0
    amplitude_norm: float = 0.0
    width_change_norm: float = 0.0
    motion_norm: float = 0.0
    motion_direction_changes: int = 0
    hand_amp: float = 0.0
    hand_sign_changes: int = 0
    hand_dx_dy: float = 0.0
    raised: bool = False
    frame_pass: bool = False
    confirm_streak: int = 0
    algorithm: str = "tracked_pose_wave"
    track_id: int | None = None
    target_id: str | None = None
    visible_track_ids: list[int] | None = None
    locked_track_id: int | None = None
    cooldown_remaining_s: float = 0.0
    last_confirmed_at: float | None = None
    pose_available: bool = False
    pose_ready: bool = False
    pose_score: float = 0.0
    pose_backend: str = "unknown"
    thresholds: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SimpleWaveDetector:
    """Detect deliberate waving per tracked person."""

    def __init__(
        self,
        window_s: float = 1.8,
        min_samples: int = 5,
        pose_amp_thresh: float = 0.14,
        pose_sign_changes_min: int = 2,
        pose_dxdy_ratio: float = 1.10,
        pose_min_confidence: float = 0.20,
        confirm_k: int = 2,
        min_confidence: float = 0.30,
        cooldown_s: float = 4.0,
        allow_flow_fallback: bool = False,
    ) -> None:
        self.window_s = window_s
        self.min_samples = min_samples
        self.pose_amp_thresh = pose_amp_thresh
        self.pose_sign_changes_min = pose_sign_changes_min
        self.pose_dxdy_ratio = pose_dxdy_ratio
        self.pose_min_confidence = pose_min_confidence
        self.confirm_k = confirm_k
        self.min_confidence = min_confidence
        self.cooldown_s = cooldown_s
        self.allow_flow_fallback = allow_flow_fallback

        self.samples: dict[int, deque[WaveSample]] = defaultdict(lambda: deque(maxlen=48))
        self.pose_buffers_left: dict[int, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=48))
        self.pose_buffers_right: dict[int, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=48))
        self.pose_debug: dict[int, dict[str, Any]] = {}
        self.confirm_streak: dict[int, int] = defaultdict(int)
        self.last_confirmed_at: dict[int, float] = {}
        self.last_frame_key: dict[int, Any] = {}
        self.locked_track_id: int | None = None
        self.status = WaveStatus()

    def thresholds(self) -> dict[str, Any]:
        return {
            "source": "desktop_wave_detection_reference",
            "min_samples": self.min_samples,
            "window_s": self.window_s,
            "wrist_above_shoulder": True,
            "hand_amp_min_shoulder_widths": self.pose_amp_thresh,
            "direction_changes_min": self.pose_sign_changes_min,
            "horizontal_vertical_ratio_min": self.pose_dxdy_ratio,
            "keypoint_confidence_min": self.pose_min_confidence,
            "confirm_streak_min": self.confirm_k,
            "cooldown_s": self.cooldown_s,
            "sampling": "background_camera_frames",
        }

    def update(self, camera_status: dict[str, Any], now: float | None = None) -> WaveStatus:
        now = time.monotonic() if now is None else now
        detections = [item for item in (camera_status.get("detections") or []) if isinstance(item, dict) and item.get("bbox")]
        resolution = camera_status.get("resolution") or camera_status.get("configured_resolution") or [320, 320]
        frame_width = max(float(resolution[0] or 320), 1.0)
        camera_available = bool(camera_status.get("available", False))

        if not detections:
            self._cleanup(set())
            self.status = WaveStatus(
                available=camera_available,
                confirmed=False,
                reason="no_person",
                visible_track_ids=[],
                locked_track_id=self.locked_track_id,
                last_confirmed_at=self._latest_confirmed_at(),
                pose_backend=self._pose_backend(camera_status),
                thresholds=self.thresholds(),
            )
            return self.status

        wave_motion = camera_status.get("wave_motion") or {}
        candidates = wave_motion.get("candidates") if isinstance(wave_motion, dict) else None
        candidate_by_track = {
            int(item.get("track_id") or 0): item
            for item in (candidates or [])
            if isinstance(item, dict)
        }

        active_ids: set[int] = set()
        frame_key = wave_motion.get("frame_index") or wave_motion.get("timestamp") or now
        for index, detection in enumerate(detections):
            track_id = int(detection.get("track_id") or index + 1)
            active_ids.add(track_id)
            bbox = detection.get("bbox") or [0, 0, 0, 0]
            x1, _y1, x2, _y2 = [float(value) for value in bbox]
            motion = candidate_by_track.get(track_id, {})
            source_key = motion.get("frame_index") or frame_key
            if self.last_frame_key.get(track_id) == source_key:
                self._trim(track_id, now)
                continue

            pose_keypoints = motion.get("pose_keypoints") if isinstance(motion, dict) else None
            if pose_keypoints:
                self._update_pose_buffers(track_id, pose_keypoints)

            self.last_frame_key[track_id] = source_key
            self.samples[track_id].append(
                WaveSample(
                    timestamp=now,
                    frame_key=source_key,
                    track_id=track_id,
                    center_x=(x1 + x2) / 2.0,
                    width=max(1.0, x2 - x1),
                    confidence=float(detection.get("confidence") or motion.get("confidence") or 0.0),
                )
            )
            self._trim(track_id, now)

        self._cleanup(active_ids)
        statuses = [self._evaluate_track(track_id, frame_width, now, camera_status) for track_id in sorted(active_ids)]
        confirmed = [item for item in statuses if item.confirmed]
        if confirmed:
            status = max(confirmed, key=lambda item: (item.reason == "confirmed_wave", item.score, item.sample_count))
            self.locked_track_id = status.track_id
        else:
            status = max(statuses, key=lambda item: (item.score, item.sample_count), default=WaveStatus(available=camera_available))

        status.available = camera_available
        status.visible_track_ids = sorted(active_ids)
        status.locked_track_id = self.locked_track_id
        status.pose_backend = self._pose_backend(camera_status)
        status.thresholds = self.thresholds()
        self.status = status
        return status

    def reset(self) -> None:
        self.samples.clear()
        self.pose_buffers_left.clear()
        self.pose_buffers_right.clear()
        self.pose_debug.clear()
        self.confirm_streak.clear()
        self.last_confirmed_at.clear()
        self.last_frame_key.clear()
        self.locked_track_id = None
        self.status = WaveStatus(reason="reset")

    def _update_pose_buffers(self, track_id: int, keypoints: dict[str, Any]) -> None:
        ls = as_point(keypoints.get("left_shoulder"))
        rs = as_point(keypoints.get("right_shoulder"))
        lw = as_point(keypoints.get("left_wrist"))
        rw = as_point(keypoints.get("right_wrist"))
        if not ls or not rs:
            self.pose_debug[track_id] = {"pose_available": False, "reason": "missing_shoulders"}
            return

        scx = (ls[0] + rs[0]) / 2.0
        scy = (ls[1] + rs[1]) / 2.0
        shoulder_w = abs(ls[0] - rs[0]) + 1e-6

        best: dict[str, Any] = {
            "pose_available": True,
            "pose_ready": False,
            "reason": "pose_not_enough_samples",
            "pose_score": min(ls[2], rs[2]),
            "side": "unknown",
            "raised": False,
            "amp": 0.0,
            "sign_changes": 0,
            "dx_dy": 0.0,
            "score": 0.0,
            "frame_pass": False,
        }

        for side, wrist, buffer in (
            ("left", lw, self.pose_buffers_left[track_id]),
            ("right", rw, self.pose_buffers_right[track_id]),
        ):
            if not wrist:
                continue
            kp_score = min(ls[2], rs[2], wrist[2])
            if kp_score < self.pose_min_confidence:
                if kp_score > best["pose_score"]:
                    best.update({"reason": "pose_low_confidence", "pose_score": kp_score, "side": side})
                continue

            x_norm = (wrist[0] - scx) / shoulder_w
            y_norm = (wrist[1] - scy) / shoulder_w
            buffer.append((x_norm, y_norm))

            if len(buffer) < self.min_samples:
                if kp_score >= best["pose_score"]:
                    best.update({"reason": "pose_not_enough_samples", "pose_score": kp_score, "side": side})
                continue

            xs = [item[0] for item in buffer]
            ys = [item[1] for item in buffer]
            raised = wrist[1] < scy
            amp = max(xs) - min(xs)
            sign_changes = count_direction_changes(xs, deadband=0.03)
            dx = sum(abs(right - left) for left, right in zip(xs, xs[1:]))
            dy = sum(abs(right - left) for left, right in zip(ys, ys[1:]))
            dx_dy = dx / (dy + 1e-6)
            gates = [
                raised,
                amp >= self.pose_amp_thresh,
                sign_changes >= self.pose_sign_changes_min,
                dx_dy >= self.pose_dxdy_ratio,
            ]
            score = sum(1 for item in gates if item) / len(gates)
            frame_pass = all(gates)
            if score >= best["score"]:
                best = {
                    "pose_available": True,
                    "pose_ready": True,
                    "reason": "pose_frame_pass" if frame_pass else "pose_gates_incomplete",
                    "pose_score": kp_score,
                    "side": side,
                    "raised": raised,
                    "amp": amp,
                    "sign_changes": sign_changes,
                    "dx_dy": dx_dy,
                    "score": score,
                    "frame_pass": frame_pass,
                }

        self.pose_debug[track_id] = best

    def _evaluate_track(self, track_id: int, frame_width: float, now: float, camera_status: dict[str, Any]) -> WaveStatus:
        cooldown = self._cooldown_remaining(track_id, now)
        if cooldown > 0:
            return self._status(track_id, True, "cooldown_active", frame_width, now, cooldown, camera_status, score=1.0)

        samples = list(self.samples.get(track_id, []))
        if len(samples) < self.min_samples:
            return self._status(track_id, False, "not_enough_samples", frame_width, now, cooldown, camera_status)

        confidence = sum(item.confidence for item in samples) / max(len(samples), 1)
        if confidence < self.min_confidence:
            return self._status(track_id, False, "low_confidence", frame_width, now, cooldown, camera_status)

        metrics = self._metrics(track_id, frame_width)
        if metrics["pose_available"]:
            frame_pass = bool(metrics["pose_ready"] and metrics["frame_pass"])
            if frame_pass:
                self.confirm_streak[track_id] += 2
            else:
                self.confirm_streak[track_id] = max(0, self.confirm_streak[track_id] - 1)

            if self.confirm_streak[track_id] < self.confirm_k:
                reason = self._pose_reject_reason(metrics)
                return self._status(track_id, False, reason, frame_width, now, cooldown, camera_status, frame_pass=frame_pass)

            score = min(1.0, max(metrics["score"], self.confirm_streak[track_id] / self.confirm_k / 2.0))
            self.last_confirmed_at[track_id] = now
            return self._status(track_id, True, "confirmed_wave", frame_width, now, cooldown, camera_status, score=score, frame_pass=frame_pass)

        self.confirm_streak[track_id] = max(0, self.confirm_streak[track_id] - 1)
        if not self.allow_flow_fallback:
            return self._status(track_id, False, "pose_unavailable", frame_width, now, cooldown, camera_status)
        return self._status(track_id, False, "flow_fallback_disabled_for_safety", frame_width, now, cooldown, camera_status)

    def _pose_reject_reason(self, metrics: dict[str, Any]) -> str:
        if not metrics["pose_ready"]:
            return "pose_not_enough_samples"
        if not metrics["raised"]:
            return "hand_not_raised"
        if metrics["hand_amp"] < self.pose_amp_thresh:
            return "hand_amplitude_too_low"
        if metrics["hand_sign_changes"] < self.pose_sign_changes_min:
            return "not_enough_direction_changes"
        if metrics["hand_dx_dy"] < self.pose_dxdy_ratio:
            return "horizontal_not_dominant"
        return "not_confirmed_yet"

    def _status(
        self,
        track_id: int,
        confirmed: bool,
        reason: str,
        frame_width: float,
        now: float,
        cooldown: float,
        camera_status: dict[str, Any],
        score: float = 0.0,
        frame_pass: bool = False,
    ) -> WaveStatus:
        metrics = self._metrics(track_id, frame_width)
        samples = self.samples.get(track_id, [])
        return WaveStatus(
            available=True,
            confirmed=confirmed,
            reason=reason,
            score=score,
            confidence=metrics["confidence"],
            side=metrics["side"],
            sample_count=len(samples),
            direction_changes=metrics["direction_changes"],
            amplitude_norm=metrics["amplitude_norm"],
            width_change_norm=metrics["width_change_norm"],
            motion_norm=metrics["motion_norm"],
            motion_direction_changes=metrics["motion_direction_changes"],
            hand_amp=metrics["hand_amp"],
            hand_sign_changes=metrics["hand_sign_changes"],
            hand_dx_dy=metrics["hand_dx_dy"],
            raised=metrics["raised"],
            frame_pass=frame_pass or metrics["frame_pass"],
            confirm_streak=self.confirm_streak.get(track_id, 0),
            track_id=track_id,
            target_id=f"track_{track_id}",
            cooldown_remaining_s=cooldown,
            last_confirmed_at=self.last_confirmed_at.get(track_id),
            pose_available=metrics["pose_available"],
            pose_ready=metrics["pose_ready"],
            pose_score=metrics["pose_score"],
            pose_backend=self._pose_backend(camera_status),
        )

    def _metrics(self, track_id: int, frame_width: float) -> dict[str, Any]:
        samples = list(self.samples.get(track_id, []))
        if not samples:
            return empty_metrics()

        direction_changes = count_direction_changes([item.center_x for item in samples])
        amplitude_norm = (max(item.center_x for item in samples) - min(item.center_x for item in samples)) / frame_width
        width_change_norm = (max(item.width for item in samples) - min(item.width for item in samples)) / frame_width
        confidence = sum(item.confidence for item in samples) / len(samples)
        side = "right" if samples[-1].center_x >= samples[0].center_x else "left"

        pose = self.pose_debug.get(track_id) or {}
        pose_available = bool(pose.get("pose_available"))
        pose_ready = bool(pose.get("pose_ready"))
        return {
            "direction_changes": direction_changes,
            "amplitude_norm": amplitude_norm,
            "width_change_norm": width_change_norm,
            "motion_norm": float(pose.get("score") or 0.0),
            "motion_direction_changes": int(pose.get("sign_changes") or 0),
            "hand_amp": float(pose.get("amp") or 0.0),
            "hand_sign_changes": int(pose.get("sign_changes") or 0),
            "hand_dx_dy": float(pose.get("dx_dy") or 0.0),
            "raised": bool(pose.get("raised", False)),
            "confidence": confidence,
            "side": str(pose.get("side") or side),
            "pose_available": pose_available,
            "pose_ready": pose_ready,
            "pose_score": float(pose.get("pose_score") or 0.0),
            "score": float(pose.get("score") or 0.0),
            "frame_pass": bool(pose.get("frame_pass", False)),
        }

    def _trim(self, track_id: int, now: float) -> None:
        samples = self.samples.get(track_id)
        if samples is not None:
            while samples and now - samples[0].timestamp > self.window_s:
                samples.popleft()
        for buffer in (self.pose_buffers_left.get(track_id), self.pose_buffers_right.get(track_id)):
            if buffer is None:
                continue
            while len(buffer) > 48:
                buffer.popleft()

    def _cleanup(self, active_ids: set[int]) -> None:
        all_ids = (
            set(self.samples.keys())
            | set(self.pose_buffers_left.keys())
            | set(self.pose_buffers_right.keys())
            | set(self.confirm_streak.keys())
            | set(self.last_confirmed_at.keys())
            | set(self.last_frame_key.keys())
            | set(self.pose_debug.keys())
        )
        for track_id in all_ids - active_ids:
            if track_id == self.locked_track_id:
                continue
            self.samples.pop(track_id, None)
            self.pose_buffers_left.pop(track_id, None)
            self.pose_buffers_right.pop(track_id, None)
            self.pose_debug.pop(track_id, None)
            self.confirm_streak.pop(track_id, None)
            self.last_confirmed_at.pop(track_id, None)
            self.last_frame_key.pop(track_id, None)

    def _cooldown_remaining(self, track_id: int, now: float) -> float:
        confirmed_at = self.last_confirmed_at.get(track_id)
        if confirmed_at is None:
            return 0.0
        return max(0.0, self.cooldown_s - (now - confirmed_at))

    def _latest_confirmed_at(self) -> float | None:
        if not self.last_confirmed_at:
            return None
        return max(self.last_confirmed_at.values())

    @staticmethod
    def _pose_backend(camera_status: dict[str, Any]) -> str:
        details = camera_status.get("details") or {}
        pose = details.get("pose") if isinstance(details, dict) else {}
        if isinstance(pose, dict):
            return str(pose.get("details", {}).get("backend") or pose.get("status") or "unknown")
        return str(camera_status.get("pose_status") or "unknown")

    def status_dict(self) -> dict[str, Any]:
        return self.status.to_dict()


def as_point(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        return float(value[0]), float(value[1]), float(value[2])
    except (TypeError, ValueError):
        return None


def empty_metrics() -> dict[str, Any]:
    return {
        "direction_changes": 0,
        "amplitude_norm": 0.0,
        "width_change_norm": 0.0,
        "motion_norm": 0.0,
        "motion_direction_changes": 0,
        "hand_amp": 0.0,
        "hand_sign_changes": 0,
        "hand_dx_dy": 0.0,
        "raised": False,
        "confidence": 0.0,
        "side": "unknown",
        "pose_available": False,
        "pose_ready": False,
        "pose_score": 0.0,
        "score": 0.0,
        "frame_pass": False,
    }


def count_direction_changes(values: list[float], deadband: float = 2.5) -> int:
    signs: list[int] = []
    for left, right in zip(values, values[1:]):
        delta = right - left
        if abs(delta) < deadband:
            continue
        signs.append(1 if delta > 0 else -1)
    changes = 0
    previous: int | None = None
    for sign in signs:
        if previous is not None and sign != previous:
            changes += 1
        previous = sign
    return changes
