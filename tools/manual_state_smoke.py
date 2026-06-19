#!/usr/bin/env python3
"""Smoke test for Phase 7 MANUAL operator controls."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pluto_runtime.web_shell import HardwareDevice, ManualRuntime, PlutoWebContext, html_page


HOST = "127.0.0.1"
PORT = 18082
BASE = f"http://{HOST}:{PORT}"


class FakeModeManager:
    current_state = "MANUAL"

    def enter_error(self, reason: str, source: str = "test") -> SimpleNamespace:
        self.current_state = "ERROR"
        return SimpleNamespace(reason=reason, source=source)


class FakeStm32Link:
    def __init__(self) -> None:
        self.drive_commands: list[tuple[int, int]] = []
        self.last_drive: tuple[int, int] | None = None

    def send_drive(self, speed: int, steer: int, wait_ack: bool = True, **_kwargs) -> dict:
        self.drive_commands.append((speed, steer))
        self.last_drive = (speed, steer)
        if not wait_ack:
            return {
                "ok": True,
                "detail": "sent",
                "command": f"CMD:DRIVE:{speed},{steer}",
            }
        return {
            "ok": True,
            "detail": f"ACK:DRIVE:{speed},{steer}",
            "ack_values": {"speed": speed, "steer": steer},
            "ack_matches_command": True,
            "command": f"CMD:DRIVE:{speed},{steer}",
        }

    def get_status(self) -> SimpleNamespace:
        return SimpleNamespace(obstacles={"F": 43.0, "FL": 43.0, "FR": 43.0})


def validate_manual_ignores_ultrasonic_gate() -> None:
    context = PlutoWebContext.__new__(PlutoWebContext)
    context.mode_manager = FakeModeManager()
    context.manual = ManualRuntime(enabled=True)
    context.hardware = {
        "stm32": HardwareDevice("STM32 motor safety controller", True, connected=True, port="COM_TEST"),
    }
    context.stm32_link = FakeStm32Link()
    context.log = lambda _level, _message: None

    result = PlutoWebContext.manual_drive(context, 100, 0)
    assert result["accepted"] is True, result
    assert result["speed"] == 100, result
    assert result["blocked_reason"] is None, result
    assert context.stm32_link.last_drive == (100, 0)

    fast = PlutoWebContext.manual_drive(context, 999, -999)
    assert fast["accepted"] is True, fast
    assert fast["speed"] == 400, fast
    assert fast["steer"] == -400, fast
    assert fast["serial"]["detail"] == "sent", fast
    assert context.manual.base_speed_setting == 400
    assert context.manual.base_steer_setting == 400


def validate_manual_pad_mapping() -> None:
    page = html_page()
    assert "if (motion === 'forward') return {speed, steer: 0}" in page
    assert "if (motion === 'back') return {speed: -speed, steer: 0}" in page


def fake_manual_context(enabled: bool = True) -> PlutoWebContext:
    context = PlutoWebContext.__new__(PlutoWebContext)
    context.mode_manager = FakeModeManager()
    context.manual = ManualRuntime(enabled=enabled)
    context.hardware = {
        "stm32": HardwareDevice("STM32 motor safety controller", True, connected=True, port="COM_TEST"),
    }
    context.stm32_link = FakeStm32Link()
    context.log = lambda _level, _message: None
    context.send_stm32_stop_safe = lambda _port: {"ok": True, "detail": "ACK:STOP"}
    return context


def validate_manual_entry_sends_neutral() -> None:
    context = fake_manual_context(enabled=False)
    result = PlutoWebContext.update_manual_enabled(context, True)
    assert context.manual.enabled is True
    assert result["ok"] is True, result
    assert result["command"] == "CMD:DRIVE:0,0", result
    assert result["ack_values"] == {"speed": 0, "steer": 0}, result
    assert context.stm32_link.drive_commands == [(0, 0)]
    assert context.manual.speed_intent == 0
    assert context.manual.steer_intent == 0


def validate_manual_release_returns_neutral() -> None:
    context = fake_manual_context(enabled=True)
    move = PlutoWebContext.manual_drive(context, 120, -30)
    assert move["accepted"] is True, move
    stop = PlutoWebContext.manual_stop(context)
    assert stop["accepted"] is True, stop
    assert stop["neutral"]["command"] == "CMD:DRIVE:0,0", stop
    assert context.stm32_link.drive_commands == [(120, -30), (0, 0)]
    assert context.manual.speed_intent == 0
    assert context.manual.steer_intent == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test Phase 7 MANUAL controls.")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--external-server", action="store_true", help="Use already running web shell.")
    parser.add_argument("--hardware-zero-drive", action="store_true", help="Enter MANUAL and send zero drive only.")
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


def run_checks(base: str, hardware_zero_drive: bool) -> int:
    wait_ready(base)

    raw_motor_code, _ = request(base, "/api/drive", "POST", {"speed": 10})
    assert raw_motor_code == 404, "raw motor route must not exist"

    drive_code, drive_raw = request(base, "/api/manual/drive", "POST", {"speed": 999, "steer": 999})
    assert drive_code == 200, drive_code
    drive = json.loads(drive_raw.decode("utf-8"))
    assert drive["accepted"] is False
    assert "only active in MANUAL" in drive["reason"]

    arm_code, arm_raw = request(base, "/api/manual/arm", "POST", {"arm": 1, "steps": 5000, "speed": 2000})
    assert arm_code == 200, arm_code
    arm = json.loads(arm_raw.decode("utf-8"))
    assert arm["accepted"] is False
    assert "only active in MANUAL" in arm["reason"]

    status_code, raw_status = request(base, "/api/status")
    assert status_code == 200, status_code
    status = json.loads(raw_status.decode("utf-8"))
    assert "manual" in status
    assert status["manual"]["max_speed"] == 400
    assert status["manual"]["max_steer"] == 400
    assert status["manual"]["base_speed_setting"] == 100
    assert status["manual"]["base_steer_setting"] == 100
    assert status["manual"]["arm_step_setting"] == 5000
    assert status["manual"]["arm_speed_setting"] == 2000
    assert status["manual"]["max_arm_steps"] == 10000
    assert status["manual"]["max_arm_speed"] == 3000

    if hardware_zero_drive and status["hardware"]["stm32"]["connected"]:
        if status["current_state"] == "ERROR":
            reset_code, reset_raw = request(base, "/api/reset-error", "POST")
            assert reset_code == 200, reset_code
            reset = json.loads(reset_raw.decode("utf-8"))
            assert reset["accepted"] is True, reset

        manual_code, manual_raw = request(base, "/api/request-state", "POST", {"state": "MANUAL"})
        assert manual_code == 200, manual_code
        manual = json.loads(manual_raw.decode("utf-8"))
        assert manual["accepted"] is True, manual

        zero_code, zero_raw = request(base, "/api/manual/drive", "POST", {"speed": 0, "steer": 0})
        assert zero_code == 200, zero_code
        zero = json.loads(zero_raw.decode("utf-8"))
        assert zero["accepted"] is True, zero
        assert str(zero["serial"]["detail"]).startswith("ACK:DRIVE"), zero

        stop_code, stop_raw = request(base, "/api/manual/stop", "POST")
        assert stop_code == 200, stop_code
        stop = json.loads(stop_raw.decode("utf-8"))
        assert stop["accepted"] is True, stop

        idle_code, idle_raw = request(base, "/api/request-state", "POST", {"state": "IDLE"})
        assert idle_code == 200, idle_code
        idle = json.loads(idle_raw.decode("utf-8"))
        assert idle["accepted"] is True, idle

    print("MANUAL_STATE_SMOKE PASS")
    return 0


def main() -> int:
    args = parse_args()
    validate_manual_entry_sends_neutral()
    validate_manual_ignores_ultrasonic_gate()
    validate_manual_pad_mapping()
    validate_manual_release_returns_neutral()
    base = f"http://{args.host}:{args.port}"
    proc = None
    if not args.external_server:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pluto_runtime.web_shell", "--host", args.host, "--port", str(args.port), "--wave-pose-disabled"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    try:
        return run_checks(base, args.hardware_zero_drive)
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
