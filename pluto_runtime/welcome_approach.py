"""WELCOME_APPROACH dry-run planner for Pluto Phase 10.

The planner turns the locked wave target, camera quality, and STM32 obstacle
telemetry into a proposed approach command. Phase 10 intentionally keeps this
as a dry-run: callers may send STOP guards, but must not send DRIVE from this
module yet.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ApproachConfig:
    dry_run: bool = True
    max_forward_speed: int = 25
    max_turn: int = 20
    center_deadband_norm: float = 0.12
    turn_deadband_norm: float = 0.25
    target_lost_timeout_s: float = 2.0
    greeting_height_ratio_min: float = 0.32
    too_close_height_ratio_min: float = 0.55
    front_stop_cm: float = 60.0
    side_stop_cm: float = 50.0
    front_slow_cm: float = 80.0
    low_light_blocks_motion: bool = True


@dataclass
class ApproachStatus:
    phase: str = "phase_10_dry_run"
    enabled: bool = True
    dry_run: bool = True
    active: bool = False
    state: str = "UNKNOWN"
    substate: str = "UNKNOWN"
    target_id: int | None = None
    target_bbox: list[int] | None = None
    target_center_norm: float | None = None
    target_box_height_ratio: float | None = None
    target_distance_class: str = "unknown"
    steering_intent: str = "unknown"
    obstacle_status: str = "unknown"
    proposed_motion: str = "stop"
    proposed_speed: int = 0
    proposed_steer: int = 0
    reason: str = "not evaluated"
    vision_quality: str = "unknown"
    image_brightness: float | None = None
    image_contrast: float | None = None
    last_update_at: float = field(default_factory=time.time)
    stop_guard: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WelcomeApproachPlanner:
    def __init__(self, config: ApproachConfig | None = None) -> None:
        self.config = config or ApproachConfig()

    def compute(
        self,
        camera_status: dict[str, Any],
        stm32_runtime: dict[str, Any],
        wave_status: dict[str, Any],
        current_state: str,
        current_substate: str,
    ) -> ApproachStatus:
        status = ApproachStatus(
            dry_run=self.config.dry_run,
            active=current_state == "WELCOME",
            state=current_state,
            substate=current_substate,
            vision_quality=str(camera_status.get("vision_quality") or "unknown"),
            image_brightness=self._float_or_none(camera_status.get("image_brightness")),
            image_contrast=self._float_or_none(camera_status.get("image_contrast")),
        )

        if current_state != "WELCOME":
            status.reason = "not in WELCOME"
            return status
        if current_substate not in {"WELCOME_DETECT", "WELCOME_APPROACH", "WELCOME_APPROACH_DRY_RUN"}:
            status.active = False
            status.reason = f"{current_substate} is not an approach substate"
            return status

        target_id = self._locked_target_id(camera_status, wave_status)
        if target_id is None:
            status.reason = "no locked wave target"
            return status

        target = self._find_detection(camera_status, target_id)
        if target is None:
            status.target_id = target_id
            status.target_bbox = self._anchor_bbox(camera_status)
            status.reason = "locked target not visible"
            return status

        width, height = self._resolution(camera_status)
        bbox = [int(value) for value in target.get("bbox", [])[:4]]
        status.target_id = target_id
        status.target_bbox = bbox
        status.target_center_norm = self._center_norm(bbox, width)
        status.target_box_height_ratio = self._height_ratio(bbox, height)
        status.target_distance_class = self._distance_class(status.target_box_height_ratio)
        status.steering_intent = self._steering_intent(status.target_center_norm)

        if self._vision_blocks(camera_status):
            status.reason = "vision quality degraded"
            return status

        obstacle_status, obstacle_reason = self._obstacle_status(stm32_runtime)
        status.obstacle_status = obstacle_status
        if obstacle_status == "blocked":
            status.reason = obstacle_reason
            return status

        if status.target_distance_class == "too_close":
            status.reason = "target too close"
            return status
        if status.target_distance_class == "good":
            status.reason = "greeting distance reached"
            return status

        speed = self.config.max_forward_speed
        if obstacle_status == "slow":
            speed = max(8, speed // 2)

        steer = self._steer_value(status.target_center_norm)
        if status.steering_intent == "center":
            motion = "forward"
        elif status.steering_intent == "left":
            motion = "turn_left"
        elif status.steering_intent == "right":
            motion = "turn_right"
        else:
            motion = "stop"
            speed = 0
            steer = 0

        status.proposed_motion = motion
        status.proposed_speed = int(speed)
        status.proposed_steer = int(steer)
        status.reason = "dry-run proposal only" if self.config.dry_run else "approach command ready"
        return status

    def _locked_target_id(self, camera_status: dict[str, Any], wave_status: dict[str, Any]) -> int | None:
        details = camera_status.get("details") if isinstance(camera_status.get("details"), dict) else {}
        candidates = [
            details.get("wave_locked_track_id"),
            (wave_status.get("detector") or {}).get("track_id") if isinstance(wave_status.get("detector"), dict) else None,
            (wave_status.get("last_event") or {}).get("track_id") if isinstance(wave_status.get("last_event"), dict) else None,
        ]
        for candidate in candidates:
            try:
                if candidate is not None:
                    return int(candidate)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _anchor_bbox(camera_status: dict[str, Any]) -> list[int] | None:
        details = camera_status.get("details") if isinstance(camera_status.get("details"), dict) else {}
        bbox = details.get("wave_lock_anchor_bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            return [int(value) for value in bbox[:4]]
        return None

    @staticmethod
    def _find_detection(camera_status: dict[str, Any], target_id: int) -> dict[str, Any] | None:
        for detection in camera_status.get("detections") or []:
            if not isinstance(detection, dict):
                continue
            try:
                det_id = int(detection.get("track_id"))
            except (TypeError, ValueError):
                continue
            if det_id == target_id:
                return detection
        return None

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
    def _center_norm(bbox: list[int], width: float) -> float:
        center_x = (float(bbox[0]) + float(bbox[2])) / 2.0
        return max(-1.0, min(1.0, (center_x - width / 2.0) / (width / 2.0)))

    @staticmethod
    def _height_ratio(bbox: list[int], height: float) -> float:
        return max(0.0, min(1.0, (float(bbox[3]) - float(bbox[1])) / height))

    def _distance_class(self, height_ratio: float | None) -> str:
        if height_ratio is None:
            return "unknown"
        if height_ratio >= self.config.too_close_height_ratio_min:
            return "too_close"
        if height_ratio >= self.config.greeting_height_ratio_min:
            return "good"
        return "far"

    def _steering_intent(self, center_norm: float | None) -> str:
        if center_norm is None:
            return "unknown"
        if abs(center_norm) <= self.config.center_deadband_norm:
            return "center"
        if center_norm < -self.config.turn_deadband_norm:
            return "left"
        if center_norm > self.config.turn_deadband_norm:
            return "right"
        return "center"

    def _steer_value(self, center_norm: float | None) -> int:
        if center_norm is None:
            return 0
        if abs(center_norm) <= self.config.center_deadband_norm:
            return 0
        return int(max(-self.config.max_turn, min(self.config.max_turn, center_norm * self.config.max_turn)))

    def _vision_blocks(self, camera_status: dict[str, Any]) -> bool:
        if not self.config.low_light_blocks_motion:
            return False
        quality = str(camera_status.get("vision_quality") or "").lower()
        return quality in {"low_light", "degraded", "unavailable"}

    def _obstacle_status(self, stm32_runtime: dict[str, Any]) -> tuple[str, str]:
        obstacles = stm32_runtime.get("obstacles") if isinstance(stm32_runtime.get("obstacles"), dict) else {}
        if not obstacles:
            return "unknown", "no STM32 obstacle telemetry"

        front = self._float_or_none(obstacles.get("F"))
        front_left = self._float_or_none(obstacles.get("FL"))
        front_right = self._float_or_none(obstacles.get("FR"))

        blocked_items: list[str] = []
        if front is not None and front < self.config.front_stop_cm:
            blocked_items.append(f"F {front:.0f}cm")
        if front_left is not None and front_left < self.config.side_stop_cm:
            blocked_items.append(f"FL {front_left:.0f}cm")
        if front_right is not None and front_right < self.config.side_stop_cm:
            blocked_items.append(f"FR {front_right:.0f}cm")
        if blocked_items:
            return "blocked", "obstacle blocked: " + ", ".join(blocked_items)

        slow_items: list[str] = []
        for key, value in (("F", front), ("FL", front_left), ("FR", front_right)):
            if value is not None and value < self.config.front_slow_cm:
                slow_items.append(f"{key} {value:.0f}cm")
        if slow_items:
            return "slow", "obstacle slow zone: " + ", ".join(slow_items)
        return "clear", "obstacle path clear"

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
