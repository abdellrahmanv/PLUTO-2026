#!/usr/bin/env python3
"""
Phase 6 PLUTO operator website shell.

This is intentionally not the final app. It provides the first safe operator
console surface: project identity, state/status display, hardware status,
events, blocked state requests, and emergency stop wiring.
"""

from __future__ import annotations

import argparse
import glob
import json
import platform
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable
from urllib.parse import urlparse

from .audio_io import AudioRuntime
from .camera import CameraService, status_to_dict
from .mode_manager import SafetyContext, ModeManager, VALID_STATES
from .stm32_link import Stm32SerialLink, status_to_dict as stm32_status_to_dict
from .welcome_talk import TalkResult, WelcomeTalkEngine


PROJECT_NAME = "PLUTO"
STM32_ID = "ID:STM32_MOTOR"
UNO_ID = "ID:UNO_LCD"


@dataclass
class HardwareDevice:
    name: str
    required: bool
    connected: bool = False
    port: str | None = None
    status: str = "unknown"
    detail: str = "not checked"
    latency_ms: float | None = None
    last_seen: float | None = None


@dataclass
class Event:
    timestamp: float
    level: str
    message: str


@dataclass
class PlutoStatus:
    project: str = PROJECT_NAME
    current_state: str = "BOOTSTRAP"
    current_substate: str = "WEB_SHELL"
    fault_reason: str | None = None
    git_commit: str = "unknown"
    started_at: float = field(default_factory=time.time)
    hardware: dict[str, HardwareDevice] = field(default_factory=dict)
    allowed_next_states: list[dict[str, Any]] = field(default_factory=list)
    bootstrap_report: dict[str, Any] = field(default_factory=dict)
    camera: dict[str, Any] = field(default_factory=dict)
    mode_manager: dict[str, Any] = field(default_factory=dict)
    stm32_runtime: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)
    manual: dict[str, Any] = field(default_factory=dict)
    talk: dict[str, Any] = field(default_factory=dict)
    audio: dict[str, Any] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)


@dataclass
class ManualRuntime:
    enabled: bool = False
    speed_intent: int = 0
    steer_intent: int = 0
    max_speed: int = 80
    max_steer: int = 80
    command_period_ms: int = 150
    last_command_at: float | None = None
    last_release_at: float | None = None
    last_result: dict[str, Any] = field(default_factory=dict)
    command_count: int = 0
    blocked_reason: str | None = None


