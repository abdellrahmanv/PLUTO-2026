#!/usr/bin/env python3
"""Smoke tests for Pluto Phase 5 mode manager."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pluto_runtime.mode_manager import ModeManager, SafetyContext


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_false(value: bool, message: str) -> None:
    if value:
        raise AssertionError(message)


def main() -> int:
    manager = ModeManager()

    result = manager.bootstrap_complete(True, "test bootstrap pass")
    assert_true(result.accepted, "BOOTSTRAP -> IDLE should pass")
    assert_true(manager.current_state == "IDLE", "state should be IDLE after bootstrap")

    no_stm32 = SafetyContext(stm32_available=False, operator_request=True)
    result = manager.request_transition("MANUAL", no_stm32, source="test")
    assert_false(result.accepted, "IDLE -> MANUAL should fail without STM32")
    assert_true("stm32_unavailable" in result.blocked_by, "STM32 gate should block motion")

    safe_operator = SafetyContext(stm32_available=True, operator_request=True)
    result = manager.request_transition("MANUAL", safe_operator, source="test")
    assert_true(result.accepted, "IDLE -> MANUAL should pass with STM32")
    assert_true(result.requires_stop, "entering MANUAL should require stop guard")

    nonzero_motion = SafetyContext(stm32_available=True, motion_intent_zero=False)
    result = manager.request_transition("IDLE", nonzero_motion, source="test")
    assert_false(result.accepted, "MANUAL -> IDLE should fail while motion intent is nonzero")

    zero_motion = SafetyContext(stm32_available=True, motion_intent_zero=True)
    result = manager.request_transition("IDLE", zero_motion, source="test")
    assert_true(result.accepted, "MANUAL -> IDLE should pass after motion intent is zero")

    result = manager.request_transition("WELCOME", SafetyContext(stm32_available=True), source="test")
    assert_false(result.accepted, "IDLE -> WELCOME should require confirmed trigger")

    result = manager.request_transition(
        "WELCOME",
        SafetyContext(stm32_available=True, welcome_trigger_confirmed=True),
        source="test",
    )
    assert_true(result.accepted, "IDLE -> WELCOME should pass with confirmed trigger")

    manager.set_substate("WELCOME_RETURN", return_lock=True)
    result = manager.request_transition("MANUAL", SafetyContext(stm32_available=True), source="test")
    assert_false(result.accepted, "WELCOME_RETURN should block MANUAL")
    assert_true("welcome_return_lock" in result.blocked_by, "return lock should be visible")

    result = manager.request_transition("ERROR", SafetyContext(fault_reason="test fault"), source="test")
    assert_true(result.accepted, "ERROR should interrupt WELCOME_RETURN")

    result = manager.request_transition(
        "IDLE",
        SafetyContext(stm32_available=True),
        source="test",
        reset_fault=False,
    )
    assert_false(result.accepted, "ERROR -> IDLE should require explicit reset")

    result = manager.request_transition(
        "IDLE",
        SafetyContext(stm32_available=True),
        source="test",
        reset_fault=True,
    )
    assert_true(result.accepted, "ERROR -> IDLE should pass with explicit reset and STM32")

    result = manager.request_transition("GAME_LATER", SafetyContext(stm32_available=True), source="test")
    assert_false(result.accepted, "GAME_LATER must not be reachable in v1")

    print("MODE_MANAGER_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
