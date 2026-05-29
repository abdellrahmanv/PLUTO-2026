#!/usr/bin/env python3
"""Smoke test for WELCOME wave-trigger event plumbing."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pluto_runtime.wave_detection import SimpleWaveDetector


HOST = "127.0.0.1"
PORT = 18085


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test WELCOME wave trigger plumbing.")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--external-server", action="store_true", help="Use already running web shell.")
    parser.add_argument("--hardware-flow", action="store_true", help="Expect accepted WELCOME trigger when STM32 is present.")
    return parser.parse_args()


def request(base: str, path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, bytes]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def wait_ready(base: str) -> None:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            status, _ = request(base, "/healthz")
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("web shell did not become ready")


def run_checks(base: str, hardware_flow: bool) -> None:
    wait_ready(base)
    status_code, raw_status = request(base, "/api/status")
    assert status_code == 200, status_code
    status = json.loads(raw_status.decode("utf-8"))
    assert "wave" in status
    assert status["wave"]["detector_status"] in {"tracked_pc_rule_lite", "simple_box_motion"}
    assert "wave_lock_active" in status["camera"]["details"]

    if status["current_state"] == "ERROR":
        request(base, "/api/reset-error", "POST")

    arm_code, arm_raw = request(base, "/api/welcome/wave-trigger", "POST", {"source": "smoke_arm_wave", "arm": True})
    assert arm_code == 200, arm_code
    arm = json.loads(arm_raw.decode("utf-8"))
    if not arm.get("accepted"):
        assert arm.get("armed") is True, arm
        assert arm["event"]["diagnostic"] is False, arm
        assert arm["event"]["source"] == "smoke_arm_wave", arm

    wave_code, wave_raw = request(base, "/api/welcome/wave-trigger", "POST", {"source": "smoke_test_wave", "diagnostic": True})
    assert wave_code == 200, wave_code
    wave = json.loads(wave_raw.decode("utf-8"))
    assert wave["event"]["type"] == "WELCOME_TRIGGER:WAVE"
    assert wave["event"]["diagnostic"] is True
    assert wave["event"]["source"] == "smoke_test_wave"

    if hardware_flow:
        assert wave["accepted"] is True, wave
        assert wave["current_state"] == "WELCOME", wave
        assert wave["current_substate"] == "WELCOME_DETECT", wave
        assert wave["stop_guard"]["ok"] is True or wave["stop_guard"].get("degraded") is True, wave
        idle_code, idle_raw = request(base, "/api/request-state", "POST", {"state": "IDLE"})
        assert idle_code == 200, idle_code
        idle = json.loads(idle_raw.decode("utf-8"))
        assert idle["accepted"] is True, idle
    else:
        assert wave["accepted"] is False or wave["current_state"] == "WELCOME", wave


def run_detector_checks() -> None:
    detector = SimpleWaveDetector(cooldown_s=0.5)
    base = {"available": True, "resolution": [320, 320], "detections": []}

    for index in range(8):
        status = detector.update(
            {
                **base,
                "detections": [{"bbox": [100, 60, 210, 260], "confidence": 0.85}],
            },
            now=float(index) * 0.2,
        )
    assert status.confirmed is False
    assert status.reason in {"not_enough_direction_changes", "amplitude_too_low"}

    detector = SimpleWaveDetector(cooldown_s=0.5)
    centers = [150, 175, 136, 180, 132, 176, 134, 178]
    widths = [100, 116, 96, 118, 94, 116, 96, 118]
    confirmed_status = None
    for index, (center, width) in enumerate(zip(centers, widths)):
        status = detector.update(
            {
                **base,
                "detections": [{"bbox": [center - width / 2, 60, center + width / 2, 260], "confidence": 0.88}],
            },
            now=float(index) * 0.2,
        )
        if status.confirmed and status.reason == "confirmed_wave":
            confirmed_status = status
    assert confirmed_status is not None, status
    assert confirmed_status.reason == "confirmed_wave", confirmed_status
    assert confirmed_status.direction_changes >= 2, confirmed_status

    detector = SimpleWaveDetector(cooldown_s=0.5)
    balances = [-0.7, 0.6, -0.65, 0.7, -0.6, 0.65, -0.7, 0.6]
    confirmed_status = None
    for index, balance in enumerate(balances):
        status = detector.update(
            {
                **base,
                "detections": [{"bbox": [105, 60, 215, 260], "confidence": 0.86}],
                "wave_motion": {"motion_norm": 0.045, "balance": balance},
            },
            now=float(index) * 0.2,
        )
        if status.confirmed and status.reason == "confirmed_wave":
            confirmed_status = status
    assert confirmed_status is not None, status
    assert confirmed_status.reason == "confirmed_wave", confirmed_status
    assert confirmed_status.motion_direction_changes >= 2, confirmed_status

    detector = SimpleWaveDetector(cooldown_s=0.5)
    hand_positions = [-0.45, 0.30, -0.38, 0.34, -0.42, 0.36, -0.40]
    confirmed_status = None
    for index, hand_x in enumerate(hand_positions):
        status = detector.update(
            {
                **base,
                "detections": [{"bbox": [90, 45, 230, 285], "confidence": 0.87}],
                "wave_motion": {
                    "motion_norm": 0.030,
                    "balance": 0.5 if hand_x > 0 else -0.5,
                    "hand_valid": True,
                    "hand_x_norm": hand_x,
                    "hand_y_norm": 0.35,
                    "raised_region": True,
                },
            },
            now=float(index) * 0.2,
        )
        if status.confirmed and status.reason == "confirmed_wave":
            confirmed_status = status
    assert confirmed_status is not None, status
    assert confirmed_status.algorithm == "tracked_pc_rule_lite", confirmed_status
    assert confirmed_status.raised is True, confirmed_status
    assert confirmed_status.hand_amp >= 0.16, confirmed_status
    assert confirmed_status.hand_sign_changes >= 2, confirmed_status
    assert confirmed_status.hand_dx_dy >= 1.2, confirmed_status

    detector = SimpleWaveDetector(cooldown_s=0.5)
    confirmed_status = None
    for index, hand_x in enumerate(hand_positions):
        status = detector.update(
            {
                **base,
                "detections": [
                    {"bbox": [15, 50, 120, 270], "confidence": 0.80, "track_id": 1},
                    {"bbox": [170, 45, 310, 285], "confidence": 0.89, "track_id": 2},
                ],
                "wave_motion": {
                    "available": True,
                    "reason": "multi_track_optical_flow",
                    "candidates": [
                        {"track_id": 1, "motion_norm": 0.004, "balance": 0.0, "hand_valid": False},
                        {
                            "track_id": 2,
                            "motion_norm": 0.034,
                            "balance": 0.5 if hand_x > 0 else -0.5,
                            "hand_valid": True,
                            "hand_x_norm": hand_x,
                            "hand_y_norm": 0.32,
                            "raised_region": True,
                        },
                    ],
                },
            },
            now=float(index) * 0.2,
        )
        if status.confirmed and status.reason == "confirmed_wave":
            confirmed_status = status
    assert confirmed_status is not None, status
    assert confirmed_status.track_id == 2, confirmed_status
    assert confirmed_status.target_id == "track_2", confirmed_status


def main() -> int:
    args = parse_args()
    run_detector_checks()
    base = f"http://{args.host}:{args.port}"
    proc = None
    if not args.external_server:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pluto_runtime.web_shell", "--host", args.host, "--port", str(args.port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    try:
        run_checks(base, args.hardware_flow)
        print("WELCOME_WAVE_SMOKE PASS")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