class PlutoWebContext:
    def __init__(
        self,
        serial_baud: int = 115200,
        camera_device: str | None = None,
        camera_resolution: tuple[int, int] = (320, 320),
        camera_fps: int = 30,
        camera_stream_fps: int = 8,
        camera_frame_skip: int = 1,
        camera_detection_hold: float = 2.0,
        camera_confidence: float = 0.30,
        yolo_model: str | None = None,
    ) -> None:
        self.serial_baud = serial_baud
        self.lock = threading.RLock()
        self.events: deque[Event] = deque(maxlen=80)
        self.started_at = time.time()
        self.mode_manager = ModeManager()
        self.stm32_link: Stm32SerialLink | None = None
        self.manual = ManualRuntime()
        self.talk_engine = WelcomeTalkEngine()
        self.talk_last_result: TalkResult | None = None
        self.talk_history: deque[TalkResult] = deque(maxlen=20)
        self.talk_last_notice = "Enter WELCOME, then ask a short question."
        self.audio_runtime = AudioRuntime()
        self.last_alert_escalated: str | None = None
        self.git_commit = read_git_commit()
        self.hardware = {
            "stm32": HardwareDevice("STM32 motor safety controller", True),
            "uno": HardwareDevice("Uno LCD face controller", False),
            "camera": HardwareDevice("Camera", False, status="starting", detail="Phase 4"),
            "speaker": HardwareDevice("Speaker", False, status="starting", detail="Phase 9 audio"),
            "microphone": HardwareDevice("Microphone", False, status="starting", detail="Phase 9 audio"),
        }
        self.log("info", "PLUTO web shell starting")
        self.camera_service = CameraService(
            device=camera_device,
            resolution=camera_resolution,
            framerate=camera_fps,
            stream_fps=camera_stream_fps,
            frame_skip=camera_frame_skip,
            detection_hold_s=camera_detection_hold,
            confidence_threshold=camera_confidence,
            model_path=yolo_model,
        )
        if self.camera_service.start():
            self.log("pass", "Camera service started")
        else:
            self.log("warn", f"Camera unavailable: {self.camera_service.get_status().error}")
        self.refresh_hardware()

    def log(self, level: str, message: str) -> None:
        with self.lock:
            self.events.appendleft(Event(time.time(), level, message))

    def refresh_hardware(self) -> None:
        self.stop_stm32_link()
        ports = candidate_ports()
        self.log("info", f"Scanning serial ports: {', '.join(ports) if ports else 'none'}")

        stm32 = probe_stm32(ports, self.serial_baud)
        uno = probe_uno(ports, self.serial_baud, skip_port=stm32.port if stm32.connected else None)
        audio_status = self.audio_runtime.probe()

        with self.lock:
            self.hardware["stm32"] = stm32
            self.hardware["uno"] = uno
            camera_status = self.camera_service.get_status()
            self.hardware["camera"] = HardwareDevice(
                "Camera",
                False,
                connected=camera_status.available,
                port=str(camera_status.device) if camera_status.device is not None else None,
                status="connected" if camera_status.available else "unavailable",
                detail=camera_status.error or f"{camera_status.backend} {camera_status.resolution}",
                last_seen=time.time() if camera_status.available else None,
            )
            self.hardware["microphone"] = HardwareDevice(
                "Microphone",
                False,
                connected=audio_status.microphone_available,
                port=audio_status.selected_microphone,
                status="connected" if audio_status.microphone_available else "unavailable",
                detail=audio_status.stt_detail if audio_status.microphone_available else "no capture device selected",
                last_seen=time.time() if audio_status.microphone_available else None,
            )
            self.hardware["speaker"] = HardwareDevice(
                "Speaker",
                False,
                connected=audio_status.speaker_available,
                port=audio_status.selected_speaker,
                status="connected" if audio_status.speaker_available else "unavailable",
                detail=audio_status.tts_detail if audio_status.speaker_available else "no playback device selected",
                last_seen=time.time() if audio_status.speaker_available else None,
            )
            self.bootstrap_report = {
                "phase": "Phase 9 WELCOME talk/audio baseline",
                "serial_ports": ports,
                "required_hardware": {"stm32": asdict(stm32)},
                "optional_hardware": {
                    "uno": asdict(uno),
                    "camera": status_to_dict(camera_status),
                    "audio": audio_status.to_dict(),
                },
                "notes": [
                    "Website shell does not enable motion states.",
                    "Emergency stop sends CMD:STOP when STM32 is available.",
                    "IDLE runtime keeps STM32 heartbeat alive when connected.",
                    "Camera feed uses threaded capture, frame skipping, MJPG, low resolution, and warmup suppression.",
                    "WELCOME_TALK v1 can use website text, camera microphone STT, and local Piper TTS when available.",
                ],
            }
            if stm32.connected:
                self.log("pass", f"STM32 detected on {stm32.port}")
                self.start_stm32_link(stm32.port)
                if self.mode_manager.current_state == "BOOTSTRAP":
                    self.mode_manager.bootstrap_complete(True, "required hardware available")
            else:
                self.log("error", "STM32 motor safety controller missing")
                if self.mode_manager.current_state == "BOOTSTRAP":
                    self.mode_manager.bootstrap_complete(False, "STM32 motor safety controller missing")
                elif self.mode_manager.current_state != "ERROR":
                    self.mode_manager.enter_error("STM32 motor safety controller missing", source="hardware_refresh")

    def start_stm32_link(self, port: str | None) -> None:
        if not port:
            return
        self.stop_stm32_link()
        link = Stm32SerialLink(port=port, baud=self.serial_baud, heartbeat_interval_s=0.4)
        link.start()
        self.stm32_link = link
        self.log("pass", f"IDLE STM32 heartbeat link started on {port}")

    def stop_stm32_link(self) -> None:
        link = self.stm32_link
        self.stm32_link = None
        if link is not None:
            link.stop()

    def emergency_stop(self) -> dict[str, Any]:
        started = time.monotonic()
        stm32 = self.hardware["stm32"]
        stop = self.send_stm32_stop_safe(stm32.port)
        elapsed_ms = (time.monotonic() - started) * 1000.0

        with self.lock:
            result = self.mode_manager.enter_error("Emergency stop requested from website", source="website")
            self.manual.enabled = False
            self.manual.speed_intent = 0
            self.manual.steer_intent = 0
            self.log("stop", f"Emergency stop requested, serial result: {stop['detail']}")

        return {
            "ok": bool(stop["ok"]),
            "elapsed_ms": elapsed_ms,
            "serial": stop,
            "state": result.current_state,
            "transition": result.to_dict(),
        }

    def inject_fault(self, reason: str, source: str = "diagnostic") -> dict[str, Any]:
        clean_reason = reason.strip() or "diagnostic fault injection"
        stop = self.send_stm32_stop_safe(self.hardware["stm32"].port)
        with self.lock:
            result = self.mode_manager.enter_error(clean_reason, source=source)
            self.manual.enabled = False
            self.manual.speed_intent = 0
            self.manual.steer_intent = 0
            self.log("error", f"Fault injected: {clean_reason}; stop result: {stop['detail']}")
        return {"accepted": True, "stop": stop, "transition": result.to_dict(), "state": result.current_state}

    def reset_error(self) -> dict[str, Any]:
        if not self.hardware["stm32"].connected:
            self.refresh_hardware()
        result = self.mode_manager.request_transition(
            "IDLE",
            self.safety_context(),
            source="website",
            reason="operator requested ERROR reset",
            reset_fault=True,
        )
        stop_result: dict[str, Any] | None = None
        if result.accepted and result.requires_stop:
            stop_result = self.send_stm32_stop_safe(self.hardware["stm32"].port)
            self.log("stop", f"ERROR reset stop guard: {stop_result['detail']}")
        self.log("pass" if result.accepted else "warn", f"ERROR reset: {result.reason}")
        payload = result.to_dict()
        payload["stop_guard"] = stop_result
        return payload

    def send_stm32_stop_safe(self, port: str | None) -> dict[str, Any]:
        if self.stm32_link is not None:
            return self.stm32_link.send_stop()
        return send_stm32_stop(port, self.serial_baud) if port else {"ok": False, "detail": "STM32 port unknown"}

    def safety_context(self, operator_request: bool = False, welcome_trigger_confirmed: bool = False) -> SafetyContext:
        stm32 = self.hardware["stm32"]
        return SafetyContext(
            stm32_available=stm32.connected,
            battery_critical=False,
            motion_intent_zero=True,
            welcome_trigger_confirmed=welcome_trigger_confirmed,
            operator_request=operator_request,
            return_lock=self.mode_manager.return_lock,
            fault_active=False,
            fault_reason=self.mode_manager.fault_reason,
        )

    def request_state(self, requested_state: str, reset_fault: bool = False) -> dict[str, Any]:
        requested_state = requested_state.strip().upper()
        if requested_state not in VALID_STATES:
            self.log("warn", f"Rejected unknown state request: {requested_state}")
            return {"accepted": False, "reason": "unknown state"}

        context = self.safety_context(
            operator_request=True,
            welcome_trigger_confirmed=requested_state == "WELCOME",
        )
        result = self.mode_manager.request_transition(
            requested_state,
            context,
            source="website",
            reason=f"website requested {requested_state}",
            reset_fault=reset_fault,
        )

        stop_result: dict[str, Any] | None = None
        if result.accepted and result.requires_stop:
            stm32 = self.hardware["stm32"]
            stop_result = self.send_stm32_stop_safe(stm32.port)
            self.log("stop", f"Transition stop guard for {requested_state}: {stop_result['detail']}")

        if result.accepted:
            self.update_manual_enabled(result.current_state == "MANUAL")

        level = "pass" if result.accepted else "warn"
        self.log(level, f"State request {requested_state}: {result.reason}")
        payload = result.to_dict()
        payload["stop_guard"] = stop_result
        return payload

    def update_manual_enabled(self, enabled: bool) -> None:
        self.manual.enabled = enabled
        if enabled:
            self.manual.speed_intent = 0
            self.manual.steer_intent = 0
            self.manual.blocked_reason = None
            self.manual.last_result = {"ok": True, "detail": "MANUAL enabled with zero intent"}
        else:
            self.manual.speed_intent = 0
            self.manual.steer_intent = 0
            self.manual.blocked_reason = "manual disabled"

    @staticmethod
    def clamp(value: int, limit: int) -> int:
        return max(-limit, min(limit, int(value)))

    def manual_drive(self, speed: int, steer: int) -> dict[str, Any]:
        if self.mode_manager.current_state != "MANUAL" or not self.manual.enabled:
            result = {"accepted": False, "reason": "manual controls are only active in MANUAL"}
            self.manual.blocked_reason = result["reason"]
            self.log("warn", f"Manual drive rejected: {result['reason']}")
            return result
        if self.stm32_link is None or not self.hardware["stm32"].connected:
            result = {"accepted": False, "reason": "STM32 unavailable"}
            self.manual.blocked_reason = result["reason"]
            self.mode_manager.enter_error("STM32 unavailable during MANUAL", source="manual")
            self.log("error", "Manual drive rejected: STM32 unavailable")
            return result

        clamped_speed = self.clamp(speed, self.manual.max_speed)
        clamped_steer = self.clamp(steer, self.manual.max_steer)
        obstacle_reason = self.forward_obstacle_reason(clamped_speed)
        if obstacle_reason:
            clamped_speed = 0
            self.manual.blocked_reason = obstacle_reason
            self.log("warn", f"Manual forward intent blocked: {obstacle_reason}")
        else:
            self.manual.blocked_reason = None

        started = time.monotonic()
        serial_result = self.stm32_link.send_drive(clamped_speed, clamped_steer)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        self.manual.speed_intent = clamped_speed
        self.manual.steer_intent = clamped_steer
        self.manual.last_command_at = time.time()
        self.manual.command_count += 1
        self.manual.last_result = serial_result
        if clamped_speed != 0 or clamped_steer != 0:
            self.log("drive", f"MANUAL drive speed={clamped_speed} steer={clamped_steer} result={serial_result['detail']}")
        return {
            "accepted": bool(serial_result["ok"]),
            "speed": clamped_speed,
            "steer": clamped_steer,
            "elapsed_ms": elapsed_ms,
            "serial": serial_result,
            "blocked_reason": self.manual.blocked_reason,
        }

    def manual_stop(self) -> dict[str, Any]:
        self.manual.speed_intent = 0
        self.manual.steer_intent = 0
        self.manual.last_release_at = time.time()
        stop = self.send_stm32_stop_safe(self.hardware["stm32"].port)
        self.manual.last_result = stop
        self.log("stop", f"MANUAL stop result: {stop['detail']}")
        return {"accepted": bool(stop["ok"]), "speed": 0, "steer": 0, "serial": stop}

    def audio_status(self) -> dict[str, Any]:
        return self.audio_runtime.status()

    def refresh_audio(self) -> dict[str, Any]:
        status = self.audio_runtime.probe()
        with self.lock:
            self.hardware["microphone"] = HardwareDevice(
                "Microphone",
                False,
                connected=status.microphone_available,
                port=status.selected_microphone,
                status="connected" if status.microphone_available else "unavailable",
                detail=status.stt_detail if status.microphone_available else "no capture device selected",
                last_seen=time.time() if status.microphone_available else None,
            )
            self.hardware["speaker"] = HardwareDevice(
                "Speaker",
                False,
                connected=status.speaker_available,
                port=status.selected_speaker,
                status="connected" if status.speaker_available else "unavailable",
                detail=status.tts_detail if status.speaker_available else "no playback device selected",
                last_seen=time.time() if status.speaker_available else None,
            )
            self.log("info", "Audio hardware refreshed")
        return status.to_dict()

    def audio_speak(self, text: str) -> dict[str, Any]:
        result = self.audio_runtime.speak_async(text)
        self.log("talk" if result.get("ok") else "warn", f"Audio speak: {result.get('detail')}")
        return {"accepted": bool(result.get("ok")), "audio": result, "status": self.audio_status()}

    def welcome_talk(self, text: str, speak: bool = False) -> dict[str, Any]:
        guard = self.prepare_welcome_talk()
        if not guard["ok"]:
            return guard["payload"]
        return self.answer_welcome_talk(text, guard["stop"], speak=speak)

    def welcome_listen(self, duration_s: float = 3.0, speak: bool = False) -> dict[str, Any]:
        guard = self.prepare_welcome_talk()
        if not guard["ok"]:
            return guard["payload"]

        with self.lock:
            self.talk_last_notice = "Listening..."
            self.log("talk", f"WELCOME_TALK listening for {duration_s:.1f}s")

        listen = self.audio_runtime.listen(duration_s)
        transcript = listen.get("transcript") or {}
        text = str(transcript.get("text") or "").strip()
        payload = self.answer_welcome_talk(text, guard["stop"], speak=speak)
        payload["audio_listen"] = listen
        payload["recognized_text"] = text
        payload["audio"] = self.audio_status()
        return payload

    def prepare_welcome_talk(self) -> dict[str, Any]:
        if self.mode_manager.current_state != "WELCOME":
            self.talk_last_notice = "Enter WELCOME first."
            result = {
                "accepted": False,
                "reason": "WELCOME_TALK is only active in WELCOME",
                "state": self.mode_manager.current_state,
                "display_response": self.talk_last_notice,
            }
            self.log("warn", f"WELCOME_TALK rejected: {result['reason']}")
            return {"ok": False, "payload": result}

        stop = self.send_stm32_stop_safe(self.hardware["stm32"].port)
        if self.hardware["stm32"].connected and not stop.get("ok"):
            self.talk_last_notice = "Stop guard failed."
            transition = self.mode_manager.enter_error("Unable to verify stopped wheels before WELCOME_TALK", source="welcome_talk")
            self.log("error", f"WELCOME_TALK blocked by stop guard: {stop['detail']}")
            result = {
                "accepted": False,
                "reason": "stop guard failed",
                "display_response": self.talk_last_notice,
                "stop_guard": stop,
                "transition": transition.to_dict(),
            }
            return {"ok": False, "payload": result}

        return {"ok": True, "stop": stop}

    def answer_welcome_talk(self, text: str, stop: dict[str, Any], speak: bool = False) -> dict[str, Any]:
        self.mode_manager.set_substate("WELCOME_TALK", return_lock=False)
        talk_result = self.talk_engine.answer(text)
        tts_result: dict[str, Any] | None = None
        if speak:
            tts_result = self.audio_runtime.speak_async(talk_result.response)
        with self.lock:
            self.talk_last_result = talk_result
            self.talk_history.appendleft(talk_result)
            self.talk_last_notice = talk_result.response
            self.log(
                "talk" if talk_result.accepted else "warn",
                f"WELCOME_TALK {talk_result.response_source} {talk_result.reason}: {talk_result.response}",
            )
        return {
            "accepted": talk_result.accepted,
            "reason": talk_result.reason,
            "state": self.mode_manager.current_state,
            "substate": self.mode_manager.current_substate,
            "stop_guard": stop,
            "talk": talk_result.to_dict(),
            "speech": tts_result,
            "display_response": talk_result.response,
        }

    def forward_obstacle_reason(self, speed: int) -> str | None:
        if speed <= 0 or self.stm32_link is None:
            return None
        status = self.stm32_link.get_status()
        obstacles = status.obstacles
        for key in ("F", "FL", "FR"):
            value = obstacles.get(key)
            if isinstance(value, (int, float)) and value < 60:
                return f"obstacle {key} at {value:.0f} cm"
        return None

    def shutdown(self, confirm: str | None) -> dict[str, Any]:
        if confirm != "PLUTO SHUTDOWN":
            self.log("warn", "Shutdown rejected because confirmation text was missing")
            return {"accepted": False, "reason": "confirmation required"}

        stop = self.emergency_stop()
        self.log("warn", "Shutdown command acknowledged as dry-run in Phase 3")
        return {
            "accepted": False,
            "reason": "Real shutdown is disabled in Phase 3 shell",
            "stop": stop,
        }

    def snapshot(self) -> PlutoStatus:
        with self.lock:
            hardware = {key: value for key, value in self.hardware.items()}
            events = list(self.events)
            mode_snapshot = self.mode_manager.snapshot(self.safety_context(operator_request=True))
            stm32_runtime = stm32_status_to_dict(self.stm32_link.get_status()) if self.stm32_link else {}
            self.escalate_critical_alert_if_needed(stm32_runtime)
            mode_snapshot = self.mode_manager.snapshot(self.safety_context(operator_request=True))
            status = PlutoStatus(
                current_state=mode_snapshot["current_state"],
                current_substate=mode_snapshot["current_substate"],
                fault_reason=mode_snapshot["fault_reason"],
                git_commit=self.git_commit,
                started_at=self.started_at,
                hardware=hardware,
                allowed_next_states=mode_snapshot["allowed_next_states"],
                bootstrap_report=self.bootstrap_report,
                camera=status_to_dict(self.camera_service.get_status()),
                mode_manager=mode_snapshot,
                stm32_runtime=stm32_runtime,
                error=self.error_status(mode_snapshot, stm32_runtime),
                manual=asdict(self.manual),
                talk=self.talk_status(),
                audio=self.audio_status(),
                events=events,
            )
            return status

    def talk_status(self) -> dict[str, Any]:
        return {
            **self.talk_engine.status(),
            "last_notice": self.talk_last_notice,
            "last_result": self.talk_last_result.to_dict() if self.talk_last_result else None,
            "history": [item.to_dict() for item in list(self.talk_history)[:8]],
        }

    def error_status(self, mode_snapshot: dict[str, Any], stm32_runtime: dict[str, Any]) -> dict[str, Any]:
        in_error = mode_snapshot["current_state"] == "ERROR"
        stm32_available = self.hardware["stm32"].connected
        return {
            "active": in_error,
            "fault_reason": mode_snapshot.get("fault_reason"),
            "previous_state": self.previous_state_before_error(mode_snapshot),
            "recovery_action": self.recovery_action(in_error, stm32_available),
            "stm32_available": stm32_available,
            "last_alert": (stm32_runtime.get("alerts") or [None])[0],
        }

    def previous_state_before_error(self, mode_snapshot: dict[str, Any]) -> str | None:
        for item in reversed(mode_snapshot.get("transition_log", [])):
            if item.get("next_state") == "ERROR" and item.get("accepted"):
                return item.get("previous_state")
        return None

    @staticmethod
    def recovery_action(in_error: bool, stm32_available: bool) -> str:
        if not in_error:
            return "No active fault"
        if stm32_available:
            return "Inspect fault, confirm motors are safe, then press Reset To IDLE"
        return "Reconnect STM32, refresh hardware, then reset"

    def escalate_critical_alert_if_needed(self, stm32_runtime: dict[str, Any]) -> None:
        alerts = stm32_runtime.get("alerts") or []
        if not alerts or self.mode_manager.current_state == "ERROR":
            return
        alert = str(alerts[0])
        critical_tokens = ("CRITICAL", "FAULT", "TIMEOUT", "ESTOP", "LOW_BAT", "DISCONNECT")
        if alert == self.last_alert_escalated:
            return
        if any(token in alert.upper() for token in critical_tokens):
            self.last_alert_escalated = alert
            stop = self.send_stm32_stop_safe(self.hardware["stm32"].port)
            result = self.mode_manager.enter_error(f"STM32 critical alert: {alert}", source="stm32_alert")
            self.manual.enabled = False
            self.manual.speed_intent = 0
            self.manual.steer_intent = 0
            self.log("error", f"Critical alert escalated to ERROR: {alert}; stop result: {stop['detail']}; {result.reason}")


