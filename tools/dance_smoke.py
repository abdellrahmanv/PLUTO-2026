#!/usr/bin/env python3
"""Smoke tests for DANCE dry-run planning."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pluto_runtime.dance import DanceConfig, DanceDryRunPlanner


def camera(bbox: list[int] | None = None, quality: str = "good") -> dict:
    detections = []
    if bbox is not None:
        detections.append({"bbox": bbox, "confidence": 0.85, "class_name": "human", "track_id": 1})
    return {
        "available": True,
        "running": True,
        "resolution": [320, 320],
        "detections": detections,
        "human_count": len(detections),
        "vision_quality": quality,
    }


def stm32(front: float = 999.0, front_left: float = 999.0, front_right: float = 999.0) -> dict:
    return {"running": True, "obstacles": {"F": front, "FL": front_left, "FR": front_right}}


def audio(speaker: bool = True) -> dict:
    return {"speaker_available": speaker}


def main() -> int:
    planner = DanceDryRunPlanner(DanceConfig())
    started = time.time() - 1.0

    inactive = planner.compute(camera(), stm32(), audio(), "IDLE", "IDLE_READY", None)
    assert inactive.active is False
    assert inactive.reason == "not in DANCE"

    active = planner.compute(camera(), stm32(), audio(), "DANCE", "DANCE_DRY_RUN", started)
    assert active.active is True
    assert active.dry_run is True
    assert active.audio_status == "silent_dry_run"
    assert active.obstacle_status == "clear"
    assert active.proposed_motion in {"stop", "glide_backward", "glide_forward", "arm_sway"}

    blocked = planner.compute(camera(), stm32(front=55), audio(), "DANCE", "DANCE_DRY_RUN", started)
    assert blocked.proposed_motion == "stop"
    assert blocked.obstacle_status == "blocked"

    slow = planner.compute(camera(), stm32(front=85), audio(), "DANCE", "DANCE_DRY_RUN", started)
    assert slow.obstacle_status == "slow"
    assert abs(slow.proposed_speed) <= 6

    clipped = planner.compute(camera([10, 20, 250, 319]), stm32(), audio(), "DANCE", "DANCE_DRY_RUN", started)
    assert clipped.proposed_motion == "stop"
    assert clipped.vision_status == "blocked"
    assert clipped.reason == "human box clipped in dance envelope"

    low_light = planner.compute(camera(quality="low_light"), stm32(), audio(), "DANCE", "DANCE_DRY_RUN", started)
    assert low_light.proposed_motion == "stop"
    assert low_light.vision_status == "blocked"

    no_silent = DanceDryRunPlanner(DanceConfig(silent_dry_run_allowed=False)).compute(
        camera(), stm32(), audio(speaker=False), "DANCE", "DANCE_DRY_RUN", started
    )
    assert no_silent.proposed_motion == "stop"
    assert no_silent.audio_status == "blocked"

    print("DANCE_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
