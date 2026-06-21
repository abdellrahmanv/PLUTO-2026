"""Live Billie Jean dance sequence controller.

This module contains the hardware-facing sequence logic only. It does not own
mode transitions; the mode manager still decides when live DANCE may run.
"""

from __future__ import annotations

import math
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


MIN_SPEED = 100
MIN_STEER = 150
MAX_SPEED = 150
MAX_STEER = 200

TARGET_DISTANCE_M = 2.0
TARGET_TURN_DEG = 180.0
DISTANCE_TOLERANCE_M = 0.10
TURN_TOLERANCE_DEG = 5.0

SAFE_OBSTACLE_DISTANCE_CM = 35.0
HEADING_KP = 1.2
MAX_HEADING_CORRECTION = 20
CONTROL_PERIOD_S = 0.05
MOVE_TIMEOUT_S = 12.0
TURN_TIMEOUT_S = 8.0


class MotorDriver(Protocol):
    def drive(self, left_speed: int, right_speed: int) -> None:
        ...

    def stop(self) -> None:
        ...


class EncoderReader(Protocol):
    def reset(self) -> None:
        ...

    def distance_m(self) -> float:
        ...

    def total_ticks(self) -> int:
        ...


class ImuReader(Protocol):
    def yaw_deg(self) -> float:
        ...


class UltrasonicReader(Protocol):
    def distance_cm(self) -> float:
        ...


