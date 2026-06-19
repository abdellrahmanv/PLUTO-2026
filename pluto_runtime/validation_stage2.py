"""Stage 2 real-world validation routines for the Pluto website.

These tests run inside the active web shell process so they reuse the existing
STM32 link, mode manager, camera service, and manual-motion safety path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


PASS = "PASS"
FAIL = "FAIL"
WARNING = "WARNING"
HARDWARE_NOT_DETECTED = "HARDWARE NOT DETECTED"


@dataclass
class Stage2Result:
    status: str
    output: str
    measurements: dict[str, Any] = field(default_factory=dict)
    failure_classification: str | None = None


class Stage2ValidationRunner:
    def __init__(self, context: Any) -> None:
        self.context = context

    def run(self, test_id: str, confirmed: bool = False) -> Stage2Result:
        table = {
            "stm32-stress": self.stm32_stress,
            "bldc-motor-physical": self.bldc_motor_physical,
            "nema-arm-physical": self.nema_arm_physical,
            "camera-live": self.camera_live,
            "human-detection-live": self.human_detection_live,
            "ultrasonic-stop-physical": self.ultrasonic_stop_physical,
            "emergency-stop-physical": self.emergency_stop_physical,
            "battery-safety": self.battery_safety,
            "full-welcome-scenario": self.full_welcome_scenario,
        }
        handler = table.get(test_id)
        if handler is None:
            return Stage2Result(FAIL, f"Unknown Stage 2 validation test: {test_id}", failure_classification="IMPLEMENTATION_FAILURE")
        try:
            return handler(confirmed)
        except Exception as exc:  # noqa: BLE001 - validation must surface exact failure
            self._safe_stop("Stage 2 exception cleanup")
            return Stage2Result(
                FAIL,
                f"Stage 2 validation raised {type(exc).__name__}: {exc}",
                failure_classification="TEST_RUNNER_FAILURE",
            )

    def stm32_stress(self, _confirmed: bool = False) -> Stage2Result:
        if not self._stm32_ready():
            return self._missing("stm32")
        samples = 25
        latencies: list[float] = []
        failures: list[str] = []
        for _ in range(samples):
            started = time.monotonic()
            result = self.context.stm32_link.send_drive(0, 0, timeout_s=0.35)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            if result.get("ok"):
                latencies.append(elapsed_ms)
            else:
                failures.append(str(result.get("detail", "missing ACK")))
            time.sleep(0.03)
        success_rate = len(latencies) / samples if samples else 0.0
        measurements = {
            "samples": samples,
            "success_count": len(latencies),
            "failure_count": len(failures),
            "success_rate": round(success_rate, 3),
            "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "worst_latency_ms": round(max(latencies), 2) if latencies else None,
        }
        status = PASS if success_rate >= 0.96 and (not latencies or max(latencies) <= 250.0) else FAIL
        return Stage2Result(
            status,
            "\n".join([
                "STM32 stress test used neutral CMD:DRIVE:0,0 ACK checks.",
                f"Success {len(latencies)}/{samples}; failures {len(failures)}.",
                *(failures[:5]),
            ]),
            measurements,
            None if status == PASS else "COMMUNICATION_FAILURE",
        )

    def bldc_motor_physical(self, confirmed: bool = False) -> Stage2Result:
        if not confirmed:
            return self._confirmation_required()
        if not self._stm32_ready():
            return self._missing("stm32")
        timeline: list[str] = []
        started = time.monotonic()
        try:
            entered = self.context.request_state("MANUAL")
            timeline.append(f"MANUAL: {entered.get('accepted')} {entered.get('reason')}")
            if not entered.get("accepted"):
                return Stage2Result(FAIL, "\n".join(timeline), {"transition": entered}, "SAFETY_GATE_FAILURE")
            forward = self.context.manual_drive(100, 0)
            timeline.append(f"forward CMD:DRIVE:100,0 -> {forward.get('serial', {}).get('detail')}")
            time.sleep(1.0)
            stop1 = self.context.manual_stop()
            timeline.append(f"stop -> {stop1.get('serial', {}).get('detail')}")
            time.sleep(0.35)
            backward = self.context.manual_drive(-100, 0)
            timeline.append(f"backward CMD:DRIVE:-100,0 -> {backward.get('serial', {}).get('detail')}")
            time.sleep(1.0)
            stop2 = self.context.manual_stop()
            timeline.append(f"stop -> {stop2.get('serial', {}).get('detail')}")
            status = PASS if forward.get("accepted") and backward.get("accepted") and stop1.get("accepted") and stop2.get("accepted") else FAIL
            measurements = {
                "default_speed": 100,
                "duration_s": round(time.monotonic() - started, 3),
                "forward": forward,
                "backward": backward,
                "stop_1": stop1,
                "stop_2": stop2,
                "stm32": self._stm32_snapshot(),
            }
            return Stage2Result(status, "\n".join(timeline), measurements, None if status == PASS else "COMMUNICATION_FAILURE")
        finally:
            self._safe_stop("BLDC physical test cleanup")
            self._return_idle()

    def nema_arm_physical(self, confirmed: bool = False) -> Stage2Result:
        if not confirmed:
            return self._confirmation_required()
        if not self._stm32_ready():
            return self._missing("stm32")
        timeline: list[str] = []
        started = time.monotonic()
        try:
            entered = self.context.request_state("MANUAL")
            timeline.append(f"MANUAL: {entered.get('accepted')} {entered.get('reason')}")
            if not entered.get("accepted"):
                return Stage2Result(FAIL, "\n".join(timeline), {"transition": entered}, "SAFETY_GATE_FAILURE")
            up = self.context.manual_arm(1, 800, 2000)
            timeline.append(f"arm up CMD:ARM:800,2000 -> {up.get('serial', {}).get('detail')}")
            time.sleep(1.0)
            down = self.context.manual_arm(1, -800, 2000)
            timeline.append(f"arm down CMD:ARM:-800,2000 -> {down.get('serial', {}).get('detail')}")
            time.sleep(0.5)
            status = PASS if up.get("accepted") and down.get("accepted") else FAIL
            measurements = {
                "arm": 1,
                "steps_up": 800,
                "steps_down": -800,
                "speed": 2000,
                "duration_s": round(time.monotonic() - started, 3),
                "up": up,
                "down": down,
                "stm32": self._stm32_snapshot(),
            }
            return Stage2Result(status, "\n".join(timeline), measurements, None if status == PASS else "COMMUNICATION_FAILURE")
        finally:
            self._safe_stop("NEMA physical test cleanup")
            self._return_idle()

    def camera_live(self, _confirmed: bool = False) -> Stage2Result:
        camera = self.context.camera_service.get_status()
        if not camera.available:
            return Stage2Result(
                HARDWARE_NOT_DETECTED,
                camera.error or "Camera hardware not detected.",
                {"camera_detected": False, "status": camera.__dict__},
                "HARDWARE_DETECTION_FAILURE",
            )
        stream_active = camera.running and camera.capture_fps > 0
        status = PASS if stream_active else FAIL
        return Stage2Result(
            status,
            f"Camera detected on {camera.device}; stream_fps={camera.stream_fps:.2f}; capture_fps={camera.capture_fps:.2f}",
            {
                "camera_detected": camera.available,
                "stream_active": stream_active,
                "capture_fps": round(camera.capture_fps, 2),
                "stream_fps": round(camera.stream_fps, 2),
                "resolution": camera.resolution,
            },
            None if status == PASS else "COMMUNICATION_FAILURE",
        )

    def human_detection_live(self, _confirmed: bool = False) -> Stage2Result:
        camera = self.context.camera_service.get_status()
        if not camera.available:
            return Stage2Result(HARDWARE_NOT_DETECTED, camera.error or "Camera hardware not detected.", {"camera_detected": False}, "HARDWARE_DETECTION_FAILURE")
        detections = [item.__dict__ for item in camera.detections]
        if not detections:
            return Stage2Result(FAIL, "Camera active but no human detected.", {"human_count": 0, "detections": []}, "PHYSICAL_CONFIRMATION_FAILURE")
        best = max(detections, key=lambda item: float(item.get("confidence", 0.0)))
        return Stage2Result(
            PASS,
            f"Detected {len(detections)} human target(s); best confidence={best.get('confidence')}",
            {"human_count": len(detections), "best_confidence": best.get("confidence"), "best_bbox": best.get("bbox"), "detections": detections},
        )

    def ultrasonic_stop_physical(self, confirmed: bool = False) -> Stage2Result:
        if not confirmed:
            return self._confirmation_required()
        if not self._stm32_ready():
            return self._missing("stm32")
        timeline: list[str] = []
        started = time.monotonic()
        obstacle_seen_at: float | None = None
        try:
            entered = self.context.request_state("MANUAL")
            if not entered.get("accepted"):
                return Stage2Result(FAIL, f"MANUAL blocked: {entered.get('reason')}", {"transition": entered}, "SAFETY_GATE_FAILURE")
            drive = self.context.manual_drive(100, 0)
            timeline.append(f"forward CMD:DRIVE:100,0 -> {drive.get('serial', {}).get('detail')}")
            deadline = time.monotonic() + 8.0
            nearest = None
            while time.monotonic() < deadline:
                obstacles = self._obstacles()
                values = [value for value in obstacles.values() if isinstance(value, (int, float)) and value > 0]
                nearest = min(values) if values else None
                if nearest is not None and nearest < 60:
                    obstacle_seen_at = time.monotonic()
                    timeline.append(f"obstacle detected at {nearest:.1f} cm")
                    break
                time.sleep(0.05)
            stop = self.context.manual_stop()
            stop_latency_ms = (time.monotonic() - obstacle_seen_at) * 1000.0 if obstacle_seen_at is not None else None
            if obstacle_seen_at is None:
                return Stage2Result(FAIL, "\n".join(timeline + ["No obstacle detected before timeout; robot stopped."]), {"nearest_cm": nearest, "duration_s": round(time.monotonic() - started, 3)}, "PHYSICAL_CONFIRMATION_FAILURE")
            return Stage2Result(PASS if stop.get("accepted") else FAIL, "\n".join(timeline + ["stop sent after obstacle detection"]), {"nearest_cm": nearest, "stop_latency_ms": round(stop_latency_ms or 0.0, 2), "stop": stop}, None if stop.get("accepted") else "COMMUNICATION_FAILURE")
        finally:
            self._safe_stop("Ultrasonic physical test cleanup")
            self._return_idle()

    def emergency_stop_physical(self, confirmed: bool = False) -> Stage2Result:
        if not confirmed:
            return self._confirmation_required()
        if not self._stm32_ready():
            return self._missing("stm32")
        started = time.monotonic()
        try:
            entered = self.context.request_state("MANUAL")
            if not entered.get("accepted"):
                return Stage2Result(FAIL, f"MANUAL blocked: {entered.get('reason')}", {"transition": entered}, "SAFETY_GATE_FAILURE")
            drive = self.context.manual_drive(100, 0)
            time.sleep(0.5)
            stop_started = time.monotonic()
            stop = self.context.emergency_stop()
            latency_ms = (time.monotonic() - stop_started) * 1000.0
            status = PASS if stop.get("ok") and stop.get("state") == "ERROR" else FAIL
            return Stage2Result(
                status,
                f"Emergency stop invoked during motion; state={stop.get('state')}; detail={stop.get('serial', {}).get('detail')}",
                {"drive": drive, "stop": stop, "stop_latency_ms": round(latency_ms, 2), "duration_s": round(time.monotonic() - started, 3)},
                None if status == PASS else "SAFETY_GATE_FAILURE",
            )
        finally:
            self._safe_stop("Emergency stop physical test cleanup")

    def battery_safety(self, _confirmed: bool = False) -> Stage2Result:
        if not self._stm32_ready():
            return self._missing("stm32")
        status = self._stm32_snapshot()
        telemetry = status.get("telemetry") or {}
        voltage = telemetry.get("battery_voltage") or telemetry.get("bat_v") or telemetry.get("BAT")
        if voltage is None:
            last_line = str(status.get("last_line") or "")
            voltage = self._parse_tel_value(last_line, "BAT")
        measurements = {"voltage": voltage, "current": telemetry.get("current"), "stm32": status}
        if voltage is None:
            return Stage2Result(WARNING, "Battery telemetry is not currently available.", measurements, "COMMUNICATION_FAILURE")
        try:
            numeric_voltage = float(voltage)
        except (TypeError, ValueError):
            return Stage2Result(WARNING, f"Battery voltage was not numeric: {voltage}", measurements, "COMMUNICATION_FAILURE")
        if numeric_voltage > 1.0 and numeric_voltage < 34.0:
            return Stage2Result(FAIL, f"Battery low: {numeric_voltage:.1f} V", measurements, "SAFETY_GATE_FAILURE")
        return Stage2Result(PASS, f"Battery voltage telemetry: {numeric_voltage:.1f} V", measurements)

    def full_welcome_scenario(self, confirmed: bool = False) -> Stage2Result:
        if not confirmed:
            return self._confirmation_required()
        timeline: list[str] = []
        if not self._stm32_ready():
            return self._missing("stm32")
        camera = self.context.camera_service.get_status()
        if not camera.available:
            return Stage2Result(HARDWARE_NOT_DETECTED, "Camera required for full welcome scenario.", {"camera_detected": False}, "HARDWARE_DETECTION_FAILURE")
        try:
            self.context.request_state("IDLE", reset_fault=True)
            wave = self.context.welcome_wave_trigger(source="validation_full_welcome", diagnostic=True)
            timeline.append(f"trigger accepted={wave.get('accepted')} reason={wave.get('reason')}")
            snapshot = self.context.snapshot()
            timeline.append(f"state={snapshot.current_state}/{snapshot.current_substate}")
            approach = snapshot.welcome_approach
            timeline.append(f"approach={approach.get('proposed_motion')} reason={approach.get('reason')}")
            talk = self.context.welcome_talk("hello pluto", speak=False)
            talk_payload = talk.get("talk") if isinstance(talk.get("talk"), dict) else {}
            timeline.append(f"talk intent={talk_payload.get('intent')} response={talk.get('display_response')}")
            returned = self.context.request_state("IDLE")
            timeline.append(f"return IDLE accepted={returned.get('accepted')}")
            status = PASS if wave.get("accepted") and returned.get("accepted") else FAIL
            classification = None if status == PASS else "SAFETY_GATE_FAILURE"
            if approach.get("dry_run", True):
                status = WARNING if status == PASS else status
                classification = "IMPLEMENTATION_FAILURE" if status == WARNING else classification
                timeline.append("WELCOME approach remains dry-run; physical return behavior not executed.")
            return Stage2Result(status, "\n".join(timeline), {"wave": wave, "approach": approach, "talk": talk, "return": returned}, classification)
        finally:
            self._safe_stop("Full welcome scenario cleanup")
            self._return_idle()

    def _stm32_ready(self) -> bool:
        hardware = self.context.hardware.get("stm32")
        return bool(hardware and hardware.connected and self.context.stm32_link is not None)

    def _missing(self, key: str) -> Stage2Result:
        return Stage2Result(HARDWARE_NOT_DETECTED, f"{key} hardware not detected.", {"missing_hardware": [key]}, "HARDWARE_DETECTION_FAILURE")

    @staticmethod
    def _confirmation_required() -> Stage2Result:
        return Stage2Result(WARNING, "Physical motion test requires operator confirmation.", {"requires_confirmation": True}, "PHYSICAL_CONFIRMATION_FAILURE")

    def _safe_stop(self, reason: str) -> None:
        try:
            self.context.manual.speed_intent = 0
            self.context.manual.steer_intent = 0
            self.context.send_manual_neutral(reason)
            self.context.send_stm32_stop_safe(self.context.hardware["stm32"].port)
        except Exception:
            pass

    def _return_idle(self) -> None:
        try:
            if self.context.mode_manager.current_state != "IDLE":
                self.context.request_state("IDLE", reset_fault=True)
        except Exception:
            pass

    def _stm32_snapshot(self) -> dict[str, Any]:
        if self.context.stm32_link is None:
            return {}
        try:
            from .stm32_link import status_to_dict

            return status_to_dict(self.context.stm32_link.get_status())
        except Exception:
            return {}

    def _obstacles(self) -> dict[str, float]:
        status = self._stm32_snapshot()
        obstacles = status.get("obstacles")
        return obstacles if isinstance(obstacles, dict) else {}

    @staticmethod
    def _parse_tel_value(line: str, key: str) -> float | None:
        prefix = f"{key}:"
        for part in line.split(","):
            if part.startswith(prefix):
                try:
                    return float(part[len(prefix) :])
                except ValueError:
                    return None
        return None
