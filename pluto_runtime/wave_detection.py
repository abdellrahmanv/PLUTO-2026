"""Lightweight WELCOME wave detection using existing human boxes.

This is intentionally simpler than the research prototype. It does not load
pose models or PyTorch. It watches the existing TFLite human box stream for a
short burst of lateral/width motion and produces a WELCOME trigger candidate.
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
    target_id: str | None = None
    cooldown_remaining_s: float = 0.0
    last_confirmed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SimpleWaveDetector:
    """Detect a deliberate wave-like motion from person bounding boxes."""

    def __init__(
        self,
        window_s: float = 2.4,
        min_samples: int = 6,
        min_direction_changes: int = 2,
        min_amplitude_norm: float = 0.045,
        min_width_change_norm: float = 0.065,
        min_confidence: float = 0.30,
        cooldown_s: float = 4.0,
    ) -> None:
        self.window_s = window_s
        self.min_samples = min_samples
        self.min_direction_changes = min_direction_changes
        self.min_amplitude_norm = min_amplitude_norm
        self.min_width_change_norm = min_width_change_norm
        self.min_confidence = min_confidence
        self.cooldown_s = cooldown_s
        self.samples: deque[WaveSample] = deque(maxlen=48)
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
        sample = WaveSample(timestamp=now, center_x=(x1 + x2) / 2.0, width=max(1.0, x2 - x1), confidence=confidence)
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
            return self._status(False, "cooldown_active", frame_width, now, cooldown)

        if len(self.samples) < self.min_samples:
            return self._status(False, "not_enough_samples", frame_width, now, cooldown)

        confidence = sum(item.confidence for item in self.samples) / max(len(self.samples), 1)
        if confidence < self.min_confidence:
            return self._status(False, "low_confidence", frame_width, now, cooldown)

        direction_changes = count_direction_changes([item.center_x for item in self.samples])
        amplitude_norm = (max(item.center_x for item in self.samples) - min(item.center_x for item in self.samples)) / frame_width
        width_change_norm = (max(item.width for item in self.samples) - min(item.width for item in self.samples)) / frame_width
        if direction_changes < self.min_direction_changes:
            return self._status(False, "not_enough_direction_changes", frame_width, now, cooldown)
        if amplitude_norm < self.min_amplitude_norm and width_change_norm < self.min_width_change_norm:
            return self._status(False, "amplitude_too_low", frame_width, now, cooldown)

        score = min(1.0, max(amplitude_norm / self.min_amplitude_norm, width_change_norm / self.min_width_change_norm) / 2.0)
        return self._status(True, "confirmed_wave", frame_width, now, cooldown, score=score)

    def _status(self, confirmed: bool, reason: str, frame_width: float, now: float, cooldown: float, score: float = 0.0) -> WaveStatus:
        samples = list(self.samples)
        direction_changes = count_direction_changes([item.center_x for item in samples])
        amplitude_norm = 0.0
        width_change_norm = 0.0
        confidence = 0.0
        side = "unknown"
        if samples:
            amplitude_norm = (max(item.center_x for item in samples) - min(item.center_x for item in samples)) / frame_width
            width_change_norm = (max(item.width for item in samples) - min(item.width for item in samples)) / frame_width
            confidence = sum(item.confidence for item in samples) / max(len(samples), 1)
            side = "right" if samples[-1].center_x >= samples[0].center_x else "left"
        return WaveStatus(
            available=True,
            confirmed=confirmed,
            reason=reason,
            score=score,
            confidence=confidence,
            side=side,
            sample_count=len(samples),
            direction_changes=direction_changes,
            amplitude_norm=amplitude_norm,
            width_change_norm=width_change_norm,
            target_id="human_0" if samples else None,
            cooldown_remaining_s=cooldown,
            last_confirmed_at=self.last_confirmed_at,
        )

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
