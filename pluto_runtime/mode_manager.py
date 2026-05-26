"""Phase 5 mode manager for Pluto.

The mode manager is deliberately hardware-light. It owns transition rules and
returns action requirements, while callers such as the web shell perform serial
I/O and record evidence.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


VALID_STATES = ("BOOTSTRAP", "IDLE", "MANUAL", "WELCOME", "DANCE", "ERROR", "GAME_LATER")
MOTION_STATES = {"MANUAL", "WELCOME", "DANCE"}
IMPLEMENTED_V1_STATES = {"BOOTSTRAP", "IDLE", "MANUAL", "WELCOME", "DANCE", "ERROR"}


@dataclass(frozen=True)
class SafetyContext:
    stm32_available: bool = False
    battery_critical: bool = False
    motion_intent_zero: bool = True
    welcome_trigger_confirmed: bool = False
    operator_request: bool = False
    return_lock: bool = False
    fault_active: bool = False
    fault_reason: str | None = None


@dataclass
class TransitionRecord:
    timestamp: float
    previous_state: str
    previous_substate: str
    requested_state: str
    accepted: bool
    next_state: str
    next_substate: str
    reason: str
    source: str
    requires_stop: bool = False
    blocked_by: list[str] = field(default_factory=list)
    fault_reason: str | None = None


@dataclass
class TransitionResult:
    accepted: bool
    previous_state: str
    current_state: str
    previous_substate: str
    current_substate: str
    requested_state: str
    reason: str
    source: str
    requires_stop: bool = False
    blocked_by: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModeManager:
    """Traceable Pluto runtime state machine."""

    def __init__(self) -> None:
        self.current_state = "BOOTSTRAP"
        self.current_substate = "BOOTSTRAP_START"
        self.fault_reason: str | None = None
        self.return_lock = False
        self.transition_log: list[TransitionRecord] = []

    def bootstrap_complete(self, required_ok: bool, reason: str = "bootstrap complete") -> TransitionResult:
        target = "IDLE" if required_ok else "ERROR"
        ctx = SafetyContext(
            stm32_available=required_ok,
            operator_request=False,
            fault_active=not required_ok,
            fault_reason=None if required_ok else reason,
        )
        return self.request_transition(target, ctx, source="bootstrap", reason=reason, reset_fault=required_ok)

    def enter_error(self, reason: str, source: str = "runtime") -> TransitionResult:
        ctx = SafetyContext(fault_active=True, fault_reason=reason)
        return self.request_transition("ERROR", ctx, source=source, reason=reason)

    def set_substate(self, substate: str, return_lock: bool | None = None) -> None:
        self.current_substate = substate
        if return_lock is not None:
            self.return_lock = return_lock

    def request_transition(
        self,
        target_state: str,
        context: SafetyContext,
        source: str = "operator",
        reason: str = "",
        reset_fault: bool = False,
    ) -> TransitionResult:
        target = target_state.strip().upper()
        previous_state = self.current_state
        previous_substate = self.current_substate
        timestamp = time.time()

        accepted, decision_reason, blocked_by = self._validate(target, context, reset_fault)
        requires_stop = accepted and self._requires_stop(previous_state, target)

        if accepted:
            self.current_state = target
            self.current_substate = self._entry_substate(target)
            self.return_lock = target == "WELCOME" and self.current_substate == "WELCOME_RETURN"
            self.fault_reason = context.fault_reason if target == "ERROR" else None
        elif target == "ERROR" and context.fault_reason:
            self.fault_reason = context.fault_reason

        final_reason = reason or decision_reason
        record = TransitionRecord(
            timestamp=timestamp,
            previous_state=previous_state,
            previous_substate=previous_substate,
            requested_state=target,
            accepted=accepted,
            next_state=self.current_state,
            next_substate=self.current_substate,
            reason=final_reason if accepted else decision_reason,
            source=source,
            requires_stop=requires_stop,
            blocked_by=blocked_by,
            fault_reason=self.fault_reason,
        )
        self.transition_log.append(record)
        self.transition_log = self.transition_log[-120:]

        return TransitionResult(
            accepted=accepted,
            previous_state=previous_state,
            current_state=self.current_state,
            previous_substate=previous_substate,
            current_substate=self.current_substate,
            requested_state=target,
            reason=record.reason,
            source=source,
            requires_stop=requires_stop,
            blocked_by=blocked_by,
            timestamp=timestamp,
        )

    def allowed_next_states(self, context: SafetyContext) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for state in VALID_STATES:
            if state == self.current_state:
                rows.append({"state": state, "allowed": False, "reason": "current state"})
                continue
            allowed, reason, blocked_by = self._validate(state, context, reset_fault=False)
            rows.append({"state": state, "allowed": allowed, "reason": reason, "blocked_by": blocked_by})
        return rows

    def snapshot(self, context: SafetyContext | None = None) -> dict[str, Any]:
        ctx = context or SafetyContext()
        return {
            "current_state": self.current_state,
            "current_substate": self.current_substate,
            "fault_reason": self.fault_reason,
            "return_lock": self.return_lock,
            "allowed_next_states": self.allowed_next_states(ctx),
            "transition_log": [asdict(item) for item in self.transition_log[-20:]],
        }

    def _validate(self, target: str, context: SafetyContext, reset_fault: bool) -> tuple[bool, str, list[str]]:
        blocked_by: list[str] = []

        if target not in VALID_STATES:
            return False, "unknown state", ["invalid_state"]

        if target == "GAME_LATER":
            return False, "GAME_LATER is documented but not reachable in v1", ["game_later"]

        if self.return_lock or context.return_lock or self.current_substate == "WELCOME_RETURN":
            if target != "ERROR":
                return False, "WELCOME_RETURN blocks all non-error transitions", ["welcome_return_lock"]

        if target == "ERROR":
            return True, context.fault_reason or "ERROR may interrupt any state", []

        if target == self.current_state:
            return False, "current state", ["current_state"]

        if self.current_state == "BOOTSTRAP":
            if target == "IDLE":
                if context.fault_active:
                    return False, "bootstrap fault is still active", ["fault_active"]
                return True, "bootstrap completed and runtime may enter IDLE", []
            return False, "BOOTSTRAP may only exit to IDLE or ERROR", ["bootstrap_gate"]

        if self.current_state == "ERROR":
            if target != "IDLE":
                return False, "ERROR only allows explicit reset to IDLE", ["error_reset_required"]
            if not reset_fault:
                return False, "ERROR reset requires explicit operator reset", ["error_reset_required"]
            if not context.stm32_available:
                return False, "cannot reset ERROR because STM32 is unavailable", ["stm32_unavailable"]
            if context.battery_critical:
                return False, "cannot reset ERROR because battery is critical", ["battery_critical"]
            if context.fault_active:
                return False, "cannot reset ERROR while fault remains active", ["fault_active"]
            return True, "ERROR reset accepted after safety checks", []

        if target in MOTION_STATES:
            if not context.stm32_available:
                blocked_by.append("stm32_unavailable")
            if context.battery_critical:
                blocked_by.append("battery_critical")
            if context.fault_active:
                blocked_by.append("fault_active")
            if blocked_by:
                return False, "motion state blocked by safety gate", blocked_by

        if self.current_state == "IDLE":
            if target == "MANUAL":
                return True, "operator selected MANUAL from IDLE", []
            if target == "WELCOME":
                if context.welcome_trigger_confirmed or context.operator_request:
                    return True, "confirmed WELCOME trigger accepted", []
                return False, "WELCOME requires confirmed trigger", ["welcome_trigger_missing"]
            if target == "DANCE":
                if context.operator_request:
                    return True, "operator selected DANCE from IDLE", []
                return False, "DANCE requires explicit operator request", ["operator_request_missing"]
            return False, "IDLE only exits to MANUAL, WELCOME, DANCE, or ERROR", ["idle_transition_gate"]

        if self.current_state == "MANUAL":
            if target == "IDLE":
                if not context.motion_intent_zero:
                    return False, "MANUAL cannot exit while nonzero motion intent exists", ["motion_intent_nonzero"]
                return True, "manual control released to IDLE", []
            return False, "MANUAL v1 exits only to IDLE or ERROR", ["manual_transition_gate"]

        if self.current_state == "WELCOME":
            if target == "IDLE":
                return True, "WELCOME completed or was safely aborted to IDLE", []
            return False, "WELCOME v1 exits only to IDLE or ERROR", ["welcome_transition_gate"]

        if self.current_state == "DANCE":
            if target == "IDLE":
                return True, "DANCE stopped and returns to IDLE", []
            return False, "DANCE v1 exits only to IDLE or ERROR", ["dance_transition_gate"]

        return False, "transition is not defined", ["undefined_transition"]

    @staticmethod
    def _entry_substate(target: str) -> str:
        return {
            "BOOTSTRAP": "BOOTSTRAP_START",
            "IDLE": "IDLE_READY",
            "MANUAL": "MANUAL_READY",
            "WELCOME": "WELCOME_DETECT",
            "DANCE": "DANCE_READY",
            "ERROR": "ERROR_ACTIVE",
        }.get(target, "UNKNOWN")

    @staticmethod
    def _requires_stop(previous_state: str, target: str) -> bool:
        return previous_state in MOTION_STATES or target in MOTION_STATES or target in {"IDLE", "ERROR"}
