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
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .audio_io import AudioRuntime
from .camera import CameraService, CameraStatus, status_to_dict
from .dance import DanceDryRunPlanner, DanceStatus
from .mode_manager import SafetyContext, ModeManager, VALID_STATES
from .stm32_link import Stm32SerialLink, status_to_dict as stm32_status_to_dict
from .validation_center import ValidationCenter
from .wave_detection import SimpleWaveDetector
from .welcome_approach import ApproachStatus, WelcomeApproachPlanner
from .welcome_talk import TalkResult, WelcomeTalkEngine


PROJECT_NAME = "PLUTO"
STM32_ID = "ID:STM32_MOTOR"
UNO_ID = "ID:UNO_LCD"
STATIC_DIR = Path(__file__).resolve().with_name("static")
STATIC_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".stl": "model/stl",
}


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
    wave: dict[str, Any] = field(default_factory=dict)
    welcome_approach: dict[str, Any] = field(default_factory=dict)
    dance: dict[str, Any] = field(default_factory=dict)
    talk: dict[str, Any] = field(default_factory=dict)
    audio: dict[str, Any] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)


@dataclass
class ManualRuntime:
    enabled: bool = False
    speed_intent: int = 0
    steer_intent: int = 0
    max_speed: int = 400
    max_steer: int = 400
    base_speed_setting: int = 100
    base_steer_setting: int = 100
    arm_step_setting: int = 5000
    arm_speed_setting: int = 2000
    max_arm_steps: int = 10000
    max_arm_speed: int = 3000
    command_period_ms: int = 75
    last_command_at: float | None = None
    last_release_at: float | None = None
    last_arm_command: dict[str, Any] = field(default_factory=dict)
    last_result: dict[str, Any] = field(default_factory=dict)
    command_count: int = 0
    blocked_reason: str | None = None