def read_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def candidate_ports() -> list[str]:
    ports: list[str] = []
    try:
        import serial.tools.list_ports  # type: ignore

        ports.extend(port.device for port in serial.tools.list_ports.comports())
    except Exception:
        pass

    system = platform.system().lower()
    if system == "linux":
        ports.extend(glob.glob("/dev/ttyACM*"))
        ports.extend(glob.glob("/dev/ttyUSB*"))
        ports.extend(glob.glob("/dev/serial/by-id/*"))
    elif system == "darwin":
        ports.extend(glob.glob("/dev/tty.usbmodem*"))
        ports.extend(glob.glob("/dev/tty.usbserial*"))
    elif system == "windows" and not ports:
        ports.extend(f"COM{i}" for i in range(1, 33))

    return unique(ports)


def serial_open(port: str, baud: int):
    import serial  # type: ignore

    return serial.Serial(port=port, baudrate=baud, timeout=0.02, write_timeout=0.1)


def serial_write(ser, command: str) -> None:
    ser.write((command.strip() + "\n").encode("ascii"))
    ser.flush()


def serial_read_line(ser) -> str | None:
    raw = ser.readline()
    if not raw:
        return None
    return raw.decode("utf-8", errors="replace").strip()


def probe_stm32(ports: list[str], baud: int) -> HardwareDevice:
    if not ports:
        return HardwareDevice("STM32 motor safety controller", True, status="missing", detail="no serial ports found")

    for port in ports:
        try:
            with serial_open(port, baud) as ser:
                time.sleep(0.15)
                started = time.monotonic()
                serial_write(ser, "CMD:PING")
                deadline = started + 0.25
                seen: list[str] = []
                while time.monotonic() < deadline:
                    line = serial_read_line(ser)
                    if not line:
                        continue
                    seen.append(line)
                    if line == "ACK:PING" or line == STM32_ID or line.startswith("TEL:") or line.startswith("OBS:"):
                        serial_write(ser, "CMD:STOP")
                        return HardwareDevice(
                            "STM32 motor safety controller",
                            True,
                            connected=True,
                            port=port,
                            status="connected",
                            detail=line,
                            latency_ms=(time.monotonic() - started) * 1000.0,
                            last_seen=time.time(),
                        )
        except Exception:
            continue

    return HardwareDevice("STM32 motor safety controller", True, status="missing", detail="STM32 identity not found")