@dataclass(frozen=True)
class LiveDanceConfig:
    use_ultrasonic: bool = True
    obstacle_distance_cm: float = SAFE_OBSTACLE_DISTANCE_CM
    audio_file_path: str | None = None

    @property
    def resolved_audio_path(self) -> Path | None:
        configured = self.audio_file_path or os.environ.get("PLUTO_DANCE_AUDIO")
        if configured:
            return Path(configured)
        candidates = [
            Path("/home/pi/PLUTO-2026/audio/billie-jean-cut.mp3"),
            Path("/home/pi/Downloads/billie-jean-cut.mp3"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None


@dataclass(frozen=True)
class DanceSegment:
    motion: str
    target: float
    speed: int


class LiveDanceSequence:
    """Run the one approved live dance sequence."""

    def __init__(
        self,
        motors: MotorDriver,
        encoders: EncoderReader,
        imu: ImuReader,
        ultrasonic: UltrasonicReader | None,
        config: LiveDanceConfig | None = None,
    ) -> None:
        self.motors = motors
        self.encoders = encoders
        self.imu = imu
        self.ultrasonic = ultrasonic
        self.config = config or LiveDanceConfig()
        self.audio_process: subprocess.Popen[bytes] | None = None
        self.segments = (
            DanceSegment("forward", TARGET_DISTANCE_M, MAX_SPEED),
            DanceSegment("backward", TARGET_DISTANCE_M, MIN_SPEED),
            DanceSegment("rotate", TARGET_TURN_DEG, MIN_STEER),
            DanceSegment("forward", TARGET_DISTANCE_M, MAX_SPEED),
            DanceSegment("backward", TARGET_DISTANCE_M, MIN_SPEED),
            DanceSegment("rotate", TARGET_TURN_DEG, MIN_STEER),
        )

    def run(self) -> None:
        self.start_audio()
        try:
            for segment in self.segments:
                if segment.motion == "forward":
                    self.move_distance(direction=1, speed=segment.speed, target_m=segment.target)
                elif segment.motion == "backward":
                    self.move_distance(direction=-1, speed=segment.speed, target_m=segment.target)
                elif segment.motion == "rotate":
                    self.rotate_degrees(target_deg=segment.target, speed=segment.speed)
                else:
                    raise ValueError(f"Unknown dance segment: {segment.motion}")
        finally:
            self.motors.stop()

    def start_audio(self) -> None:
        audio_path = self.config.resolved_audio_path
        if audio_path is None or not audio_path.exists():
            raise FileNotFoundError(
                "Dance audio file not found. Set PLUTO_DANCE_AUDIO or copy the cut song to "
                "/home/pi/PLUTO-2026/audio/billie-jean-cut.mp3."
            )

        commands = (
            ("mpg123", "-q", str(audio_path)),
            ("ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_path)),
        )
        for command in commands:
            try:
                self.audio_process = subprocess.Popen(command)
                time.sleep(0.3)
                return
            except FileNotFoundError:
                continue
        raise RuntimeError("No supported audio player found. Install mpg123 or ffmpeg.")

    def move_distance(self, direction: int, speed: int, target_m: float) -> None:
        self.encoders.reset()
        start_yaw = self.imu.yaw_deg()
        started_at = time.monotonic()

        while self.encoders.distance_m() < target_m - DISTANCE_TOLERANCE_M:
            self.raise_if_blocked()
            self.raise_if_timed_out(started_at, MOVE_TIMEOUT_S, "dance distance move")

            yaw_error = angle_delta_deg(start_yaw, self.imu.yaw_deg())
            correction = clamp(round(yaw_error * HEADING_KP), -MAX_HEADING_CORRECTION, MAX_HEADING_CORRECTION)
            base = direction * speed
            self.motors.drive(base - correction, base + correction)
            time.sleep(CONTROL_PERIOD_S)

        self.motors.stop()
        measured = self.encoders.distance_m()
        if abs(target_m - measured) > DISTANCE_TOLERANCE_M:
            raise RuntimeError(f"Dance distance outside tolerance: target={target_m:.2f}m measured={measured:.2f}m")

    def rotate_degrees(self, target_deg: float, speed: int) -> None:
        self.encoders.reset()
        start_yaw = self.imu.yaw_deg()
        started_at = time.monotonic()

        while abs(angle_delta_deg(start_yaw, self.imu.yaw_deg())) < target_deg - TURN_TOLERANCE_DEG:
            self.raise_if_timed_out(started_at, TURN_TIMEOUT_S, "dance rotation")
            self.motors.drive(speed, -speed)
            time.sleep(CONTROL_PERIOD_S)

        self.motors.stop()
        turned = abs(angle_delta_deg(start_yaw, self.imu.yaw_deg()))
        if abs(target_deg - turned) > TURN_TOLERANCE_DEG:
            raise RuntimeError(f"Dance turn outside tolerance: target={target_deg:.1f}deg measured={turned:.1f}deg")
        if self.encoders.total_ticks() <= 0:
            raise RuntimeError("Dance turn failed validation: encoders detected no wheel movement.")

    def raise_if_blocked(self) -> None:
        if not self.config.use_ultrasonic:
            return
        if self.ultrasonic is None:
            raise RuntimeError("Careful dance requires ultrasonic distance readings.")
        distance_cm = self.ultrasonic.distance_cm()
        if distance_cm < self.config.obstacle_distance_cm:
            raise RuntimeError(f"Dance obstacle detected: {distance_cm:.1f}cm")

    @staticmethod
    def raise_if_timed_out(started_at: float, timeout_s: float, label: str) -> None:
        if time.monotonic() - started_at > timeout_s:
            raise TimeoutError(f"{label} timed out.")


def angle_delta_deg(start: float, current: float) -> float:
    return (current - start + 180.0) % 360.0 - 180.0


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


class SimMotors:
    def __init__(self) -> None:
        self.commands: list[tuple[int, int]] = []
        self.stopped = False

    def drive(self, left_speed: int, right_speed: int) -> None:
        self.commands.append((left_speed, right_speed))

    def stop(self) -> None:
        self.stopped = True


class SimEncoders:
    def __init__(self) -> None:
        self.started_at = time.monotonic()
        self.ticks = 1

    def reset(self) -> None:
        self.started_at = time.monotonic()
        self.ticks = 1

    def distance_m(self) -> float:
        return min(TARGET_DISTANCE_M, (time.monotonic() - self.started_at) * 0.8)

    def total_ticks(self) -> int:
        return self.ticks


class SimImu:
    def __init__(self) -> None:
        self.yaw = 0.0

    def yaw_deg(self) -> float:
        self.yaw = math.fmod(self.yaw + 3.0, 360.0)
        return self.yaw


class SimUltrasonic:
    def __init__(self, distance_cm: float = 100.0) -> None:
        self._distance_cm = distance_cm

    def distance_cm(self) -> float:
        return self._distance_cm
