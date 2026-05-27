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
    assert status["wave"]["detector_status"] == "simple_box_motion"

    if status["current_state"] == "ERROR":
        request(base, "/api/reset-error", "POST")

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
        if status.confirmed:
            confirmed_status = status
    assert confirmed_status is not None, status
    assert confirmed_status.reason == "confirmed_wave", confirmed_status
    assert confirmed_status.direction_changes >= 2, confirmed_status


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