def probe_uno(ports: list[str], baud: int, skip_port: str | None = None) -> HardwareDevice:
    for port in ports:
        if skip_port and port == skip_port:
            continue
        try:
            with serial_open(port, baud) as ser:
                time.sleep(1.2)
                serial_write(ser, "ID?")
                deadline = time.monotonic() + 0.8
                while time.monotonic() < deadline:
                    line = serial_read_line(ser)
                    if line == UNO_ID:
                        return HardwareDevice(
                            "Uno LCD face controller",
                            False,
                            connected=True,
                            port=port,
                            status="connected",
                            detail=line,
                            last_seen=time.time(),
                        )
        except Exception:
            continue

    return HardwareDevice("Uno LCD face controller", False, status="unavailable", detail="optional hardware not detected")


def send_stm32_stop(port: str | None, baud: int) -> dict[str, Any]:
    if not port:
        return {"ok": False, "detail": "STM32 port unknown"}

    try:
        with serial_open(port, baud) as ser:
            started = time.monotonic()
            serial_write(ser, "CMD:STOP")
            deadline = started + 0.15
            lines: list[str] = []
            while time.monotonic() < deadline:
                line = serial_read_line(ser)
                if not line:
                    continue
                lines.append(line)
                if line == "ACK:STOP":
                    return {
                        "ok": True,
                        "detail": "ACK:STOP",
                        "latency_ms": (time.monotonic() - started) * 1000.0,
                        "lines": lines,
                    }
            return {"ok": False, "detail": "STOP sent but ACK:STOP not received within 150 ms", "lines": lines}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def encode_json(data: Any) -> bytes:
    def default(value: Any) -> Any:
        if hasattr(value, "__dataclass_fields__"):
            return asdict(value)
        return str(value)

    return json.dumps(data, default=default, indent=2).encode("utf-8")


