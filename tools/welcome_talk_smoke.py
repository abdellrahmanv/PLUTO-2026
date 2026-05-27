#!/usr/bin/env python3
"""Smoke test for WELCOME_TALK v1 offline answer engine."""

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

from pluto_runtime.welcome_talk import INTENT_RULES, WelcomeTalkEngine, count_words


HOST = "127.0.0.1"
PORT = 18083


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test WELCOME_TALK v1.")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--external-server", action="store_true", help="Use already running web shell.")
    parser.add_argument("--hardware-flow", action="store_true", help="Enter WELCOME and test the API with STM32 present.")
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


def assert_word_limited(text: str, limit: int = 9) -> None:
    assert count_words(text) <= limit, f"response too long: {text!r}"


def run_engine_checks() -> None:
    engine = WelcomeTalkEngine()

    for rule in INTENT_RULES:
        assert_word_limited(rule.response)

    name = engine.answer("what is your name")
    assert name.accepted is True
    assert name.intent == "name"
    assert name.response_source == "keyword"
    assert_word_limited(name.response)

    fuzzy = engine.answer("who ar you")
    assert fuzzy.accepted is True
    assert fuzzy.intent == "name"
    assert fuzzy.response_source in {"keyword", "fuzzy"}
    assert_word_limited(fuzzy.response)

    unknown = engine.answer("banana window")
    assert unknown.accepted is True
    assert unknown.response_source == "fallback"
    assert unknown.reason == "no_intent_match"
    assert_word_limited(unknown.response)

    empty = engine.answer("")
    assert empty.accepted is False
    assert empty.reason == "empty_input"
    assert_word_limited(empty.response)

    long_question = engine.answer("one two three four five six seven eight nine ten")
    assert long_question.accepted is False
    assert long_question.reason == "input_too_long"
    assert_word_limited(long_question.response)


def run_web_checks(base: str, hardware_flow: bool) -> None:
    wait_ready(base)
    status_code, raw_status = request(base, "/api/status")
    assert status_code == 200, status_code
    status = json.loads(raw_status.decode("utf-8"))
    assert "talk" in status
    assert status["talk"]["version"] == "v1"
    assert status["talk"]["max_input_words"] == 9
    assert status["talk"]["max_output_words"] == 9
    assert status["talk"]["ollama_fallback_enabled"] is False
    assert status["talk"]["intent_count"] >= 60
    assert "audio" in status

    blocked_code, blocked_raw = request(base, "/api/welcome/talk", "POST", {"text": "what is your name"})
    assert blocked_code == 200, blocked_code
    blocked = json.loads(blocked_raw.decode("utf-8"))
    if status["current_state"] != "WELCOME":
        assert blocked["accepted"] is False
        assert "only active in WELCOME" in blocked["reason"]
        assert blocked["display_response"] == "Enter WELCOME first."

    if hardware_flow and status["hardware"]["stm32"]["connected"]:
        if status["current_state"] == "ERROR":
            reset_code, reset_raw = request(base, "/api/reset-error", "POST")
            assert reset_code == 200, reset_code
            reset = json.loads(reset_raw.decode("utf-8"))
            assert reset["accepted"] is True, reset

        welcome_code, welcome_raw = request(base, "/api/request-state", "POST", {"state": "WELCOME"})
        assert welcome_code == 200, welcome_code
        welcome = json.loads(welcome_raw.decode("utf-8"))
        assert welcome["accepted"] is True, welcome

        talk_code, talk_raw = request(base, "/api/welcome/talk", "POST", {"text": "what is your name"})
        assert talk_code == 200, talk_code
        talk = json.loads(talk_raw.decode("utf-8"))
        assert talk["accepted"] is True, talk
        assert talk["talk"]["intent"] == "name"
        assert talk["talk"]["response_words"] <= 9
        assert talk["stop_guard"]["ok"] is True

        idle_code, idle_raw = request(base, "/api/request-state", "POST", {"state": "IDLE"})
        assert idle_code == 200, idle_code
        idle = json.loads(idle_raw.decode("utf-8"))
        assert idle["accepted"] is True, idle


def main() -> int:
    args = parse_args()
    run_engine_checks()

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
        run_web_checks(base, args.hardware_flow)
        print("WELCOME_TALK_SMOKE PASS")
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
