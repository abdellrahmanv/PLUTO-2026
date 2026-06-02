#!/usr/bin/env python3
"""Smoke test for Phase 8 ERROR operator behavior."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request


HOST = "127.0.0.1"
PORT = 18081
BASE = f"http://{HOST}:{PORT}"


def request(path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, bytes]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def wait_ready() -> None:
    deadline = time.monotonic() + 25
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
        [sys.executable, "-m", "pluto_runtime.web_shell", "--host", HOST, "--port", str(PORT), "--wave-pose-disabled"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_ready()

        estop_code, estop_raw = request("/api/emergency-stop", "POST")
        assert estop_code == 200, estop_code
        estop = json.loads(estop_raw.decode("utf-8"))
        assert estop["state"] == "ERROR"

        status_code, raw_status = request("/api/status")
        assert status_code == 200, status_code
        status = json.loads(raw_status.decode("utf-8"))
        assert status["current_state"] == "ERROR"
        assert status["error"]["active"] is True
        assert status["error"]["fault_reason"]
        assert status["error"]["recovery_action"]

        dance_code, dance_raw = request("/api/request-state", "POST", {"state": "DANCE"})
        assert dance_code == 200, dance_code
        dance = json.loads(dance_raw.decode("utf-8"))
        assert dance["accepted"] is False
        assert "error_reset_required" in dance["blocked_by"]

        fault_code, fault_raw = request("/api/inject-fault", "POST", {"reason": "smoke test fault"})
        assert fault_code == 200, fault_code
        fault = json.loads(fault_raw.decode("utf-8"))
        assert fault["state"] == "ERROR"
        assert "smoke test fault" in fault["transition"]["reason"]

        reset_code, reset_raw = request("/api/reset-error", "POST")
        assert reset_code == 200, reset_code
        reset = json.loads(reset_raw.decode("utf-8"))
        if reset["accepted"] is False:
            assert "stm32_unavailable" in reset["blocked_by"]

        print("ERROR_STATE_SMOKE PASS")
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