def html_page() -> str:
    states = "".join(f'<button class="state" data-state="{state}">{state}</button>' for state in VALID_STATES)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PLUTO Operator Console</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7f8;
      --panel: #ffffff;
      --ink: #172026;
      --muted: #66737c;
      --line: #d7dee3;
      --good: #1f7a4d;
      --warn: #9a6500;
      --bad: #b42318;
      --accent: #255c99;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 15px/1.45 system-ui, -apple-system, Segoe UI, sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px clamp(16px, 4vw, 40px);
      background: #111820;
      color: white;
      border-bottom: 4px solid var(--accent);
    }}
    h1, h2 {{ margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: clamp(28px, 6vw, 54px); line-height: 1; }}
    h2 {{ font-size: 17px; }}
    main {{
      width: min(1180px, 100%);
      margin: 0 auto;
      padding: 20px clamp(14px, 3vw, 28px) 36px;
      display: grid;
      gap: 16px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 16px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-width: 0;
    }}
    .span-4 {{ grid-column: span 4; }}
    .span-6 {{ grid-column: span 6; }}
    .span-8 {{ grid-column: span 8; }}
    .span-12 {{ grid-column: span 12; }}
    .metric {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 0;
      border-bottom: 1px solid var(--line);
    }}
    .metric:last-child {{ border-bottom: 0; }}
    .label {{ color: var(--muted); }}
    .value {{ font-weight: 700; text-align: right; overflow-wrap: anywhere; }}
    .status-good {{ color: var(--good); }}
    .status-warn {{ color: var(--warn); }}
    .status-bad {{ color: var(--bad); }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    button {{
      min-height: 42px;
      border: 1px solid var(--line);
      background: white;
      color: var(--ink);
      border-radius: 8px;
      padding: 10px 13px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    button:hover {{ border-color: var(--accent); }}
    .danger {{ background: var(--bad); color: white; border-color: var(--bad); }}
    .primary {{ background: var(--accent); color: white; border-color: var(--accent); }}
    .state {{ min-width: 118px; }}
    .state[disabled] {{ opacity: 0.55; cursor: not-allowed; }}
    .manual-pad {{
      display: grid;
      grid-template-columns: repeat(3, minmax(76px, 1fr));
      gap: 10px;
      max-width: 360px;
      margin-top: 12px;
    }}
    .manual-pad button {{
      aspect-ratio: 1 / 0.72;
      font-size: 20px;
    }}
    .manual-pad .wide {{
      grid-column: span 3;
      aspect-ratio: auto;
    }}
    .talk-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto auto;
      gap: 10px;
      margin-top: 12px;
    }}
    .talk-row input {{
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      font: inherit;
    }}
    .events {{
      min-height: 180px;
      max-height: 320px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
    }}
    .event {{
      display: grid;
      grid-template-columns: 86px 70px 1fr;
      gap: 8px;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 13px;
    }}
    .event:last-child {{ border-bottom: 0; }}
    .cameraBox {{
      position: relative;
      width: 100%;
      aspect-ratio: 4 / 3;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: #101820;
      margin: 12px 0;
      display: grid;
      place-items: center;
    }}
    #cameraFeed {{
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: none;
    }}
    #cameraUnavailable {{
      color: #d8e2ea;
      padding: 16px;
      text-align: center;
      font-weight: 700;
    }}
    pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: 0;
      padding: 12px;
      background: #111820;
      color: #e8eef3;
      border-radius: 8px;
      max-height: 280px;
      overflow: auto;
    }}
    @media (max-width: 860px) {{
      header {{ align-items: flex-start; flex-direction: column; }}
      .span-4, .span-6, .span-8 {{ grid-column: span 12; }}
      .event {{ grid-template-columns: 1fr; }}
      .talk-row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>PLUTO</h1>
      <div>Operator Console</div>
    </div>
    <button class="danger" id="estop">Emergency Stop</button>
  </header>
  <main>
    <div class="grid">
      <section class="span-4">
        <h2>State</h2>
        <div class="metric"><span class="label">Current</span><span class="value" id="state">...</span></div>
        <div class="metric"><span class="label">Substate</span><span class="value" id="substate">...</span></div>
        <div class="metric"><span class="label">Fault</span><span class="value" id="fault">none</span></div>
        <div class="metric"><span class="label">Recovery</span><span class="value" id="recovery">none</span></div>
        <div class="metric"><span class="label">Return Lock</span><span class="value" id="returnLock">false</span></div>
        <div class="metric"><span class="label">Commit</span><span class="value" id="commit">...</span></div>
      </section>
      <section class="span-8">
        <h2>Allowed Next States</h2>
        <div class="actions" id="states">{states}</div>
        <div class="actions" style="margin-top: 12px;">
          <button id="resetError">Reset To IDLE</button>
          <button id="injectFault">Inject Test Fault</button>
        </div>
        <div id="stateReasons" style="margin-top: 12px;"></div>
      </section>
      <section class="span-6">
        <h2>Hardware</h2>
        <div id="hardware"></div>
        <div class="actions" style="margin-top: 14px;">
          <button class="primary" id="refresh">Refresh Hardware</button>
        </div>
      </section>
      <section class="span-6">
        <h2>STM32 Runtime</h2>
        <div class="metric"><span class="label">Heartbeat</span><span class="value" id="stmHeartbeat">...</span></div>
        <div class="metric"><span class="label">Ping Latency</span><span class="value" id="stmPing">...</span></div>
        <div class="metric"><span class="label">Telemetry</span><span class="value" id="stmTel">...</span></div>
        <div class="metric"><span class="label">Obstacles</span><span class="value" id="stmObs">...</span></div>
        <div class="metric"><span class="label">Last Line</span><span class="value" id="stmLine">...</span></div>
      </section>
      <section class="span-6">
        <h2>Manual Control</h2>
        <div class="metric"><span class="label">Enabled</span><span class="value" id="manualEnabled">false</span></div>
        <div class="metric"><span class="label">Intent</span><span class="value" id="manualIntent">0,0</span></div>
        <div class="metric"><span class="label">Limit</span><span class="value" id="manualLimit">...</span></div>
        <div class="metric"><span class="label">Blocked</span><span class="value" id="manualBlocked">none</span></div>
        <div class="manual-pad" id="manualPad">
          <span></span><button data-speed="80" data-steer="0">Forward</button><span></span>
          <button data-speed="0" data-steer="-80">Left</button><button class="danger" id="manualStop">Stop</button><button data-speed="0" data-steer="80">Right</button>
          <span></span><button data-speed="-80" data-steer="0">Back</button><span></span>
        </div>
      </section>
      <section class="span-6">
        <h2>Welcome Talk</h2>
        <div class="metric"><span class="label">Version</span><span class="value" id="talkVersion">v1</span></div>
        <div class="metric"><span class="label">Limits</span><span class="value" id="talkLimits">9 in / 9 out</span></div>
        <div class="metric"><span class="label">Source</span><span class="value" id="talkSource">none</span></div>
        <div class="metric"><span class="label">Latency</span><span class="value" id="talkLatency">none</span></div>
        <div class="metric"><span class="label">Notice</span><span class="value" id="talkNotice">Enter WELCOME first</span></div>
        <div class="metric"><span class="label">Response</span><span class="value" id="talkResponse">none</span></div>
        <div class="metric"><span class="label">Transcript</span><span class="value" id="talkTranscript">none</span></div>
        <div class="metric"><span class="label">Audio</span><span class="value" id="audioState">not checked</span></div>
        <div class="metric"><span class="label">Mic</span><span class="value" id="audioMic">none</span></div>
        <div class="metric"><span class="label">Speaker</span><span class="value" id="audioSpeaker">none</span></div>
        <div class="metric"><span class="label">Speech IO</span><span class="value" id="audioEngines">none</span></div>
        <div class="talk-row">
          <input id="talkInput" maxlength="120" placeholder="Ask Pluto a short question">
          <button class="primary" id="talkAsk">Ask</button>
          <button id="talkSpeak">Ask+Speak</button>
          <button id="talkListen">Listen 3s</button>
        </div>
      </section>
      <section class="span-6">
        <h2>Camera</h2>
        <div class="cameraBox">
          <img id="cameraFeed" alt="PLUTO camera feed">
          <div id="cameraUnavailable">Camera feed unavailable</div>
        </div>
        <div class="metric"><span class="label">Status</span><span class="value" id="cameraStatus">...</span></div>
        <div class="metric"><span class="label">Humans</span><span class="value" id="humanCount">0</span></div>
        <div class="metric"><span class="label">FPS</span><span class="value" id="cameraFps">0</span></div>
        <div class="metric"><span class="label">Inference</span><span class="value" id="cameraInference">0 ms</span></div>
      </section>
      <section class="span-12">
        <h2>Events</h2>
        <div class="events" id="events"></div>
      </section>
      <section class="span-12">
        <h2>Bootstrap Report</h2>
        <pre id="report">{{}}</pre>
      </section>
    </div>
  </main>
  <script>
    async function api(path, options) {{
      const res = await fetch(path, options);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }}
    function clsFor(status) {{
      if (status === 'connected') return 'status-good';
      if (status === 'missing' || status === 'error') return 'status-bad';
      return 'status-warn';
    }}
    function render(data) {{
      document.getElementById('state').textContent = data.current_state;
      document.getElementById('substate').textContent = data.current_substate || 'none';
      document.getElementById('fault').textContent = data.fault_reason || 'none';
      document.getElementById('recovery').textContent = (data.error && data.error.recovery_action) || 'none';
      document.getElementById('returnLock').textContent = data.mode_manager && data.mode_manager.return_lock ? 'true' : 'false';
      document.getElementById('commit').textContent = data.git_commit || 'unknown';
      const hardware = document.getElementById('hardware');
      hardware.innerHTML = Object.entries(data.hardware).map(([key, item]) => `
        <div class="metric">
          <span class="label">${{item.name}}</span>
          <span class="value ${{clsFor(item.status)}}">${{item.status}}${{item.port ? ' - ' + item.port : ''}}</span>
        </div>
      `).join('');
      const allowed = Object.fromEntries(data.allowed_next_states.map(item => [item.state, item]));
      document.querySelectorAll('.state').forEach(btn => {{
        const item = allowed[btn.dataset.state];
        btn.disabled = !item || !item.allowed;
        btn.title = item ? item.reason : 'unavailable';
      }});
      document.getElementById('stateReasons').innerHTML = data.allowed_next_states.map(item => `
        <div class="metric">
          <span class="label">${{item.state}}</span>
          <span class="value ${{item.allowed ? 'status-good' : 'status-warn'}}">${{item.reason}}</span>
        </div>
      `).join('');
      document.getElementById('events').innerHTML = data.events.map(item => {{
        const t = new Date(item.timestamp * 1000).toLocaleTimeString();
        return `<div class="event"><span>${{t}}</span><span>${{item.level}}</span><span>${{item.message}}</span></div>`;
      }}).join('');
      document.getElementById('report').textContent = JSON.stringify(data.bootstrap_report, null, 2);
      const stm = data.stm32_runtime || {{}};
      document.getElementById('stmHeartbeat').textContent = stm.running ? `${{stm.ack_ping_count || 0}} ACK / ${{stm.ping_count || 0}} PING` : 'not running';
      document.getElementById('stmPing').textContent = stm.last_ping_latency_ms == null ? 'none' : `${{stm.last_ping_latency_ms.toFixed(1)}} ms`;
      document.getElementById('stmTel').textContent = stm.telemetry ? JSON.stringify(stm.telemetry) : '{{}}';
      document.getElementById('stmObs').textContent = stm.obstacles ? JSON.stringify(stm.obstacles) : '{{}}';
      document.getElementById('stmLine').textContent = stm.last_line || stm.error || 'none';
      const manual = data.manual || {{}};
      document.getElementById('manualEnabled').textContent = manual.enabled ? 'true' : 'false';
      document.getElementById('manualIntent').textContent = `${{manual.speed_intent || 0}}, ${{manual.steer_intent || 0}}`;
      document.getElementById('manualLimit').textContent = `${{manual.max_speed || 0}} speed / ${{manual.max_steer || 0}} steer`;
      document.getElementById('manualBlocked').textContent = manual.blocked_reason || 'none';
      document.querySelectorAll('#manualPad button[data-speed]').forEach(btn => {{
        btn.disabled = !manual.enabled;
      }});
      document.getElementById('manualStop').disabled = !manual.enabled;
      const talk = data.talk || {{}};
      const lastTalk = talk.last_result || null;
      document.getElementById('talkVersion').textContent = `${{talk.version || 'v1'}} / ${{talk.primary_engine || 'keyword'}}`;
      document.getElementById('talkLimits').textContent = `${{talk.max_input_words || 9}} in / ${{talk.max_output_words || 9}} out`;
      document.getElementById('talkSource').textContent = lastTalk ? `${{lastTalk.response_source}} / ${{lastTalk.intent || 'none'}}` : 'none';
      document.getElementById('talkLatency').textContent = lastTalk ? `${{lastTalk.latency_ms.toFixed(2)}} ms` : 'none';
      document.getElementById('talkNotice').textContent = talk.last_notice || 'Enter WELCOME first.';
      document.getElementById('talkResponse').textContent = lastTalk ? lastTalk.response : (talk.last_notice || 'none');
      const audio = data.audio || {{}};
      const transcript = audio.last_transcript || {{}};
      const tts = audio.last_tts || {{}};
      document.getElementById('talkTranscript').textContent = transcript.text || 'none';
      document.getElementById('audioState').textContent =
        `${{audio.microphone_available ? 'mic ok' : 'no mic'}} / ${{audio.speaker_available ? 'speaker ok' : 'no speaker'}}`;
      document.getElementById('audioMic').textContent = audio.selected_microphone || 'none';
      document.getElementById('audioSpeaker').textContent = audio.selected_speaker || 'none';
      document.getElementById('audioEngines').textContent =
        `${{audio.stt_backend || 'stt?'}} / ${{audio.tts_backend || 'tts?'}}${{tts.detail ? ' / ' + tts.detail : ''}}`;
      const camera = data.camera || {{}};
      const feed = document.getElementById('cameraFeed');
      const unavailable = document.getElementById('cameraUnavailable');
      if (camera.available && camera.running) {{
        if (!feed.src.includes('/camera.mjpg')) feed.src = '/camera.mjpg';
        feed.style.display = 'block';
        unavailable.style.display = 'none';
      }} else {{
        feed.removeAttribute('src');
        feed.style.display = 'none';
        unavailable.style.display = 'grid';
        unavailable.textContent = camera.error || 'Camera feed unavailable';
      }}
      document.getElementById('cameraStatus').textContent = camera.running ? `${{camera.backend}} ${{camera.resolution}}` : (camera.error || 'unavailable');
      document.getElementById('humanCount').textContent = camera.human_count || 0;
      document.getElementById('cameraFps').textContent = `${{(camera.stream_fps || 0).toFixed(1)}} stream / ${{(camera.capture_fps || 0).toFixed(1)}} capture`;
      document.getElementById('cameraInference').textContent = `${{(camera.inference_ms || 0).toFixed(1)}} ms`;
    }}
    async function refresh() {{
      try {{ render(await api('/api/status')); }}
      catch (err) {{ console.error(err); }}
    }}
    document.getElementById('refresh').addEventListener('click', async () => {{
      await api('/api/refresh-hardware', {{method: 'POST'}});
      await refresh();
    }});
    document.getElementById('estop').addEventListener('click', async () => {{
      await api('/api/emergency-stop', {{method: 'POST'}});
      await refresh();
    }});
    document.getElementById('resetError').addEventListener('click', async () => {{
      await api('/api/reset-error', {{method: 'POST'}});
      await refresh();
    }});
    document.getElementById('injectFault').addEventListener('click', async () => {{
      await api('/api/inject-fault', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{reason: 'operator diagnostic test fault'}})
      }});
      await refresh();
    }});
    document.querySelectorAll('.state').forEach(btn => btn.addEventListener('click', async () => {{
      await api('/api/request-state', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{state: btn.dataset.state, reset_fault: btn.dataset.state === 'IDLE'}})
      }});
      await refresh();
    }}));
    let manualTimer = null;
    async function manualDrive(speed, steer) {{
      await api('/api/manual/drive', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{speed, steer}})
      }});
      await refresh();
    }}
    async function manualStop() {{
      if (manualTimer) {{
        clearInterval(manualTimer);
        manualTimer = null;
      }}
      await api('/api/manual/stop', {{method: 'POST'}});
      await refresh();
    }}
    document.querySelectorAll('#manualPad button[data-speed]').forEach(btn => {{
      const start = async (event) => {{
        event.preventDefault();
        const speed = Number(btn.dataset.speed);
        const steer = Number(btn.dataset.steer);
        if (manualTimer) clearInterval(manualTimer);
        await manualDrive(speed, steer);
        manualTimer = setInterval(() => manualDrive(speed, steer).catch(console.error), 150);
      }};
      btn.addEventListener('mousedown', start);
      btn.addEventListener('touchstart', start, {{passive: false}});
    }});
    ['mouseup', 'mouseleave', 'touchend', 'touchcancel'].forEach(name => {{
      document.addEventListener(name, () => {{
        if (manualTimer) manualStop().catch(console.error);
      }});
    }});
    document.getElementById('manualStop').addEventListener('click', async () => {{
      await manualStop();
    }});
    async function submitTalk(speak) {{
      const input = document.getElementById('talkInput');
      const result = await api('/api/welcome/talk', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{text: input.value, speak}})
      }});
      document.getElementById('talkNotice').textContent = result.display_response || result.reason || 'no response';
      if (result.talk) {{
        document.getElementById('talkResponse').textContent = result.talk.response;
        document.getElementById('talkSource').textContent = `${{result.talk.response_source}} / ${{result.talk.intent || 'none'}}`;
        document.getElementById('talkLatency').textContent = `${{result.talk.latency_ms.toFixed(2)}} ms`;
      }} else {{
        document.getElementById('talkResponse').textContent = result.display_response || result.reason || 'no response';
      }}
      input.value = '';
      await refresh();
    }}
    document.getElementById('talkAsk').addEventListener('click', async () => submitTalk(false));
    document.getElementById('talkSpeak').addEventListener('click', async () => submitTalk(true));
    document.getElementById('talkListen').addEventListener('click', async () => {{
      document.getElementById('talkNotice').textContent = 'Listening...';
      const result = await api('/api/welcome/listen', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{duration_s: 3.0, speak: true}})
      }});
      document.getElementById('talkNotice').textContent = result.display_response || result.reason || 'no response';
      document.getElementById('talkTranscript').textContent = result.recognized_text || 'none';
      if (result.talk) {{
        document.getElementById('talkResponse').textContent = result.talk.response;
        document.getElementById('talkSource').textContent = `${{result.talk.response_source}} / ${{result.talk.intent || 'none'}}`;
        document.getElementById('talkLatency').textContent = `${{result.talk.latency_ms.toFixed(2)}} ms`;
      }}
      await refresh();
    }});
    document.getElementById('talkInput').addEventListener('keydown', async (event) => {{
      if (event.key === 'Enter') {{
        event.preventDefault();
        document.getElementById('talkAsk').click();
      }}
    }});
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>"""


class PlutoRequestHandler(BaseHTTPRequestHandler):
    server_version = "PlutoWebShell/0.1"

    @property
    def context(self) -> PlutoWebContext:
        return self.server.context  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        if self.path not in {"/api/status", "/healthz"}:
            self.context.log("http", fmt % args)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, payload: Any) -> None:
        self.send_bytes(status, encode_json(payload), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_bytes(HTTPStatus.OK, html_page().encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/status":
            self.send_json(HTTPStatus.OK, self.context.snapshot())
            return
        if path == "/api/camera/status":
            self.send_json(HTTPStatus.OK, self.context.snapshot().camera)
            return
        if path == "/api/audio/status":
            self.send_json(HTTPStatus.OK, self.context.audio_status())
            return
        if path == "/camera.jpg":
            frame = self.context.camera_service.get_jpeg()
            if frame is None:
                self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "camera frame unavailable"})
                return
            self.send_bytes(HTTPStatus.OK, frame, "image/jpeg")
            return
        if path == "/camera.mjpg":
            self.send_response(HTTPStatus.OK)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            for frame in self.context.camera_service.stream_frames():
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    break
            return
        if path == "/healthz":
            self.send_json(HTTPStatus.OK, {"ok": True, "project": PROJECT_NAME})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/refresh-hardware":
                self.context.refresh_hardware()
                self.send_json(HTTPStatus.OK, self.context.snapshot())
                return
            if path == "/api/emergency-stop":
                self.send_json(HTTPStatus.OK, self.context.emergency_stop())
                return
            if path == "/api/inject-fault":
                body = self.read_json()
                self.send_json(HTTPStatus.OK, self.context.inject_fault(str(body.get("reason", ""))))
                return
            if path == "/api/reset-error":
                self.send_json(HTTPStatus.OK, self.context.reset_error())
                return
            if path == "/api/request-state":
                body = self.read_json()
                self.send_json(
                    HTTPStatus.OK,
                    self.context.request_state(
                        str(body.get("state", "")),
                        bool(body.get("reset_fault", False)),
                    ),
                )
                return
            if path == "/api/manual/drive":
                body = self.read_json()
                self.send_json(
                    HTTPStatus.OK,
                    self.context.manual_drive(int(body.get("speed", 0)), int(body.get("steer", 0))),
                )
                return
            if path == "/api/manual/stop":
                self.send_json(HTTPStatus.OK, self.context.manual_stop())
                return
            if path == "/api/audio/refresh":
                self.send_json(HTTPStatus.OK, self.context.refresh_audio())
                return
            if path == "/api/audio/speak":
                body = self.read_json()
                self.send_json(HTTPStatus.OK, self.context.audio_speak(str(body.get("text", ""))))
                return
            if path == "/api/welcome/talk":
                body = self.read_json()
                self.send_json(HTTPStatus.OK, self.context.welcome_talk(str(body.get("text", "")), bool(body.get("speak", False))))
                return
            if path == "/api/welcome/listen":
                body = self.read_json()
                self.send_json(
                    HTTPStatus.OK,
                    self.context.welcome_listen(float(body.get("duration_s", 3.0)), bool(body.get("speak", False))),
                )
                return
            if path == "/api/shutdown":
                body = self.read_json()
                self.send_json(HTTPStatus.OK, self.context.shutdown(body.get("confirm")))
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except Exception as exc:
            self.context.log("error", f"API failure on {path}: {exc}")
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


class PlutoWebServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], handler, context: PlutoWebContext) -> None:
        super().__init__(address, handler)
        self.context = context


def local_addresses(port: int) -> list[str]:
    addresses = [f"http://127.0.0.1:{port}"]
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            ip = item[4][0]
            if ip != "127.0.0.1":
                addresses.append(f"http://{ip}:{port}")
    except Exception:
        pass
    return unique(addresses)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 6 PLUTO operator website shell.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Use 0.0.0.0 on Raspberry Pi.")
    parser.add_argument("--port", type=int, default=8080, help="Bind port. Default: 8080.")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud for hardware probes.")
    parser.add_argument("--camera-device", help="Camera device, for example /dev/video0.")
    parser.add_argument("--camera-resolution", default="320x320", help="Capture resolution WIDTHxHEIGHT. Default: 320x320.")
    parser.add_argument("--camera-fps", type=int, default=30, help="Requested camera FPS. Default: 30.")
    parser.add_argument("--camera-stream-fps", type=int, default=8, help="MJPEG stream FPS. Default: 8.")
    parser.add_argument("--camera-frame-skip", type=int, default=1, help="Run human detection every Nth frame. Default: 1.")
    parser.add_argument("--camera-detection-hold", type=float, default=2.0, help="Seconds to keep last human detection visible after missed frames.")
    parser.add_argument("--camera-confidence", type=float, default=0.30, help="Human detection confidence threshold. Default: 0.30.")
    parser.add_argument("--yolo-model", help="TFLite YOLO model path. Defaults to PLUTO_YOLO_MODEL or /home/pi/yolo/model/yolov8n-fp16.tflite.")
    return parser.parse_args(argv)


def parse_resolution(value: str) -> tuple[int, int]:
    try:
        left, right = value.lower().split("x", 1)
        width = int(left)
        height = int(right)
    except Exception as exc:
        raise argparse.ArgumentTypeError("resolution must look like WIDTHxHEIGHT, for example 320x320") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("resolution dimensions must be positive")
    return width, height


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    context = PlutoWebContext(
        serial_baud=args.baud,
        camera_device=args.camera_device,
        camera_resolution=parse_resolution(args.camera_resolution),
        camera_fps=args.camera_fps,
        camera_stream_fps=args.camera_stream_fps,
        camera_frame_skip=args.camera_frame_skip,
        camera_detection_hold=args.camera_detection_hold,
        camera_confidence=args.camera_confidence,
        yolo_model=args.yolo_model,
    )
    server = PlutoWebServer((args.host, args.port), PlutoRequestHandler, context)
    print(f"PLUTO web shell running on {args.host}:{args.port}")
    for address in local_addresses(args.port):
        print(f"Open {address}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping PLUTO web shell")
    finally:
        context.stop_stm32_link()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
