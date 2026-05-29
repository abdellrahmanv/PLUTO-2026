"""Pi-friendly WELCOME wave detection using the PC prototype's rules.

The desktop prototype used YOLOv5 + SORT + MediaPipe pose. Pluto keeps the
parts that made it reliable but avoids the heavy stack on the Raspberry Pi:

1. Reuse the existing TFLite human boxes from the camera service.
2. Extract a cheap hand-motion candidate from the upper human crop.
3. Apply the same gates as the PC detector: raised region, horizontal
   amplitude, x direction changes, horizontal-dominates-vertical, confirmation
   streak, and cooldown.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class WaveSample:
    timestamp: float
    center_x: float
    width: float
    confidence: float
    motion_norm: float = 0.0
    motion_balance: float = 0.0
    hand_valid: bool = False
    hand_x_norm: float = 0.0
    hand_y_norm: float = 1.0
    raised_region: bool = False


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
    algorithm: str = "pc_rule_lite"
    target_id: str | None = None
    cooldown_remaining_s: float = 0.0
    last_confirmed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SimpleWaveDetector:
    """Detect deliberate waving with the PC prototype gates, minus pose model."""

    def __init__(
        self,
        window_s: float = 1.8,
        min_samples: int = 5,
        min_direction_changes: int = 2,
        min_amplitude_norm: float = 0.045,
        min_width_change_norm: float = 0.065,
        min_motion_norm: float = 0.010,
        min_motion_direction_changes: int = 2,
        hand_amp_thresh: float = 0.10,
        hand_dxdy_ratio: float = 1.05,
        confirm_k: int = 2,
        min_confidence: float = 0.30,
        cooldown_s: float = 4.0,
    ) -> None:
        self.window_s = window_s
        self.min_samples = min_samples
        self.min_direction_changes = min_direction_changes
        self.min_amplitude_norm = min_amplitude_norm
        self.min_width_change_norm = min_width_change_norm
        self.min_motion_norm = min_motion_norm
        self.min_motion_direction_changes = min_motion_direction_changes
        self.hand_amp_thresh = hand_amp_thresh
        self.hand_dxdy_ratio = hand_dxdy_ratio
        self.confirm_k = confirm_k
        self.min_confidence = min_confidence
        self.cooldown_s = cooldown_s
        self.samples: deque[WaveSample] = deque(maxlen=48)
        self.confirm_streak = 0
        self.last_confirmed_at: float | None = None
        self.status = WaveStatus()

    def update(self, camera_status: dict[str, Any], now: float | None = None) -> WaveStatus:
        now = time.monotonic() if now is None else now
        detections = camera_status.get("detections") or []
        resolution = camera_status.get("resolution") or camera_status.get("configured_resolution") or [320, 320]
        frame_width = max(float(resolution[0] or 320), 1.0)

        target = self._select_target(detections)
        if target is None:
            self.samples.clear()
            self.confirm_streak = 0
            self.status = WaveStatus(
                available=bool(camera_status.get("available", False)),
                confirmed=False,
                reason="no_person",
                cooldown_remaining_s=self._cooldown_remaining(now),
                last_confirmed_at=self.last_confirmed_at,
            )
            return self.status

        bbox = target.get("bbox") or [0, 0, 0, 0]
        x1, _y1, x2, _y2 = [float(value) for value in bbox]
        confidence = float(target.get("confidence") or 0.0)
        motion = camera_status.get("wave_motion") or {}
        hand_y = motion.get("hand_y_norm")
        sample = WaveSample(
            timestamp=now,
            center_x=(x1 + x2) / 2.0,
            width=max(1.0, x2 - x1),
            confidence=confidence,
            motion_norm=float(motion.get("motion_norm") or 0.0),
            motion_balance=float(motion.get("balance") or 0.0),
            hand_valid=bool(motion.get("hand_valid", False)),
            hand_x_norm=float(motion.get("hand_x_norm") or 0.0),
            hand_y_norm=float(hand_y if hand_y is not None else 1.0),
            raised_region=bool(motion.get("raised_region", False)),
        )
        self.samples.append(sample)
        self._trim(now)

        status = self._evaluate(frame_width, now)
        if status.confirmed:
            self.last_confirmed_at = now
            status.last_confirmed_at = now
        self.status = status
        return status

    def _select_target(self, detections: list[Any]) -> dict[str, Any] | None:
        dicts = [item for item in detections if isinstance(item, dict) and item.get("bbox")]
        if not dicts:
            return None
        return max(dicts, key=lambda item: box_area(item.get("bbox") or [0, 0, 0, 0]))

    def _trim(self, now: float) -> None:
        while self.samples and now - self.samples[0].timestamp > self.window_s:
            self.samples.popleft()

    def _evaluate(self, frame_width: float, now: float) -> WaveStatus:
        cooldown = self._cooldown_remaining(now)
        if cooldown > 0:
            return self._status(True, "cooldown_active", frame_width, now, cooldown, score=1.0)

        if len(self.samples) < self.min_samples:
            return self._status(False, "not_enough_samples", frame_width, now, cooldown)

        confidence = sum(item.confidence for item in self.samples) / max(len(self.samples), 1)
        if confidence < self.min_confidence:
            return self._status(False, "low_confidence", frame_width, now, cooldown)

        metrics = self._metrics(frame_width)
        hand_gate = (
            metrics["raised"]
            and metrics["hand_amp"] >= self.hand_amp_thresh
            and metrics["hand_sign_changes"] >= self.min_direction_changes
            and metrics["hand_dx_dy"] >= self.hand_dxdy_ratio
            and metrics["motion_norm"] >= self.min_motion_norm
        )
        if hand_gate:
            self.confirm_streak += 2
        else:
            self.confirm_streak = max(0, self.confirm_streak - 1)

        pc_rule_wave = self.confirm_streak >= self.confirm_k
        box_wave = metrics["direction_changes"] >= self.min_direction_changes and (
            metrics["amplitude_norm"] >= self.min_amplitude_norm or metrics["width_change_norm"] >= self.min_width_change_norm
        )
        pixel_wave = (
            metrics["motion_direction_changes"] >= self.min_motion_direction_changes
            and metrics["motion_norm"] >= self.min_motion_norm
        )

        if not pc_rule_wave and not box_wave and not pixel_wave:
            if (
                metrics["motion_norm"] < self.min_motion_norm
                and metrics["amplitude_norm"] < self.min_amplitude_norm
                and metrics["width_change_norm"] < self.min_width_change_norm
            ):
                return self._status(False, "amplitude_too_low", frame_width, now, cooldown)
            return self._status(False, "not_enough_direction_changes", frame_width, now, cooldown)

        score = min(
            1.0,
            max(
                metrics["hand_amp"] / self.hand_amp_thresh,
                metrics["motion_norm"] / self.min_motion_norm,
                self.confirm_streak / self.confirm_k,
                metrics["amplitude_norm"] / self.min_amplitude_norm,
                metrics["width_change_norm"] / self.min_width_change_norm,
            )
            / 2.0,
        )
        return self._status(True, "confirmed_wave", frame_width, now, cooldown, score=score, frame_pass=hand_gate)

    def _status(
        self,
        confirmed: bool,
        reason: str,
        frame_width: float,
        now: float,
        cooldown: float,
        score: float = 0.0,
        frame_pass: bool = False,
    ) -> WaveStatus:
        metrics = self._metrics(frame_width)
        return WaveStatus(
            available=True,
            confirmed=confirmed,
            reason=reason,
            score=score,
            confidence=metrics["confidence"],
            side=metrics["side"],
            sample_count=len(self.samples),
            direction_changes=metrics["direction_changes"],
            amplitude_norm=metrics["amplitude_norm"],
            width_change_norm=metrics["width_change_norm"],
            motion_norm=metrics["motion_norm"],
            motion_direction_changes=metrics["motion_direction_changes"],
            hand_amp=metrics["hand_amp"],
            hand_sign_changes=metrics["hand_sign_changes"],
            hand_dx_dy=metrics["hand_dx_dy"],
            raised=metrics["raised"],
            frame_pass=frame_pass,
            confirm_streak=self.confirm_streak,
            target_id="human_0" if self.samples else None,
            cooldown_remaining_s=cooldown,
            last_confirmed_at=self.last_confirmed_at,
        )

    def _metrics(self, frame_width: float) -> dict[str, Any]:
        samples = list(self.samples)
        if not samples:
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
            }

        direction_changes = count_direction_changes([item.center_x for item in samples])
        amplitude_norm = (max(item.center_x for item in samples) - min(item.center_x for item in samples)) / frame_width
        width_change_norm = (max(item.width for item in samples) - min(item.width for item in samples)) / frame_width
        motion_norm = sum(item.motion_norm for item in samples) / len(samples)
        motion_direction_changes = count_direction_changes([item.motion_balance for item in samples], deadband=0.18)
        confidence = sum(item.confidence for item in samples) / len(samples)
        side = "right" if samples[-1].center_x >= samples[0].center_x else "left"

        hand_amp = 0.0
        hand_sign_changes = 0
        hand_dx_dy = 0.0
        raised = False
        hand_samples = [item for item in samples if item.hand_valid]
        if hand_samples:
            xs = [item.hand_x_norm for item in hand_samples]
            ys = [item.hand_y_norm for item in hand_samples]
            hand_amp = max(xs) - min(xs)
            hand_sign_changes = count_direction_changes(xs, deadband=0.03)
            dx = sum(abs(right - left) for left, right in zip(xs, xs[1:]))
            dy = sum(abs(right - left) for left, right in zip(ys, ys[1:]))
            hand_dx_dy = dx / (dy + 1e-6)
            raised = sum(1 for item in hand_samples if item.raised_region) / len(hand_samples) >= 0.55
            side = "right" if hand_samples[-1].hand_x_norm >= 0 else "left"

        return {
            "direction_changes": direction_changes,
            "amplitude_norm": amplitude_norm,
            "width_change_norm": width_change_norm,
            "motion_norm": motion_norm,
            "motion_direction_changes": motion_direction_changes,
            "hand_amp": hand_amp,
            "hand_sign_changes": hand_sign_changes,
            "hand_dx_dy": hand_dx_dy,
            "raised": raised,
            "confidence": confidence,
            "side": side,
        }

    def _cooldown_remaining(self, now: float) -> float:
        if self.last_confirmed_at is None:
            return 0.0
        return max(0.0, self.cooldown_s - (now - self.last_confirmed_at))

    def status_dict(self) -> dict[str, Any]:
        return self.status.to_dict()


def box_area(bbox: list[Any]) -> float:
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox]
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)
    except Exception:
        return 0.0


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
