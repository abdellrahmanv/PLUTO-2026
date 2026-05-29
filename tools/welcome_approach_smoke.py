#!/usr/bin/env python3
"""Smoke tests for Phase 10 WELCOME_APPROACH dry-run planning."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pluto_runtime.welcome_approach import WelcomeApproachPlanner


def camera(
    bbox: list[int] | None = None,
    track_id: int = 7,
    quality: str = "good",
    brightness: float = 90.0,
    contrast: float = 35.0,
) -> dict:
    detections = []
    if bbox is not None:
        detections.append({"bbox": bbox, "confidence": 0.86, "class_name": "human", "track_id": track_id})
    return {
        "available": True,
        "running": True,
        "resolution": [320, 320],
        "configured_resolution": [320, 320],
        "detections": detections,
        "human_count": len(detections),
        "vision_quality": quality,
        "image_brightness": brightness,
        "image_contrast": contrast,
        "details": {
            "wave_lock_active": True,
            "wave_locked_track_id": track_id,
            "wave_lock_anchor_bbox": bbox,
        },
    }


def stm32(front: float = 999.0, front_left: float = 999.0, front_right: float = 999.0) -> dict:
    return {"running": True, "obstacles": {"F": front, "FL": front_left, "FR": front_right}}


def wave(track_id: int = 7) -> dict:
    return {"detector": {"track_id": track_id, "confirmed": True}}


def compute(camera_status: dict, stm32_runtime: dict | None = None):
    planner = WelcomeApproachPlanner()
    return planner.compute(camera_status, stm32_runtime or stm32(), wave(), "WELCOME", "WELCOME_DETECT")


def main() -> int:
    inactive = WelcomeApproachPlanner().compute(camera([120, 80, 200, 170]), stm32(), wave(), "IDLE", "IDLE_READY")
    assert inactive.active is False
    assert inactive.reason == "not in WELCOME"

    forward = compute(camera([120, 80, 200, 170]))
    assert forward.active is True
    assert forward.dry_run is True
    assert forward.target_id == 7
    assert forward.target_distance_class == "far"
    assert forward.proposed_motion == "forward"
    assert forward.proposed_speed > 0

    left = compute(camera([10, 80, 90, 170]))
    assert left.proposed_motion == "turn_left"
    assert left.proposed_steer < 0

    right = compute(camera([230, 80, 310, 170]))
    assert right.proposed_motion == "turn_right"
    assert right.proposed_steer > 0

    arrived = compute(camera([90, 35, 230, 235]))
    assert arrived.proposed_motion == "stop"
    assert arrived.target_distance_class == "good"
    assert arrived.reason == "greeting distance reached"

    too_close = compute(camera([70, 20, 250, 285]))
    assert too_close.proposed_motion == "stop"
    assert too_close.target_distance_class == "too_close"

    clipped = compute(camera([7, 150, 259, 319]))
    assert clipped.proposed_motion == "stop"
    assert clipped.target_distance_class == "unknown_clipped"
    assert clipped.target_box_clipped is True
    assert "bottom" in clipped.target_edge_contact
    assert clipped.reason == "target distance uncertain"

    blocked = compute(camera([120, 80, 200, 170]), stm32_runtime=stm32(front=55))
    assert blocked.proposed_motion == "stop"
    assert blocked.obstacle_status == "blocked"

    low_light = compute(camera([120, 80, 200, 170], quality="low_light", brightness=20, contrast=8))
    assert low_light.proposed_motion == "stop"
    assert low_light.reason == "vision quality degraded"

    missing = compute(camera(None))
    assert missing.proposed_motion == "stop"
    assert missing.reason == "locked target not visible"

    print("WELCOME_APPROACH_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
