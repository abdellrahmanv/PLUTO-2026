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
        assert b"PLUTO" in home, "PLUTO project identity missing"
        assert b"PLUTO Mission Control" in home, "production mission console title missing"
        assert b'id="themeMode"' in home, "theme selector missing"
        assert b"pluto-theme" in home, "theme persistence key missing"
        assert b'data-theme' in home, "theme boot script missing"
        assert b'id="missionSafety"' in home, "mission safety strip missing"
        assert b"Tablet Face" in home, "tablet face link missing"
        assert b"CAD Vehicle Digital Twin" in home, "CAD-backed 3D monitor label missing"
        assert b"Launch & Monitor Unit" in home, "3D launch monitor title missing"
        assert b'id="pluto3dCanvas"' in home, "3D vehicle monitor canvas missing"
        assert b"Launch Gate" in home, "launch readiness gate missing"
        assert b"Operations Readiness" in home, "operator readiness summary missing"
        assert b"Mode Command Matrix" in home, "mode command matrix missing"
        assert b"Systems Rack" in home, "hardware systems rack missing"
        assert b"Sensor Intelligence" in home, "sensor interpretation deck missing"
        assert b"Range Radar & Occupancy Corridor" in home, "advanced sensor range map missing"
        assert b"Nearest Object" in home, "readable sensor nearest-object card missing"
        assert b"Sensor Confidence" in home, "sensor confidence readout missing"
        assert b"Mode-Adaptive Guard" in home, "mode-aware sensor guard missing"
        assert b"Dance Envelope Map" in home, "advanced dance envelope map missing"
        assert b'id="talkBank"' in home, "welcome talk bank metric missing"
        assert b"Validation Center" in home, "validation center section missing"
        assert b"/api/validation/catalog" in home, "validation catalog route missing from UI"
        assert b"/api/validation/run" in home, "validation run route missing from UI"
        assert b"Mission Log" in home, "mission log summary missing"

        js_status, js_body = request("/static/pluto_3d.js")
        assert js_status == 200, js_status
        assert b"Pluto3D" in js_body, "3D monitor module missing"

        three_status, three_body = request("/static/three.module.min.js")
        assert three_status == 200, three_status
        assert len(three_body) > 100000, "local Three.js runtime missing or truncated"

        core_status, core_body = request("/static/three.core.min.js")
        assert core_status == 200, core_status
        assert len(core_body) > 100000, "local Three.js core runtime missing or truncated"

        loader_status, loader_body = request("/static/STLLoader.js")
        assert loader_status == 200, loader_status
        assert b"STLLoader" in loader_body, "local STL loader missing"

        mesh_status, mesh_body = request("/static/robot_meshes/base_link.STL")
        assert mesh_status == 200, mesh_status
        assert len(mesh_body) > 100000, "CAD base mesh missing or truncated"

        face_status, face = request("/face")
        assert face_status == 200, face_status
        assert b"PLUTO Face" in face, "tablet robot face route missing"
        assert b'id="faceStop"' in face, "tablet face emergency stop missing"

        status_code, raw_status = request("/api/status")
        assert status_code == 200, status_code
        status = json.loads(raw_status.decode("utf-8"))
        assert status["project"] == "PLUTO"
        assert status["current_state"] in {"IDLE", "ERROR", "BOOTSTRAP"}
        assert "stm32" in status["hardware"]
        assert "camera" in status
        assert "mode_manager" in status
        assert "stm32_runtime" in status
        assert "error" in status
        assert "manual" in status
        assert "wave" in status
        assert "welcome_approach" in status
        assert status["welcome_approach"]["dry_run"] is True
        assert "dance" in status
        assert status["dance"]["dry_run"] is True
        assert status["wave"]["detector_status"] in {"tracked_pose_wave", "tracked_pc_rule_lite", "simple_box_motion"}
        assert "talk" in status
        assert status["talk"]["intent_count"] >= 180
        assert status["talk"]["script_count"] >= 30
        assert status["talk"]["response_bank_size"] >= 210
        assert status["talk"]["alias_group_count"] >= 20
        assert "audio" in status
        assert "allowed_next_states" in status
        assert "transition_log" in status["mode_manager"]

        camera_code, raw_camera = request("/api/camera/status")
        assert camera_code == 200, camera_code
        camera = json.loads(raw_camera.decode("utf-8"))
        assert "available" in camera
        assert camera["running"] is False
        assert camera["error"] == "camera disabled by operator"

        audio_code, raw_audio = request("/api/audio/status")
        assert audio_code == 200, audio_code
        audio = json.loads(raw_audio.decode("utf-8"))
        assert "microphone_available" in audio
        assert "speaker_available" in audio
        assert "requested_microphone" in audio
        assert "requested_speaker" in audio

        validation_code, raw_validation = request("/api/validation/catalog")
        assert validation_code == 200, validation_code
        validation = json.loads(raw_validation.decode("utf-8"))
        assert validation["name"] == "Validation Center"
        validation_tests = {item["id"]: item for item in validation["tests"]}
        assert "mode-transition" in validation_tests
        assert "stm32-communication" in validation_tests
        assert validation_tests["welcome-approach-dry-run"]["dry_run_only"] is True

        select_mic_code, select_mic_raw = request("/api/audio/select-microphone", "POST", {"device": ""})
        assert select_mic_code == 200, select_mic_code
        selected_mic = json.loads(select_mic_raw.decode("utf-8"))
        assert "requested_microphone" in selected_mic

        jpg_code, _ = request("/camera.jpg")
        assert jpg_code in {200, 503}, jpg_code

        blocked_code, blocked_raw = request("/api/request-state", "POST", {"state": "GAME_LATER"})
        assert blocked_code == 200, blocked_code
        blocked = json.loads(blocked_raw.decode("utf-8"))
        assert blocked["accepted"] is False
        assert "GAME_LATER" in blocked["requested_state"]

        wave_code, wave_raw = request("/api/welcome/wave-trigger", "POST", {"source": "smoke_test", "diagnostic": True})
        assert wave_code == 200, wave_code
        wave = json.loads(wave_raw.decode("utf-8"))
        assert "event" in wave
        assert wave["event"]["type"] == "WELCOME_TRIGGER:WAVE"
        assert "wave" in wave or wave["accepted"] is False

        estop_code, estop_raw = request("/api/emergency-stop", "POST")
        assert estop_code == 200, estop_code
        estop = json.loads(estop_raw.decode("utf-8"))
        assert estop["state"] == "ERROR"
        assert "transition" in estop

        raw_motor_code, _ = request("/api/drive", "POST", {"speed": 10})
        assert raw_motor_code == 404, "raw motor route must not exist"

        manual_code, manual_raw = request("/api/manual/drive", "POST", {"speed": 999, "steer": 999})
        assert manual_code == 200, manual_code
        manual = json.loads(manual_raw.decode("utf-8"))
        assert manual["accepted"] is False

        talk_code, talk_raw = request("/api/welcome/talk", "POST", {"text": "what is your name"})
        assert talk_code == 200, talk_code
        talk = json.loads(talk_raw.decode("utf-8"))
        assert talk["accepted"] is False
        assert "WELCOME_TALK" in talk["reason"]
        assert talk["display_response"] == "Enter WELCOME first."

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
