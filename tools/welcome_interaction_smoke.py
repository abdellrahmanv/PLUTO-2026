#!/usr/bin/env python3
"""Smoke test for the no-motion WELCOME interaction FSM."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pluto_runtime.welcome_interaction import WelcomeInteractionConfig, WelcomeInteractionFSM
from pluto_runtime.welcome_talk import WelcomeTalkEngine


class FakeAudioRuntime:
    def __init__(self) -> None:
        self.min_rms = 0.03
        self.listen_calls = 0
        self.speak_calls = 0
        self.stop_calls = 0
        self.listening = False
        self.saw_listen_during_tts = False
        self.spoken_texts: list[str] = []
        self.last_recording = None
        self.last_transcript = None
        self.last_tts = None

    def status(self) -> dict:
        return {
            "microphone_available": True,
            "speaker_available": True,
            "selected_microphone": "fake-mic",
            "selected_speaker": "fake-speaker",
            "min_rms": self.min_rms,
            "last_recording": self.last_recording,
            "last_transcript": self.last_transcript,
            "last_tts": self.last_tts,
        }

    def stop_playback(self, reason: str = "stop requested") -> dict:
        self.stop_calls += 1
        return {"ok": True, "detail": reason}

    def listen(self, duration_s: float = 3.0) -> dict:
        self.listen_calls += 1
        self.listening = True
        time.sleep(0.02)
        self.listening = False
        self.last_recording = {
            "ok": True,
            "duration_s": duration_s,
            "signal": {"rms": 0.12, "peak": 0.4},
        }
        self.last_transcript = {
            "ok": True,
            "detail": "transcribed",
            "text": "what is your name",
            "signal": self.last_recording["signal"],
        }
        return {"ok": True, "recording": self.last_recording, "transcript": self.last_transcript}

    def speak(self, text: str) -> dict:
        self.speak_calls += 1
        self.spoken_texts.append(text)
        if self.listening:
            self.saw_listen_during_tts = True
        time.sleep(0.02)
        self.last_tts = {"ok": True, "detail": "spoken", "text": text}
        return self.last_tts


def wait_for(condition, detail, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError(detail())


def main() -> int:
    camera_calls = {"count": 0}
    logs: list[tuple[str, str]] = []

    def camera_status() -> dict:
        camera_calls["count"] += 1
        if camera_calls["count"] <= 5:
            return {
                "available": True,
                "running": True,
                "human_count": 1,
                "detections": [{"bbox": [70, 40, 220, 280], "confidence": 0.88, "class_name": "human", "track_id": 1}],
            }
        return {"available": True, "running": True, "human_count": 0, "detections": []}

    audio = FakeAudioRuntime()
    fsm = WelcomeInteractionFSM(
        camera_status=camera_status,
        audio_runtime=audio,
        talk_engine=WelcomeTalkEngine(),
        mode_state=lambda: "WELCOME",
        stop_guard=lambda: {"ok": True, "detail": "ACK:STOP"},
        log=lambda level, message: logs.append((level, message)),
        config=WelcomeInteractionConfig(
            post_tts_delay=0.05,
            cooldown_duration=0.05,
            max_recording_time=0.5,
            silence_duration=0.1,
            min_speech_duration=0.0,
            queue_flush_duration=0.0,
            scan_period=0.02,
        ),
    )
    fsm.start(trigger_source="smoke", operator_triggered=True, greet_on_human_detection=True)

    deadline = time.monotonic() + 5.0
    required = {
        "HUMAN_DETECTED",
        "ACTIVE_LISTENING",
        "WAITING_FOR_RESPONSE",
        "SPEAKING",
        "POST_TTS_BUFFER",
        "COOLDOWN",
    }
    seen: set[str] = set()
    while time.monotonic() < deadline:
        status = fsm.status()
        seen.add(status["current_welcome_state"])
        seen.update(item["current"] for item in status["transition_log"])
        if required.issubset(seen) and status["current_welcome_state"] == "SCANNING" and audio.speak_calls >= 2:
            break
        time.sleep(0.02)
    else:
        raise AssertionError(f"WELCOME interaction did not complete: seen={seen}, status={fsm.status()}")

    status = fsm.status()
    assert required.issubset(seen), seen
    assert audio.listen_calls == 1, audio.listen_calls
    assert audio.speak_calls == 2, audio.speak_calls
    assert audio.saw_listen_during_tts is False
    assert status["transcript"] == "what is your name", status
    assert status["response_text"] == "I am Pluto.", status
    assert status["tts_finished"] is True, status
    assert status["post_tts_active"] is False, status
    assert status["cooldown_active"] is False, status
    assert any("previous='SPEAKING'" in message and "current='POST_TTS_BUFFER'" in message for _, message in logs), logs
    fsm.stop("smoke complete")

    sequence = [
        False,
        False,
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        True,
        False,
    ]

    def edge_camera_status() -> dict:
        present = sequence.pop(0) if sequence else False
        detections = [{"bbox": [70, 40, 220, 280], "confidence": 0.88, "class_name": "human", "track_id": 1}] if present else []
        return {"available": True, "running": True, "human_count": len(detections), "detections": detections}

    edge_audio = FakeAudioRuntime()
    edge_fsm = WelcomeInteractionFSM(
        camera_status=edge_camera_status,
        audio_runtime=edge_audio,
        talk_engine=WelcomeTalkEngine(),
        mode_state=lambda: "WELCOME",
        stop_guard=lambda: {"ok": True, "detail": "ACK:STOP"},
        log=lambda level, message: logs.append((level, message)),
        config=WelcomeInteractionConfig(post_tts_delay=0.01, cooldown_duration=0.01, max_recording_time=0.5, queue_flush_duration=0.0, scan_period=0.02),
    )
    edge_fsm.start(trigger_source="edge_smoke", operator_triggered=True, greet_on_human_detection=True)
    intro = "Welcome. I am Pluto, a graduation project robot."
    wait_for(
        lambda: edge_audio.spoken_texts.count(intro) >= 2,
        lambda: f"human re-entry did not speak intro twice: {edge_fsm.status()} spoken={edge_audio.spoken_texts}",
    )
    edge_fsm.stop("edge smoke complete")

    auto_audio = FakeAudioRuntime()
    auto_fsm = WelcomeInteractionFSM(
        camera_status=lambda: {
            "available": True,
            "running": True,
            "human_count": 1,
            "detections": [{"bbox": [70, 40, 220, 280], "confidence": 0.88, "class_name": "human", "track_id": 1}],
        },
        audio_runtime=auto_audio,
        talk_engine=WelcomeTalkEngine(),
        mode_state=lambda: "WELCOME",
        stop_guard=lambda: {"ok": True, "detail": "ACK:STOP"},
        log=lambda level, message: logs.append((level, message)),
        config=WelcomeInteractionConfig(post_tts_delay=0.01, cooldown_duration=0.01, max_recording_time=0.5, queue_flush_duration=0.0, scan_period=0.02),
    )
    auto_fsm.start(trigger_source="camera_human", auto_return_to_idle=True, greet_on_human_detection=False)
    wait_for(lambda: auto_audio.listen_calls >= 1 and auto_audio.speak_calls >= 1, lambda: f"auto human did not listen/respond: {auto_fsm.status()} spoken={auto_audio.spoken_texts}")
    assert intro not in auto_audio.spoken_texts, auto_audio.spoken_texts
    assert "I am Pluto." in auto_audio.spoken_texts, auto_audio.spoken_texts
    auto_fsm.stop("auto smoke complete")

    flicker_sequence = [True, False, False, True, True]

    def flicker_camera_status() -> dict:
        present = flicker_sequence.pop(0) if flicker_sequence else True
        detections = [{"bbox": [70, 40, 220, 280], "confidence": 0.88, "class_name": "human", "track_id": 1}] if present else []
        return {"available": True, "running": True, "human_count": len(detections), "detections": detections}

    flicker_logs: list[tuple[str, str]] = []
    flicker_audio = FakeAudioRuntime()
    flicker_fsm = WelcomeInteractionFSM(
        camera_status=flicker_camera_status,
        audio_runtime=flicker_audio,
        talk_engine=WelcomeTalkEngine(),
        mode_state=lambda: "WELCOME",
        stop_guard=lambda: {"ok": True, "detail": "ACK:STOP"},
        log=lambda level, message: flicker_logs.append((level, message)),
        config=WelcomeInteractionConfig(
            post_tts_delay=0.01,
            cooldown_duration=0.01,
            max_recording_time=0.5,
            queue_flush_duration=0.0,
            scan_period=0.02,
            human_detection_grace_duration=1.0,
        ),
    )
    flicker_fsm.start(trigger_source="camera_human", operator_triggered=False, auto_return_to_idle=True, greet_on_human_detection=False)
    wait_for(
        lambda: flicker_audio.listen_calls >= 1,
        lambda: f"auto WELCOME flicker blocked first listen: {flicker_fsm.status()} logs={flicker_logs}",
    )
    assert any("auto human detection grace used" in message for _, message in flicker_logs), flicker_logs
    flicker_fsm.stop("flicker smoke complete")

    print("WELCOME_INTERACTION_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
