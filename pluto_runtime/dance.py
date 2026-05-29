"""DANCE dry-run planner for Pluto.

The first DANCE implementation is intentionally evidence-only. It evaluates
audio readiness, STM32 obstacle telemetry, vision envelope safety, and the
bounded motion step that would be commanded later.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DanceConfig:
    dry_run: bool = True
    silent_dry_run_allowed: bool = True
    audio_file_path: str | None = None
    max_forward_speed: int = 12
    max_backward_speed: int = -12
    max_translation_cm: int = 40
    obstacle_stop_cm: float = 70.0
    obstacle_slow_cm: float = 100.0
    vision_stop_height_ratio: float = 0.65
    vision_slow_height_ratio: float = 0.45
    vertical_clip_margin_px: int = 3


@dataclass
class DanceStatus:
    phase: str = "dance_dry_run"
    enabled: bool = True
    dry_run: bool = True
    active: bool = False
    state: str = "UNKNOWN"
    substate: str = "UNKNOWN"
    elapsed_s: float = 0.0
    audio_status: str = "unknown"
    audio_file: str | None = None
    audio_file_present: bool = False
    speaker_available: bool = False
    obstacle_status: str = "unknown"
    vision_status: str = "unknown"
    vision_reason: str = "not evaluated"
    dance_step: str = "idle"
    proposed_motion: str = "stop"
    proposed_speed: int = 0
    proposed_steer: int = 0
    proposed_arm_motion: str = "disabled"
    max_translation_cm: int = 40
    reason: str = "not evaluated"
    stop_guard: dict[str, Any] = field(default_factory=dict)
    last_update_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DanceDryRunPlanner:
    def __init__(self, config: DanceConfig | None = None) -> None:
        audio_file = os.environ.get("PLUTO_DANCE_AUDIO")
        if config is None and audio_file:
            config = DanceConfig(audio_file_path=audio_file)
        self.config = config or DanceConfig()
        self.sequence = [
            ("pose", 0.8, "stop", 0, 0),
            ("moonwalk_back", 1.2, "glide_backward", self.config.max_backward_speed, 0),
            ("hold", 0.5, "stop", 0, 0),
            ("return_forward", 1.0, "glide_forward", self.config.max_forward_speed, 0),
            ("hold", 0.5, "stop", 0, 0),
            ("arm_sway_left", 0.8, "arm_sway", 0, 0),
            ("arm_sway_right", 0.8, "arm_sway", 0, 0),
        ]

    def compute(
        self,
        camera_status: dict[str, Any],
        stm32_runtime: dict[str, Any],
        audio_status: dict[str, Any],
        current_state: str,
        current_substate: str,
        dance_started_at: float | None,
    ) -> DanceStatus:
        now = time.time()
        elapsed = max(0.0, now - dance_started_at) if dance_started_at else 0.0
        status = DanceStatus(
            dry_run=self.config.dry_run,
            active=current_state == "DANCE",
            state=current_state,
            substate=current_substate,
            elapsed_s=elapsed,
            max_translation_cm=self.config.max_translation_cm,
        )
        status.audio_file = self.config.audio_file_path
        status.audio_file_present = self._audio_file_present()
        status.speaker_available = bool(audio_status.get("speaker_available"))
        status.audio_status = self._audio_status(status)

        if current_state != "DANCE":
            status.reason = "not in DANCE"
            return status

        obstacle_status, obstacle_reason = self._obstacle_status(stm32_runtime)
        status.obstacle_status = obstacle_status
        vision_status, vision_reason = self._vision_status(camera_status)
        status.vision_status = vision_status
        status.vision_reason = vision_reason

        if status.audio_status == "blocked":
            status.reason = "audio output unavailable"
            return status
        if obstacle_status in {"unknown", "blocked"}:
            status.reason = obstacle_reason
            return status
        if vision_status == "blocked":
            status.reason = vision_reason
            return status

        step_name, motion, speed, steer = self._sequence_step(elapsed)
        if obstacle_status == "slow" or vision_status == "slow":
            if speed != 0:
                speed = max(-6, min(6, int(speed / 2)))
            status.reason = "dry-run slowed by safety envelope"
        else:
            status.reason = "dry-run proposal only"

        status.dance_step = step_name
        status.proposed_motion = motion
        status.proposed_speed = int(speed)
        status.proposed_steer = int(steer)
        status.proposed_arm_motion = "disabled_until_arm_validated"
        return status

    def _audio_file_present(self) -> bool:
        if not self.config.audio_file_path:
            return False
        return Path(self.config.audio_file_path).exists()

    def _audio_status(self, status: DanceStatus) -> str:
        if status.speaker_available and status.audio_file_present:
            return "ready"
        if self.config.dry_run and self.config.silent_dry_run_allowed:
            return "silent_dry_run"
        return "blocked"

    def _sequence_step(self, elapsed_s: float) -> tuple[str, str, int, int]:
        total = sum(item[1] for item in self.sequence)
        cursor = elapsed_s % max(0.1, total)
        for step_name, duration, motion, speed, steer in self.sequence:
            if cursor <= duration:
                return step_name, motion, speed, steer
            cursor -= duration
        step_name, _, motion, speed, steer = self.sequence[-1]
        return step_name, motion, speed, steer

    def _obstacle_status(self, stm32_runtime: dict[str, Any]) -> tuple[str, str]:
        obstacles = stm32_runtime.get("obstacles") if isinstance(stm32_runtime.get("obstacles"), dict) else {}
        if not obstacles:
            return "unknown", "no STM32 obstacle telemetry"

        values = []
        for key in ("F", "FL", "FR"):
            value = self._float_or_none(obstacles.get(key))
            if value is not None:
                values.append((key, value))
        if not values:
            return "unknown", "no valid obstacle values"

        blocked = [f"{key} {value:.0f}cm" for key, value in values if value < self.config.obstacle_stop_cm]
        if blocked:
            return "blocked", "dance obstacle blocked: " + ", ".join(blocked)
        slowed = [f"{key} {value:.0f}cm" for key, value in values if value < self.config.obstacle_slow_cm]
        if slowed:
            return "slow", "dance obstacle slow zone: " + ", ".join(slowed)
        return "clear", "dance obstacle path clear"

    def _vision_status(self, camera_status: dict[str, Any]) -> tuple[str, str]:
        if not camera_status.get("available") or not camera_status.get("running"):
            return "unavailable", "vision unavailable; STM32 remains primary"
        quality = str(camera_status.get("vision_quality") or "").lower()
        if quality in {"low_light", "degraded"}:
            return "blocked", "vision quality degraded during DANCE"

        width, height = self._resolution(camera_status)
        worst_ratio = 0.0
        clipped = False
        for detection in camera_status.get("detections") or []:
            if not isinstance(detection, dict):
                continue
            bbox = detection.get("bbox")
            if not isinstance(bbox, list) or len(bbox) < 4:
                continue
            box = [int(value) for value in bbox[:4]]
            worst_ratio = max(worst_ratio, self._height_ratio(box, height))
            clipped = clipped or self._vertical_clipped(box, width, height)

        if clipped:
            return "blocked", "human box clipped in dance envelope"
        if worst_ratio >= self.config.vision_stop_height_ratio:
            return "blocked", f"human too near dance envelope h={worst_ratio:.2f}"
        if worst_ratio >= self.config.vision_slow_height_ratio:
            return "slow", f"human near dance envelope h={worst_ratio:.2f}"
        return "clear", "vision envelope clear"

    @staticmethod
    def _resolution(camera_status: dict[str, Any]) -> tuple[float, float]:
        resolution = camera_status.get("resolution") or camera_status.get("configured_resolution") or [320, 320]
        try:
            width = float(resolution[0])
            height = float(resolution[1])
        except (TypeError, ValueError, IndexError):
            width, height = 320.0, 320.0
        return max(1.0, width), max(1.0, height)

    @staticmethod
    def _height_ratio(bbox: list[int], height: float) -> float:
        return max(0.0, min(1.0, (float(bbox[3]) - float(bbox[1])) / height))

    def _vertical_clipped(self, bbox: list[int], width: float, height: float) -> bool:
        del width
        margin = float(self.config.vertical_clip_margin_px)
        return float(bbox[1]) <= margin or float(bbox[3]) >= height - 1.0 - margin

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
