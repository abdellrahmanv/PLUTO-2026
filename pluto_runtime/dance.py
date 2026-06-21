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
    obstacle_telemetry_required: bool = False
    audio_file_path: str | None = None
    max_forward_speed: int = 12
    max_backward_speed: int = -12
    max_translation_cm: int = 60
    envelope_size_cm: int = 300
    vertical_clearance_cm: int = 300
    turn_steer: int = 24
    turn_duration_s: float = 2.2
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
    max_translation_cm: int = 60
    envelope_size_cm: int = 300
    vertical_clearance_cm: int = 300
    envelope_margin_cm: float | None = None
    odometry_status: str = "unknown"
    odometry_reason: str = "not evaluated"
    odometry_confidence: float = 0.0
    estimated_x_cm: float = 0.0
    estimated_y_cm: float = 0.0
    heading_deg: int = 0
    heading_quadrant: str = "north"
    segment_distance_cm: float = 0.0
    predicted_x_cm: float = 0.0
    predicted_y_cm: float = 0.0
    direction_safety: str = "unknown"
    stage_assumption: str = "operator_verified_empty_3m_stage"
    reason: str = "not evaluated"
    stop_guard: dict[str, Any] = field(default_factory=dict)
    last_update_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DanceDryRunPlanner:
    def __init__(self, config: DanceConfig | None = None) -> None:
        audio_file = os.environ.get("PLUTO_DANCE_AUDIO") or self._default_audio_file()
        if config is None and audio_file:
            config = DanceConfig(audio_file_path=audio_file)
        self.config = config or DanceConfig()
        self.sequence = [
            {"name": "pose_north", "duration": 0.8, "motion": "stop", "speed": 0, "steer": 0, "distance_cm": 0, "turn_deg": 0},
            {"name": "moonwalk_back_north", "duration": 1.4, "motion": "glide_backward", "speed": self.config.max_backward_speed, "steer": 0, "distance_cm": -self.config.max_translation_cm, "turn_deg": 0},
            {"name": "return_forward_north", "duration": 1.2, "motion": "glide_forward", "speed": self.config.max_forward_speed, "steer": 0, "distance_cm": int(self.config.max_translation_cm * 0.75), "turn_deg": 0},
            {"name": "turn_right_90", "duration": self.config.turn_duration_s, "motion": "turn_90_right", "speed": 0, "steer": self.config.turn_steer, "distance_cm": 0, "turn_deg": 90},
            {"name": "moonwalk_back_east", "duration": 1.4, "motion": "glide_backward", "speed": self.config.max_backward_speed, "steer": 0, "distance_cm": -self.config.max_translation_cm, "turn_deg": 0},
            {"name": "return_forward_east", "duration": 1.2, "motion": "glide_forward", "speed": self.config.max_forward_speed, "steer": 0, "distance_cm": int(self.config.max_translation_cm * 0.75), "turn_deg": 0},
            {"name": "turn_right_90", "duration": self.config.turn_duration_s, "motion": "turn_90_right", "speed": 0, "steer": self.config.turn_steer, "distance_cm": 0, "turn_deg": 90},
            {"name": "arm_sway_left", "duration": 0.8, "motion": "arm_sway", "speed": 0, "steer": 0, "distance_cm": 0, "turn_deg": 0},
            {"name": "arm_sway_right", "duration": 0.8, "motion": "arm_sway", "speed": 0, "steer": 0, "distance_cm": 0, "turn_deg": 0},
        ]

    @staticmethod
    def _default_audio_file() -> str | None:
        candidates = [
            r"C:\Users\Asus\Downloads\Michael_Jackson_-_Billie_Jean_This_is_it_2009_(mp3.pm).mp3",
            "/home/pi/PLUTO-2026/audio/Michael_Jackson_-_Billie_Jean_This_is_it_2009_(mp3.pm).mp3",
            "/home/pi/Downloads/Michael_Jackson_-_Billie_Jean_This_is_it_2009_(mp3.pm).mp3",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate
        return None

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
            envelope_size_cm=self.config.envelope_size_cm,
            vertical_clearance_cm=self.config.vertical_clearance_cm,
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

        odom = self._odometry_status(stm32_runtime, elapsed)
        status.odometry_status = odom["status"]
        status.odometry_reason = odom["reason"]
        status.odometry_confidence = odom["confidence"]
        status.estimated_x_cm = odom["x_cm"]
        status.estimated_y_cm = odom["y_cm"]
        status.heading_deg = odom["heading_deg"]
        status.heading_quadrant = self._heading_quadrant(status.heading_deg)

        segment = self._sequence_step(elapsed)
        step_name = str(segment["name"])
        motion = str(segment["motion"])
        speed = int(segment["speed"])
        steer = int(segment["steer"])
        segment_distance_cm = float(segment["distance_cm"])
        predicted_x, predicted_y, predicted_heading = self._predict_segment(
            status.estimated_x_cm,
            status.estimated_y_cm,
            status.heading_deg,
            segment_distance_cm,
            int(segment["turn_deg"]),
        )
        status.segment_distance_cm = segment_distance_cm
        status.predicted_x_cm = predicted_x
        status.predicted_y_cm = predicted_y
        status.heading_deg = predicted_heading if motion.startswith("turn_") else status.heading_deg
        status.heading_quadrant = self._heading_quadrant(status.heading_deg)
        status.envelope_margin_cm = self._envelope_margin(predicted_x, predicted_y)
        status.direction_safety = self._direction_safety(motion, speed, stm32_runtime)

        if status.envelope_margin_cm < 0:
            status.dance_step = step_name
            status.proposed_motion = "stop"
            status.proposed_speed = 0
            status.proposed_steer = 0
            status.proposed_arm_motion = "disabled_until_arm_validated"
            status.reason = "dance envelope boundary would be exceeded"
            return status

        if status.direction_safety == "blocked":
            status.dance_step = step_name
            status.proposed_motion = "stop"
            status.proposed_speed = 0
            status.proposed_steer = 0
            status.proposed_arm_motion = "disabled_until_arm_validated"
            status.reason = "obstacle blocks next dance movement direction"
            return status

        if obstacle_status == "slow" or vision_status == "slow":
            if speed != 0:
                speed = max(-6, min(6, int(speed / 2)))
            status.reason = "dry-run slowed by safety envelope"
        else:
            status.reason = "dry-run envelope proposal only"

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

    def _sequence_step(self, elapsed_s: float) -> dict[str, Any]:
        total = sum(float(item["duration"]) for item in self.sequence)
        cursor = elapsed_s % max(0.1, total)
        for item in self.sequence:
            duration = float(item["duration"])
            if cursor <= duration:
                return item
            cursor -= duration
        return self.sequence[-1]

    def _obstacle_status(self, stm32_runtime: dict[str, Any]) -> tuple[str, str]:
        if not self.config.obstacle_telemetry_required:
            return "ignored", "ultrasonic dance blocking disabled"
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

    def _odometry_status(self, stm32_runtime: dict[str, Any], elapsed_s: float) -> dict[str, Any]:
        telemetry = stm32_runtime.get("telemetry") if isinstance(stm32_runtime.get("telemetry"), dict) else {}
        x = self._first_float(telemetry, ("X", "POSX", "XCM", "ODOMX", "x_cm"))
        y = self._first_float(telemetry, ("Y", "POSY", "YCM", "ODOMY", "y_cm"))
        heading = self._first_float(telemetry, ("H", "HDG", "HEAD", "HEADING", "heading_deg"))
        if x is not None and y is not None:
            return {
                "status": "stm32",
                "reason": "STM32 odometry telemetry available",
                "confidence": 0.85,
                "x_cm": x,
                "y_cm": y,
                "heading_deg": int(round(heading if heading is not None else 0.0)) % 360,
            }

        x_sim, y_sim, heading_sim = self._simulate_pose(elapsed_s)
        return {
            "status": "simulated_dry_run",
            "reason": "STM32 odometry position not exposed; using dry-run sequence estimate",
            "confidence": 0.25,
            "x_cm": x_sim,
            "y_cm": y_sim,
            "heading_deg": heading_sim,
        }

    def _simulate_pose(self, elapsed_s: float) -> tuple[float, float, int]:
        total = sum(float(item["duration"]) for item in self.sequence)
        cursor = elapsed_s % max(0.1, total)
        x, y, heading = 0.0, 0.0, 0
        for item in self.sequence:
            duration = float(item["duration"])
            if cursor <= duration:
                break
            x, y, heading = self._predict_segment(
                x,
                y,
                heading,
                float(item["distance_cm"]),
                int(item["turn_deg"]),
            )
            cursor -= duration
        return x, y, heading

    def _predict_segment(
        self,
        x_cm: float,
        y_cm: float,
        heading_deg: int,
        distance_cm: float,
        turn_deg: int,
    ) -> tuple[float, float, int]:
        heading = int(heading_deg) % 360
        dx, dy = self._heading_vector(heading)
        next_x = x_cm + dx * distance_cm
        next_y = y_cm + dy * distance_cm
        next_heading = (heading + int(turn_deg)) % 360
        return next_x, next_y, next_heading

    def _envelope_margin(self, x_cm: float, y_cm: float) -> float:
        half = float(self.config.envelope_size_cm) / 2.0
        return min(half - abs(float(x_cm)), half - abs(float(y_cm)))

    def _direction_safety(self, motion: str, speed: int, stm32_runtime: dict[str, Any]) -> str:
        if motion in {"stop", "arm_sway"} or speed == 0:
            return "stationary"
        obstacles = stm32_runtime.get("obstacles") if isinstance(stm32_runtime.get("obstacles"), dict) else {}
        if speed < 0:
            return "stage_clear_assumed_backward"
        values = [self._float_or_none(obstacles.get(key)) for key in ("F", "FL", "FR")]
        front_values = [value for value in values if value is not None]
        if not front_values:
            return "unknown"
        if min(front_values) < self.config.obstacle_stop_cm:
            return "blocked"
        if min(front_values) < self.config.obstacle_slow_cm:
            return "slow"
        return "clear"

    @staticmethod
    def _heading_vector(heading_deg: int) -> tuple[int, int]:
        heading = int(round(heading_deg / 90.0) * 90) % 360
        if heading == 0:
            return 0, 1
        if heading == 90:
            return 1, 0
        if heading == 180:
            return 0, -1
        return -1, 0

    @staticmethod
    def _heading_quadrant(heading_deg: int) -> str:
        heading = int(round(heading_deg / 90.0) * 90) % 360
        return {0: "north", 90: "east", 180: "south", 270: "west"}.get(heading, "unknown")

    @staticmethod
    def _first_float(source: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        lowered = {str(key).lower(): value for key, value in source.items()}
        for key in keys:
            value = source.get(key)
            if value is None:
                value = lowered.get(key.lower())
            parsed = DanceDryRunPlanner._float_or_none(value)
            if parsed is not None:
                return parsed
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
