#!/usr/bin/env python3
"""Smoke test for the Phase 3 PLUTO web shell."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request


HOST = "127.0.0.1"
PORT = 18080
BASE = f"http://{HOST}:{PORT}"


def request(path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, bytes]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def wait_ready() -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            status, _ = request("/healthz")
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("web shell did not become ready")


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "pluto_runtime.web_shell", "--host", HOST, "--port", str(PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_ready()

        home_status, home = request("/")
        assert home_status == 200, home_status
        assert b"PLUTO" in home, "PLUTO project identity missing"

        status_code, raw_status = request("/api/status")
        assert status_code == 200, status_code
        status = json.loads(raw_status.decode("utf-8"))
        assert status["project"] == "PLUTO"
        assert status["current_state"] in {"IDLE", "ERROR", "BOOTSTRAP"}
        assert "stm32" in status["hardware"]
        assert "camera" in status
        assert "mode_manager" in status
        assert "allowed_next_states" in status
        assert "transition_log" in status["mode_manager"]

        camera_code, raw_camera = request("/api/camera/status")
        assert camera_code == 200, camera_code
        camera = json.loads(raw_camera.decode("utf-8"))
        assert "available" in camera

        jpg_code, _ = request("/camera.jpg")
        assert jpg_code in {200, 503}, jpg_code

        blocked_code, blocked_raw = request("/api/request-state", "POST", {"state": "GAME_LATER"})
        assert blocked_code == 200, blocked_code
        blocked = json.loads(blocked_raw.decode("utf-8"))
        assert blocked["accepted"] is False
        assert "GAME_LATER" in blocked["requested_state"]

        estop_code, estop_raw = request("/api/emergency-stop", "POST")
        assert estop_code == 200, estop_code
        estop = json.loads(estop_raw.decode("utf-8"))
        assert estop["state"] == "ERROR"

        raw_motor_code, _ = request("/api/drive", "POST", {"speed": 10})
        assert raw_motor_code == 404, "raw motor route must not exist"

        print("WEB_SHELL_SMOKE PASS")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
