#!/usr/bin/env python3
"""Smoke tests for the live Dance Mode sequence contract."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pluto_runtime.dance_live import (  # noqa: E402
    MAX_SPEED,
    MIN_SPEED,
    MIN_STEER,
    TARGET_DISTANCE_M,
    TARGET_TURN_DEG,
    LiveDanceConfig,
    LiveDanceSequence,
    SimEncoders,
    SimImu,
    SimMotors,
    SimUltrasonic,
    angle_delta_deg,
)


def main() -> int:
    motors = SimMotors()
    dance = LiveDanceSequence(
        motors=motors,
        encoders=SimEncoders(),
        imu=SimImu(),
        ultrasonic=SimUltrasonic(),
        config=LiveDanceConfig(use_ultrasonic=True),
    )

    assert [segment.motion for segment in dance.segments] == [
        "forward",
        "backward",
        "rotate",
        "forward",
        "backward",
        "rotate",
    ]
    assert dance.segments[0].target == TARGET_DISTANCE_M
    assert dance.segments[0].speed == MAX_SPEED
    assert dance.segments[1].target == TARGET_DISTANCE_M
    assert dance.segments[1].speed == MIN_SPEED
    assert dance.segments[2].target == TARGET_TURN_DEG
    assert dance.segments[2].speed == MIN_STEER

    assert angle_delta_deg(350, 10) == 20
    assert angle_delta_deg(10, 350) == -20

    dance.raise_if_blocked()
    blocked = LiveDanceSequence(
        motors=motors,
        encoders=SimEncoders(),
        imu=SimImu(),
        ultrasonic=SimUltrasonic(distance_cm=10.0),
        config=LiveDanceConfig(use_ultrasonic=True),
    )
    try:
        blocked.raise_if_blocked()
        raise AssertionError("careful dance did not stop on obstacle")
    except RuntimeError as exc:
        assert "obstacle" in str(exc).lower()

    free = LiveDanceSequence(
        motors=motors,
        encoders=SimEncoders(),
        imu=SimImu(),
        ultrasonic=SimUltrasonic(distance_cm=10.0),
        config=LiveDanceConfig(use_ultrasonic=False),
    )
    free.raise_if_blocked()

    print("DANCE_LIVE_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
