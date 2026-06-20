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

from pluto_runtime.welcome_talk import INTENT_RULES, SCRIPT_RULES, WelcomeTalkEngine, count_words


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
    engine_status = engine.status()
    assert engine_status["intent_count"] >= 180
    assert engine_status["script_count"] >= 30
    assert engine_status["response_bank_size"] >= 210
    assert engine_status["alias_group_count"] >= 20

    for rule in INTENT_RULES:
        assert_word_limited(rule.response)
    for rule in SCRIPT_RULES:
        assert_word_limited(rule.response)

    name = engine.answer("what is your name")
    assert name.accepted is True
    assert name.intent == "name"
    assert name.response_source == "keyword"
    assert_word_limited(name.response)

    location = engine.answer("where are you")
    assert location.accepted is True
    assert location.intent == "place"
    assert location.response == "MSA University in Egypt."
    assert_word_limited(location.response)

    creator = engine.answer("who made pluto")
    assert creator.accepted is True
    assert creator.intent == "creator"
    assert creator.response == "Abdelrahman and Hamza built me."
    assert_word_limited(creator.response)

    creator_plain = engine.answer("Who made you?")
    assert creator_plain.accepted is True
    assert creator_plain.intent == "creator"
    assert creator_plain.response == "Abdelrahman and Hamza built me."
    assert_word_limited(creator_plain.response)

    weather = engine.answer("weather")
    assert weather.accepted is True
    assert weather.intent == "weather"
    assert weather.response == "It is slightly hot today."
    assert_word_limited(weather.response)

    script = engine.answer("demo script")
    assert script.accepted is True
    assert script.intent == "script_demo_opening"
    assert script.response_source == "script"
    assert script.response == "Welcome. I am Pluto, your graduation robot."
    assert_word_limited(script.response)

    no_llm = engine.answer("are you chatgpt")
    assert no_llm.accepted is True
    assert no_llm.intent == "not_llm"
    assert no_llm.response == "No LLM. Local matching only."
    assert_word_limited(no_llm.response)

    matching = engine.answer("word matching")
    assert matching.accepted is True
    assert matching.intent == "matching_method"
    assert matching.response == "I match words, aliases, scripts, and fuzziness."
    assert_word_limited(matching.response)

    alias = engine.answer("dashboard pitch")
    assert alias.accepted is True
    assert alias.intent == "script_system_website"
    assert alias.response_source == "script"
    assert_word_limited(alias.response)

    msa_name = engine.answer("what means msa")
    assert msa_name.accepted is True
    assert msa_name.intent == "msa_full_name"
    assert msa_name.response == "October University for Modern Sciences and Arts."
    assert_word_limited(msa_name.response)

    msa_founder = engine.answer("who founded msa")
    assert msa_founder.accepted is True
    assert msa_founder.intent == "msa_founder"
    assert msa_founder.response == "Dr. Nawal El Degwi established MSA."
    assert_word_limited(msa_founder.response)

    msa_faculties = engine.answer("how many faculties")
    assert msa_faculties.accepted is True
    assert msa_faculties.intent == "msa_faculty_count"
    assert msa_faculties.response == "MSA has eleven faculties."
    assert_word_limited(msa_faculties.response)

    msa_address = engine.answer("msa address")
    assert msa_address.accepted is True
    assert msa_address.intent == "msa_address"
    assert msa_address.response == "26 July Mehwar, Wahat Road, 6th October."
    assert_word_limited(msa_address.response)

    msa_hotline = engine.answer("msa hotline")
    assert msa_hotline.accepted is True
    assert msa_hotline.intent == "msa_hotline"
    assert msa_hotline.response == "MSA hotline is 16672."
    assert_word_limited(msa_hotline.response)

    generic_people = engine.answer("How many people?")
    assert generic_people.accepted is True
    assert generic_people.response_source == "fallback"
    assert generic_people.response == "Ask me something simpler please."
    assert generic_people.intent is None

    generic_food = engine.answer("What is your favorite food?")
    assert generic_food.accepted is True
    assert generic_food.response_source == "fallback"
    assert generic_food.response == "Ask me something simpler please."
    assert generic_food.intent is None

    generic_tell = engine.answer("Tell me something")
    assert generic_tell.accepted is True
    assert generic_tell.response_source == "fallback"
    assert generic_tell.response == "Ask me something simpler please."
    assert generic_tell.intent is None

    generic_where = engine.answer("Where are we going?")
    assert generic_where.accepted is True
    assert generic_where.response_source == "fallback"
    assert generic_where.response == "Ask me something simpler please."
    assert generic_where.intent is None

    msa_labs = engine.answer("How many labs does MSA have?")
    assert msa_labs.accepted is True
    assert msa_labs.intent == "msa_labs"
    assert msa_labs.response == "MSA has ninety-three scientific laboratories."
    assert_word_limited(msa_labs.response)

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
    assert status["talk"]["intent_count"] >= 180
    assert status["talk"]["script_count"] >= 30
    assert status["talk"]["response_bank_size"] >= 210
    assert status["talk"]["alias_group_count"] >= 20
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
            [sys.executable, "-m", "pluto_runtime.web_shell", "--host", args.host, "--port", str(args.port), "--wave-pose-disabled"],
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
