#!/usr/bin/env python3
"""Website-facing validation catalog and runner for existing Pluto tools."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .validation_stage2 import HARDWARE_NOT_DETECTED, Stage2ValidationRunner


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ValidationTest:
    test_id: str
    name: str
    category: str
    safety_level: str
    required_hardware: tuple[str, ...]
    script_args: tuple[str, ...]
    button_label: str
    timeout_s: float
    dry_run_only: bool = False
    stage: str = "Stage 1"
    requires_confirmation: bool = False
    physical_motion: bool = False
    runtime_test: bool = False

    @property
    def terminal_command(self) -> str:
        return "python " + " ".join(self.script_args)

    def command(self, python_executable: str) -> list[str]:
        return [python_executable, *self.script_args]


@dataclass
class ValidationResult:
    test_id: str
    name: str
    category: str
    status: str
    terminal_command: str
    command: list[str]
    started_at: float
    duration_s: float
    timeout_s: float
    returncode: int | None
    output: str
    measurements: dict[str, Any] = field(default_factory=dict)
    warning: str | None = None
    failure_classification: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


TESTS: tuple[ValidationTest, ...] = (
    ValidationTest(
        test_id="stm32-communication",
        name="STM32 Communication Test",
        category="Communication Tests",
        safety_level="hardware-safe",
        required_hardware=("stm32",),
        script_args=("tools/stm32_probe.py",),
        button_label="Run STM32",
        timeout_s=90,
    ),
    ValidationTest(
        test_id="stm32-runtime-heartbeat",
        name="Raspberry Pi STM32 Runtime Heartbeat Test",
        category="Communication Tests",
        safety_level="hardware-safe",
        required_hardware=("stm32",),
        script_args=("tools/idle_runtime_smoke.py", "--require-hardware"),
        button_label="Run Heartbeat",
        timeout_s=90,
    ),
    ValidationTest(
        test_id="stm32-stress",
        name="Raspberry Pi STM32 Stress Test",
        category="Communication Tests",
        safety_level="hardware-safe",
        required_hardware=("stm32",),
        script_args=("tools/validation_stage2_runner.py", "--test", "stm32-stress"),
        button_label="Run Stress",
        timeout_s=30,
        stage="Stage 2",
        runtime_test=True,
    ),
    ValidationTest(
        test_id="uno-communication",
        name="Arduino Uno Communication Test",
        category="Communication Tests",
        safety_level="hardware-safe",
        required_hardware=("uno",),
        script_args=("tools/uno_probe.py",),
        button_label="Run Uno",
        timeout_s=90,
    ),
    ValidationTest(
        test_id="welcome-approach-dry-run",
        name="Welcome Approach Motion Dry Run",
        category="Motion Tests",
        safety_level="dry-run",
        required_hardware=(),
        script_args=("tools/welcome_approach_smoke.py",),
        button_label="Run Approach",
        timeout_s=60,
        dry_run_only=True,
    ),
    ValidationTest(
        test_id="dance-dry-run",
        name="Dance Motion Dry Run",
        category="Motion Tests",
        safety_level="dry-run",
        required_hardware=(),
        script_args=("tools/dance_smoke.py",),
        button_label="Run Dance",
        timeout_s=60,
        dry_run_only=True,
    ),
    ValidationTest(
        test_id="bldc-motor-physical",
        name="Physical BLDC Motor Test",
        category="Motion Tests",
        safety_level="physical-motion",
        required_hardware=("stm32",),
        script_args=("tools/validation_stage2_runner.py", "--test", "bldc-motor-physical", "--confirm-physical"),
        button_label="Run BLDC",
        timeout_s=20,
        stage="Stage 2",
        requires_confirmation=True,
        physical_motion=True,
        runtime_test=True,
    ),
    ValidationTest(
        test_id="nema-arm-physical",
        name="Physical NEMA Arm Test",
        category="Motion Tests",
        safety_level="physical-motion",
        required_hardware=("stm32",),
        script_args=("tools/validation_stage2_runner.py", "--test", "nema-arm-physical", "--confirm-physical"),
        button_label="Run Arm",
        timeout_s=20,
        stage="Stage 2",
        requires_confirmation=True,
        physical_motion=True,
        runtime_test=True,
    ),
    ValidationTest(
        test_id="camera-live",
        name="Live Camera Test",
        category="Perception Tests",
        safety_level="hardware-safe",
        required_hardware=("camera",),
        script_args=("tools/validation_stage2_runner.py", "--test", "camera-live"),
        button_label="Run Camera",
        timeout_s=15,
        stage="Stage 2",
        runtime_test=True,
    ),
    ValidationTest(
        test_id="human-detection-live",
        name="Live Human Detection Test",
        category="Perception Tests",
        safety_level="hardware-safe",
        required_hardware=("camera",),
        script_args=("tools/validation_stage2_runner.py", "--test", "human-detection-live"),
        button_label="Run Human",
        timeout_s=20,
        stage="Stage 2",
        runtime_test=True,
    ),
    ValidationTest(
        test_id="wave-detection",
        name="Wave Detection Test",
        category="Perception Tests",
        safety_level="software-safe",
        required_hardware=(),
        script_args=("tools/welcome_wave_smoke.py",),
        button_label="Run Wave",
        timeout_s=90,
    ),
    ValidationTest(
        test_id="speaker",
        name="Speaker Test",
        category="Audio Tests",
        safety_level="hardware-safe",
        required_hardware=("speaker",),
        script_args=("tools/audio_io_smoke.py", "--require-speaker"),
        button_label="Run Speaker",
        timeout_s=90,
    ),
    ValidationTest(
        test_id="microphone",
        name="Microphone Test",
        category="Audio Tests",
        safety_level="hardware-safe",
        required_hardware=("microphone",),
        script_args=("tools/audio_io_smoke.py", "--require-microphone"),
        button_label="Run Mic",
        timeout_s=90,
    ),
    ValidationTest(
        test_id="ai-voice",
        name="AI Voice Test",
        category="Audio Tests",
        safety_level="software-safe",
        required_hardware=(),
        script_args=("tools/welcome_talk_smoke.py",),
        button_label="Run Voice",
        timeout_s=90,
    ),
    ValidationTest(
        test_id="emergency-stop",
        name="Emergency Stop Test",
        category="Safety Tests",
        safety_level="software-safe",
        required_hardware=(),
        script_args=("tools/error_state_smoke.py",),
        button_label="Run E-Stop",
        timeout_s=90,
    ),
    ValidationTest(
        test_id="ultrasonic-stop-physical",
        name="Physical Ultrasonic Stop Test",
        category="Safety Tests",
        safety_level="physical-motion",
        required_hardware=("stm32",),
        script_args=("tools/validation_stage2_runner.py", "--test", "ultrasonic-stop-physical", "--confirm-physical"),
        button_label="Run Ultrasonic",
        timeout_s=25,
        stage="Stage 2",
        requires_confirmation=True,
        physical_motion=True,
        runtime_test=True,
    ),
    ValidationTest(
        test_id="emergency-stop-physical",
        name="Physical Emergency Stop Test",
        category="Safety Tests",
        safety_level="physical-motion",
        required_hardware=("stm32",),
        script_args=("tools/validation_stage2_runner.py", "--test", "emergency-stop-physical", "--confirm-physical"),
        button_label="Run E-Stop Live",
        timeout_s=20,
        stage="Stage 2",
        requires_confirmation=True,
        physical_motion=True,
        runtime_test=True,
    ),
    ValidationTest(
        test_id="battery-safety",
        name="Battery Safety Test",
        category="Safety Tests",
        safety_level="hardware-safe",
        required_hardware=("stm32",),
        script_args=("tools/validation_stage2_runner.py", "--test", "battery-safety"),
        button_label="Run Battery",
        timeout_s=15,
        stage="Stage 2",
        runtime_test=True,
    ),
    ValidationTest(
        test_id="operator-website-safety",
        name="Operator Website Safety Test",
        category="Safety Tests",
        safety_level="software-safe",
        required_hardware=(),
        script_args=("tools/web_shell_smoke.py",),
        button_label="Run Website",
        timeout_s=90,
    ),
    ValidationTest(
        test_id="mode-transition",
        name="Mode Transition Test",
        category="System Tests",
        safety_level="software-safe",
        required_hardware=(),
        script_args=("tools/mode_manager_smoke.py",),
        button_label="Run Modes",
        timeout_s=60,
    ),
    ValidationTest(
        test_id="hardware-detection",
        name="Hardware Detection Test",
        category="System Tests",
        safety_level="software-safe",
        required_hardware=(),
        script_args=("tools/idle_runtime_smoke.py",),
        button_label="Run Detect",
        timeout_s=60,
    ),
    ValidationTest(
        test_id="full-welcome-scenario",
        name="Full Welcome Scenario Test",
        category="System Tests",
        safety_level="physical-motion",
        required_hardware=("stm32", "camera"),
        script_args=("tools/validation_stage2_runner.py", "--test", "full-welcome-scenario", "--confirm-physical"),
        button_label="Run Welcome",
        timeout_s=45,
        stage="Stage 2",
        requires_confirmation=True,
        physical_motion=True,
        runtime_test=True,
    ),
)


class ValidationCenter:
    def __init__(self, python_executable: str | None = None) -> None:
        self.python_executable = python_executable or sys.executable
        self._tests = {item.test_id: item for item in TESTS}
        self._last_results: dict[str, ValidationResult] = {}
        self._lock = threading.RLock()

    def catalog(self, hardware: dict[str, Any] | None = None) -> dict[str, Any]:
        hardware = hardware or {}
        with self._lock:
            tests = [self._test_payload(test, hardware) for test in TESTS]
        return {
            "name": "Validation Center",
            "stage": "Stage 2",
            "tests": tests,
            "categories": sorted({test.category for test in TESTS}),
        }

    def run(self, test_id: str, hardware: dict[str, Any] | None = None, context: Any | None = None, confirmed: bool = False) -> ValidationResult:
        test = self._tests.get(test_id)
        if test is None:
            raise KeyError(f"unknown validation test: {test_id}")

        hardware = hardware or {}
        missing = self.missing_hardware(test, hardware)
        if missing:
            result = ValidationResult(
                test_id=test.test_id,
                name=test.name,
                category=test.category,
                status=HARDWARE_NOT_DETECTED,
                terminal_command=test.terminal_command,
                command=test.command(self.python_executable),
                started_at=time.time(),
                duration_s=0.0,
                timeout_s=test.timeout_s,
                returncode=None,
                output=f"HARDWARE NOT DETECTED: {', '.join(missing)}",
                measurements={"missing_hardware": missing},
                warning="required hardware missing",
                failure_classification="HARDWARE_DETECTION_FAILURE",
            )
            with self._lock:
                self._last_results[test.test_id] = result
            return result

        started_wall = time.time()
        started = time.monotonic()
        command = test.command(self.python_executable)
        if test.runtime_test:
            if context is None:
                result = ValidationResult(
                    test_id=test.test_id,
                    name=test.name,
                    category=test.category,
                    status="FAIL",
                    terminal_command=test.terminal_command,
                    command=command,
                    started_at=started_wall,
                    duration_s=0.0,
                    timeout_s=test.timeout_s,
                    returncode=None,
                    output="Runtime validation requires active website context.",
                    measurements={},
                    failure_classification="TEST_RUNNER_FAILURE",
                )
            else:
                stage2 = Stage2ValidationRunner(context).run(test.test_id, confirmed=confirmed)
                duration = time.monotonic() - started
                result = ValidationResult(
                    test_id=test.test_id,
                    name=test.name,
                    category=test.category,
                    status=stage2.status,
                    terminal_command=test.terminal_command,
                    command=command,
                    started_at=started_wall,
                    duration_s=duration,
                    timeout_s=test.timeout_s,
                    returncode=0 if stage2.status == "PASS" else None,
                    output=stage2.output,
                    measurements={"duration_s": round(duration, 3), **stage2.measurements},
                    warning=stage2.failure_classification if stage2.status == "WARNING" else None,
                    failure_classification=stage2.failure_classification,
                )
            with self._lock:
                self._last_results[test.test_id] = result
            return result

        try:
            proc = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=test.timeout_s,
            )
            duration = time.monotonic() - started
            output = self._combine_output(proc.stdout, proc.stderr)
            status = "PASS" if proc.returncode == 0 else "FAIL"
            warning = None
            if proc.returncode == 0 and (" SKIP" in output or "OPTIONAL_FAIL" in output):
                status = "WARNING"
                warning = "test reported skipped or optional failure evidence"
            result = ValidationResult(
                test_id=test.test_id,
                name=test.name,
                category=test.category,
                status=status,
                terminal_command=test.terminal_command,
                command=command,
                started_at=started_wall,
                duration_s=duration,
                timeout_s=test.timeout_s,
                returncode=proc.returncode,
                output=output,
                measurements={
                    "duration_s": round(duration, 3),
                    "returncode": proc.returncode,
                    "stdout_lines": len(proc.stdout.splitlines()),
                    "stderr_lines": len(proc.stderr.splitlines()),
                },
                warning=warning,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            result = ValidationResult(
                test_id=test.test_id,
                name=test.name,
                category=test.category,
                status="FAIL",
                terminal_command=test.terminal_command,
                command=command,
                started_at=started_wall,
                duration_s=duration,
                timeout_s=test.timeout_s,
                returncode=124,
                output=self._combine_output(exc.stdout or "", exc.stderr or "") + f"\nTimeout after {test.timeout_s:.0f}s",
                measurements={"duration_s": round(duration, 3), "returncode": 124, "timeout_s": test.timeout_s},
                warning="timeout",
                failure_classification="TEST_RUNNER_FAILURE",
            )

        with self._lock:
            self._last_results[test.test_id] = result
        return result

    def _test_payload(self, test: ValidationTest, hardware: dict[str, Any]) -> dict[str, Any]:
        missing = self.missing_hardware(test, hardware)
        last = self._last_results.get(test.test_id)
        return {
            "id": test.test_id,
            "name": test.name,
            "category": test.category,
            "safety_level": test.safety_level,
            "required_hardware": list(test.required_hardware),
            "terminal_command": test.terminal_command,
            "button_label": test.button_label,
            "timeout_s": test.timeout_s,
            "dry_run_only": test.dry_run_only,
            "stage": test.stage,
            "requires_confirmation": test.requires_confirmation,
            "physical_motion": test.physical_motion,
            "enabled": not missing,
            "blocked_reason": f"HARDWARE NOT DETECTED: {', '.join(missing)}" if missing else "",
            "last_result": last.to_dict() if last else None,
        }

    @staticmethod
    def missing_hardware(test: ValidationTest, hardware: dict[str, Any]) -> list[str]:
        return [item for item in test.required_hardware if not ValidationCenter.hardware_connected(hardware, item)]

    @staticmethod
    def hardware_connected(hardware: dict[str, Any], key: str) -> bool:
        item = hardware.get(key)
        if item is None:
            return False
        if isinstance(item, dict):
            return bool(item.get("connected"))
        return bool(getattr(item, "connected", False))

    @staticmethod
    def _combine_output(stdout: str, stderr: str) -> str:
        if stdout and stderr:
            return stdout.rstrip() + "\n\n[stderr]\n" + stderr.rstrip()
        return (stdout or stderr or "").rstrip()
