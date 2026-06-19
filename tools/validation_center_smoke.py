#!/usr/bin/env python3
"""Smoke test for the Stage 1 Validation Center."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request


HOST = "127.0.0.1"
PORT = 18089
BASE = f"http://{HOST}:{PORT}"


REQUIRED_FIELDS = {
    "id",
    "name",
    "category",
    "safety_level",
    "required_hardware",
    "terminal_command",
    "button_label",
    "timeout_s",
    "dry_run_only",
    "stage",
    "requires_confirmation",
    "physical_motion",
    "enabled",
}


def request(path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, bytes]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
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
        [
            sys.executable,
            "-m",
            "pluto_runtime.web_shell",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--camera-disabled",
            "--wave-pose-disabled",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_ready()

        home_status, home = request("/")
        assert home_status == 200, home_status
        assert b"Validation Center" in home, "Validation Center section missing"
        assert b"/api/validation/catalog" in home, "Validation Center catalog route not wired"
        assert b"/api/validation/run" in home, "Validation Center run route not wired"

        catalog_code, catalog_raw = request("/api/validation/catalog")
        assert catalog_code == 200, catalog_code
        catalog = json.loads(catalog_raw.decode("utf-8"))
        tests = catalog["tests"]
        assert catalog["name"] == "Validation Center"
        assert catalog["stage"] == "Stage 2"
        assert len(tests) >= 20, tests

        by_id = {item["id"]: item for item in tests}
        assert "stm32-communication" in by_id
        assert "uno-communication" in by_id
        assert "mode-transition" in by_id
        assert "welcome-approach-dry-run" in by_id
        assert "dance-dry-run" in by_id
        assert "speaker" in by_id
        assert "microphone" in by_id
        assert "stm32-stress" in by_id
        assert "welcome-interaction-loop" in by_id
        assert "bldc-motor-physical" in by_id
        assert "nema-arm-physical" in by_id
        assert "camera-live" in by_id
        assert "human-detection-live" in by_id
        assert "ultrasonic-stop-physical" in by_id
        assert "emergency-stop-physical" in by_id
        assert "battery-safety" in by_id
        assert "full-welcome-scenario" in by_id

        for item in tests:
            missing = REQUIRED_FIELDS - set(item)
            assert not missing, f"{item.get('id')} missing fields {missing}"
            assert item["terminal_command"].startswith("python tools/"), item
            assert item["button_label"], item
            assert item["timeout_s"] > 0, item
            if item["dry_run_only"]:
                assert item["dry_run_only"] is True, item
                assert item["safety_level"] == "dry-run", item
            if item["physical_motion"]:
                assert item["requires_confirmation"] is True, item
                assert item["safety_level"] == "physical-motion", item

        run_code, run_raw = request("/api/validation/run", "POST", {"test_id": "mode-transition"})
        assert run_code == 200, run_code
        result = json.loads(run_raw.decode("utf-8"))
        assert result["status"] == "PASS", result
        assert result["terminal_command"] == "python tools/mode_manager_smoke.py"
        assert "MODE_MANAGER_SMOKE PASS" in result["output"], result["output"]
        assert result["measurements"]["returncode"] == 0
        assert "catalog" in result

        stm32_code, stm32_raw = request("/api/validation/run", "POST", {"test_id": "stm32-communication"})
        assert stm32_code == 200, stm32_code
        stm32 = json.loads(stm32_raw.decode("utf-8"))
        assert stm32["status"] in {"PASS", "FAIL", "WARNING", "HARDWARE NOT DETECTED"}, stm32
        if stm32["status"] in {"WARNING", "HARDWARE NOT DETECTED"}:
            assert "hardware" in stm32["output"].lower(), stm32

        missing_code, _ = request("/api/validation/run", "POST", {"test_id": "does-not-exist"})
        assert missing_code == 404, missing_code

        print("VALIDATION_CENTER_SMOKE PASS")
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
