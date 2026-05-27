#!/usr/bin/env python3
"""Smoke test for Phase 9 audio I/O detection and WELCOME speech plumbing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pluto_runtime.audio_io import AudioRuntime


HOST = "127.0.0.1"
PORT = 18084


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test Pluto audio I/O.")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--external-server", action="store_true", help="Use already running web shell.")
    parser.add_argument("--require-microphone", action="store_true", help="Fail if no microphone is detected.")
    parser.add_argument("--require-speaker", action="store_true", help="Fail if no speaker is detected.")
    parser.add_argument("--record-probe", action="store_true", help="Record one second from selected microphone.")
    parser.add_argument("--tts-probe", action="store_true", help="Ask the web server to speak a short line.")
    return parser.parse_args()


def request(base: str, path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, bytes]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
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


def validate_status(status: dict, require_microphone: bool, require_speaker: bool) -> None:
    assert "microphone_available" in status
    assert "speaker_available" in status
    assert "capture_devices" in status
    assert "playback_devices" in status
    assert "stt_backend" in status
    assert "tts_backend" in status
    if require_microphone:
        assert status["microphone_available"] is True, status
        assert status["selected_microphone"], status
        assert any(token in status["selected_microphone"].lower() for token in ("camera", "usb", "mic", "hw")), status
    if require_speaker:
        assert status["speaker_available"] is True, status
        assert status["selected_speaker"], status


def run_local_checks(args: argparse.Namespace) -> None:
    audio = AudioRuntime()
    status = audio.status()
    validate_status(status, args.require_microphone, args.require_speaker)
    if args.record_probe:
        result = audio.record(1.0)
        assert result["ok"] is True, result
        assert result["bytes"] > 44, result
    print(json.dumps(status, indent=2))


def run_web_checks(base: str, args: argparse.Namespace) -> None:
    wait_ready(base)
    status_code, raw_status = request(base, "/api/audio/status")
    assert status_code == 200, status_code
    status = json.loads(raw_status.decode("utf-8"))
    validate_status(status, args.require_microphone, args.require_speaker)

    refresh_code, raw_refresh = request(base, "/api/audio/refresh", "POST")
    assert refresh_code == 200, refresh_code
    refreshed = json.loads(raw_refresh.decode("utf-8"))
    validate_status(refreshed, args.require_microphone, args.require_speaker)

    if args.tts_probe:
        speak_code, raw_speak = request(base, "/api/audio/speak", "POST", {"text": "I am Pluto."})
        assert speak_code == 200, speak_code
        speak = json.loads(raw_speak.decode("utf-8"))
        assert "audio" in speak, speak


def main() -> int:
    args = parse_args()
    run_local_checks(args)

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
        run_web_checks(base, args)
        print("AUDIO_IO_SMOKE PASS")
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