@dataclass
class WaveTriggerRuntime:
    enabled: bool = True
    detector_status: str = "tracked_pose_wave"
    sample_hz: float = 8.0
    last_sample_at: float | None = None
    thresholds: dict[str, Any] = field(default_factory=dict)
    armed_until: float = 0.0
    armed_source: str | None = None
    trigger_count: int = 0
    rejected_count: int = 0
    last_event: dict[str, Any] | None = None
    last_result: dict[str, Any] | None = None
    last_reason: str = "no wave trigger yet"
    detector: dict[str, Any] = field(default_factory=dict)
    pending_confirmed_until: float = 0.0
    last_confirmed_detector: dict[str, Any] = field(default_factory=dict)


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
        camera_disabled: bool = False,
        yolo_model: str | None = None,
        wave_pose_model: str | None = None,
        wave_pose_disabled: bool = False,
        wave_pose_frame_skip: int = 1,
        wave_pose_max_tracks: int = 2,
        microphone_device: str | None = None,
        speaker_device: str | None = None,
    ) -> None:
        self.serial_baud = serial_baud
        self.lock = threading.RLock()
        self.events: deque[Event] = deque(maxlen=80)
        self.started_at = time.time()
        self.mode_manager = ModeManager()
        self.stm32_link: Stm32SerialLink | None = None
        self.manual = ManualRuntime()
        self.wave = WaveTriggerRuntime()
        self.wave_detector = SimpleWaveDetector()
        self.wave.thresholds = self.wave_detector.thresholds()
        self.wave_thread_running = True
        self.wave_thread: threading.Thread | None = None
        self.approach_planner = WelcomeApproachPlanner()
        self.approach_status = ApproachStatus()
        self.approach_last_stop_at = 0.0
        self.dance_planner = DanceDryRunPlanner()
        self.dance_status = DanceStatus()
        self.dance_started_at: float | None = None
        self.dance_last_stop_at = 0.0
        self.dance_audio_started = False
        self.talk_engine = WelcomeTalkEngine()
        self.talk_last_result: TalkResult | None = None
        self.talk_history: deque[TalkResult] = deque(maxlen=20)
        self.talk_last_notice = "Enter WELCOME, then ask a short question."
        self.audio_runtime = AudioRuntime(preferred_microphone=microphone_device, preferred_speaker=speaker_device)
        self.validation_center = ValidationCenter()
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
            pose_model_path=wave_pose_model,
            pose_enabled=not wave_pose_disabled,
            pose_frame_skip=wave_pose_frame_skip,
            pose_max_tracks=wave_pose_max_tracks,
        )
        if camera_disabled:
            self.camera_service.status = CameraStatus(
                available=False,
                running=False,
                configured_resolution=[camera_resolution[0], camera_resolution[1]],
                frame_skip=max(1, camera_frame_skip),
                detector_status="disabled",
                pose_status="disabled",
                error="camera disabled by operator",
                details={"reason": "camera disabled by --camera-disabled"},
            )
            self.log("warn", "Camera service disabled by operator")
        elif self.camera_service.start():
            self.log("pass", "Camera service started")
        else:
            self.log("warn", f"Camera unavailable: {self.camera_service.get_status().error}")
        self.refresh_hardware()
        self.start_wave_monitor()

    def log(self, level: str, message: str) -> None:
        with self.lock:
            self.events.appendleft(Event(time.time(), level, message))

    def start_wave_monitor(self) -> None:
        if self.wave_thread and self.wave_thread.is_alive():
            return
        self.wave_thread_running = True
        self.wave_thread = threading.Thread(target=self._wave_monitor_loop, name="pluto-wave-monitor", daemon=True)
        self.wave_thread.start()

    def stop(self) -> None:
        self.wave_thread_running = False
        if self.wave_thread and self.wave_thread.is_alive():
            self.wave_thread.join(timeout=1.0)
        self.stop_stm32_link()
        self.audio_runtime.stop_playback(reason="web shell stopping")
        self.camera_service.stop()

    def _wave_monitor_loop(self) -> None:
        period_s = 1.0 / max(1.0, self.wave.sample_hz)
        while self.wave_thread_running:
            started = time.monotonic()
            try:
                with self.lock:
                    self.update_wave_detector()
                    self.process_idle_wave_trigger()
                    self.wave.last_sample_at = time.time()
            except Exception as exc:
                self.log("warn", f"Wave monitor error: {exc}")
                time.sleep(0.5)
            elapsed = time.monotonic() - started
            time.sleep(max(0.01, period_s - elapsed))

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
                detail=audio_status.tts_detail
                if audio_status.speaker_available
                else (
                    "playback device detected but no confirmed speaker selected"
                    if audio_status.playback_devices
                    else "no playback device selected"
                ),
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
                    "WELCOME wave uses quantized MoveNet pose when available; pixel motion is debug-only.",
                    "WELCOME_TALK v1 can use website text, camera microphone STT, and local Piper TTS when available.",
                    "WELCOME_APPROACH Phase 10 is dry-run only: it computes target, safety, and proposed motion while holding STOP.",
                    "DANCE is dry-run only until bounded audio, obstacle, and proposed-motion evidence are reviewed.",
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

    def welcome_wave_trigger(self, source: str = "website_wave_test", diagnostic: bool = False, arm: bool = False) -> dict[str, Any]:
        camera = status_to_dict(self.camera_service.get_status())
        wave_detector = self.update_wave_detector(camera)
        pending_confirmed = time.time() <= self.wave.pending_confirmed_until and bool(self.wave.last_confirmed_detector)
        if pending_confirmed and not wave_detector.get("confirmed", False):
            wave_detector = dict(self.wave.last_confirmed_detector)
        human_count = int(camera.get("human_count") or 0)
        detections = camera.get("detections") or []
        target = detections[0] if detections else None
        target_id = wave_detector.get("target_id") or (f"track_{target.get('track_id')}" if isinstance(target, dict) and target.get("track_id") is not None else None)
        event = {
            "type": "WELCOME_TRIGGER:WAVE",
            "source": source,
            "diagnostic": bool(diagnostic),
            "timestamp": time.time(),
            "human_count": human_count,
            "target_id": target_id,
            "track_id": wave_detector.get("track_id"),
            "confidence": float(wave_detector.get("confidence") or (1.0 if diagnostic else 0.0)),
            "score": float(wave_detector.get("score") or (1.0 if diagnostic else 0.0)),
            "side": wave_detector.get("side", "unknown"),
            "reason": "diagnostic_wave" if diagnostic else str(wave_detector.get("reason", "no_person")),
            "mode_substate": self.mode_manager.current_substate,
        }
        self.wave.last_event = event

        if arm and not wave_detector.get("confirmed", False):
            self.wave_detector.reset()
            self.camera_service.clear_wave_lock()
            self.wave.pending_confirmed_until = 0.0
            self.wave.last_confirmed_detector = {}
            self.wave.armed_until = time.time() + 12.0
            self.wave.armed_source = source
            self.wave.last_reason = "armed: waiting for real wave"
            payload = {
                "accepted": False,
                "armed": True,
                "reason": self.wave.last_reason,
                "event": event,
                "wave": self.wave_status(),
            }
            self.wave.last_result = payload
            self.log("info", "WELCOME wave test armed; waiting for confirmed wave")
            return payload

        if not self.wave.enabled:
            self.wave.rejected_count += 1
            self.wave.last_reason = "wave trigger disabled"
            payload = {"accepted": False, "reason": self.wave.last_reason, "event": event}
            self.wave.last_result = payload
            self.log("warn", "WELCOME wave trigger rejected: disabled")
            return payload

        if not diagnostic and not wave_detector.get("confirmed", False):
            self.wave.rejected_count += 1
            self.wave.last_reason = f"wave not confirmed: {event['reason']}"
            payload = {"accepted": False, "reason": self.wave.last_reason, "event": event}
            self.wave.last_result = payload
            self.log("warn", f"WELCOME wave trigger rejected: {event['reason']}")
            return payload

        context = self.safety_context(operator_request=False, welcome_trigger_confirmed=True)
        result = self.mode_manager.request_transition(
            "WELCOME",
            context,
            source=source,
            reason=f"{event['type']} accepted",
        )

        stop_result: dict[str, Any] | None = None
        if result.accepted and result.requires_stop:
            stm32 = self.hardware["stm32"]
            stop_result = self.send_stm32_stop_safe(stm32.port)
            stop_result = self.degraded_stop_guard_if_safe(stop_result)
            self.log("stop", f"WELCOME wave trigger stop guard: {stop_result['detail']}")
            if stm32.connected and not stop_result.get("ok"):
                transition = self.mode_manager.enter_error("Unable to verify stopped wheels before WELCOME wave trigger", source=source)
                self.wave.rejected_count += 1
                self.wave.last_reason = "stop guard failed"
                payload = {
                    "accepted": False,
                    "reason": "stop guard failed",
                    "event": event,
                    "stop_guard": stop_result,
                    "transition": transition.to_dict(),
                    "wave": self.wave_status(),
                }
                self.wave.last_result = payload
                self.log("error", f"WELCOME wave trigger blocked by stop guard: {stop_result['detail']}")
                return payload

        if result.accepted:
            self.wave.trigger_count += 1
            self.wave.last_reason = "wave trigger accepted"
        else:
            self.wave.rejected_count += 1
            self.wave.last_reason = result.reason

        payload = result.to_dict()
        payload["event"] = event
        payload["stop_guard"] = stop_result
        payload["wave"] = self.wave_status()
        self.wave.last_result = payload
        self.log("pass" if result.accepted else "warn", f"WELCOME wave trigger: {result.reason}")
        return payload

    def update_wave_detector(self, camera_status: dict[str, Any] | None = None) -> dict[str, Any]:
        camera_status = camera_status or status_to_dict(self.camera_service.get_status())
        detector_status = self.wave_detector.update(camera_status).to_dict()
        self.wave.detector = detector_status
        self.wave.detector_status = str(detector_status.get("algorithm") or "tracked_pose_wave")
        self.wave.thresholds = dict(detector_status.get("thresholds") or self.wave_detector.thresholds())
        if detector_status.get("confirmed"):
            self.wave.pending_confirmed_until = time.time() + 1.5
            self.wave.last_confirmed_detector = dict(detector_status)
            self.camera_service.set_wave_lock(
                duration_s=4.0,
                label="WAVE LOCK",
                track_id=detector_status.get("track_id"),
                bbox=self.wave_lock_bbox(camera_status, detector_status.get("track_id")),
            )
            self.wave.last_reason = f"detected wave: {detector_status.get('reason')}"
        elif self.wave.last_event is None:
            self.wave.last_reason = str(detector_status.get("reason", "not checked"))
        return detector_status

    @staticmethod
    def wave_lock_bbox(camera_status: dict[str, Any], track_id: Any) -> list[int] | None:
        try:
            target_id = int(track_id)
        except (TypeError, ValueError):
            return None
        for detection in camera_status.get("detections") or []:
            if not isinstance(detection, dict):
                continue
            try:
                det_id = int(detection.get("track_id"))
            except (TypeError, ValueError):
                continue
            if det_id == target_id and detection.get("bbox"):
                return [int(value) for value in detection["bbox"]]
        return None

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
        self.manual.blocked_reason = None

        started = time.monotonic()
        wait_ack = clamped_speed == 0 and clamped_steer == 0
        serial_result = self.stm32_link.send_drive(clamped_speed, clamped_steer, wait_ack=wait_ack)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        self.manual.speed_intent = clamped_speed
        self.manual.steer_intent = clamped_steer
        if clamped_speed != 0:
            self.manual.base_speed_setting = abs(clamped_speed)
        if clamped_steer != 0:
            self.manual.base_steer_setting = abs(clamped_steer)
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

    def manual_arm(self, arm: int, steps: int, speed: int) -> dict[str, Any]:
        if self.mode_manager.current_state != "MANUAL" or not self.manual.enabled:
            result = {"accepted": False, "reason": "manual arm controls are only active in MANUAL"}
            self.manual.blocked_reason = result["reason"]
            self.log("warn", f"Manual arm rejected: {result['reason']}")
            return result
        if self.stm32_link is None or not self.hardware["stm32"].connected:
            result = {"accepted": False, "reason": "STM32 unavailable"}
            self.manual.blocked_reason = result["reason"]
            self.mode_manager.enter_error("STM32 unavailable during MANUAL arm", source="manual_arm")
            self.log("error", "Manual arm rejected: STM32 unavailable")
            return result

        arm_num = 2 if int(arm) == 2 else 1
        step_limit = max(1, int(self.manual.max_arm_steps))
        speed_limit = max(1, int(self.manual.max_arm_speed))
        clamped_steps = self.clamp(int(steps), step_limit)
        clamped_speed = max(2000, min(speed_limit, int(speed)))

        started = time.monotonic()
        if arm_num == 2:
            serial_result = self.stm32_link.send_arm2(clamped_steps, clamped_speed)
        else:
            serial_result = self.stm32_link.send_arm(clamped_steps, clamped_speed)
        elapsed_ms = (time.monotonic() - started) * 1000.0

        result = {
            "accepted": bool(serial_result["ok"]),
            "arm": arm_num,
            "steps": clamped_steps,
            "speed": clamped_speed,
            "elapsed_ms": elapsed_ms,
            "serial": serial_result,
        }
        self.manual.arm_step_setting = abs(clamped_steps) or self.manual.arm_step_setting
        self.manual.arm_speed_setting = clamped_speed
        self.manual.last_command_at = time.time()
        self.manual.command_count += 1
        self.manual.last_arm_command = result
        self.manual.last_result = serial_result
        self.log("drive", f"MANUAL arm{arm_num} steps={clamped_steps} speed={clamped_speed} result={serial_result['detail']}")
        return result

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
                detail=status.tts_detail
                if status.speaker_available
                else (
                    "playback device detected but no confirmed speaker selected"
                    if status.playback_devices
                    else "no playback device selected"
                ),
                last_seen=time.time() if status.speaker_available else None,
            )
            self.log("info", "Audio hardware refreshed")
        return status.to_dict()

    def select_microphone(self, device: str | None) -> dict[str, Any]:
        status = self.audio_runtime.set_microphone(device)
        self.refresh_audio()
        self.log("info", f"Microphone preference set to {device or 'automatic'}")
        return status

    def select_speaker(self, device: str | None) -> dict[str, Any]:
        status = self.audio_runtime.set_speaker(device)
        self.refresh_audio()
        self.log("info", f"Speaker preference set to {device or 'automatic'}")
        return status

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
        stop = self.degraded_stop_guard_if_safe(stop)
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

    def degraded_stop_guard_if_safe(self, stop: dict[str, Any]) -> dict[str, Any]:
        if stop.get("ok") or self.stm32_link is None:
            return stop
        runtime = self.stm32_link.get_status()
        now = time.time()
        recent_link = bool(runtime.running and runtime.last_seen and now - runtime.last_seen <= 2.0)
        telemetry_speed = runtime.telemetry.get("SPD") if runtime.telemetry else None
        try:
            speed_zero = abs(float(telemetry_speed or 0.0)) <= 0.01
        except (TypeError, ValueError):
            speed_zero = False
        manual_zero = self.manual.speed_intent == 0 and self.manual.steer_intent == 0
        if recent_link and speed_zero and manual_zero:
            degraded = dict(stop)
            degraded.update(
                {
                    "ok": True,
                    "acknowledged": False,
                    "degraded": True,
                    "original_detail": stop.get("detail"),
                    "detail": "STOP sent; ACK missing, link alive, speed zero",
                }
            )
            self.log("warn", f"WELCOME_TALK using degraded stop guard: {stop.get('detail')}")
            return degraded
        return stop

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
        command = ["sudo", "shutdown", "-h", "now"]
        try:
            subprocess.Popen(command)
        except Exception as exc:
            self.log("error", f"Raspberry Pi shutdown command failed: {exc}")
            return {
                "accepted": False,
                "reason": str(exc),
                "command": " ".join(command),
                "stop": stop,
            }

        self.log("warn", "Raspberry Pi shutdown command executed")
        return {
            "accepted": True,
            "reason": "Raspberry Pi shutdown command executed",
            "command": " ".join(command),
            "stop": stop,
        }

    def hardware_status_for_validation(self) -> dict[str, Any]:
        with self.lock:
            return {key: asdict(value) for key, value in self.hardware.items()}

    def validation_catalog(self) -> dict[str, Any]:
        return self.validation_center.catalog(self.hardware_status_for_validation())

    def run_validation_test(self, test_id: str) -> dict[str, Any]:
        result = self.validation_center.run(test_id, self.hardware_status_for_validation())
        level = "pass" if result.status == "PASS" else ("warn" if result.status == "WARNING" else "error")
        self.log(level, f"Validation {result.name}: {result.status}")
        payload = result.to_dict()
        payload["catalog"] = self.validation_catalog()
        return payload

    def snapshot(self) -> PlutoStatus:
        with self.lock:
            hardware = {key: value for key, value in self.hardware.items()}
            events = list(self.events)
            mode_snapshot = self.mode_manager.snapshot(self.safety_context(operator_request=True))
            stm32_runtime = stm32_status_to_dict(self.stm32_link.get_status()) if self.stm32_link else {}
            self.escalate_critical_alert_if_needed(stm32_runtime)
            self.process_idle_wave_trigger()
            mode_snapshot = self.mode_manager.snapshot(self.safety_context(operator_request=True))
            camera_status = status_to_dict(self.camera_service.get_status())
            welcome_approach = self.update_welcome_approach(mode_snapshot, camera_status, stm32_runtime)
            mode_snapshot = self.mode_manager.snapshot(self.safety_context(operator_request=True))
            dance = self.update_dance_runtime(mode_snapshot, camera_status, stm32_runtime)
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
                camera=camera_status,
                mode_manager=mode_snapshot,
                stm32_runtime=stm32_runtime,
                error=self.error_status(mode_snapshot, stm32_runtime),
                manual=asdict(self.manual),
                wave=self.wave_status(),
                welcome_approach=welcome_approach,
                dance=dance,
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

    def wave_status(self) -> dict[str, Any]:
        return asdict(self.wave)

    def update_welcome_approach(
        self,
        mode_snapshot: dict[str, Any] | None = None,
        camera_status: dict[str, Any] | None = None,
        stm32_runtime: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mode_snapshot = mode_snapshot or self.mode_manager.snapshot(self.safety_context(operator_request=True))
        camera_status = camera_status or status_to_dict(self.camera_service.get_status())
        stm32_runtime = stm32_runtime or (stm32_status_to_dict(self.stm32_link.get_status()) if self.stm32_link else {})

        status = self.approach_planner.compute(
            camera_status=camera_status,
            stm32_runtime=stm32_runtime,
            wave_status=self.wave_status(),
            current_state=str(mode_snapshot.get("current_state", "UNKNOWN")),
            current_substate=str(mode_snapshot.get("current_substate", "UNKNOWN")),
        )

        if (
            status.active
            and status.target_id is not None
            and self.mode_manager.current_state == "WELCOME"
            and self.mode_manager.current_substate == "WELCOME_DETECT"
        ):
            self.mode_manager.set_substate("WELCOME_APPROACH_DRY_RUN", return_lock=False)
            status.substate = self.mode_manager.current_substate

        if status.active:
            now = time.monotonic()
            if now - self.approach_last_stop_at >= 1.0:
                stop = self.send_stm32_stop_safe(self.hardware["stm32"].port)
                status.stop_guard = self.degraded_stop_guard_if_safe(stop)
                self.approach_last_stop_at = now
                if self.hardware["stm32"].connected and not status.stop_guard.get("ok"):
                    transition = self.mode_manager.enter_error(
                        "Unable to verify stopped wheels during WELCOME_APPROACH dry-run",
                        source="welcome_approach",
                    )
                    status.active = False
                    status.proposed_motion = "stop"
                    status.proposed_speed = 0
                    status.proposed_steer = 0
                    status.reason = "stop guard failed"
                    status.stop_guard["transition"] = transition.to_dict()
                    self.log("error", f"WELCOME_APPROACH dry-run stop guard failed: {status.stop_guard.get('detail')}")
            elif not status.stop_guard:
                status.stop_guard = {"ok": True, "detail": "recent STOP guard still valid", "degraded": False}

        self.approach_status = status
        return status.to_dict()

    def update_dance_runtime(
        self,
        mode_snapshot: dict[str, Any] | None = None,
        camera_status: dict[str, Any] | None = None,
        stm32_runtime: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mode_snapshot = mode_snapshot or self.mode_manager.snapshot(self.safety_context(operator_request=True))
        camera_status = camera_status or status_to_dict(self.camera_service.get_status())
        stm32_runtime = stm32_runtime or (stm32_status_to_dict(self.stm32_link.get_status()) if self.stm32_link else {})

        if self.mode_manager.current_state == "DANCE":
            if self.dance_started_at is None:
                self.dance_started_at = time.time()
                self.dance_audio_started = False
            if self.mode_manager.current_substate == "DANCE_READY":
                self.mode_manager.set_substate("DANCE_DRY_RUN", return_lock=False)
        else:
            if self.dance_audio_started:
                self.audio_runtime.stop_playback(reason="DANCE exited")
                self.log("info", "DANCE audio stopped")
            self.dance_audio_started = False
            self.dance_started_at = None

        status = self.dance_planner.compute(
            camera_status=camera_status,
            stm32_runtime=stm32_runtime,
            audio_status=self.audio_status(),
            current_state=self.mode_manager.current_state,
            current_substate=self.mode_manager.current_substate,
            dance_started_at=self.dance_started_at,
        )

        if status.active:
            if not self.dance_audio_started and status.audio_status == "ready" and status.audio_file:
                play = self.audio_runtime.play_file_async(status.audio_file)
                self.dance_audio_started = bool(play.get("ok"))
                if play.get("ok"):
                    self.log("pass", f"DANCE audio started: {status.audio_file}")
                else:
                    self.log("warn", f"DANCE audio failed: {play.get('detail')}")
            now = time.monotonic()
            if now - self.dance_last_stop_at >= 1.0:
                stop = self.send_stm32_stop_safe(self.hardware["stm32"].port)
                status.stop_guard = self.degraded_stop_guard_if_safe(stop)
                self.dance_last_stop_at = now
                if self.hardware["stm32"].connected and not status.stop_guard.get("ok"):
                    transition = self.mode_manager.enter_error(
                        "Unable to verify stopped wheels during DANCE dry-run",
                        source="dance",
                    )
                    status.active = False
                    status.proposed_motion = "stop"
                    status.proposed_speed = 0
                    status.proposed_steer = 0
                    status.reason = "stop guard failed"
                    status.stop_guard["transition"] = transition.to_dict()
                    self.log("error", f"DANCE dry-run stop guard failed: {status.stop_guard.get('detail')}")
            elif not status.stop_guard:
                status.stop_guard = {"ok": True, "detail": "recent STOP guard still valid", "degraded": False}

        self.dance_status = status
        return status.to_dict()

    def process_idle_wave_trigger(self) -> None:
        if self.mode_manager.current_state != "IDLE" or not self.wave.enabled:
            return
        detector = dict(self.wave.detector or self.update_wave_detector())
        if not detector.get("confirmed", False):
            return
        source = self.wave.armed_source if time.time() <= self.wave.armed_until and self.wave.armed_source else "camera_wave"
        result = self.welcome_wave_trigger(source=source, diagnostic=False)
        if result.get("accepted"):
            self.wave.armed_until = 0.0
            self.wave.armed_source = None
            self.log("pass", "IDLE real wave detected; WELCOME requested")

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
                    if (
                        line == "ACK:PING"
                        or line == STM32_ID
                        or line.startswith("TEL:")
                        or line.startswith("OBS:")
                        or line.startswith("IMU:")
                    ):
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
  <meta name="color-scheme" content="dark light">
  <title>PLUTO Mission Control</title>
  <script>
    (() => {{
      try {{
        const saved = localStorage.getItem('pluto-theme') || 'auto';
        const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        const resolved = saved === 'dark' || (saved === 'auto' && prefersDark) ? 'dark' : 'light';
        document.documentElement.dataset.theme = resolved;
        document.documentElement.dataset.themeChoice = saved;
      }} catch (err) {{
        document.documentElement.dataset.theme = 'light';
        document.documentElement.dataset.themeChoice = 'auto';
      }}
    }})();
  </script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #eef2f5;
      --panel: #ffffff;
      --panel-soft: #f8fafb;
      --ink: #111417;
      --muted: #68727b;
      --heading: #26313a;
      --line: #cfd7de;
      --line-strong: #9ba7b1;
      --good: #137a47;
      --warn: #9a6500;
      --bad: #b42318;
      --accent: #1769aa;
      --accent-strong: #0c4f82;
      --shell: #0b0d10;
      --shell-2: #171b20;
      --button-bg: #ffffff;
      --input-bg: #ffffff;
      --section-shadow: 0 1px 2px rgba(17, 20, 23, 0.04);
      --accent-bg: #eef7ff;
      --good-bg: #effaf3;
      --warn-bg: #fff8e8;
      --bad-bg: #fff1f0;
      --info-bg: #f4f8fa;
      --track-bg: #d8e0e6;
    }}
    :root[data-theme="dark"] {{
      color-scheme: dark;
      --bg: #071018;
      --panel: #0e161f;
      --panel-soft: #111d27;
      --ink: #e8eef3;
      --muted: #94a8b8;
      --heading: #dbe9f2;
      --line: #253441;
      --line-strong: #40576a;
      --good: #39d98a;
      --warn: #ffc857;
      --bad: #ff5d52;
      --accent: #52a8ff;
      --accent-strong: #8fc8ff;
      --shell: #05090d;
      --shell-2: #101820;
      --button-bg: #121e28;
      --input-bg: #0a121a;
      --section-shadow: 0 10px 26px rgba(0, 0, 0, 0.28);
      --accent-bg: rgba(82, 168, 255, 0.16);
      --good-bg: rgba(57, 217, 138, 0.12);
      --warn-bg: rgba(255, 200, 87, 0.13);
      --bad-bg: rgba(255, 93, 82, 0.14);
      --info-bg: rgba(82, 168, 255, 0.10);
      --track-bg: #233341;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 14px/1.45 system-ui, -apple-system, Segoe UI, sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      display: grid;
      grid-template-columns: minmax(220px, 1fr) auto;
      gap: 18px;
      padding: 14px clamp(16px, 4vw, 40px);
      background: var(--shell);
      color: white;
      border-bottom: 4px solid var(--accent);
      box-shadow: 0 10px 30px rgba(15, 20, 25, 0.2);
    }}
    h1, h2 {{ margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: clamp(26px, 5vw, 46px); line-height: 0.96; }}
    h2 {{
      font-size: 13px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--heading);
    }}
    .eyebrow {{
      margin-bottom: 4px;
      color: #aab6c0;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .header-subtitle {{
      margin-top: 6px;
      color: #c6d0d9;
      font-weight: 700;
    }}
    .header-actions {{
      display: grid;
      grid-template-columns: repeat(4, auto);
      gap: 10px;
      align-content: center;
      justify-content: end;
    }}
    main {{
      width: min(1380px, 100%);
      margin: 0 auto;
      padding: 20px clamp(14px, 3vw, 28px) 36px;
      display: grid;
      gap: 16px;
    }}
    .mission-strip {{
      display: grid;
      grid-template-columns: 1.25fr 1fr 1fr 1fr;
      gap: 12px;
    }}
    .mission-card {{
      min-width: 0;
      background: var(--shell);
      color: white;
      border: 1px solid #28313a;
      border-radius: 8px;
      padding: 14px;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
    }}
    .mission-card strong {{
      display: block;
      margin-top: 4px;
      font-size: clamp(19px, 3vw, 34px);
      line-height: 1;
      overflow-wrap: anywhere;
    }}
    .mission-card span {{
      display: block;
      color: #b7c1ca;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .mission-detail {{
      margin-top: 8px;
      color: #cad3db;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .mission-good {{ border-color: rgba(19, 122, 71, 0.8); }}
    .mission-warn {{ border-color: rgba(154, 101, 0, 0.9); }}
    .mission-bad {{ border-color: rgba(180, 35, 24, 0.9); }}
    .ops-brief {{
      display: grid;
      grid-template-columns: 1.15fr 1fr 1fr 1.35fr;
      gap: 10px;
      margin-top: 10px;
    }}
    .brief-card {{
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 12px;
    }}
    .brief-card.good {{ border-color: rgba(19, 122, 71, 0.45); background: var(--good-bg); }}
    .brief-card.warn {{ border-color: rgba(154, 101, 0, 0.45); background: var(--warn-bg); }}
    .brief-card.bad {{ border-color: rgba(180, 35, 24, 0.45); background: var(--bad-bg); }}
    .brief-label {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .brief-value {{
      display: block;
      margin-top: 5px;
      font-size: clamp(18px, 2.5vw, 28px);
      font-weight: 900;
      line-height: 1.08;
      overflow-wrap: anywhere;
    }}
    .brief-detail {{
      margin-top: 6px;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .visual-band {{
      grid-column: span 12;
      display: grid;
      grid-template-columns: minmax(0, 2fr) minmax(300px, 0.9fr);
      padding: 0;
      min-height: 520px;
      overflow: hidden;
      background: #081016;
      color: #e8eef3;
      border-color: #253441;
      box-shadow: 0 12px 35px rgba(8, 16, 22, 0.25);
    }}
    .visual-scene {{
      position: relative;
      min-height: 520px;
      overflow: hidden;
    }}
    #pluto3dCanvas {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 520px;
      background: #081016;
    }}
    .visual-overlay {{
      position: absolute;
      inset: 14px auto auto 14px;
      width: min(420px, calc(100% - 28px));
      display: grid;
      gap: 8px;
      pointer-events: none;
    }}
    .visual-kicker {{
      color: #8fb3c9;
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }}
    .visual-title {{
      font-size: clamp(24px, 4vw, 42px);
      font-weight: 950;
      line-height: 0.98;
    }}
    .visual-status {{
      width: fit-content;
      max-width: 100%;
      border: 1px solid rgba(143, 179, 201, 0.34);
      border-radius: 8px;
      background: rgba(8, 16, 22, 0.76);
      padding: 8px 10px;
      color: #d9e8f2;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .visual-readouts {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 4px;
    }}
    .visual-readout {{
      border: 1px solid rgba(143, 179, 201, 0.22);
      border-radius: 8px;
      background: rgba(8, 16, 22, 0.68);
      padding: 8px;
      min-width: 0;
    }}
    .visual-readout span {{
      display: block;
      color: #8fb3c9;
      font-size: 10px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .visual-readout strong {{
      display: block;
      margin-top: 3px;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 15px;
      overflow-wrap: anywhere;
    }}
    .launch-panel {{
      display: grid;
      align-content: start;
      gap: 12px;
      padding: 16px;
      background: #101820;
      border-left: 1px solid #253441;
    }}
    .launch-panel h2 {{
      color: #e8eef3;
      border-bottom-color: #253441;
    }}
    .launch-gate {{
      border: 1px solid #364958;
      border-radius: 8px;
      padding: 12px;
      background: #15202a;
    }}
    .launch-gate.good {{ border-color: rgba(57, 217, 138, 0.65); }}
    .launch-gate.warn {{ border-color: rgba(255, 200, 87, 0.65); }}
    .launch-gate.bad {{ border-color: rgba(255, 93, 82, 0.72); }}
    .launch-gate span {{
      display: block;
      color: #8fb3c9;
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .launch-gate strong {{
      display: block;
      margin-top: 6px;
      font-size: 30px;
      line-height: 1;
    }}
    .launch-gate small {{
      display: block;
      margin-top: 6px;
      color: #b6cad8;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      overflow-wrap: anywhere;
    }}
    .launch-progress {{
      height: 9px;
      border-radius: 999px;
      background: #263441;
      overflow: hidden;
    }}
    .launch-progress-fill {{
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: #52a8ff;
      transition: width 180ms ease, background 180ms ease;
    }}
    .launch-checklist {{
      display: grid;
      gap: 7px;
    }}
    .launch-check {{
      display: grid;
      grid-template-columns: 76px 1fr;
      gap: 8px;
      align-items: center;
      border: 1px solid #253441;
      border-radius: 8px;
      padding: 8px;
      background: #0e151c;
      color: #d9e8f2;
    }}
    .launch-check .tag {{
      border-radius: 6px;
      padding: 4px 6px;
      text-align: center;
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .launch-check.good .tag {{ background: rgba(57, 217, 138, 0.18); color: #a7f3c4; }}
    .launch-check.warn .tag {{ background: rgba(255, 200, 87, 0.18); color: #ffd166; }}
    .launch-check.bad .tag {{ background: rgba(255, 93, 82, 0.18); color: #ffaaa3; }}
    .launch-check strong {{
      display: block;
      font-size: 13px;
    }}
    .launch-check small {{
      display: block;
      margin-top: 2px;
      color: #90a7b6;
      font-size: 12px;
      overflow-wrap: anywhere;
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
      padding: 14px;
      min-width: 0;
      box-shadow: var(--section-shadow);
    }}
    section > h2 {{
      display: flex;
      align-items: center;
      min-height: 26px;
      margin-bottom: 6px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 8px;
    }}
    .span-4 {{ grid-column: span 4; }}
    .span-6 {{ grid-column: span 6; }}
    .span-8 {{ grid-column: span 8; }}
    .span-12 {{ grid-column: span 12; }}
    .metric {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 8px 0;
      border-bottom: 1px solid var(--line);
    }}
    .metric:last-child {{ border-bottom: 0; }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .value {{
      font-weight: 800;
      text-align: right;
      overflow-wrap: anywhere;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    }}
    .status-good {{ color: var(--good); }}
    .status-warn {{ color: var(--warn); }}
    .status-bad {{ color: var(--bad); }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .mode-flow {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 8px;
      margin: 12px 0;
    }}
    .mode-node {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 9px;
      min-width: 0;
    }}
    .mode-node.current {{ border-color: var(--accent); background: var(--accent-bg); }}
    .mode-node.allowed {{ border-color: rgba(19, 122, 71, 0.35); }}
    .mode-node.blocked {{ opacity: 0.68; }}
    .mode-node span {{
      display: block;
      color: var(--muted);
      font-size: 10px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .mode-node strong {{
      display: block;
      margin-top: 4px;
      font-size: 13px;
      overflow-wrap: anywhere;
    }}
    .top-link {{
      min-height: 42px;
      display: inline-flex;
      align-items: center;
      border: 1px solid #40505d;
      background: var(--shell-2);
      color: white;
      border-radius: 8px;
      padding: 10px 13px;
      font-weight: 800;
      text-decoration: none;
    }}
    .theme-control {{
      display: grid;
      grid-template-columns: auto minmax(112px, 1fr);
      align-items: center;
      gap: 7px;
      min-height: 42px;
      border: 1px solid #40505d;
      border-radius: 8px;
      background: var(--shell-2);
      color: white;
      padding: 7px 10px;
      font-weight: 800;
    }}
    .theme-control span {{
      color: #aab6c0;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .theme-control select {{
      min-height: 28px;
      border: 1px solid #40505d;
      border-radius: 6px;
      background: #0b0d10;
      color: white;
      font: inherit;
      font-weight: 800;
      padding: 3px 7px;
    }}
    button {{
      min-height: 42px;
      border: 1px solid var(--line);
      background: var(--button-bg);
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
    .state.is-current {{
      background: var(--shell);
      color: white;
      border-color: var(--shell);
      opacity: 1;
    }}
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
    .manual-controls {{
      display: grid;
      gap: 10px;
      margin-top: 12px;
      max-width: 520px;
    }}
    .manual-control-row {{
      display: grid;
      grid-template-columns: 96px minmax(120px, 1fr) 54px;
      align-items: center;
      gap: 10px;
      font-size: 13px;
    }}
    .manual-control-row input[type="range"] {{
      width: 100%;
    }}
    .manual-arm-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(70px, 1fr));
      gap: 8px;
      margin-top: 8px;
    }}
    .manual-arm-settings {{
      display: grid;
      grid-template-columns: repeat(2, minmax(110px, 1fr));
      gap: 10px;
    }}
    .manual-arm-settings label {{
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    .manual-arm-settings input {{
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 10px;
      font: inherit;
      background: var(--input-bg);
      color: var(--ink);
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
      background: var(--input-bg);
      color: var(--ink);
    }}
    .events {{
      min-height: 180px;
      max-height: 320px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
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
    .event-summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }}
    .event-tile {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 10px;
      min-width: 0;
    }}
    .event-tile span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .event-tile strong {{
      display: block;
      margin-top: 4px;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 18px;
      overflow-wrap: anywhere;
    }}
    .event:last-child {{ border-bottom: 0; }}
    .event.warn {{ background: var(--warn-bg); }}
    .event.error, .event.bad {{ background: var(--bad-bg); }}
    .event.pass, .event.info {{ background: var(--info-bg); }}
    .validation-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 10px;
    }}
    .validation-group {{
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 10px;
    }}
    .validation-group h3 {{
      margin: 0 0 8px;
      color: var(--heading);
      font-size: 12px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .validation-test {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px 10px;
      border-top: 1px solid var(--line);
      padding: 10px 0;
    }}
    .validation-test:first-of-type {{ border-top: 0; }}
    .validation-name {{
      font-weight: 850;
      overflow-wrap: anywhere;
    }}
    .validation-meta, .validation-command, .validation-output {{
      grid-column: 1 / -1;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .validation-output {{
      max-height: 180px;
      overflow: auto;
      white-space: pre-wrap;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 8px;
    }}
    .validation-status {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 74px;
      min-height: 30px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 4px 8px;
      font-weight: 900;
      font-size: 12px;
    }}
    .validation-status.pass {{ color: var(--good); border-color: var(--good); background: var(--good-bg); }}
    .validation-status.fail {{ color: var(--bad); border-color: var(--bad); background: var(--bad-bg); }}
    .validation-status.warning, .validation-status.running {{ color: var(--warn); border-color: var(--warn); background: var(--warn-bg); }}
    .hardware-rack {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 9px;
    }}
    .hardware-tile {{
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 10px;
    }}
    .hardware-tile.good {{ border-color: rgba(19, 122, 71, 0.45); background: var(--good-bg); }}
    .hardware-tile.warn {{ border-color: rgba(154, 101, 0, 0.45); background: var(--warn-bg); }}
    .hardware-tile.bad {{ border-color: rgba(180, 35, 24, 0.45); background: var(--bad-bg); }}
    .hardware-tile span {{
      display: block;
      color: var(--muted);
      font-size: 10px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .hardware-tile strong {{
      display: block;
      margin-top: 4px;
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    .hardware-tile small {{
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 11px;
      overflow-wrap: anywhere;
    }}
    .cameraBox {{
      position: relative;
      width: 100%;
      aspect-ratio: 4 / 3;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: #0c1014;
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
    .stageBox {{
      width: 100%;
      aspect-ratio: 1 / 1;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #0b1015;
      margin: 12px 0;
      overflow: hidden;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
    }}
    #danceStage {{
      width: 100%;
      height: 100%;
      display: block;
    }}
    .sensor-summary {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin: 12px 0;
    }}
    .sensor-pill {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: var(--panel-soft);
      min-width: 0;
    }}
    .sensor-pill .sensor-title {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 4px;
    }}
    .sensor-pill .sensor-value {{
      display: block;
      font-weight: 800;
      overflow-wrap: anywhere;
    }}
    .sensor-pill.good {{ border-color: rgba(31, 122, 77, 0.35); background: var(--good-bg); }}
    .sensor-pill.warn {{ border-color: rgba(154, 101, 0, 0.35); background: var(--warn-bg); }}
    .sensor-pill.bad {{ border-color: rgba(180, 35, 24, 0.35); background: var(--bad-bg); }}
    .sensor-canvas-wrap {{
      width: 100%;
      aspect-ratio: 1.55 / 1;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #0b1015;
      overflow: hidden;
      margin: 12px 0;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
    }}
    #sensorStage {{
      width: 100%;
      height: 100%;
      display: block;
    }}
    .readout-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 12px 0;
    }}
    .readout-grid.three {{
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    .readout-grid.four {{
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }}
    .readout {{
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 10px;
    }}
    .readout.ok, .readout.good {{ border-color: rgba(19, 122, 71, 0.45); background: var(--good-bg); }}
    .readout.warn {{ border-color: rgba(154, 101, 0, 0.45); background: var(--warn-bg); }}
    .readout.bad {{ border-color: rgba(180, 35, 24, 0.45); background: var(--bad-bg); }}
    .readout-label {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .readout-value {{
      margin-top: 4px;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: clamp(18px, 2.5vw, 26px);
      font-weight: 900;
      line-height: 1.05;
      overflow-wrap: anywhere;
    }}
    .readout-detail {{
      margin-top: 5px;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .readout-bar {{
      height: 7px;
      margin-top: 9px;
      border-radius: 999px;
      background: var(--track-bg);
      overflow: hidden;
    }}
    .readout-fill {{
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: var(--accent);
      transition: width 180ms ease, background 180ms ease;
    }}
    .map-head {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 12px;
      margin-top: 12px;
    }}
    .map-title {{
      color: var(--heading);
      font-weight: 900;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }}
    .map-subtitle {{
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12px;
    }}
    .map-legend {{
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
    }}
    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      white-space: nowrap;
    }}
    .swatch {{
      width: 12px;
      height: 12px;
      border-radius: 3px;
      background: var(--line-strong);
    }}
    .swatch.good {{ background: var(--good); }}
    .swatch.warn {{ background: var(--warn); }}
    .swatch.bad {{ background: var(--bad); }}
    .swatch.blue {{ background: var(--accent); }}
    .fusion-flow {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin: 12px 0;
    }}
    .fusion-step {{
      position: relative;
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 10px;
    }}
    .fusion-step::after {{
      content: "";
      position: absolute;
      top: 50%;
      right: -8px;
      width: 8px;
      border-top: 2px solid var(--line-strong);
    }}
    .fusion-step:last-child::after {{ display: none; }}
    .fusion-step.good {{ border-color: rgba(19, 122, 71, 0.45); }}
    .fusion-step.warn {{ border-color: rgba(154, 101, 0, 0.45); }}
    .fusion-step.bad {{ border-color: rgba(180, 35, 24, 0.45); }}
    .fusion-step span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .fusion-step strong {{
      display: block;
      margin-top: 4px;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 17px;
      overflow-wrap: anywhere;
    }}
    .fusion-step small {{
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .guard-panel {{
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 12px;
      margin: 12px 0;
    }}
    .guard-panel.good {{ border-left-color: var(--good); }}
    .guard-panel.warn {{ border-left-color: var(--warn); }}
    .guard-panel.bad {{ border-left-color: var(--bad); }}
    .guard-title {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .guard-decision {{
      display: block;
      margin-top: 4px;
      font-size: 22px;
      font-weight: 900;
      line-height: 1.1;
    }}
    .guard-detail {{
      margin-top: 5px;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .guard-list {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 10px;
    }}
    .guard-item {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--button-bg);
      padding: 8px;
      color: var(--ink);
      font-size: 12px;
      font-weight: 800;
      overflow-wrap: anywhere;
    }}
    pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: 0;
      padding: 12px;
      background: #0c1014;
      color: #e8eef3;
      border-radius: 8px;
      max-height: 280px;
      overflow: auto;
    }}
    @media (max-width: 860px) {{
      header {{ grid-template-columns: 1fr; position: static; }}
      .header-actions {{ grid-template-columns: repeat(2, minmax(0, 1fr)); justify-content: stretch; }}
      .header-actions > * {{ width: 100%; justify-content: center; }}
      .mission-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .mission-card {{ padding: 12px; }}
      .mission-card strong {{ font-size: 20px; }}
      .span-4, .span-6, .span-8 {{ grid-column: span 12; }}
      .visual-band {{ grid-template-columns: 1fr; }}
      .launch-panel {{ border-left: 0; border-top: 1px solid #253441; }}
      .visual-scene, #pluto3dCanvas {{ min-height: 430px; }}
      .visual-readouts {{ grid-template-columns: 1fr; }}
      .ops-brief {{ grid-template-columns: 1fr; }}
      .event {{ grid-template-columns: 1fr; }}
      .event-summary, .hardware-rack, .mode-flow, .validation-grid {{ grid-template-columns: 1fr; }}
      .talk-row {{ grid-template-columns: 1fr; }}
      .sensor-summary {{ grid-template-columns: 1fr; }}
      .readout-grid, .readout-grid.three, .readout-grid.four {{ grid-template-columns: 1fr; }}
      .fusion-flow, .guard-list {{ grid-template-columns: 1fr; }}
      .fusion-step::after {{ display: none; }}
      .map-head {{ align-items: flex-start; flex-direction: column; }}
      .map-legend {{ justify-content: flex-start; }}
    }}
    @media (min-width: 861px) and (max-width: 1180px) {{
      .mission-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <div class="eyebrow">Flight-Ready Operator Console</div>
      <h1>PLUTO Mission Control</h1>
      <div class="header-subtitle">Mode manager owns transitions. STM32 owns motor safety. Operator sees the truth.</div>
    </div>
    <div class="header-actions">
      <label class="theme-control" for="themeMode">
        <span>Theme</span>
        <select id="themeMode" aria-label="Theme mode">
          <option value="auto">Auto</option>
          <option value="dark">Dark</option>
          <option value="light">Light</option>
        </select>
      </label>
      <a class="top-link" href="/face" target="_blank" rel="noopener">Tablet Face</a>
      <button class="danger" id="estop">Emergency Stop</button>
      <button class="danger" id="piShutdown">Shutdown Pi</button>
    </div>
  </header>
  <main>
    <div class="mission-strip" aria-label="PLUTO mission readiness">
      <div class="mission-card mission-warn" id="missionStateCard">
        <span>Current State</span>
        <strong id="missionState">...</strong>
        <div class="mission-detail" id="missionSubstate">substate ...</div>
      </div>
      <div class="mission-card mission-warn" id="missionSafetyCard">
        <span>Safety Gate</span>
        <strong id="missionSafety">checking</strong>
        <div class="mission-detail" id="missionFault">fault none</div>
      </div>
      <div class="mission-card mission-warn" id="missionHardwareCard">
        <span>Hardware Link</span>
        <strong id="missionHardware">0/0</strong>
        <div class="mission-detail" id="missionHeartbeat">heartbeat waiting</div>
      </div>
      <div class="mission-card mission-warn" id="missionTimeCard">
        <span>Runtime</span>
        <strong id="missionUptime">00:00</strong>
        <div class="mission-detail" id="missionUpdated">last update ...</div>
      </div>
    </div>
    <div class="grid">
      <section class="visual-band" aria-label="PLUTO launch and 3D monitor">
        <div class="visual-scene" id="ops3dViewport">
          <canvas id="pluto3dCanvas"></canvas>
          <div class="visual-overlay">
            <div class="visual-kicker">CAD Vehicle Digital Twin</div>
            <div class="visual-title">Launch & Monitor Unit</div>
            <div class="visual-status" id="visual3dStatus">loading 3D monitor</div>
            <div class="visual-readouts">
              <div class="visual-readout">
                <span>Pose</span>
                <strong id="visualPose">waiting</strong>
              </div>
              <div class="visual-readout">
                <span>Envelope</span>
                <strong id="visualEnvelope">waiting</strong>
              </div>
              <div class="visual-readout">
                <span>Mode</span>
                <strong id="visualMode">waiting</strong>
              </div>
            </div>
          </div>
        </div>
        <aside class="launch-panel">
          <h2>Launch Gate</h2>
          <div class="launch-gate warn" id="launchGate">
            <span>Go / No-Go</span>
            <strong id="launchGateState">CHECKING</strong>
            <small id="launchGateDetail">waiting for system readiness</small>
          </div>
          <div class="launch-progress" aria-label="Launch readiness progress">
            <div class="launch-progress-fill" id="launchProgressFill"></div>
          </div>
          <div class="launch-checklist" id="launchChecklist">
            <div class="launch-check warn"><span class="tag">WAIT</span><div><strong>Telemetry</strong><small>waiting</small></div></div>
          </div>
        </aside>
      </section>
      <section class="span-12">
        <h2>Operations Readiness</h2>
        <div class="ops-brief">
          <div class="brief-card warn" id="opsLinkCard">
            <span class="brief-label">Telemetry Truth</span>
            <strong class="brief-value" id="opsLink">waiting</strong>
            <div class="brief-detail" id="opsLinkDetail">STM32 heartbeat and sensor confidence</div>
          </div>
          <div class="brief-card warn" id="opsDecisionCard">
            <span class="brief-label">Robot Decision</span>
            <strong class="brief-value" id="opsDecision">hold</strong>
            <div class="brief-detail" id="opsDecisionDetail">range corridor not evaluated</div>
          </div>
          <div class="brief-card warn" id="opsModeCard">
            <span class="brief-label">Mode Personality</span>
            <strong class="brief-value" id="opsMode">booting</strong>
            <div class="brief-detail" id="opsModeDetail">mode-aware behavior profile</div>
          </div>
          <div class="brief-card warn" id="opsActionCard">
            <span class="brief-label">Operator Action</span>
            <strong class="brief-value" id="opsAction">watch</strong>
            <div class="brief-detail" id="opsActionDetail">next useful human move</div>
          </div>
        </div>
      </section>
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
        <h2>Mode Command Matrix</h2>
        <div class="mode-flow" id="modeFlow"></div>
        <div class="actions" id="states">{states}</div>
        <div class="actions" style="margin-top: 12px;">
          <button id="resetError">Reset To IDLE</button>
          <button id="injectFault">Inject Test Fault</button>
          <button id="waveTrigger">Arm Wave Test</button>
        </div>
        <div id="stateReasons" style="margin-top: 12px;"></div>
      </section>
      <section class="span-6">
        <h2>Systems Rack</h2>
        <div id="hardware"></div>
        <div class="actions" style="margin-top: 14px;">
          <button class="primary" id="refresh">Refresh Hardware</button>
        </div>
      </section>
      <section class="span-6">
        <h2>STM32 Runtime</h2>
        <div class="readout-grid">
          <div class="readout warn" id="stmHeartbeatCard">
            <div class="readout-label">Heartbeat</div>
            <div class="readout-value" id="stmHeartbeat">...</div>
            <div class="readout-detail" id="stmHeartbeatDetail">waiting</div>
            <div class="readout-bar"><div class="readout-fill" id="stmHeartbeatFill"></div></div>
          </div>
          <div class="readout warn" id="stmPingCard">
            <div class="readout-label">Ping Latency</div>
            <div class="readout-value" id="stmPing">...</div>
            <div class="readout-detail">USB CDC response</div>
            <div class="readout-bar"><div class="readout-fill" id="stmPingFill"></div></div>
          </div>
          <div class="readout warn" id="stmBatteryCard">
            <div class="readout-label">Battery</div>
            <div class="readout-value" id="stmBattery">...</div>
            <div class="readout-detail" id="stmBatteryDetail">TEL:BAT</div>
            <div class="readout-bar"><div class="readout-fill" id="stmBatteryFill"></div></div>
          </div>
          <div class="readout warn" id="stmMotionCard">
            <div class="readout-label">Motion</div>
            <div class="readout-value" id="stmMotion">...</div>
            <div class="readout-detail" id="stmMotionDetail">speed and pose</div>
            <div class="readout-bar"><div class="readout-fill" id="stmMotionFill"></div></div>
          </div>
        </div>
        <div class="metric"><span class="label">Pose</span><span class="value" id="stmTel">...</span></div>
        <div class="metric"><span class="label">Range Summary</span><span class="value" id="stmObs">...</span></div>
        <div class="metric"><span class="label">IMU Fusion</span><span class="value" id="stmImu">...</span></div>
        <div class="metric"><span class="label">Last Line</span><span class="value" id="stmLine">...</span></div>
      </section>
      <section class="span-6">
        <h2>Sensor Intelligence</h2>
        <div class="sensor-summary">
          <div class="sensor-pill warn" id="sensorFlCard">
            <span class="sensor-title">Front Left</span>
            <span class="sensor-value" id="sensorFl">...</span>
          </div>
          <div class="sensor-pill warn" id="sensorFCard">
            <span class="sensor-title">Front</span>
            <span class="sensor-value" id="sensorF">...</span>
          </div>
          <div class="sensor-pill warn" id="sensorFrCard">
            <span class="sensor-title">Front Right</span>
            <span class="sensor-value" id="sensorFr">...</span>
          </div>
        </div>
        <div class="fusion-flow" aria-label="Sensor interpretation pipeline">
          <div class="fusion-step warn" id="fusionRangeStep">
            <span>01 Raw Range</span>
            <strong id="fusionRange">...</strong>
            <small id="fusionRangeDetail">ultrasonic echo quality</small>
          </div>
          <div class="fusion-step warn" id="fusionImuStep">
            <span>02 IMU Filter</span>
            <strong id="fusionImu">...</strong>
            <small id="fusionImuDetail">noise handled by calibration and fusion</small>
          </div>
          <div class="fusion-step warn" id="fusionOdomStep">
            <span>03 Odometry</span>
            <strong id="fusionOdom">...</strong>
            <small id="fusionOdomDetail">hall telemetry and pose</small>
          </div>
          <div class="fusion-step warn" id="fusionDecisionStep">
            <span>04 Decision</span>
            <strong id="fusionDecision">...</strong>
            <small id="fusionDecisionDetail">mode guard output</small>
          </div>
        </div>
        <div class="readout-grid four">
          <div class="readout warn" id="sensorNearestCard">
            <div class="readout-label">Nearest Object</div>
            <div class="readout-value" id="sensorNearest">...</div>
            <div class="readout-detail" id="sensorNearestDetail">front arc</div>
            <div class="readout-bar"><div class="readout-fill" id="sensorNearestFill"></div></div>
          </div>
          <div class="readout warn" id="sensorCorridorCard">
            <div class="readout-label">Path Corridor</div>
            <div class="readout-value" id="sensorCorridor">...</div>
            <div class="readout-detail" id="sensorCorridorDetail">ultrasonic decision</div>
            <div class="readout-bar"><div class="readout-fill" id="sensorCorridorFill"></div></div>
          </div>
          <div class="readout warn" id="sensorAttitudeCard">
            <div class="readout-label">Attitude</div>
            <div class="readout-value" id="sensorAttitude">...</div>
            <div class="readout-detail" id="sensorAttitudeDetail">filtered IMU</div>
            <div class="readout-bar"><div class="readout-fill" id="sensorAttitudeFill"></div></div>
          </div>
          <div class="readout warn" id="sensorConfidenceCard">
            <div class="readout-label">Sensor Confidence</div>
            <div class="readout-value" id="sensorConfidence">...</div>
            <div class="readout-detail" id="sensorConfidenceDetail">link + range + IMU</div>
            <div class="readout-bar"><div class="readout-fill" id="sensorConfidenceFill"></div></div>
          </div>
        </div>
        <div class="guard-panel warn" id="modeGuardPanel">
          <div class="guard-title">Mode-Adaptive Guard</div>
          <strong class="guard-decision" id="modeGuardDecision">waiting for telemetry</strong>
          <div class="guard-detail" id="modeGuardDetail">Each mode gets a different interpretation of the same sensors.</div>
          <div class="guard-list" id="modeGuardList">
            <div class="guard-item">Range gate pending</div>
            <div class="guard-item">IMU fusion pending</div>
            <div class="guard-item">Operator action pending</div>
          </div>
        </div>
        <div class="map-head">
          <div>
            <div class="map-title">Range Radar & Occupancy Corridor</div>
            <div class="map-subtitle" id="sensorMapSubtitle">stop zone 60 cm / slow zone 120 cm</div>
          </div>
          <div class="map-legend">
            <span class="legend-item"><span class="swatch bad"></span>stop</span>
            <span class="legend-item"><span class="swatch warn"></span>slow</span>
            <span class="legend-item"><span class="swatch good"></span>clear</span>
            <span class="legend-item"><span class="swatch blue"></span>robot</span>
          </div>
        </div>
        <div class="sensor-canvas-wrap"><canvas id="sensorStage" width="560" height="360"></canvas></div>
        <div class="metric"><span class="label">Sensor Health</span><span class="value" id="sensorHealth">...</span></div>
        <div class="metric"><span class="label">MPU</span><span class="value" id="sensorMpu">...</span></div>
        <div class="metric"><span class="label">Acceleration</span><span class="value" id="sensorAccel">...</span></div>
        <div class="metric"><span class="label">Gyro</span><span class="value" id="sensorGyro">...</span></div>
        <div class="metric"><span class="label">Hoverboard Hall UART</span><span class="value" id="sensorHall">...</span></div>
        <div class="metric"><span class="label">Hall Odometry</span><span class="value" id="sensorHallOdom">...</span></div>
        <div class="metric"><span class="label">Robot Pose</span><span class="value" id="sensorPose">...</span></div>
      </section>
      <section class="span-6">
        <h2>Welcome Wave</h2>
        <div class="metric"><span class="label">Detector</span><span class="value" id="waveDetector">...</span></div>
        <div class="metric"><span class="label">Last Reason</span><span class="value" id="waveReason">none</span></div>
        <div class="metric"><span class="label">Counts</span><span class="value" id="waveCounts">0 / 0</span></div>
        <div class="metric"><span class="label">Thresholds</span><span class="value" id="waveThresholds">...</span></div>
        <div class="metric"><span class="label">Sampler</span><span class="value" id="waveSampler">...</span></div>
        <div class="metric"><span class="label">Last Event</span><span class="value" id="waveEvent">none</span></div>
      </section>
      <section class="span-6">
        <h2>Welcome Approach</h2>
        <div class="metric"><span class="label">Mode</span><span class="value" id="approachMode">dry-run</span></div>
        <div class="metric"><span class="label">Target</span><span class="value" id="approachTarget">none</span></div>
        <div class="metric"><span class="label">Distance</span><span class="value" id="approachDistance">unknown</span></div>
        <div class="metric"><span class="label">Steering</span><span class="value" id="approachSteering">unknown</span></div>
        <div class="metric"><span class="label">Obstacles</span><span class="value" id="approachObstacles">unknown</span></div>
        <div class="metric"><span class="label">Proposal</span><span class="value" id="approachProposal">stop</span></div>
        <div class="metric"><span class="label">Reason</span><span class="value" id="approachReason">not evaluated</span></div>
        <div class="metric"><span class="label">STOP Guard</span><span class="value" id="approachStop">none</span></div>
      </section>
      <section class="span-6">
        <h2>Manual Control</h2>
        <div class="metric"><span class="label">Enabled</span><span class="value" id="manualEnabled">false</span></div>
        <div class="metric"><span class="label">Intent</span><span class="value" id="manualIntent">0,0</span></div>
        <div class="metric"><span class="label">Limit</span><span class="value" id="manualLimit">...</span></div>
        <div class="metric"><span class="label">Blocked</span><span class="value" id="manualBlocked">none</span></div>
        <div class="metric"><span class="label">Arm Last</span><span class="value" id="manualArmLast">none</span></div>
        <div class="manual-controls">
          <div class="manual-control-row">
            <label for="manualBaseSpeed">Base speed</label>
            <input id="manualBaseSpeed" type="range" min="50" max="400" step="50" value="100">
            <span id="manualBaseSpeedValue">100</span>
          </div>
          <div class="manual-control-row">
            <label for="manualBaseSteer">Base steer</label>
            <input id="manualBaseSteer" type="range" min="50" max="400" step="50" value="100">
            <span id="manualBaseSteerValue">100</span>
          </div>
        </div>
        <div class="manual-pad" id="manualPad">
          <span></span><button data-motion="forward">Forward</button><span></span>
          <button data-motion="left">Left</button><button class="danger" id="manualStop">Stop</button><button data-motion="right">Right</button>
          <span></span><button data-motion="back">Back</button><span></span>
        </div>
        <div class="manual-controls">
          <div class="manual-arm-settings">
            <label>Arm steps
              <input id="manualArmSteps" type="number" min="1" max="10000" step="10" value="5000">
            </label>
            <label>Arm speed
              <input id="manualArmSpeed" type="number" min="2000" max="3000" step="10" value="2000">
            </label>
          </div>
          <div class="manual-arm-grid">
            <button data-arm="1" data-arm-dir="1">Arm1 +</button>
            <button data-arm="1" data-arm-dir="-1">Arm1 -</button>
            <button data-arm="2" data-arm-dir="1">Arm2 +</button>
            <button data-arm="2" data-arm-dir="-1">Arm2 -</button>
          </div>
        </div>
      </section>
      <section class="span-6">
        <h2>Dance</h2>
        <div class="metric"><span class="label">Mode</span><span class="value" id="danceMode">dry-run</span></div>
        <div class="metric"><span class="label">Audio</span><span class="value" id="danceAudio">unknown</span></div>
        <div class="metric"><span class="label">Playback</span><span class="value" id="dancePlayback">none</span></div>
        <div class="metric"><span class="label">Step</span><span class="value" id="danceStep">idle</span></div>
        <div class="metric"><span class="label">Obstacles</span><span class="value" id="danceObstacles">unknown</span></div>
        <div class="metric"><span class="label">Vision</span><span class="value" id="danceVision">unknown</span></div>
        <div class="metric"><span class="label">Proposal</span><span class="value" id="danceProposal">stop</span></div>
        <div class="metric"><span class="label">Envelope</span><span class="value" id="danceEnvelope">unknown</span></div>
        <div class="metric"><span class="label">Odometry</span><span class="value" id="danceOdom">unknown</span></div>
        <div class="metric"><span class="label">Direction</span><span class="value" id="danceDirection">unknown</span></div>
        <div class="metric"><span class="label">Reason</span><span class="value" id="danceReason">not evaluated</span></div>
        <div class="metric"><span class="label">STOP Guard</span><span class="value" id="danceStop">none</span></div>
        <div class="map-head">
          <div>
            <div class="map-title">Dance Envelope Map</div>
            <div class="map-subtitle" id="danceMapSubtitle">3 m x 3 m operating box / predicted next pose</div>
          </div>
          <div class="map-legend">
            <span class="legend-item"><span class="swatch blue"></span>current</span>
            <span class="legend-item"><span class="swatch good"></span>safe path</span>
            <span class="legend-item"><span class="swatch warn"></span>margin</span>
            <span class="legend-item"><span class="swatch bad"></span>limit</span>
          </div>
        </div>
        <div class="stageBox"><canvas id="danceStage" width="360" height="360"></canvas></div>
        <div class="actions" style="margin-top: 12px;">
          <button class="primary" id="danceStart">Start Dance Dry Run</button>
          <button id="danceStopBtn">Stop Dance</button>
        </div>
      </section>
      <section class="span-6">
        <h2>Welcome Talk</h2>
        <div class="metric"><span class="label">Version</span><span class="value" id="talkVersion">v1</span></div>
        <div class="metric"><span class="label">Limits</span><span class="value" id="talkLimits">9 in / 9 out</span></div>
        <div class="metric"><span class="label">Bank</span><span class="value" id="talkBank">loading</span></div>
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
        <div class="talk-row">
          <input id="audioMicOverride" maxlength="160" placeholder="Mic override, e.g. headset or plughw:CARD=...">
          <button id="audioUseMic">Use Mic</button>
          <button id="audioAutoMic">Auto Mic</button>
          <button id="audioRefresh">Audio Refresh</button>
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
        <div class="metric"><span class="label">Pose</span><span class="value" id="cameraPose">not checked</span></div>
      </section>
      <section class="span-12">
        <h2>Validation Center</h2>
        <div class="validation-grid" id="validationCenter"></div>
      </section>
      <section class="span-12">
        <h2>Mission Log</h2>
        <div class="event-summary">
          <div class="event-tile"><span>Latest</span><strong id="eventLatest">none</strong></div>
          <div class="event-tile"><span>Warnings</span><strong id="eventWarnings">0</strong></div>
          <div class="event-tile"><span>Fault Events</span><strong id="eventFaults">0</strong></div>
          <div class="event-tile"><span>Log Depth</span><strong id="eventDepth">0</strong></div>
        </div>
        <div class="events" id="events"></div>
      </section>
      <section class="span-12">
        <h2>Bootstrap Report</h2>
        <pre id="report">{{}}</pre>
      </section>
    </div>
  </main>
  <script type="module" src="/static/pluto_3d.js"></script>
  <script>
    const THEME_KEY = 'pluto-theme';
    const themeMedia = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    let validationCatalog = [];
    let validationLastResults = {{}};
    function getStoredTheme() {{
      try {{
        return localStorage.getItem(THEME_KEY) || 'auto';
      }} catch (err) {{
        return 'auto';
      }}
    }}
    function resolveTheme(choice) {{
      return choice === 'dark' || (choice === 'auto' && themeMedia && themeMedia.matches) ? 'dark' : 'light';
    }}
    function applyTheme(choice) {{
      const safeChoice = ['auto', 'dark', 'light'].includes(choice) ? choice : 'auto';
      document.documentElement.dataset.theme = resolveTheme(safeChoice);
      document.documentElement.dataset.themeChoice = safeChoice;
      const select = document.getElementById('themeMode');
      if (select) select.value = safeChoice;
      try {{
        localStorage.setItem(THEME_KEY, safeChoice);
      }} catch (err) {{}}
    }}
    applyTheme(getStoredTheme());
    if (themeMedia) {{
      const refreshAutoTheme = () => {{
        if (getStoredTheme() === 'auto') applyTheme('auto');
      }};
      if (themeMedia.addEventListener) {{
        themeMedia.addEventListener('change', refreshAutoTheme);
      }} else if (themeMedia.addListener) {{
        themeMedia.addListener(refreshAutoTheme);
      }}
    }}
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
    function parseKvLine(line, prefix) {{
      if (!line || !line.startsWith(prefix)) return null;
      const out = {{}};
      line.slice(prefix.length).split(',').forEach(part => {{
        const idx = part.indexOf(':');
        if (idx < 0) return;
        const key = part.slice(0, idx).trim();
        const raw = part.slice(idx + 1).trim();
        const num = Number(raw);
        out[key] = Number.isFinite(num) ? num : raw;
      }});
      return out;
    }}
    function finiteNumber(value, fallback = null) {{
      const n = Number(value);
      return Number.isFinite(n) ? n : fallback;
    }}
    function pct(value, min, max) {{
      const n = finiteNumber(value, min);
      return Math.max(0, Math.min(100, ((n - min) / Math.max(1, max - min)) * 100));
    }}
    function setReadout(id, value, detail, level = 'warn', percent = null) {{
      const card = document.getElementById(`${{id}}Card`);
      const valueNode = document.getElementById(id);
      const detailNode = document.getElementById(`${{id}}Detail`);
      const fill = document.getElementById(`${{id}}Fill`);
      if (card) card.className = `readout ${{level}}`;
      if (valueNode) valueNode.textContent = value;
      if (detailNode) detailNode.textContent = detail;
      if (fill) {{
        fill.style.width = percent == null ? '0%' : `${{Math.max(0, Math.min(100, percent)).toFixed(0)}}%`;
        fill.style.background = level === 'bad' ? '#b42318' : (level === 'warn' ? '#9a6500' : '#137a47');
      }}
    }}
    function setBrief(id, value, detail, level = 'warn') {{
      const card = document.getElementById(`${{id}}Card`);
      const valueNode = document.getElementById(id);
      const detailNode = document.getElementById(`${{id}}Detail`);
      if (card) card.className = `brief-card ${{level}}`;
      if (valueNode) valueNode.textContent = value;
      if (detailNode) detailNode.textContent = detail;
    }}
    function setFusion(id, value, detail, level = 'warn') {{
      const step = document.getElementById(`${{id}}Step`);
      const valueNode = document.getElementById(id);
      const detailNode = document.getElementById(`${{id}}Detail`);
      if (step) step.className = `fusion-step ${{level}}`;
      if (valueNode) valueNode.textContent = value;
      if (detailNode) detailNode.textContent = detail;
    }}
    function roundedRect(ctx, x, y, width, height, radius) {{
      if (typeof ctx.roundRect === 'function') {{
        ctx.roundRect(x, y, width, height, radius);
        return;
      }}
      const r = Math.max(0, Math.min(radius, Math.abs(width) / 2, Math.abs(height) / 2));
      ctx.moveTo(x + r, y);
      ctx.lineTo(x + width - r, y);
      ctx.quadraticCurveTo(x + width, y, x + width, y + r);
      ctx.lineTo(x + width, y + height - r);
      ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
      ctx.lineTo(x + r, y + height);
      ctx.quadraticCurveTo(x, y + height, x, y + height - r);
      ctx.lineTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
    }}
    function modeLabel(state) {{
      if (state === 'IDLE') return 'playful idle';
      if (state === 'WELCOME') return 'social approach';
      if (state === 'MANUAL') return 'direct drive';
      if (state === 'DANCE') return 'performance';
      if (state === 'ERROR') return 'safe stop';
      if (state === 'BOOTSTRAP') return 'bring-up';
      return String(state || 'unknown').toLowerCase();
    }}
    function esc(value) {{
      return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({{
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }}[ch]));
    }}
    function cleanClass(value) {{
      return String(value || '').toLowerCase().replace(/[^a-z0-9_-]/g, '');
    }}
    function renderModeFlow(data, allowed) {{
      const flow = document.getElementById('modeFlow');
      if (!flow) return;
      const states = ['BOOTSTRAP', 'IDLE', 'MANUAL', 'WELCOME', 'DANCE', 'ERROR', 'GAME_LATER'];
      flow.innerHTML = states.map((state, index) => {{
        const item = allowed[state];
        const status = state === data.current_state ? 'current' : (item && item.allowed ? 'allowed' : 'blocked');
        const reason = item ? item.reason : 'unavailable';
        return `<div class="mode-node ${{status}}">
          <span>${{String(index + 1).padStart(2, '0')}} / ${{status}}</span>
          <strong>${{esc(state)}}</strong>
          <small>${{esc(reason)}}</small>
        </div>`;
      }}).join('');
    }}
    function renderHardwareRack(hardwareRows) {{
      const hardware = document.getElementById('hardware');
      hardware.innerHTML = hardwareRows.map(item => {{
        const level = item.connected ? 'good' : (item.required ? 'bad' : 'warn');
        const tag = item.required ? 'required' : 'optional';
        const detail = `${{item.status || 'unknown'}}${{item.port ? ' / ' + item.port : ''}}${{item.detail ? ' / ' + item.detail : ''}}`;
        return `<div class="hardware-tile ${{level}}">
          <span>${{esc(tag)}}</span>
          <strong>${{esc(item.name)}}</strong>
          <small>${{esc(detail)}}</small>
        </div>`;
      }}).join('');
    }}
    function validationMissingHardware(test, hardware) {{
      return (test.required_hardware || []).filter(key => !(hardware[key] && hardware[key].connected));
    }}
    function validationStatusClass(status) {{
      const clean = cleanClass(status || 'warning');
      if (clean === 'pass') return 'pass';
      if (clean === 'fail') return 'fail';
      if (clean === 'running') return 'running';
      return 'warning';
    }}
    function renderValidationCatalog(catalog, hardware) {{
      const root = document.getElementById('validationCenter');
      if (!root) return;
      if (!catalog.length) {{
        root.innerHTML = '<div class="validation-group"><h3>Validation Center</h3><div class="validation-meta">loading catalog</div></div>';
        return;
      }}
      const order = ['Communication Tests', 'Motion Tests', 'Perception Tests', 'Audio Tests', 'Safety Tests', 'System Tests'];
      const groups = new Map();
      catalog.forEach(test => {{
        if (!groups.has(test.category)) groups.set(test.category, []);
        groups.get(test.category).push(test);
      }});
      root.innerHTML = order.filter(category => groups.has(category)).map(category => {{
        const tests = groups.get(category);
        return `<div class="validation-group">
          <h3>${{esc(category)}}</h3>
          ${{tests.map(test => {{
            const missing = validationMissingHardware(test, hardware || {{}});
            const result = validationLastResults[test.id] || test.last_result || null;
            const status = result ? result.status : (missing.length ? 'WARNING' : 'READY');
            const statusClass = validationStatusClass(status);
            const disabled = missing.length > 0 || status === 'RUNNING';
            const hardwareText = (test.required_hardware || []).length ? test.required_hardware.join(', ') : 'none';
            const block = missing.length ? ` / missing ${{missing.join(', ')}}` : '';
            const measurements = result && result.measurements ? ` / ${{Object.entries(result.measurements).map(([k, v]) => `${{k}}=${{v}}`).join(' / ')}}` : '';
            const output = result && result.output ? result.output : (missing.length ? `Required hardware not detected: ${{missing.join(', ')}}` : 'no run yet');
            return `<div class="validation-test" id="validation-${{esc(test.id)}}">
              <div class="validation-name">${{esc(test.name)}}</div>
              <span class="validation-status ${{statusClass}}">${{esc(status)}}</span>
              <div class="validation-meta">safety=${{esc(test.safety_level)}} / hardware=${{esc(hardwareText)}} / timeout=${{Number(test.timeout_s || 0).toFixed(0)}}s${{esc(block)}}${{esc(measurements)}}</div>
              <div class="validation-command">${{esc(test.terminal_command)}}</div>
              <button data-validation-id="${{esc(test.id)}}" ${{disabled ? 'disabled' : ''}}>${{esc(test.button_label)}}</button>
              <div class="validation-output">${{esc(output)}}</div>
            </div>`;
          }}).join('')}}
        </div>`;
      }}).join('');
    }}
    async function loadValidationCatalog() {{
      const payload = await api('/api/validation/catalog');
      validationCatalog = payload.tests || [];
      validationCatalog.forEach(test => {{
        if (test.last_result) validationLastResults[test.id] = test.last_result;
      }});
      return payload;
    }}
    async function runValidationTest(testId) {{
      const test = validationCatalog.find(item => item.id === testId);
      if (!test) return;
      validationLastResults[testId] = {{
        status: 'RUNNING',
        output: `running ${{test.terminal_command}}`,
        measurements: {{}},
      }};
      renderValidationCatalog(validationCatalog, window.lastPlutoHardware || {{}});
      try {{
        const result = await api('/api/validation/run', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{test_id: testId}})
        }});
        validationLastResults[testId] = result;
        if (result.catalog && result.catalog.tests) {{
          validationCatalog = result.catalog.tests;
        }}
      }} catch (err) {{
        validationLastResults[testId] = {{
          status: 'FAIL',
          output: String(err),
          measurements: {{}},
        }};
      }}
      renderValidationCatalog(validationCatalog, window.lastPlutoHardware || {{}});
    }}
    function renderEventSummary(events) {{
      const warningCount = events.filter(item => cleanClass(item.level) === 'warn').length;
      const faultCount = events.filter(item => ['error', 'bad', 'fail'].includes(cleanClass(item.level))).length;
      const latest = events[0] ? `${{events[0].level}} / ${{events[0].message}}` : 'none';
      document.getElementById('eventLatest').textContent = latest;
      document.getElementById('eventWarnings').textContent = warningCount;
      document.getElementById('eventFaults').textContent = faultCount;
      document.getElementById('eventDepth').textContent = events.length;
    }}
    function renderLaunchGate(checks) {{
      const bad = checks.filter(item => item.level === 'bad').length;
      const warn = checks.filter(item => item.level === 'warn').length;
      const good = checks.filter(item => item.level === 'good').length;
      const progress = Math.round(((good + warn * 0.45) / Math.max(1, checks.length)) * 100);
      const level = bad ? 'bad' : (warn ? 'warn' : 'good');
      const state = bad ? 'NO-GO' : (warn ? 'VERIFY' : 'GO');
      const detail = bad
        ? `${{bad}} blocking check${{bad === 1 ? '' : 's'}} before motion`
        : (warn ? `${{warn}} check${{warn === 1 ? '' : 's'}} need operator validation` : 'software checks green for launch monitor');
      const gate = document.getElementById('launchGate');
      const fill = document.getElementById('launchProgressFill');
      gate.className = `launch-gate ${{level}}`;
      document.getElementById('launchGateState').textContent = state;
      document.getElementById('launchGateDetail').textContent = detail;
      fill.style.width = `${{progress}}%`;
      fill.style.background = level === 'bad' ? '#ff5d52' : (level === 'warn' ? '#ffc857' : '#39d98a');
      document.getElementById('launchChecklist').innerHTML = checks.map(item => `
        <div class="launch-check ${{item.level}}">
          <span class="tag">${{item.level === 'good' ? 'GO' : (item.level === 'bad' ? 'HOLD' : 'CHECK')}}</span>
          <div><strong>${{esc(item.label)}}</strong><small>${{esc(item.detail)}}</small></div>
        </div>
      `).join('');
    }}
    function updateModeGuard(data, corridorLevel, nearest, liveCount, orientation, sensorConfidence) {{
      const panel = document.getElementById('modeGuardPanel');
      const decision = document.getElementById('modeGuardDecision');
      const detail = document.getElementById('modeGuardDetail');
      const list = document.getElementById('modeGuardList');
      if (!panel || !decision || !detail || !list) return;
      const state = data.current_state || 'UNKNOWN';
      const stm = data.stm32_runtime || {{}};
      const rangeText = nearest ? `${{nearest.cm.toFixed(0)}} cm nearest` : `no valid echo, ${{liveCount}}/3 range live`;
      const rangeGateActive = state !== 'MANUAL';
      const guardCorridorLevel = rangeGateActive ? corridorLevel : 'ok';
      let level = guardCorridorLevel === 'bad' ? 'bad' : (guardCorridorLevel === 'warn' ? 'warn' : 'good');
      let headline = guardCorridorLevel === 'bad' ? 'STOP: object inside guard' : (guardCorridorLevel === 'warn' ? 'SLOW: corridor uncertain' : 'CLEAR: front arc open');
      let guardDetail = `${{rangeText}} / confidence ${{sensorConfidence}}% / ${{modeLabel(state)}}`;
      let steps = [];
      if (!stm.running) {{
        level = 'bad';
        headline = 'HOLD: STM32 link offline';
        guardDetail = 'Motor safety controller must be alive before motion validation.';
        steps = ['Connect STM32 USB CDC', 'Refresh hardware', 'Confirm heartbeat before moving'];
      }} else if (state === 'ERROR') {{
        level = 'bad';
        headline = 'SAFE STOP ACTIVE';
        guardDetail = data.fault_reason || 'Fault latched by mode manager.';
        steps = ['Read fault reason', 'Clear physical hazard', 'Reset to IDLE only after verification'];
      }} else if (state === 'IDLE') {{
        steps = ['Face can stay expressive and playful', 'Wheels remain stopped until a mode request', corridorLevel === 'good' ? 'Ready for WELCOME or MANUAL request' : 'Clear front arc before approach'];
      }} else if (state === 'WELCOME') {{
        steps = ['Use camera target plus front range gate', corridorLevel === 'good' ? 'Approach may propose motion' : 'Approach must hold or slow', orientation.available ? 'Filtered IMU available for stable pose' : 'IMU still raw or calibrating'];
      }} else if (state === 'MANUAL') {{
        headline = 'MANUAL: range gate informational';
        guardDetail = `${{rangeText}} / ultrasonic blocking disabled in MANUAL / bounded operator control`;
        steps = ['Operator command remains bounded', 'Ultrasonic readings are displayed only', 'Release controls returns to stop'];
      }} else if (state === 'DANCE') {{
        steps = ['Stay inside dance envelope', corridorLevel === 'good' ? 'Front arc clear for choreography' : 'Obstacle guard reduces confidence', 'Watch margin and predicted pose'];
      }} else {{
        steps = ['Finish bootstrap checks', 'Verify required hardware', 'Then enter IDLE for standby'];
      }}
      panel.className = `guard-panel ${{level}}`;
      decision.textContent = headline;
      detail.textContent = guardDetail;
      list.innerHTML = steps.map(item => `<div class="guard-item">${{item}}</div>`).join('');
      setBrief(
        'opsLink',
        stm.running ? 'live' : 'offline',
        `confidence ${{sensorConfidence}}% / range ${{liveCount}} of 3 / IMU ${{orientation.available ? 'filtered' : (orientation.calibrating ? 'calibrating' : 'raw')}}`,
        stm.running ? (sensorConfidence >= 70 ? 'good' : 'warn') : 'bad'
      );
      setBrief(
        'opsDecision',
        state === 'MANUAL' ? 'INFO' : (corridorLevel === 'bad' ? 'STOP' : (corridorLevel === 'warn' ? 'SLOW' : 'CLEAR')),
        state === 'MANUAL' ? `${{rangeText}} / manual ignores range gate` : rangeText,
        level
      );
      setBrief(
        'opsMode',
        modeLabel(state),
        state === 'IDLE' ? 'alive, calm, playful standby' : `state ${{state}} / ${{data.current_substate || 'no substate'}}`,
        state === 'ERROR' ? 'bad' : (state === 'BOOTSTRAP' ? 'warn' : 'good')
      );
      setBrief(
        'opsAction',
        !stm.running ? 'connect STM32' : (state === 'MANUAL' ? 'operator control' : (corridorLevel === 'bad' ? 'clear path' : (state === 'ERROR' ? 'recover fault' : 'validate mode'))),
        headline,
        !stm.running || state === 'ERROR' || (rangeGateActive && corridorLevel === 'bad') ? 'bad' : (rangeGateActive && corridorLevel === 'warn' ? 'warn' : 'good')
      );
    }}
    function sensorState(value) {{
      const n = Number(value);
      if (!Number.isFinite(n) || n >= 999) return {{label: 'no echo', cls: 'warn', color: '#94a3b8', alive: false, cm: null, pct: 0}};
      if (n <= 60) return {{label: `${{n.toFixed(0)}} cm - stop`, cls: 'bad', color: '#b42318', alive: true, cm: n, pct: pct(n, 0, 420)}};
      if (n <= 120) return {{label: `${{n.toFixed(0)}} cm - slow`, cls: 'warn', color: '#9a6500', alive: true, cm: n, pct: pct(n, 0, 420)}};
      return {{label: `${{n.toFixed(0)}} cm - clear`, cls: 'good', color: '#137a47', alive: true, cm: n, pct: pct(n, 0, 420)}};
    }}
    function setSensorCard(id, value) {{
      const state = sensorState(value);
      document.getElementById(`${{id}}Card`).className = `sensor-pill ${{state.cls}}`;
      document.getElementById(id).textContent = state.label;
      return state;
    }}
    function drawSensorStage(stm) {{
      const canvas = document.getElementById('sensorStage');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#0b1015';
      ctx.fillRect(0, 0, w, h);

      const obstacles = stm.obstacles || {{}};
      const tel = stm.telemetry || {{}};
      const imu = (stm.imu && Object.keys(stm.imu).length) ? stm.imu : (parseKvLine(stm.last_line || '', 'IMU:') || {{}});
      const orient = stm.imu_orientation || {{}};
      const cx = w / 2;
      const cy = h - 52;
      const maxCm = 420;
      const scale = (h * 0.72) / maxCm;
      const toPoint = (angleDeg, cm) => {{
        const r = Math.max(0, cm) * scale;
        const rad = angleDeg * Math.PI / 180;
        return [cx + Math.sin(rad) * r, cy - Math.cos(rad) * r];
      }};
      const drawForwardZone = (cm, color, alpha, label) => {{
        ctx.save();
        ctx.fillStyle = color;
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        for (let a = -58; a <= 58; a += 3) {{
          const [x, y] = toPoint(a, cm);
          ctx.lineTo(x, y);
        }}
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.setLineDash([6, 7]);
        ctx.beginPath();
        for (let a = -58; a <= 58; a += 3) {{
          const [x, y] = toPoint(a, cm);
          if (a === -58) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }}
        ctx.stroke();
        ctx.setLineDash([]);
        const [lx, ly] = toPoint(54, cm);
        ctx.fillStyle = color;
        ctx.font = '11px ui-monospace, Consolas, monospace';
        ctx.fillText(label, lx - 38, ly - 4);
        ctx.restore();
      }};

      ctx.strokeStyle = 'rgba(210, 225, 236, 0.10)';
      ctx.lineWidth = 1;
      for (let x = 0; x <= w; x += 40) {{
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      }}
      for (let y = 0; y <= h; y += 40) {{
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      }}
      drawForwardZone(420, '#137a47', 0.10, 'clear');
      drawForwardZone(120, '#9a6500', 0.18, 'slow 120cm');
      drawForwardZone(60, '#b42318', 0.26, 'stop 60cm');

      const beams = [
        ['FL', obstacles.FL, -34],
        ['F', obstacles.F, 0],
        ['FR', obstacles.FR, 34],
      ];
      const beamStates = beams.map(([key, value, deg]) => ({{key, value, deg, state: sensorState(value)}}));
      const liveCount = beamStates.filter(item => item.state.alive).length;
      const confidence = Math.round((liveCount / 3) * 65 + (stm.running ? 20 : 0) + (orient.available ? 15 : 0));
      for (let forward = 45; forward <= maxCm; forward += 32) {{
        for (let lateral = -190; lateral <= 190; lateral += 32) {{
          const dist = Math.sqrt(forward * forward + lateral * lateral);
          const angle = Math.atan2(lateral, forward) * 180 / Math.PI;
          if (dist > maxCm || Math.abs(angle) > 58) continue;
          const beam = beamStates.reduce((best, item) => Math.abs(item.deg - angle) < Math.abs(best.deg - angle) ? item : best, beamStates[0]);
          const state = beam.state;
          let color = '#51606d';
          let alpha = 0.09;
          if (state.alive) {{
            if (dist < state.cm - 24) {{
              color = '#137a47';
              alpha = 0.16;
            }} else if (Math.abs(dist - state.cm) <= 28) {{
              color = state.color;
              alpha = 0.55;
            }} else {{
              color = '#51606d';
              alpha = 0.05;
            }}
          }}
          const [x, y] = toPoint(angle, dist);
          ctx.save();
          ctx.globalAlpha = alpha;
          ctx.fillStyle = color;
          ctx.beginPath();
          roundedRect(ctx, x - 4, y - 4, 8, 8, 2);
          ctx.fill();
          ctx.restore();
        }}
      }}

      ctx.fillStyle = '#d9e8f2';
      ctx.font = 'bold 13px ui-monospace, Consolas, monospace';
      ctx.fillText('RANGE RADAR & OCCUPANCY CORRIDOR', 16, 24);
      ctx.fillStyle = '#8fa3b2';
      ctx.font = '12px ui-monospace, Consolas, monospace';
      ctx.fillText('green known-clear / amber caution / red obstacle return / gray unknown', 16, 43);

      beamStates.forEach(({{key, value, deg, state}}) => {{
        const cm = state.cm == null ? maxCm : Math.max(10, Math.min(maxCm, state.cm));
        const widthDeg = key === 'F' ? 16 : 20;
        const left = deg - widthDeg;
        const right = deg + widthDeg;
        const [tipX, tipY] = toPoint(deg, cm);
        ctx.save();
        ctx.fillStyle = state.color;
        ctx.globalAlpha = state.alive ? 0.28 : 0.10;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        for (let a = left; a <= right; a += 2) {{
          const [x, y] = toPoint(a, cm);
          ctx.lineTo(x, y);
        }}
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = state.color;
        ctx.lineWidth = state.alive ? 3 : 2;
        if (!state.alive) ctx.setLineDash([8, 8]);
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(tipX, tipY); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = state.color;
        ctx.beginPath();
        ctx.arc(tipX, tipY, state.alive ? 7 : 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.font = 'bold 12px ui-monospace, Consolas, monospace';
        ctx.fillText(`${{key}} ${{state.label}}`, Math.max(12, Math.min(w - 120, tipX - 48)), Math.max(58, tipY - 10));
        ctx.restore();
      }});

      ctx.save();
      ctx.fillStyle = 'rgba(8, 13, 18, 0.74)';
      ctx.strokeStyle = 'rgba(217, 232, 242, 0.18)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      roundedRect(ctx, w - 168, 16, 150, 76, 8);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = confidence >= 70 ? '#a7f3c4' : (confidence >= 40 ? '#ffd166' : '#ff8d87');
      ctx.font = 'bold 22px ui-monospace, Consolas, monospace';
      ctx.fillText(`${{confidence}}%`, w - 152, 45);
      ctx.fillStyle = '#8fa3b2';
      ctx.font = '11px ui-monospace, Consolas, monospace';
      ctx.fillText('sensor confidence', w - 152, 62);
      ctx.fillText(`${{liveCount}}/3 range / ${{stm.running ? 'link' : 'no link'}}`, w - 152, 78);
      ctx.restore();

      const robotW = 74;
      const robotH = 102;
      ctx.save();
      ctx.translate(cx, cy - robotH / 2);
      ctx.fillStyle = '#e8f2f8';
      ctx.strokeStyle = '#52a8ff';
      ctx.lineWidth = 3;
      ctx.beginPath();
      roundedRect(ctx, -robotW / 2, -robotH / 2, robotW, robotH, 16);
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = '#0b1015';
      ctx.font = 'bold 14px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('PLUTO', 0, 6);
      ctx.fillStyle = '#52a8ff';
      ctx.beginPath();
      ctx.moveTo(0, -robotH / 2 - 20);
      ctx.lineTo(-13, -robotH / 2 + 4);
      ctx.lineTo(13, -robotH / 2 + 4);
      ctx.closePath();
      ctx.fill();
      ctx.restore();

      const heading = Number(tel.H || 0) * 180 / Math.PI;
      const roll = orient.available ? Number(orient.roll || 0).toFixed(1) : 'raw';
      const pitch = orient.available ? Number(orient.pitch || 0).toFixed(1) : 'raw';
      const yaw = orient.available ? Number(orient.yaw || 0).toFixed(1) : heading.toFixed(1);
      ctx.fillStyle = '#d9e8f2';
      ctx.font = '12px ui-monospace, Consolas, monospace';
      ctx.fillText(`pose x ${{Number(tel.X || 0).toFixed(0)}}cm y ${{Number(tel.Y || 0).toFixed(0)}}cm heading ${{heading.toFixed(0)}}deg`, 16, h - 30);
      ctx.fillText(`attitude roll ${{roll}} pitch ${{pitch}} yaw ${{yaw}} / MPU ${{Number(imu.OK || 0) === 1 ? 'alive' : 'waiting'}}`, 16, h - 12);
    }}
    function drawDanceStage(dance) {{
      const canvas = document.getElementById('danceStage');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#0b1015';
      ctx.fillRect(0, 0, w, h);

      const pad = 42;
      const box = Math.min(w, h) - pad * 2;
      const cx = w / 2;
      const cy = h / 2;
      const halfCm = Math.max(1, (dance.envelope_size_cm || 300) / 2);
      const scale = box / (halfCm * 2);
      const toPx = (xCm, yCm) => [cx + xCm * scale, cy - yCm * scale];

      ctx.fillStyle = '#d9e8f2';
      ctx.font = 'bold 13px ui-monospace, Consolas, monospace';
      ctx.fillText('DANCE ENVELOPE / ODOMETRY MAP', 16, 24);
      ctx.fillStyle = '#8fa3b2';
      ctx.font = '12px ui-monospace, Consolas, monospace';
      ctx.fillText('current pose, prediction, margin, and no-go boundary', 16, 43);

      const left = cx - box / 2;
      const top = cy - box / 2;
      const marginCm = dance.envelope_margin_cm;
      const marginPx = marginCm == null ? 0 : Math.max(0, Math.min(box / 2, marginCm * scale));
      ctx.fillStyle = 'rgba(19, 122, 71, 0.14)';
      ctx.fillRect(left, top, box, box);
      ctx.strokeStyle = '#d9e8f2';
      ctx.lineWidth = 2;
      ctx.strokeRect(left, top, box, box);
      ctx.fillStyle = 'rgba(180, 35, 24, 0.18)';
      ctx.fillRect(left, top, box, 8);
      ctx.fillRect(left, top + box - 8, box, 8);
      ctx.fillRect(left, top, 8, box);
      ctx.fillRect(left + box - 8, top, 8, box);
      if (marginPx > 0) {{
        ctx.strokeStyle = marginCm < 20 ? '#b42318' : '#ffd166';
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 6]);
        ctx.strokeRect(left + marginPx, top + marginPx, box - marginPx * 2, box - marginPx * 2);
        ctx.setLineDash([]);
      }}

      ctx.strokeStyle = 'rgba(217, 232, 242, 0.16)';
      ctx.lineWidth = 1;
      for (let cm = -halfCm; cm <= halfCm; cm += 50) {{
        const [gx] = toPx(cm, 0);
        const [, gy] = toPx(0, cm);
        ctx.beginPath(); ctx.moveTo(gx, top); ctx.lineTo(gx, top + box); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(left, gy); ctx.lineTo(left + box, gy); ctx.stroke();
      }}
      ctx.strokeStyle = 'rgba(82, 168, 255, 0.5)';
      ctx.beginPath(); ctx.moveTo(left, cy); ctx.lineTo(left + box, cy); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cx, top); ctx.lineTo(cx, top + box); ctx.stroke();

      const x = Number(dance.estimated_x_cm || 0);
      const y = Number(dance.estimated_y_cm || 0);
      const px = Number(dance.predicted_x_cm || x);
      const py = Number(dance.predicted_y_cm || y);
      const [rx, ry] = toPx(x, y);
      const [nx, ny] = toPx(px, py);

      const pathSafe = !dance.direction_safety || String(dance.direction_safety).includes('safe');
      ctx.strokeStyle = pathSafe ? '#39d98a' : '#b42318';
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.moveTo(rx, ry);
      ctx.lineTo(nx, ny);
      ctx.stroke();
      ctx.fillStyle = ctx.strokeStyle;
      ctx.beginPath();
      ctx.arc(nx, ny, 7, 0, Math.PI * 2);
      ctx.fill();

      const heading = ((Number(dance.heading_deg || 0) % 360) + 360) % 360;
      const rad = (90 - heading) * Math.PI / 180;
      ctx.save();
      ctx.translate(rx, ry);
      ctx.rotate(-heading * Math.PI / 180);
      ctx.fillStyle = '#e8f2f8';
      ctx.strokeStyle = '#52a8ff';
      ctx.lineWidth = 2;
      ctx.beginPath();
      roundedRect(ctx, -13, -18, 26, 36, 7);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#52a8ff';
      ctx.beginPath();
      ctx.moveTo(0, -30);
      ctx.lineTo(-9, -13);
      ctx.lineTo(9, -13);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(rx, ry);
      ctx.lineTo(rx + Math.cos(rad) * 18, ry - Math.sin(rad) * 18);
      ctx.stroke();

      ctx.fillStyle = '#d9e8f2';
      ctx.font = '12px ui-monospace, Consolas, monospace';
      ctx.fillText(`pose x ${{x.toFixed(0)}} y ${{y.toFixed(0)}} heading ${{heading.toFixed(0)}}deg`, 16, h - 30);
      ctx.fillStyle = marginCm != null && marginCm < 20 ? '#ff8d87' : '#a7f3c4';
      ctx.fillText(`margin ${{marginCm == null ? 'unknown' : marginCm.toFixed(0) + 'cm'}} / prediction ${{pathSafe ? 'safe' : 'blocked'}} / ${{dance.reason || 'not evaluated'}}`, 16, h - 12);
    }}
    function formatUptime(startedAt) {{
      const seconds = Math.max(0, Math.floor(Date.now() / 1000 - Number(startedAt || Date.now() / 1000)));
      const h = Math.floor(seconds / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      const s = seconds % 60;
      return h > 0
        ? `${{String(h).padStart(2, '0')}}:${{String(m).padStart(2, '0')}}:${{String(s).padStart(2, '0')}}`
        : `${{String(m).padStart(2, '0')}}:${{String(s).padStart(2, '0')}}`;
    }}
    function setMissionClass(id, level) {{
      const node = document.getElementById(id);
      node.classList.remove('mission-good', 'mission-warn', 'mission-bad');
      node.classList.add(`mission-${{level}}`);
    }}
    function render(data) {{
      const stm = data.stm32_runtime || {{}};
      const hardwareRows = Object.values(data.hardware || {{}});
      window.lastPlutoHardware = data.hardware || {{}};
      const connectedHardware = hardwareRows.filter(item => item.connected).length;
      const requiredMissing = hardwareRows.filter(item => item.required && !item.connected);
      const returnLocked = data.mode_manager && data.mode_manager.return_lock;
      const stateLevel = data.current_state === 'ERROR' ? 'bad' : (data.current_state === 'BOOTSTRAP' ? 'warn' : 'good');
      const safetyLevel = data.current_state === 'ERROR' || requiredMissing.length ? 'bad' : (returnLocked ? 'warn' : 'good');
      const hardwareLevel = requiredMissing.length ? 'bad' : (connectedHardware === hardwareRows.length ? 'good' : 'warn');
      const heartbeatLevel = stm.running ? 'good' : 'warn';
      setMissionClass('missionStateCard', stateLevel);
      setMissionClass('missionSafetyCard', safetyLevel);
      setMissionClass('missionHardwareCard', hardwareLevel);
      setMissionClass('missionTimeCard', heartbeatLevel);
      document.getElementById('missionState').textContent = data.current_state || 'UNKNOWN';
      document.getElementById('missionSubstate').textContent = data.current_substate || 'no substate';
      document.getElementById('missionSafety').textContent = data.current_state === 'ERROR'
        ? 'FAULT'
        : (returnLocked ? 'RETURN LOCK' : (requiredMissing.length ? 'SAFE HOLD' : 'GO'));
      document.getElementById('missionFault').textContent = data.fault_reason || (requiredMissing.length ? `${{requiredMissing.map(item => item.name).join(', ')}} missing` : 'fault none');
      document.getElementById('missionHardware').textContent = `${{connectedHardware}}/${{hardwareRows.length}}`;
      document.getElementById('missionHeartbeat').textContent = stm.running
        ? `${{stm.ack_ping_count || 0}} ACK / ${{stm.ping_count || 0}} PING / ${{stm.last_ping_latency_ms == null ? 'no latency' : stm.last_ping_latency_ms.toFixed(1) + ' ms'}}`
        : 'STM32 heartbeat offline';
      document.getElementById('missionUptime').textContent = formatUptime(data.started_at);
      document.getElementById('missionUpdated').textContent = `updated ${{new Date().toLocaleTimeString()}} / commit ${{data.git_commit || 'unknown'}}`;
      document.getElementById('state').textContent = data.current_state;
      document.getElementById('substate').textContent = data.current_substate || 'none';
      document.getElementById('fault').textContent = data.fault_reason || 'none';
      document.getElementById('recovery').textContent = (data.error && data.error.recovery_action) || 'none';
      document.getElementById('returnLock').textContent = data.mode_manager && data.mode_manager.return_lock ? 'true' : 'false';
      document.getElementById('commit').textContent = data.git_commit || 'unknown';
      renderHardwareRack(hardwareRows);
      const allowed = Object.fromEntries(data.allowed_next_states.map(item => [item.state, item]));
      renderModeFlow(data, allowed);
      document.querySelectorAll('.state').forEach(btn => {{
        const item = allowed[btn.dataset.state];
        btn.disabled = !item || !item.allowed;
        btn.title = item ? item.reason : 'unavailable';
        btn.classList.toggle('is-current', btn.dataset.state === data.current_state);
      }});
      document.getElementById('stateReasons').innerHTML = data.allowed_next_states.map(item => `
        <div class="metric">
          <span class="label">${{item.state}}</span>
          <span class="value ${{item.allowed ? 'status-good' : 'status-warn'}}">${{item.reason}}</span>
        </div>
      `).join('');
      document.getElementById('events').innerHTML = data.events.map(item => {{
        const t = new Date(item.timestamp * 1000).toLocaleTimeString();
        return `<div class="event ${{cleanClass(item.level)}}"><span>${{t}}</span><span>${{esc(item.level)}}</span><span>${{esc(item.message)}}</span></div>`;
      }}).join('');
      renderEventSummary(data.events || []);
      document.getElementById('report').textContent = JSON.stringify(data.bootstrap_report, null, 2);
      const obstacles = stm.obstacles || {{}};
      const telemetry = stm.telemetry || {{}};
      const imu = (stm.imu && Object.keys(stm.imu).length) ? stm.imu : (parseKvLine(stm.last_line || '', 'IMU:') || {{}});
      const orientation = stm.imu_orientation || {{}};
      const headingDeg = Number(telemetry.H || 0) * 180 / Math.PI;
      const hallBattery = Number(telemetry.BAT || 0);
      const hallSpeed = Number(telemetry.SPD || 0);
      const hallDistance = Number(telemetry.DIST || 0);
      const hallAlive = hallBattery > 1 || Math.abs(hallSpeed) > 0.01 || Math.abs(hallDistance) > 0.01;
      const heartbeatRatio = stm.ping_count ? ((stm.ack_ping_count || 0) / Math.max(1, stm.ping_count)) * 100 : 0;
      const pingMs = finiteNumber(stm.last_ping_latency_ms, null);
      setReadout(
        'stmHeartbeat',
        stm.running ? 'LIVE' : 'OFFLINE',
        stm.running ? `${{stm.ack_ping_count || 0}} ACK / ${{stm.ping_count || 0}} PING` : 'runtime link not open',
        stm.running ? 'ok' : 'bad',
        heartbeatRatio
      );
      setReadout(
        'stmPing',
        pingMs == null ? 'none' : `${{pingMs.toFixed(1)}}ms`,
        pingMs == null ? 'waiting for ACK:PING' : (pingMs <= 100 ? 'inside 100 ms target' : 'above 100 ms target'),
        pingMs == null ? 'warn' : (pingMs <= 100 ? 'ok' : (pingMs <= 250 ? 'warn' : 'bad')),
        pingMs == null ? 0 : 100 - Math.min(100, pingMs)
      );
      setReadout(
        'stmBattery',
        hallBattery > 0 ? `${{hallBattery.toFixed(1)}}V` : 'waiting',
        hallBattery > 0 ? (hallBattery < 34 ? 'critical threshold' : 'hoverboard telemetry') : 'TEL:BAT not received',
        hallBattery <= 0 ? 'warn' : (hallBattery < 34 ? 'bad' : (hallBattery < 36 ? 'warn' : 'ok')),
        hallBattery <= 0 ? 0 : pct(hallBattery, 34, 42)
      );
      setReadout(
        'stmMotion',
        `${{hallSpeed.toFixed(1)}}`,
        `speed / dist ${{hallDistance.toFixed(1)}}cm / heading ${{headingDeg.toFixed(0)}}deg`,
        Math.abs(hallSpeed) > 0.01 ? 'warn' : 'ok',
        Math.min(100, Math.abs(hallSpeed))
      );
      document.getElementById('stmTel').textContent =
        `X ${{Number(telemetry.X || 0).toFixed(1)}} cm / Y ${{Number(telemetry.Y || 0).toFixed(1)}} cm / H ${{headingDeg.toFixed(1)}} deg / DIST ${{hallDistance.toFixed(1)}} cm`;
      document.getElementById('stmObs').textContent =
        `FL ${{sensorState(obstacles.FL).label}} / F ${{sensorState(obstacles.F).label}} / FR ${{sensorState(obstacles.FR).label}}`;
      document.getElementById('stmImu').textContent = orientation.available && !orientation.calibrating
        ? `roll ${{Number(orientation.roll || 0).toFixed(1)}} / pitch ${{Number(orientation.pitch || 0).toFixed(1)}} / yaw ${{Number(orientation.yaw || 0).toFixed(1)}} / ${{orientation.filter || 'filter'}}`
        : (orientation.calibrating ? `calibrating ${{Math.round((orientation.calibration_progress || 0) * 100)}}%` : `raw AX ${{Number(imu.AX || 0).toFixed(0)}} / AY ${{Number(imu.AY || 0).toFixed(0)}} / AZ ${{Number(imu.AZ || 0).toFixed(0)}}`);
      document.getElementById('stmLine').textContent = stm.last_line || stm.error || 'none';
      const flState = setSensorCard('sensorFl', obstacles.FL);
      const fState = setSensorCard('sensorF', obstacles.F);
      const frState = setSensorCard('sensorFr', obstacles.FR);
      const liveCount = [flState, fState, frState].filter(item => item.alive).length;
      const liveRanges = [flState, fState, frState].filter(item => item.cm != null);
      const nearest = liveRanges.length ? liveRanges.reduce((best, item) => item.cm < best.cm ? item : best) : null;
      const corridorLevel = [flState, fState, frState].some(item => item.cls === 'bad')
        ? 'bad'
        : ([flState, fState, frState].some(item => item.cls === 'warn') ? 'warn' : 'ok');
      const manualRangeInfoOnly = data.current_state === 'MANUAL';
      const mpuAlive = Number(imu.OK || 0) === 1 && String(imu.WHO || '').toLowerCase() === '0x68';
      const imuFiltered = orientation.available && !orientation.calibrating;
      const sensorConfidence = Math.round((stm.running ? 20 : 0) + (liveCount / 3) * 45 + (mpuAlive ? 10 : 0) + (imuFiltered ? 20 : 0) + (hallAlive ? 5 : 0));
      const confidenceLevel = sensorConfidence >= 70 ? 'ok' : (sensorConfidence >= 40 ? 'warn' : 'bad');
      setReadout(
        'sensorNearest',
        nearest ? `${{nearest.cm.toFixed(0)}}cm` : 'no echo',
        nearest ? 'closest detected object in front arc' : 'no valid ultrasonic echo',
        nearest ? nearest.cls : 'warn',
        nearest ? nearest.pct : 0
      );
      setReadout(
        'sensorCorridor',
        corridorLevel === 'bad' ? 'STOP' : (corridorLevel === 'warn' ? 'SLOW' : 'CLEAR'),
        `FL ${{flState.label}} / F ${{fState.label}} / FR ${{frState.label}}`,
        corridorLevel,
        corridorLevel === 'bad' ? 25 : (corridorLevel === 'warn' ? 58 : 100)
      );
      setReadout(
        'sensorAttitude',
        orientation.available && !orientation.calibrating ? `${{Number(orientation.roll || 0).toFixed(0)}}/${{Number(orientation.pitch || 0).toFixed(0)}}/${{Number(orientation.yaw || 0).toFixed(0)}}` : (orientation.calibrating ? 'CAL' : 'RAW'),
        orientation.available && !orientation.calibrating ? 'roll / pitch / yaw degrees' : (orientation.calibrating ? 'keep robot still during calibration' : 'waiting for filtered IMU'),
        orientation.available && !orientation.calibrating ? 'ok' : 'warn',
        orientation.available && !orientation.calibrating ? 100 : Math.round((orientation.calibration_progress || 0) * 100)
      );
      setReadout(
        'sensorConfidence',
        `${{sensorConfidence}}%`,
        `STM32 ${{stm.running ? 'live' : 'offline'}} / range ${{liveCount}} of 3 / IMU ${{imuFiltered ? 'filtered' : (orientation.calibrating ? 'calibrating' : 'raw')}}`,
        confidenceLevel,
        sensorConfidence
      );
      setFusion(
        'fusionRange',
        `${{liveCount}}/3 live`,
        nearest ? `nearest object ${{nearest.cm.toFixed(0)}} cm` : 'no valid ultrasonic echo',
        liveCount === 3 ? 'good' : (liveCount > 0 ? 'warn' : 'bad')
      );
      setFusion(
        'fusionImu',
        imuFiltered ? 'filtered' : (orientation.calibrating ? 'calibrating' : 'raw'),
        imuFiltered ? `${{orientation.filter || 'Madgwick'}} roll/pitch/yaw ready` : (mpuAlive ? 'MPU alive, waiting for stable filter' : 'MPU not parsed yet'),
        imuFiltered ? 'good' : (mpuAlive ? 'warn' : 'bad')
      );
      setFusion(
        'fusionOdom',
        hallAlive ? 'live' : 'waiting',
        `speed ${{hallSpeed.toFixed(1)}} / distance ${{hallDistance.toFixed(1)}} cm / heading ${{headingDeg.toFixed(0)}} deg`,
        hallAlive ? 'good' : 'warn'
      );
      setFusion(
        'fusionDecision',
        manualRangeInfoOnly ? 'INFO' : (corridorLevel === 'bad' ? 'STOP' : (corridorLevel === 'warn' ? 'SLOW' : 'CLEAR')),
        `${{modeLabel(data.current_state)}} guard / confidence ${{sensorConfidence}}%${{manualRangeInfoOnly ? ' / range informational' : ''}}`,
        manualRangeInfoOnly ? 'good' : (corridorLevel === 'ok' ? 'good' : corridorLevel)
      );
      updateModeGuard(data, corridorLevel, nearest, liveCount, orientation, sensorConfidence);
      const cameraStatus = data.camera || {{}};
      const audioStatus = data.audio || {{}};
      const launchChecks = [
        {{
          label: 'Mode Manager',
          level: data.current_state === 'ERROR' ? 'bad' : (data.current_state === 'BOOTSTRAP' ? 'warn' : 'good'),
          detail: `${{data.current_state || 'UNKNOWN'}} / ${{data.current_substate || 'no substate'}}`,
        }},
        {{
          label: 'STM32 Safety Link',
          level: stm.running ? 'good' : 'bad',
          detail: stm.running ? `${{stm.ack_ping_count || 0}} ACK / latency ${{pingMs == null ? 'waiting' : pingMs.toFixed(1) + ' ms'}}` : 'motor safety controller offline',
        }},
        {{
          label: 'Required Hardware',
          level: requiredMissing.length ? 'bad' : 'good',
          detail: requiredMissing.length ? requiredMissing.map(item => item.name).join(', ') : 'all required devices available',
        }},
        {{
          label: 'Range Corridor',
          level: manualRangeInfoOnly ? 'good' : (corridorLevel === 'ok' ? 'good' : corridorLevel),
          detail: manualRangeInfoOnly
            ? (nearest ? `manual info only / ${{nearest.cm.toFixed(0)}} cm nearest / ${{liveCount}} of 3 live` : `manual info only / no valid echo / ${{liveCount}} of 3 live`)
            : (nearest ? `${{nearest.cm.toFixed(0)}} cm nearest / ${{liveCount}} of 3 live` : `no valid echo / ${{liveCount}} of 3 live`),
        }},
        {{
          label: 'IMU Attitude',
          level: imuFiltered ? 'good' : (mpuAlive ? 'warn' : 'warn'),
          detail: imuFiltered ? `${{orientation.filter || 'filter'}} roll/pitch/yaw ready` : (mpuAlive ? 'MPU alive, filter settling' : 'raw or not parsed yet'),
        }},
        {{
          label: 'Vision Stack',
          level: cameraStatus.running ? 'good' : 'warn',
          detail: cameraStatus.running ? `${{cameraStatus.backend || 'camera'}} / humans ${{cameraStatus.human_count || 0}}` : (cameraStatus.error || 'camera optional or unavailable'),
        }},
        {{
          label: 'Audio IO',
          level: audioStatus.microphone_available || audioStatus.speaker_available ? 'good' : 'warn',
          detail: `${{audioStatus.microphone_available ? 'mic ok' : 'no mic'}} / ${{audioStatus.speaker_available ? 'speaker ok' : 'no speaker'}}`,
        }},
      ];
      renderLaunchGate(launchChecks);
      document.getElementById('visualPose').textContent =
        `x ${{Number(telemetry.X || 0).toFixed(0)}} y ${{Number(telemetry.Y || 0).toFixed(0)}} h ${{headingDeg.toFixed(0)}}deg`;
      document.getElementById('visualEnvelope').textContent =
        `${{(data.dance && data.dance.envelope_size_cm) || 300}}cm / ${{corridorLevel === 'ok' ? 'clear' : corridorLevel}}`;
      document.getElementById('visualMode').textContent = modeLabel(data.current_state);
      if (window.Pluto3D && typeof window.Pluto3D.update === 'function') {{
        window.Pluto3D.update(data, {{
          corridorLevel: corridorLevel === 'ok' ? 'clear' : corridorLevel,
          sensorConfidence,
          nearestCm: nearest ? nearest.cm : null,
          liveCount,
        }});
      }}
      document.getElementById('sensorMapSubtitle').textContent =
        nearest ? `nearest ${{nearest.cm.toFixed(0)}} cm / corridor ${{corridorLevel.toUpperCase()}} / live ${{liveCount}} of 3` : `no range echo / live ${{liveCount}} of 3`;
      document.getElementById('sensorHealth').textContent =
        `ultrasonic echo ${{liveCount}}/3 / MPU ${{mpuAlive ? 'alive' : 'not ready'}} / STM32 ${{stm.running ? 'alive' : 'offline'}}`;
      document.getElementById('sensorMpu').textContent = mpuAlive
        ? `OK / addr ${{imu.ADDR || '0x68'}} / who ${{imu.WHO || '0x68'}} / temp ${{Number(imu.TEMP || 0).toFixed(1)}} C`
        : 'not parsed';
      document.getElementById('sensorAccel').textContent =
        `AX ${{Number(imu.AX || 0).toFixed(0)}} / AY ${{Number(imu.AY || 0).toFixed(0)}} / AZ ${{Number(imu.AZ || 0).toFixed(0)}}`;
      document.getElementById('sensorGyro').textContent =
        `GX ${{Number(imu.GX || 0).toFixed(0)}} / GY ${{Number(imu.GY || 0).toFixed(0)}} / GZ ${{Number(imu.GZ || 0).toFixed(0)}}`;
      document.getElementById('sensorHall').textContent =
        `${{hallAlive ? 'alive' : 'waiting'}} / UART via STM32 / speed ${{hallSpeed.toFixed(1)}} / battery ${{hallBattery.toFixed(1)}}`;
      document.getElementById('sensorHallOdom').textContent =
        `distance ${{hallDistance.toFixed(1)}} cm / home ${{Number(telemetry.HOME || 0).toFixed(1)}} cm / return ${{Number(telemetry.RET || 0).toFixed(0)}}`;
      document.getElementById('sensorPose').textContent =
        `X ${{Number(telemetry.X || 0).toFixed(1)}} cm / Y ${{Number(telemetry.Y || 0).toFixed(1)}} cm / H ${{headingDeg.toFixed(1)}} deg`;
      drawSensorStage(stm);
      const wave = data.wave || {{}};
      const waveEvent = wave.last_event || null;
      const waveDetector = wave.detector || {{}};
      document.getElementById('waveDetector').textContent = `${{wave.enabled ? 'enabled' : 'disabled'}} / ${{wave.detector_status || 'unknown'}}`;
      document.getElementById('waveReason').textContent = wave.last_reason || 'none';
      const armed = wave.armed_until && (Date.now() / 1000) < wave.armed_until;
      document.getElementById('waveCounts').textContent = `${{wave.trigger_count || 0}} accepted / ${{wave.rejected_count || 0}} rejected${{armed ? ' / ARMED' : ''}}`;
      const waveThresholds = wave.thresholds || {{}};
      document.getElementById('waveThresholds').textContent =
        `amp≥${{waveThresholds.hand_amp_min_shoulder_widths || 0}} shoulder / sc≥${{waveThresholds.direction_changes_min || 0}} / dxdy≥${{waveThresholds.horizontal_vertical_ratio_min || 0}} / kp≥${{waveThresholds.keypoint_confidence_min || 0}}`;
      document.getElementById('waveSampler').textContent =
        `${{(wave.sample_hz || 0).toFixed(1)}} Hz / last ${{wave.last_sample_at ? new Date(wave.last_sample_at * 1000).toLocaleTimeString() : 'none'}}`;
      document.getElementById('waveEvent').textContent = waveEvent
        ? `${{waveEvent.reason}} / ${{waveEvent.target_id || 'no target'}} / score ${{(waveEvent.score || 0).toFixed(2)}}`
        : `${{waveDetector.reason || 'none'}} / ${{waveDetector.target_id || 'no target'}} / raised ${{waveDetector.raised ? 'yes' : 'no'}} / amp ${{(waveDetector.hand_amp || 0).toFixed(2)}} / sc ${{waveDetector.hand_sign_changes || 0}} / dxdy ${{(waveDetector.hand_dx_dy || 0).toFixed(1)}}`;
      const approach = data.welcome_approach || {{}};
      const stopGuard = approach.stop_guard || {{}};
      const center = approach.target_center_norm == null ? 'unknown' : approach.target_center_norm.toFixed(2);
      const height = approach.target_box_height_ratio == null ? 'unknown' : approach.target_box_height_ratio.toFixed(2);
      document.getElementById('approachMode').textContent =
        `${{approach.active ? 'active' : 'inactive'}} / ${{approach.dry_run ? 'dry-run' : 'live'}}`;
      document.getElementById('approachTarget').textContent =
        approach.target_id == null ? 'none' : `track ${{approach.target_id}} / center ${{center}}`;
      document.getElementById('approachDistance').textContent =
        `${{approach.target_distance_class || 'unknown'}} / h ${{height}}${{approach.target_box_clipped ? ' / clipped ' + (approach.target_edge_contact || []).join(',') : ''}}`;
      document.getElementById('approachSteering').textContent =
        `${{approach.steering_intent || 'unknown'}} / steer ${{approach.proposed_steer || 0}}`;
      document.getElementById('approachObstacles').textContent = approach.obstacle_status || 'unknown';
      document.getElementById('approachProposal').textContent =
        `${{approach.proposed_motion || 'stop'}} / speed ${{approach.proposed_speed || 0}}`;
      document.getElementById('approachReason').textContent = approach.reason || 'not evaluated';
      document.getElementById('approachStop').textContent =
        stopGuard.detail ? `${{stopGuard.ok ? 'ok' : 'fail'}} / ${{stopGuard.detail}}` : 'none';
      const manual = data.manual || {{}};
      document.getElementById('manualEnabled').textContent = manual.enabled ? 'true' : 'false';
      document.getElementById('manualIntent').textContent = `${{manual.speed_intent || 0}}, ${{manual.steer_intent || 0}}`;
      document.getElementById('manualLimit').textContent = `${{manual.max_speed || 0}} speed / ${{manual.max_steer || 0}} steer`;
      document.getElementById('manualBlocked').textContent = manual.blocked_reason || 'none';
      const baseSpeed = document.getElementById('manualBaseSpeed');
      const baseSteer = document.getElementById('manualBaseSteer');
      baseSpeed.max = manual.max_speed || 400;
      baseSteer.max = manual.max_steer || 400;
      if (document.activeElement !== baseSpeed) baseSpeed.value = manual.base_speed_setting || 100;
      if (document.activeElement !== baseSteer) baseSteer.value = manual.base_steer_setting || 100;
      document.getElementById('manualBaseSpeedValue').textContent = baseSpeed.value;
      document.getElementById('manualBaseSteerValue').textContent = baseSteer.value;
      const armSteps = document.getElementById('manualArmSteps');
      const armSpeed = document.getElementById('manualArmSpeed');
      armSteps.max = manual.max_arm_steps || 10000;
      armSpeed.max = manual.max_arm_speed || 3000;
      if (document.activeElement !== armSteps) armSteps.value = manual.arm_step_setting || 5000;
      if (document.activeElement !== armSpeed) armSpeed.value = manual.arm_speed_setting || 2000;
      const lastArm = manual.last_arm_command || null;
      document.getElementById('manualArmLast').textContent = lastArm && lastArm.arm
        ? `arm${{lastArm.arm}} ${{lastArm.steps}} steps @ ${{lastArm.speed}}`
        : 'none';
      document.querySelectorAll('#manualPad button[data-motion]').forEach(btn => {{
        btn.disabled = !manual.enabled;
      }});
      document.getElementById('manualStop').disabled = !manual.enabled;
      document.querySelectorAll('[data-arm]').forEach(btn => {{
        btn.disabled = !manual.enabled;
      }});
      baseSpeed.disabled = !manual.enabled;
      baseSteer.disabled = !manual.enabled;
      armSteps.disabled = !manual.enabled;
      armSpeed.disabled = !manual.enabled;
      const dance = data.dance || {{}};
      const danceStop = dance.stop_guard || {{}};
      document.getElementById('danceMode').textContent =
        `${{dance.active ? 'active' : 'inactive'}} / ${{dance.dry_run ? 'dry-run' : 'live'}} / ${{(dance.elapsed_s || 0).toFixed(1)}}s`;
      document.getElementById('danceAudio').textContent =
        `${{dance.audio_status || 'unknown'}} / speaker ${{dance.speaker_available ? 'ok' : 'no'}} / file ${{dance.audio_file_present ? 'ok' : 'missing'}}`;
      const dancePlayback = (data.audio || {{}}).last_playback || {{}};
      document.getElementById('dancePlayback').textContent =
        dancePlayback.detail ? `${{dancePlayback.ok ? 'ok' : 'fail'}} / ${{dancePlayback.detail}}` : 'none';
      document.getElementById('danceStep').textContent = dance.dance_step || 'idle';
      document.getElementById('danceObstacles').textContent = dance.obstacle_status || 'unknown';
      document.getElementById('danceVision').textContent =
        `${{dance.vision_status || 'unknown'}} / ${{dance.vision_reason || 'not evaluated'}}`;
      document.getElementById('danceProposal').textContent =
        `${{dance.proposed_motion || 'stop'}} / speed ${{dance.proposed_speed || 0}} / steer ${{dance.proposed_steer || 0}}`;
      document.getElementById('danceEnvelope').textContent =
        `${{dance.envelope_size_cm || 0}}x${{dance.envelope_size_cm || 0}} cm / margin ${{dance.envelope_margin_cm == null ? 'unknown' : dance.envelope_margin_cm.toFixed(0) + ' cm'}}`;
      document.getElementById('danceOdom').textContent =
        `${{dance.odometry_status || 'unknown'}} / ${{dance.heading_quadrant || 'unknown'}} / x ${{(dance.estimated_x_cm || 0).toFixed(0)}} y ${{(dance.estimated_y_cm || 0).toFixed(0)}}`;
      document.getElementById('danceDirection').textContent =
        `${{dance.direction_safety || 'unknown'}} / predicted x ${{(dance.predicted_x_cm || 0).toFixed(0)}} y ${{(dance.predicted_y_cm || 0).toFixed(0)}}`;
      document.getElementById('danceReason').textContent = dance.reason || 'not evaluated';
      document.getElementById('danceStop').textContent =
        danceStop.detail ? `${{danceStop.ok ? 'ok' : 'fail'}} / ${{danceStop.detail}}` : 'none';
      document.getElementById('danceMapSubtitle').textContent =
        `${{dance.envelope_size_cm || 0}} cm envelope / margin ${{dance.envelope_margin_cm == null ? 'unknown' : dance.envelope_margin_cm.toFixed(0) + ' cm'}} / ${{dance.direction_safety || 'direction unknown'}}`;
      drawDanceStage(dance);
      const talk = data.talk || {{}};
      const lastTalk = talk.last_result || null;
      document.getElementById('talkVersion').textContent = `${{talk.version || 'v1'}} / ${{talk.primary_engine || 'keyword'}}`;
      document.getElementById('talkLimits').textContent = `${{talk.max_input_words || 9}} in / ${{talk.max_output_words || 9}} out`;
      document.getElementById('talkBank').textContent = `${{talk.intent_count || 0}} intents / ${{talk.script_count || 0}} scripts / ${{talk.alias_group_count || 0}} aliases`;
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
      document.getElementById('audioMicOverride').placeholder = audio.requested_microphone || 'Mic override, e.g. headset or plughw:CARD=...';
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
      document.getElementById('cameraPose').textContent =
        `${{camera.pose_status || 'unknown'}} / ${{(camera.pose_inference_ms || 0).toFixed(1)}} ms`;
      renderValidationCatalog(validationCatalog, data.hardware || {{}});
    }}
    async function refresh() {{
      try {{ render(await api('/api/status')); }}
      catch (err) {{ console.error(err); }}
    }}
    document.getElementById('refresh').addEventListener('click', async () => {{
      await api('/api/refresh-hardware', {{method: 'POST'}});
      await refresh();
    }});
    document.getElementById('themeMode').addEventListener('change', event => {{
      applyTheme(event.target.value);
    }});
    document.getElementById('estop').addEventListener('click', async () => {{
      await api('/api/emergency-stop', {{method: 'POST'}});
      await refresh();
    }});
    document.getElementById('piShutdown').addEventListener('click', async () => {{
      const ok = window.confirm('Shut down the Raspberry Pi now? This will run: sudo shutdown -h now');
      if (!ok) return;
      await api('/api/shutdown', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{confirm: 'PLUTO SHUTDOWN'}})
      }});
      document.getElementById('fault').textContent = 'Pi shutdown requested';
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
    document.getElementById('waveTrigger').addEventListener('click', async () => {{
      await api('/api/welcome/wave-trigger', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{source: 'website_wave_test', arm: true}})
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
    let manualHoldMotion = null;
    function numericInput(id, fallback, minValue, maxValue) {{
      const node = document.getElementById(id);
      const raw = Number(node.value);
      const value = Number.isFinite(raw) ? raw : fallback;
      return Math.max(minValue, Math.min(maxValue, Math.round(value)));
    }}
    function updateManualLabels() {{
      document.getElementById('manualBaseSpeedValue').textContent = document.getElementById('manualBaseSpeed').value;
      document.getElementById('manualBaseSteerValue').textContent = document.getElementById('manualBaseSteer').value;
    }}
    function manualMotionIntent(motion) {{
      const speedMax = Number(document.getElementById('manualBaseSpeed').max || 400);
      const steerMax = Number(document.getElementById('manualBaseSteer').max || 400);
      const speed = numericInput('manualBaseSpeed', 100, 50, speedMax);
      const steer = numericInput('manualBaseSteer', 100, 50, steerMax);
      if (motion === 'forward') return {{speed, steer: 0}};
      if (motion === 'back') return {{speed: -speed, steer: 0}};
      if (motion === 'left') return {{speed: 0, steer: -steer}};
      if (motion === 'right') return {{speed: 0, steer}};
      return {{speed: 0, steer: 0}};
    }}
    async function manualDrive(speed, steer, refreshAfter = true) {{
      await api('/api/manual/drive', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{speed, steer}})
      }});
      if (refreshAfter) await refresh();
    }}
    async function manualArm(arm, direction) {{
      const maxSteps = Number(document.getElementById('manualArmSteps').max || 10000);
      const maxSpeed = Number(document.getElementById('manualArmSpeed').max || 3000);
      const steps = numericInput('manualArmSteps', 5000, 1, maxSteps) * direction;
      const speed = numericInput('manualArmSpeed', 2000, 2000, maxSpeed);
      await api('/api/manual/arm', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{arm, steps, speed}})
      }});
      await refresh();
    }}
    async function manualStop() {{
      if (manualTimer) {{
        clearInterval(manualTimer);
        manualTimer = null;
      }}
      manualHoldMotion = null;
      await api('/api/manual/stop', {{method: 'POST'}});
      await refresh();
    }}
    document.getElementById('manualBaseSpeed').addEventListener('input', updateManualLabels);
    document.getElementById('manualBaseSteer').addEventListener('input', updateManualLabels);
    document.querySelectorAll('#manualPad button[data-motion]').forEach(btn => {{
      const start = (event) => {{
        event.preventDefault();
        manualHoldMotion = btn.dataset.motion;
        if (manualTimer) clearInterval(manualTimer);
        const {{speed, steer}} = manualMotionIntent(manualHoldMotion);
        manualDrive(speed, steer, false).catch(console.error);
        manualTimer = setInterval(() => {{
          if (!manualHoldMotion) return;
          const intent = manualMotionIntent(manualHoldMotion);
          manualDrive(intent.speed, intent.steer, false).catch(console.error);
        }}, 75);
      }};
      btn.addEventListener('pointerdown', start);
      btn.addEventListener('pointerup', event => {{
        event.preventDefault();
        if (manualHoldMotion === btn.dataset.motion) manualStop().catch(console.error);
      }});
      btn.addEventListener('pointercancel', event => {{
        event.preventDefault();
        if (manualHoldMotion === btn.dataset.motion) manualStop().catch(console.error);
      }});
      btn.addEventListener('lostpointercapture', () => {{
        if (manualHoldMotion === btn.dataset.motion) manualStop().catch(console.error);
      }});
    }});
    document.querySelectorAll('[data-arm]').forEach(btn => {{
      btn.addEventListener('click', async () => {{
        await manualArm(Number(btn.dataset.arm), Number(btn.dataset.armDir));
      }});
    }});
    ['mouseup', 'mouseleave', 'touchend', 'touchcancel', 'pointerup', 'pointercancel'].forEach(name => {{
      document.addEventListener(name, () => {{
        if (manualTimer) manualStop().catch(console.error);
      }});
    }});
    document.getElementById('manualStop').addEventListener('click', async () => {{
      await manualStop();
    }});
    document.getElementById('danceStart').addEventListener('click', async () => {{
      await api('/api/request-state', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{state: 'DANCE'}})
      }});
      await refresh();
    }});
    document.getElementById('danceStopBtn').addEventListener('click', async () => {{
      await api('/api/request-state', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{state: 'IDLE'}})
      }});
      await refresh();
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
    document.getElementById('audioUseMic').addEventListener('click', async () => {{
      const input = document.getElementById('audioMicOverride');
      await api('/api/audio/select-microphone', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{device: input.value}})
      }});
      await refresh();
    }});
    document.getElementById('audioAutoMic').addEventListener('click', async () => {{
      await api('/api/audio/select-microphone', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{device: ''}})
      }});
      document.getElementById('audioMicOverride').value = '';
      await refresh();
    }});
    document.getElementById('audioRefresh').addEventListener('click', async () => {{
      await api('/api/audio/refresh', {{method: 'POST'}});
      await refresh();
    }});
    document.getElementById('talkInput').addEventListener('keydown', async (event) => {{
      if (event.key === 'Enter') {{
        event.preventDefault();
        document.getElementById('talkAsk').click();
      }}
    }});
    document.getElementById('validationCenter').addEventListener('click', async (event) => {{
      const button = event.target.closest('button[data-validation-id]');
      if (!button || button.disabled) return;
      await runValidationTest(button.dataset.validationId);
    }});
    loadValidationCatalog()
      .then(() => renderValidationCatalog(validationCatalog, window.lastPlutoHardware || {{}}))
      .catch(console.error);
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>"""


def face_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>PLUTO Face</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #05080b;
      --face: #e8fbff;
      --face-dim: #82d8ec;
      --accent: #32b5ff;
      --happy: #39d98a;
      --warn: #ffd166;
      --bad: #ff5f57;
      --mood: var(--accent);
      --mood-rgb: 50, 181, 255;
      --eye-tilt: 0deg;
      --left-brow: 0deg;
      --right-brow: 0deg;
    }
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; }
    body {
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      background:
        radial-gradient(circle at 50% 34%, rgba(50, 181, 255, 0.24), transparent 42%),
        linear-gradient(180deg, #071018 0%, var(--bg) 100%);
      color: var(--face);
      touch-action: manipulation;
      user-select: none;
    }
    .face-screen {
      width: 100vw;
      height: 100dvh;
      min-height: 100vh;
      display: grid;
      grid-template-rows: 1fr auto;
      padding: max(18px, env(safe-area-inset-top)) max(18px, env(safe-area-inset-right)) max(18px, env(safe-area-inset-bottom)) max(18px, env(safe-area-inset-left));
    }
    .face {
      position: relative;
      display: grid;
      place-items: center;
      min-height: 0;
    }
    .halo {
      position: absolute;
      width: min(78vw, 980px);
      aspect-ratio: 1 / 0.5;
      border-radius: 50%;
      background: radial-gradient(ellipse at center, rgba(var(--mood-rgb), 0.28), transparent 68%);
      filter: blur(18px);
      opacity: 0.78;
      transform: translateY(-8vh) scale(var(--halo-scale, 1));
      transition: background 220ms ease, transform 220ms ease, opacity 220ms ease;
      pointer-events: none;
    }
    .eyes {
      width: min(86vw, 1160px);
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: clamp(34px, 8vw, 120px);
      align-items: center;
      transform: translateY(-3vh);
    }
    .eye {
      height: clamp(142px, 29vh, 330px);
      border-radius: clamp(34px, 7vw, 82px);
      background: var(--face);
      box-shadow: 0 0 26px rgba(232, 251, 255, 0.95), 0 0 90px rgba(var(--mood-rgb), 0.45);
      transform: translateY(var(--look-y, 0)) rotate(var(--eye-tilt)) scaleY(var(--blink, 1));
      transition: transform 120ms ease, border-radius 180ms ease, background 180ms ease;
    }
    .eye::after {
      content: "";
      display: block;
      width: 18%;
      height: 18%;
      margin: -44% 0 0 14%;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.38);
    }
    .pupil {
      width: 34%;
      height: 46%;
      margin: 18% auto 0;
      border-radius: 999px;
      background: #061019;
      opacity: 0.82;
      transform: translateX(var(--look-x, 0));
      transition: transform 180ms ease;
    }
    .mouth {
      position: absolute;
      left: 50%;
      top: 67%;
      width: min(32vw, 390px);
      height: clamp(22px, 5vh, 62px);
      border: clamp(8px, 1.7vw, 18px) solid var(--face);
      border-top: 0;
      border-radius: 0 0 999px 999px;
      transform: translateX(-50%) scaleY(var(--talk, 1));
      filter: drop-shadow(0 0 20px rgba(232, 251, 255, 0.75));
      transition: width 200ms ease, height 160ms ease, border-color 180ms ease, transform 90ms ease;
    }
    .brows {
      position: absolute;
      top: 21%;
      left: 50%;
      width: min(78vw, 1040px);
      display: flex;
      justify-content: space-between;
      transform: translateX(-50%);
      pointer-events: none;
    }
    .brow {
      width: min(24vw, 300px);
      height: clamp(10px, 1.8vh, 20px);
      border-radius: 999px;
      background: rgba(var(--mood-rgb), 0.78);
      box-shadow: 0 0 22px rgba(var(--mood-rgb), 0.55);
      opacity: 0.7;
      transition: transform 180ms ease, opacity 180ms ease, background 180ms ease;
    }
    .brow-left { transform: rotate(var(--left-brow)); }
    .brow-right { transform: rotate(var(--right-brow)); }
    .cheeks {
      position: absolute;
      top: 58%;
      left: 50%;
      width: min(82vw, 1060px);
      display: flex;
      justify-content: space-between;
      transform: translateX(-50%);
      pointer-events: none;
    }
    .cheek {
      width: clamp(36px, 7vw, 82px);
      height: clamp(20px, 4vw, 46px);
      border-radius: 999px;
      background: rgba(57, 217, 138, 0.22);
      box-shadow: 0 0 28px rgba(57, 217, 138, 0.32);
      opacity: 0;
      transition: opacity 180ms ease;
    }
    .sparkles {
      position: absolute;
      inset: 9% 8% 20%;
      pointer-events: none;
      opacity: 0;
      transition: opacity 180ms ease;
    }
    .sparkles i {
      position: absolute;
      width: clamp(8px, 1.4vw, 18px);
      height: clamp(8px, 1.4vw, 18px);
      border-radius: 4px;
      background: var(--mood);
      box-shadow: 0 0 24px var(--mood);
      transform: rotate(45deg) scale(var(--spark-scale, 1));
      animation: floatSpark 1800ms ease-in-out infinite;
    }
    .sparkles i:nth-child(1) { left: 9%; top: 16%; animation-delay: 0ms; }
    .sparkles i:nth-child(2) { left: 84%; top: 12%; animation-delay: 320ms; }
    .sparkles i:nth-child(3) { left: 18%; top: 70%; animation-delay: 620ms; }
    .sparkles i:nth-child(4) { left: 76%; top: 66%; animation-delay: 920ms; }
    .face-caption {
      position: absolute;
      left: 50%;
      bottom: 8%;
      display: grid;
      gap: 4px;
      width: min(78vw, 760px);
      text-align: center;
      transform: translateX(-50%);
      pointer-events: none;
    }
    #faceMood {
      font-size: clamp(18px, 3.6vw, 42px);
      font-weight: 900;
      color: var(--face);
      text-shadow: 0 0 22px rgba(var(--mood-rgb), 0.64);
    }
    #faceHint {
      font-size: clamp(12px, 1.8vw, 18px);
      font-weight: 800;
      color: rgba(232, 251, 255, 0.7);
    }
    .status {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 10px 14px;
      border: 1px solid rgba(232, 251, 255, 0.18);
      border-radius: 8px;
      background: rgba(5, 8, 11, 0.58);
      color: rgba(232, 251, 255, 0.78);
      font: 700 clamp(12px, 1.7vw, 18px) ui-monospace, SFMono-Regular, Consolas, monospace;
    }
    .face-stop {
      min-height: 38px;
      border: 0;
      border-radius: 8px;
      padding: 8px 14px;
      background: var(--bad);
      color: white;
      font: inherit;
      font-weight: 900;
      box-shadow: 0 0 18px rgba(255, 95, 87, 0.45);
    }
    @keyframes floatSpark {
      0%, 100% { opacity: 0.25; transform: translateY(0) rotate(45deg) scale(0.78); }
      50% { opacity: 1; transform: translateY(-14px) rotate(45deg) scale(1.1); }
    }
    .state-bootstrap { --mood: var(--face-dim); --mood-rgb: 130, 216, 236; --halo-scale: 0.82; --left-brow: 0deg; --right-brow: 0deg; }
    .state-idle { --mood: var(--happy); --mood-rgb: 57, 217, 138; --left-brow: -5deg; --right-brow: 5deg; }
    .state-idle .cheek, .state-idle .sparkles, .state-welcome .cheek, .state-welcome .sparkles { opacity: 1; }
    .state-idle .mouth, .state-welcome .mouth { width: min(40vw, 480px); height: clamp(46px, 8vh, 92px); border-color: var(--happy); }
    .state-manual { --mood: #75d7ff; --mood-rgb: 117, 215, 255; --left-brow: 7deg; --right-brow: -7deg; --eye-tilt: 0deg; }
    .state-manual .mouth { width: min(24vw, 300px); height: clamp(12px, 2vh, 28px); border-color: #75d7ff; }
    .state-welcome { --mood: var(--happy); --mood-rgb: 57, 217, 138; --left-brow: -9deg; --right-brow: 9deg; }
    .state-return { --mood: var(--warn); --mood-rgb: 255, 209, 102; --left-brow: 10deg; --right-brow: -10deg; }
    .state-return .mouth { width: min(28vw, 340px); height: clamp(18px, 3vh, 40px); border-color: var(--warn); }
    .state-talk .mouth { width: min(26vw, 320px); height: clamp(54px, 9vh, 106px); border-radius: 999px; border-top: clamp(8px, 1.7vw, 18px) solid var(--face); }
    .state-talk { --mood: var(--accent); --mood-rgb: 50, 181, 255; --left-brow: -3deg; --right-brow: 3deg; }
    .state-dance { --mood: var(--happy); --mood-rgb: 57, 217, 138; --eye-tilt: -2deg; }
    .state-dance .sparkles, .state-dance .cheek { opacity: 1; }
    .state-dance .eye { background: var(--happy); box-shadow: 0 0 34px rgba(57, 217, 138, 0.9), 0 0 100px rgba(57, 217, 138, 0.38); }
    .state-game { --mood: #c7a6ff; --mood-rgb: 199, 166, 255; --left-brow: -12deg; --right-brow: 4deg; }
    .state-game .mouth { width: min(30vw, 360px); height: clamp(18px, 3vh, 42px); border-color: #c7a6ff; }
    .state-error { --mood: var(--bad); --mood-rgb: 255, 95, 87; --left-brow: 16deg; --right-brow: -16deg; }
    .state-error .eye { background: var(--bad); box-shadow: 0 0 34px rgba(255, 95, 87, 0.85), 0 0 100px rgba(255, 95, 87, 0.36); }
    .state-error .mouth { width: min(30vw, 360px); height: 0; border-color: var(--bad); border-top: clamp(8px, 1.7vw, 18px) solid var(--bad); border-radius: 999px; }
    .state-bootstrap .eye { border-radius: 999px; transform: translateY(4vh) scaleY(0.16); }
    .state-bootstrap .mouth { width: min(18vw, 220px); height: 0; border-top: clamp(8px, 1.7vw, 18px) solid var(--face-dim); border-color: var(--face-dim); }
    @media (orientation: portrait) {
      .eyes { width: 88vw; gap: 9vw; }
      .eye { height: clamp(112px, 20vh, 230px); }
      .mouth { top: 63%; }
    }
  </style>
</head>
<body>
  <main class="face-screen state-idle" id="screen">
    <section class="face" aria-label="PLUTO robot face">
      <div class="halo" aria-hidden="true"></div>
      <div class="sparkles" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      <div class="brows" aria-hidden="true">
        <div class="brow brow-left"></div>
        <div class="brow brow-right"></div>
      </div>
      <div class="eyes">
        <div class="eye"><div class="pupil"></div></div>
        <div class="eye"><div class="pupil"></div></div>
      </div>
      <div class="mouth"></div>
      <div class="cheeks"><div class="cheek"></div><div class="cheek"></div></div>
      <div class="face-caption">
        <span id="faceMood">Waking safely</span>
        <span id="faceHint">Waiting for Pluto status</span>
      </div>
    </section>
    <footer class="status">
      <span id="faceState">PLUTO BOOTING</span>
      <span id="faceImu">IMU waiting</span>
      <span id="faceClock">--:--</span>
      <button class="face-stop" id="faceStop">STOP</button>
    </footer>
  </main>
  <script>
    const screen = document.getElementById('screen');
    const stateText = document.getElementById('faceState');
    const imuText = document.getElementById('faceImu');
    const clockText = document.getElementById('faceClock');
    const moodText = document.getElementById('faceMood');
    const hintText = document.getElementById('faceHint');
    const stopButton = document.getElementById('faceStop');
    let blinkUntil = 0;
    let lastData = null;
    const moodProfiles = {
      bootstrap: ['Waking safely', 'Self-check first. Motion stays zero.'],
      idle: ['Ready and playful', 'Waiting, watching, and gently being Pluto.'],
      manual: ['Focused control', 'Operator is driving. Eyes stay attentive.'],
      welcome: ['Warm welcome', 'Looking for a person and a safe greeting.'],
      talk: ['Speaking', 'Short local answers, friendly face fallback.'],
      return: ['Careful return', 'Return lock is active. Other modes wait.'],
      dance: ['Dance energy', 'Joyful look, dry-run safe until cleared.'],
      error: ['Safe stop', 'Clear fault face. No playful motion here.'],
      game: ['Game later', 'Polite unavailable mode for v1.'],
      idleSafe: ['Ready, but safe', 'STM32 is offline, so motion stays blocked.'],
    };

    function moodFor(data) {
      const state = String(data.current_state || 'BOOTSTRAP').toUpperCase();
      const sub = String(data.current_substate || '').toUpperCase();
      if (state === 'ERROR') return 'error';
      if (state === 'GAME_LATER') return 'game';
      if (state === 'DANCE') return 'dance';
      if (state === 'MANUAL') return 'manual';
      if (state === 'WELCOME' && (sub.includes('RETURN') || data.mode_manager && data.mode_manager.return_lock)) return 'return';
      if (state === 'WELCOME' && sub.includes('TALK')) return 'talk';
      if (state === 'WELCOME') return 'welcome';
      if (state === 'IDLE') {
        const stm = data.stm32_runtime || {};
        return stm.running === false ? 'idleSafe' : 'idle';
      }
      if (state === 'BOOTSTRAP') return 'bootstrap';
      return 'idle';
    }
    window.plutoFaceMoodFor = moodFor;
    function setMood(mood) {
      const visualMood = mood === 'idleSafe' ? 'idle' : mood;
      screen.className = `face-screen state-${visualMood}`;
      const profile = moodProfiles[mood] || moodProfiles.idle;
      moodText.textContent = profile[0];
      hintText.textContent = profile[1];
    }
    function render(data) {
      lastData = data;
      const mood = moodFor(data);
      setMood(mood);
      const state = data.current_state || 'UNKNOWN';
      const substate = data.current_substate ? ` / ${data.current_substate}` : '';
      stateText.textContent = `PLUTO ${state}${substate}`;
      if (data.fault_reason && mood === 'error') hintText.textContent = data.fault_reason;
      const orient = data.stm32_runtime && data.stm32_runtime.imu_orientation;
      if (orient && orient.available && !orient.calibrating) {
        imuText.textContent = `roll ${Number(orient.roll || 0).toFixed(0)} pitch ${Number(orient.pitch || 0).toFixed(0)} yaw ${Number(orient.yaw || 0).toFixed(0)}`;
      } else if (orient && orient.calibrating) {
        imuText.textContent = `IMU calibrating ${Math.round((orient.calibration_progress || 0) * 100)}%`;
      } else {
        imuText.textContent = data.stm32_runtime && data.stm32_runtime.running ? 'IMU waiting' : 'STM32 offline';
      }
    }
    async function refresh() {
      try {
        const res = await fetch('/api/status', {cache: 'no-store'});
        render(await res.json());
      } catch (err) {
        stateText.textContent = 'PLUTO LINK LOST';
        imuText.textContent = 'retrying';
        setMood('error');
      }
    }
    function animate() {
      const now = performance.now();
      const mood = moodFor(lastData || {});
      const playful = mood === 'idle' || mood === 'welcome';
      if (now > blinkUntil && Math.random() < (playful ? 0.026 : 0.014)) blinkUntil = now + (playful ? 120 : 145);
      const blink = now < blinkUntil ? 0.08 : 1;
      const talk = mood === 'talk' ? 0.72 + Math.abs(Math.sin(now / 105)) * 0.95 : 1;
      const dance = mood === 'dance' ? Math.sin(now / 170) * 22 : 0;
      const idleLook = playful ? Math.sin(now / 850) * 18 + Math.sin(now / 2300) * 9 : Math.sin(now / 1800) * 8;
      const manualLook = mood === 'manual' ? Math.sin(now / 1400) * 4 : 0;
      const lookX = dance || idleLook + manualLook;
      const bob = mood === 'dance' ? Math.sin(now / 140) * 12 : (playful ? Math.sin(now / 1100) * 7 : Math.sin(now / 2400) * 4);
      const halo = mood === 'dance' ? 1.04 + Math.abs(Math.sin(now / 220)) * 0.08 : (playful ? 1.0 + Math.sin(now / 1800) * 0.04 : 1);
      const spark = mood === 'dance' ? 1.25 : (playful ? 1 : 0.8);
      screen.style.setProperty('--blink', blink);
      screen.style.setProperty('--talk', talk);
      screen.style.setProperty('--look-x', `${lookX}px`);
      screen.style.setProperty('--look-y', `${bob}px`);
      screen.style.setProperty('--halo-scale', halo);
      screen.style.setProperty('--spark-scale', spark);
      clockText.textContent = new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
      requestAnimationFrame(animate);
    }
    screen.addEventListener('click', () => {
      if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
    });
    stopButton.addEventListener('click', async (event) => {
      event.stopPropagation();
      stopButton.textContent = 'STOPPING';
      try {
        await fetch('/api/emergency-stop', {method: 'POST'});
        stopButton.textContent = 'STOP SENT';
      } catch (err) {
        stopButton.textContent = 'STOP ERROR';
      }
      setTimeout(() => { stopButton.textContent = 'STOP'; }, 1800);
      await refresh();
    });
    refresh();
    setInterval(refresh, 500);
    animate();
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

    def send_static(self, path: str) -> bool:
        name = path.removeprefix("/static/").replace("\\", "/")
        if not name or name.startswith("/") or ".." in name.split("/"):
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return True
        target = (STATIC_DIR / name).resolve()
        if not str(target).startswith(str(STATIC_DIR)) or not target.is_file():
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return True
        content_type = STATIC_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self.send_bytes(HTTPStatus.OK, target.read_bytes(), content_type)
        return True

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_bytes(HTTPStatus.OK, html_page().encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/face":
            self.send_bytes(HTTPStatus.OK, face_page().encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/favicon.ico":
            self.send_bytes(HTTPStatus.OK, b"", "image/x-icon")
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
        if path == "/api/validation/catalog":
            self.send_json(HTTPStatus.OK, self.context.validation_catalog())
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
        if path.startswith("/static/") and self.send_static(path):
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
            if path == "/api/welcome/wave-trigger":
                body = self.read_json()
                self.send_json(
                    HTTPStatus.OK,
                    self.context.welcome_wave_trigger(
                        source=str(body.get("source", "website_wave_test")),
                        diagnostic=bool(body.get("diagnostic", False)),
                        arm=bool(body.get("arm", False)),
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
            if path == "/api/manual/arm":
                body = self.read_json()
                self.send_json(
                    HTTPStatus.OK,
                    self.context.manual_arm(
                        int(body.get("arm", 1)),
                        int(body.get("steps", 0)),
                        int(body.get("speed", 0)),
                    ),
                )
                return
            if path == "/api/manual/stop":
                self.send_json(HTTPStatus.OK, self.context.manual_stop())
                return
            if path == "/api/audio/refresh":
                self.send_json(HTTPStatus.OK, self.context.refresh_audio())
                return
            if path == "/api/audio/select-microphone":
                body = self.read_json()
                self.send_json(HTTPStatus.OK, self.context.select_microphone(body.get("device")))
                return
            if path == "/api/audio/select-speaker":
                body = self.read_json()
                self.send_json(HTTPStatus.OK, self.context.select_speaker(body.get("device")))
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
            if path == "/api/validation/run":
                body = self.read_json()
                self.send_json(HTTPStatus.OK, self.context.run_validation_test(str(body.get("test_id", ""))))
                return
            if path == "/api/shutdown":
                body = self.read_json()
                self.send_json(HTTPStatus.OK, self.context.shutdown(body.get("confirm")))
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except KeyError as exc:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
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
    parser.add_argument("--camera-disabled", action="store_true", help="Do not open the camera device; website shows camera disabled.")
    parser.add_argument("--yolo-model", help="TFLite YOLO model path. Defaults to PLUTO_YOLO_MODEL or /home/pi/yolo/model/yolov8n-fp16.tflite.")
    parser.add_argument("--wave-pose-model", help="MoveNet TFLite pose model path. Defaults to PLUTO_POSE_MODEL or bundled model.")
    parser.add_argument("--wave-pose-disabled", action="store_true", help="Disable pose wave backend and expose wave as unavailable.")
    parser.add_argument("--wave-pose-frame-skip", type=int, default=1, help="Run pose estimation every Nth processed camera frame. Default: 1.")
    parser.add_argument("--wave-pose-max-tracks", type=int, default=2, help="Maximum tracked humans to run pose on. Default: 2.")
    parser.add_argument("--microphone-device", help="Preferred ALSA microphone id/name, for example headset or plughw:CARD=...,DEV=0.")
    parser.add_argument("--speaker-device", help="Preferred ALSA speaker id/name.")
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
        camera_disabled=args.camera_disabled,
        yolo_model=args.yolo_model,
        wave_pose_model=args.wave_pose_model,
        wave_pose_disabled=args.wave_pose_disabled,
        wave_pose_frame_skip=args.wave_pose_frame_skip,
        wave_pose_max_tracks=args.wave_pose_max_tracks,
        microphone_device=args.microphone_device,
        speaker_device=args.speaker_device,
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
        context.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
