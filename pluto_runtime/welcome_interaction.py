"""Realtime WELCOME interaction FSM.

This layer coordinates the existing camera, audio, and rule-based welcome talk
tools. It intentionally does not own top-level mode transitions or physical
motion; those remain in ModeManager, WebShell, and STM32 safety code.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable


WELCOME_STATES = (
    "SCANNING",
    "HUMAN_DETECTED",
    "ACTIVE_LISTENING",
    "WAITING_FOR_RESPONSE",
    "SPEAKING",
    "POST_TTS_BUFFER",
    "COOLDOWN",
)


@dataclass
class WelcomeInteractionConfig:
    post_tts_delay: float = 1.0
    cooldown_duration: float = 2.0
    max_recording_time: float = 3.0
    silence_duration: float = 1.0
    min_speech_duration: float = 0.3
    queue_flush_duration: float = 0.15
    human_detection_grace_duration: float = 1.5
    speech_threshold: float = 0.03
    scan_period: float = 0.15
    intro_text: str = "Welcome. I am Pluto, a graduation project robot."

    def update(self, values: dict[str, Any]) -> None:
        ranges = {
            "post_tts_delay": (0.1, 5.0),
            "cooldown_duration": (0.2, 10.0),
            "max_recording_time": (0.5, 8.0),
            "silence_duration": (0.2, 5.0),
            "min_speech_duration": (0.0, 3.0),
            "queue_flush_duration": (0.0, 2.0),
            "human_detection_grace_duration": (0.0, 5.0),
            "speech_threshold": (0.0, 1.0),
            "scan_period": (0.05, 2.0),
        }
        for key, bounds in ranges.items():
            if key not in values:
                continue
            try:
                value = float(values[key])
            except (TypeError, ValueError):
                continue
            low, high = bounds
            setattr(self, key, max(low, min(high, value)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WelcomeInteractionStatus:
    enabled: bool = False
    current_welcome_state: str = "SCANNING"
    human_detected: bool = False
    speech_detected: bool = False
    transcript_received: bool = False
    response_text: str = ""
    tts_finished: bool = False
    cooldown_active: bool = False
    post_tts_active: bool = False
    interaction_timer: float = 0.0
    audio_queue: list[str] = field(default_factory=list)
    silence_duration: float = 0.0
    speech_threshold: float = 0.03
    post_tts_delay: float = 1.0
    cooldown_duration: float = 2.0
    max_recording_time: float = 3.0
    min_speech_duration: float = 0.3
    queue_flush_duration: float = 0.15
    human_detection_grace_duration: float = 1.5
    human_detection_confidence: float = 0.0
    human_count: int = 0
    bounding_box: list[int] | None = None
    last_human_seen_time: float | None = None
    transcript: str = ""
    last_reason: str = "not started"
    last_transition_at: float | None = None
    trigger_source: str = ""
    operator_triggered: bool = False
    auto_return_to_idle: bool = False
    greet_on_human_detection: bool = False
    initial_response_pending: bool = False
    transition_log: list[dict[str, Any]] = field(default_factory=list)
    audio_status: dict[str, Any] = field(default_factory=dict)
    stop_guard: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WelcomeInteractionFSM:
    """Owns one WELCOME conversation loop while top-level state is WELCOME."""

    def __init__(
        self,
        camera_status: Callable[[], dict[str, Any]],
        audio_runtime: Any,
        talk_engine: Any,
        mode_state: Callable[[], str],
        stop_guard: Callable[[], dict[str, Any]],
        log: Callable[[str, str], None],
        on_talk_result: Callable[[Any], None] | None = None,
        config: WelcomeInteractionConfig | None = None,
    ) -> None:
        self.camera_status = camera_status
        self.audio_runtime = audio_runtime
        self.talk_engine = talk_engine
        self.mode_state = mode_state
        self.stop_guard = stop_guard
        self.log = log
        self.on_talk_result = on_talk_result
        self.config = config or WelcomeInteractionConfig()
        self._status = WelcomeInteractionStatus()
        self._transition_log: deque[dict[str, Any]] = deque(maxlen=80)
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.RLock()
        self._operator_triggered = False
        self._trigger_source = ""
        self._auto_return_to_idle = False
        self._initial_response = ""
        self._greet_on_human_detection = False
        self._intro_text = self.config.intro_text
        self._interaction_started = 0.0
        self._human_detection_grace_until = 0.0

    def start(
        self,
        trigger_source: str = "operator",
        operator_triggered: bool = False,
        initial_response: str = "",
        auto_return_to_idle: bool = False,
        greet_on_human_detection: bool = False,
    ) -> None:
        with self._lock:
            self._operator_triggered = bool(operator_triggered)
            self._trigger_source = trigger_source
            self._initial_response = str(initial_response or "").strip()
            self._auto_return_to_idle = bool(auto_return_to_idle)
            self._greet_on_human_detection = bool(greet_on_human_detection)
            self._intro_text = self.config.intro_text
            self._running = True
            self._interaction_started = time.monotonic()
            self._human_detection_grace_until = 0.0
            transition = self._set_state_locked("SCANNING", "WELCOME interaction armed")
            self._sync_config_locked()
            self._status.enabled = True
            self._status.human_detected = False
            self._status.human_count = 0
            self._status.human_detection_confidence = 0.0
            self._status.bounding_box = None
            self._status.trigger_source = trigger_source
            self._status.operator_triggered = bool(operator_triggered)
            self._status.auto_return_to_idle = bool(auto_return_to_idle)
            self._status.greet_on_human_detection = bool(greet_on_human_detection)
            self._status.initial_response_pending = bool(self._initial_response)
        self._log_transition(transition)
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="pluto-welcome-interaction", daemon=True)
        self._thread.start()

    def stop(self, reason: str = "WELCOME inactive") -> None:
        with self._lock:
            self._running = False
            self._status.enabled = False
            self._status.cooldown_active = False
            self._status.post_tts_active = False
            self._status.initial_response_pending = False
            self._status.greet_on_human_detection = False
            self._status.last_reason = reason
        try:
            self.audio_runtime.stop_playback(reason="welcome interaction stop")
        except Exception:
            pass

    def configure(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.config.update(values)
            self._sync_config_locked()
            try:
                self.audio_runtime.min_rms = self.config.speech_threshold
            except Exception:
                pass
        self.log("info", "WELCOME interaction parameters updated")
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._sync_config_locked()
            self._status.transition_log = list(self._transition_log)
            return self._status.to_dict()

    def _run_loop(self) -> None:
        while True:
            with self._lock:
                running = self._running
            if not running:
                return
            if self.mode_state() != "WELCOME":
                self.stop("top-level mode left WELCOME")
                return
            state = self.status()["current_welcome_state"]
            try:
                if state == "SCANNING":
                    self._scan_once()
                elif state == "HUMAN_DETECTED":
                    self._initialize_interaction()
                elif state == "ACTIVE_LISTENING":
                    self._listen_once()
                elif state == "WAITING_FOR_RESPONSE":
                    self._generate_response()
                elif state == "SPEAKING":
                    self._speak_once()
                elif state == "POST_TTS_BUFFER":
                    self._post_tts_buffer()
                elif state == "COOLDOWN":
                    self._cooldown()
                else:
                    self._transition("SCANNING", "unknown WELCOME state")
            except Exception as exc:  # noqa: BLE001 - FSM must report and recover
                self._transition("COOLDOWN", f"WELCOME interaction error: {type(exc).__name__}: {exc}")
            time.sleep(max(0.02, self.config.scan_period))

    def _scan_once(self) -> None:
        camera = self.camera_status()
        perception = self._extract_perception(camera)
        with self._lock:
            was_human_detected = self._status.human_detected
            self._apply_perception_locked(perception)
            self._status.speech_detected = False
            self._status.transcript_received = False
            self._status.response_text = ""
            self._status.tts_finished = False
            self._status.cooldown_active = False
            self._status.post_tts_active = False
            self._status.audio_queue = []
            if perception["human_detected"] and not was_human_detected and self._greet_on_human_detection:
                self._initial_response = self._intro_text
                self._status.initial_response_pending = True
        if perception["human_detected"]:
            if not self._operator_triggered:
                self._human_detection_grace_until = time.monotonic() + self.config.human_detection_grace_duration
            reason = "human detected; intro pending" if not was_human_detected else "human still detected"
            self._transition("HUMAN_DETECTED", reason)

    def _initialize_interaction(self) -> None:
        stop = self.stop_guard()
        audio = self.audio_runtime.status()
        try:
            self.audio_runtime.stop_playback(reason="prepare WELCOME interaction")
        except Exception:
            pass
        if self.config.queue_flush_duration > 0:
            time.sleep(self.config.queue_flush_duration)
        with self._lock:
            self._status.stop_guard = stop
            self._status.audio_status = audio
            self._status.audio_queue = []
            self._status.interaction_timer = time.monotonic() - self._interaction_started
            initial_response = self._initial_response
            if initial_response:
                self._initial_response = ""
                self._status.initial_response_pending = False
                self._status.response_text = initial_response
                self._status.transcript = ""
                self._status.transcript_received = False
        if initial_response:
            self._transition("SPEAKING", "initial IDLE human greeting")
            return
        if not audio.get("microphone_available"):
            self._transition("COOLDOWN", "microphone unavailable")
            return
        self._transition("ACTIVE_LISTENING", "audio initialized")

    def _listen_once(self) -> None:
        perception = self._extract_perception(self.camera_status())
        with self._lock:
            self._apply_perception_locked(perception)
        if not perception["human_detected"] and not self._operator_triggered:
            if time.monotonic() > self._human_detection_grace_until:
                self._transition("SCANNING", "human no longer detected before listening")
                return
            self._log_trace(
                "auto human detection grace used",
                grace_until_monotonic=self._human_detection_grace_until,
                trigger_source=self._trigger_source,
            )
        with self._lock:
            self._status.audio_queue = ["microphone"]
            self._status.speech_detected = False
            self._status.transcript_received = False
            self._status.transcript = ""
            self._status.tts_finished = False
        try:
            self.audio_runtime.min_rms = self.config.speech_threshold
        except Exception:
            pass
        self._log_trace(
            "audio listen start",
            current_welcome_state=self.status().get("current_welcome_state"),
            max_recording_time_s=self.config.max_recording_time,
            selected_microphone=(self.audio_runtime.status() or {}).get("selected_microphone"),
        )
        listen = self.audio_runtime.listen(self.config.max_recording_time)
        listen_timing = listen.get("timing") or {}
        self._log_trace(
            "audio listen end",
            listen_started_at=listen_timing.get("listen_started_at"),
            listen_ended_at=listen_timing.get("listen_ended_at"),
            listen_latency_ms=listen_timing.get("listen_latency_ms"),
            record_started_at=listen_timing.get("record_started_at"),
            record_ended_at=listen_timing.get("record_ended_at"),
            record_latency_ms=listen_timing.get("record_latency_ms"),
            transcribe_started_at=listen_timing.get("transcribe_started_at"),
            transcribe_ended_at=listen_timing.get("transcribe_ended_at"),
            transcribe_latency_ms=listen_timing.get("transcribe_latency_ms"),
            transcribe_wall_latency_ms=listen_timing.get("transcribe_wall_latency_ms"),
            model_load_ms=listen_timing.get("model_load_ms"),
        )
        recording = listen.get("recording") or {}
        transcript = listen.get("transcript") or {}
        signal = recording.get("signal") or transcript.get("signal") or {}
        rms = float(signal.get("rms") or 0.0)
        text = str(transcript.get("text") or "").strip()
        self._log_trace(
            "transcript text received",
            transcript_text=text,
            transcript_word_count=len(text.split()) if text else 0,
            transcript_confidence=transcript.get("confidence"),
            transcript_segment_count=transcript.get("segment_count"),
            transcript_ok=bool(transcript.get("ok")),
            transcript_detail=transcript.get("detail", ""),
            audio_rms=rms,
            audio_peak=signal.get("peak"),
        )
        speech_detected = rms >= self.config.speech_threshold
        perception = self._extract_perception(self.camera_status())
        with self._lock:
            self._apply_perception_locked(perception)
            self._status.audio_status = self.audio_runtime.status()
            self._status.speech_detected = speech_detected
            self._status.transcript_received = bool(text)
            self._status.transcript = text
            self._status.silence_duration = 0.0 if speech_detected else self.config.silence_duration
            self._status.audio_queue = []
        if not text:
            if perception["human_detected"] or self._operator_triggered:
                self._transition("SCANNING", "silence timeout; return to detection")
            else:
                self._transition("SCANNING", "human no longer detected after listening")
            return
        self._transition("WAITING_FOR_RESPONSE", "transcript received")

    def _generate_response(self) -> None:
        text = self.status().get("transcript", "")
        self._log_trace("talk_engine.answer start", transcript_text=text, transcript_word_count=len(str(text).split()) if text else 0)
        result = self.talk_engine.answer(text)
        unknown_response = str(getattr(getattr(self.talk_engine, "config", None), "unknown_response", ""))
        fallback_used = getattr(result, "response_source", "") == "fallback" or str(getattr(result, "response", "")) == unknown_response
        ollama_enabled = bool(getattr(getattr(self.talk_engine, "config", None), "enable_ollama_fallback", False))
        self._log_trace(
            "talk_engine.answer end",
            intent=getattr(result, "intent", None),
            reason=getattr(result, "reason", ""),
            latency_ms=getattr(result, "latency_ms", None),
            response_text=getattr(result, "response", ""),
            response_word_count=getattr(result, "response_words", None),
            response_source=getattr(result, "response_source", ""),
            score=getattr(result, "score", None),
            fallback_unknown_response_used=fallback_used,
            ollama_llm_fallback_called=False,
            ollama_llm_fallback_enabled=ollama_enabled,
        )
        response = str(getattr(result, "response", "") or "").strip()
        with self._lock:
            self._status.response_text = response
            self._status.audio_status = self.audio_runtime.status()
        if self.on_talk_result is not None:
            callback_started = time.monotonic()
            self._log_trace("on_talk_result start", intent=getattr(result, "intent", None), reason=getattr(result, "reason", ""))
            self.on_talk_result(result)
            self._log_trace(
                "on_talk_result end",
                callback_latency_ms=(time.monotonic() - callback_started) * 1000.0,
                intent=getattr(result, "intent", None),
                reason=getattr(result, "reason", ""),
            )
        if not response or not getattr(result, "accepted", False):
            self._transition("COOLDOWN", getattr(result, "reason", "empty response"))
            return
        self._transition("SPEAKING", "response generated")

    def _speak_once(self) -> None:
        response = self.status().get("response_text", "")
        with self._lock:
            self._status.audio_queue = ["tts"]
            self._status.tts_finished = False
        self._log_trace("TTS preparation start", response_text=response, response_word_count=len(str(response).split()) if response else 0)
        result = self.audio_runtime.speak(response)
        self._log_trace(
            "TTS finished",
            tts_ok=bool(result.get("ok")),
            tts_detail=result.get("detail", ""),
            tts_generated=bool(result.get("generated")),
            tts_cache_hit=result.get("cache_hit"),
            tts_started_at=result.get("started_at"),
            tts_prepare_ended_at=result.get("prepare_ended_at"),
            tts_synthesis_started_at=result.get("synthesis_started_at"),
            tts_synthesis_ended_at=result.get("synthesis_ended_at"),
            tts_playback_started_at=result.get("playback_started_at"),
            tts_playback_ended_at=result.get("playback_ended_at"),
            tts_ended_at=result.get("ended_at"),
            tts_generate_ms=result.get("generate_ms"),
            tts_play_ms=result.get("play_ms"),
            total_tts_latency_ms=result.get("total_latency_ms"),
            selected_speaker=result.get("device"),
        )
        if result.get("playback_started_at"):
            self._log_trace("TTS playback start", playback_started_at=result.get("playback_started_at"))
        if result.get("playback_ended_at"):
            self._log_trace(
                "TTS playback end",
                playback_started_at=result.get("playback_started_at"),
                playback_ended_at=result.get("playback_ended_at"),
                playback_latency_ms=result.get("play_ms"),
            )
        with self._lock:
            self._status.audio_status = self.audio_runtime.status()
            self._status.audio_queue = []
            self._status.tts_finished = bool(result.get("ok"))
        if not result.get("ok"):
            self._transition("COOLDOWN", f"TTS failed: {result.get('detail', 'unknown')}")
            return
        self._transition("POST_TTS_BUFFER", "TTS finished")

    def _post_tts_buffer(self) -> None:
        with self._lock:
            self._status.post_tts_active = True
            self._status.audio_queue = []
        time.sleep(max(0.0, self.config.post_tts_delay))
        with self._lock:
            self._status.post_tts_active = False
        self._transition("COOLDOWN", "post-TTS buffer complete")

    def _cooldown(self) -> None:
        with self._lock:
            self._status.cooldown_active = True
            self._status.audio_queue = []
        time.sleep(max(0.0, self.config.cooldown_duration))
        with self._lock:
            self._status.cooldown_active = False
            self._operator_triggered = False
        self._transition("SCANNING", "cooldown complete")

    def _transition(self, next_state: str, reason: str) -> None:
        with self._lock:
            transition = self._set_state_locked(next_state, reason)
        self._log_transition(transition)

    def _set_state_locked(self, next_state: str, reason: str) -> dict[str, Any] | None:
        previous = self._status.current_welcome_state
        now = time.time()
        if next_state not in WELCOME_STATES:
            next_state = "SCANNING"
        self._status.current_welcome_state = next_state
        self._status.last_reason = reason
        self._status.last_transition_at = now
        self._status.interaction_timer = time.monotonic() - self._interaction_started if self._interaction_started else 0.0
        if previous != next_state:
            item = {
                "timestamp": now,
                "timestamp_iso": datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
                "previous": previous,
                "current": next_state,
                "reason": reason,
            }
            self._transition_log.appendleft(item)
            return item
        return None

    def _log_transition(self, transition: dict[str, Any] | None) -> None:
        if not transition:
            return
        self.log(
            "talk",
            f"WELCOME TRACE state transition / timestamp={transition.get('timestamp_iso')} / "
            f"previous={transition['previous']!r} / current={transition['current']!r} / reason={transition['reason']!r}",
        )

    def _log_trace(self, event: str, **fields: Any) -> None:
        timestamp = datetime.now().isoformat(timespec="milliseconds")
        parts = [f"WELCOME TRACE {event}", f"timestamp={timestamp}"]
        for key, value in fields.items():
            parts.append(f"{key}={value!r}")
        self.log("talk", " / ".join(parts))

    def _sync_config_locked(self) -> None:
        self._status.speech_threshold = self.config.speech_threshold
        self._status.post_tts_delay = self.config.post_tts_delay
        self._status.cooldown_duration = self.config.cooldown_duration
        self._status.max_recording_time = self.config.max_recording_time
        self._status.min_speech_duration = self.config.min_speech_duration
        self._status.queue_flush_duration = self.config.queue_flush_duration
        self._status.human_detection_grace_duration = self.config.human_detection_grace_duration

    def _apply_perception_locked(self, perception: dict[str, Any]) -> None:
        self._status.human_detected = perception["human_detected"]
        self._status.human_count = perception["human_count"]
        self._status.human_detection_confidence = perception["confidence"]
        self._status.bounding_box = perception["bbox"]
        if perception["human_detected"]:
            self._status.last_human_seen_time = time.time()

    @staticmethod
    def _extract_perception(camera: dict[str, Any]) -> dict[str, Any]:
        detections = [item for item in (camera.get("detections") or []) if isinstance(item, dict)]
        best = max(detections, key=lambda item: float(item.get("confidence") or 0.0), default={})
        human_count = int(camera.get("human_count") or len(detections))
        return {
            "human_detected": human_count > 0,
            "human_count": human_count,
            "confidence": float(best.get("confidence") or 0.0),
            "bbox": list(best.get("bbox")) if best.get("bbox") else None,
        }
