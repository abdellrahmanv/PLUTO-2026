"""Audio hardware and offline speech helpers for Pluto.

The implementation is intentionally dependency-light. It probes Linux ALSA
devices with system tools, uses faster-whisper only when available, and uses
Piper only when its local binary/model are present.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from array import array
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


CAPTURE_RE = re.compile(
    r"card\s+(?P<card>\d+):\s+(?P<card_id>[^\[]+)\[(?P<card_name>[^\]]+)\],\s+"
    r"device\s+(?P<device>\d+):\s+(?P<device_id>[^\[]+)\[(?P<device_name>[^\]]+)\]"
)


@dataclass
class AudioDevice:
    id: str
    name: str
    kind: str
    card: str | None = None
    device: str | None = None
    detail: str = ""
    preferred: bool = False


@dataclass
class AudioProbe:
    microphone_available: bool = False
    speaker_available: bool = False
    selected_microphone: str | None = None
    selected_speaker: str | None = None
    requested_microphone: str | None = None
    requested_speaker: str | None = None
    capture_devices: list[AudioDevice] = field(default_factory=list)
    playback_devices: list[AudioDevice] = field(default_factory=list)
    tools: dict[str, bool] = field(default_factory=dict)
    packages: dict[str, bool] = field(default_factory=dict)
    stt_backend: str = "unavailable"
    stt_detail: str = "not checked"
    tts_backend: str = "unavailable"
    tts_detail: str = "not checked"
    min_rms: float = 0.03
    last_recording: dict[str, Any] | None = None
    last_transcript: dict[str, Any] | None = None
    last_tts: dict[str, Any] | None = None
    last_playback: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AudioRuntime:
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        cache_dir: str | None = None,
        min_rms: float = 0.03,
        preferred_microphone: str | None = None,
        preferred_speaker: str | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.min_rms = min_rms
        self.preferred_microphone = preferred_microphone or os.environ.get("PLUTO_MIC_DEVICE")
        self.preferred_speaker = preferred_speaker or os.environ.get("PLUTO_SPEAKER_DEVICE")
        self.cache_dir = Path(cache_dir or Path(tempfile.gettempdir()) / "pluto_tts_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.probe_status = AudioProbe()
        self._whisper_model = None
        self._whisper_model_path: str | None = None
        self._play_lock = threading.RLock()
        self._play_procs: list[subprocess.Popen] = []
        self.probe()

    def ensure_max_volume(self) -> None:
        amixer = shutil.which("amixer")
        if not amixer:
            return
        for control in ("Master", "PCM", "Headphone", "Speaker"):
            try:
                subprocess.run(
                    [amixer, "-q", "sset", control, "100%", "unmute"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                    check=False,
                )
            except Exception:
                continue

    def probe(self) -> AudioProbe:
        self.ensure_max_volume()
        tools = {name: shutil.which(name) is not None for name in ("arecord", "aplay", "ffmpeg", "piper")}
        tools["piper_local"] = Path("/home/pi/pluto-v2/piper/piper").exists()

        capture = parse_alsa_devices(run_text(["arecord", "-l"]) if tools["arecord"] else "", "capture")
        playback = parse_alsa_devices(run_text(["aplay", "-l"]) if tools["aplay"] else "", "playback")
        selected_mic = select_capture_device(capture, self.preferred_microphone)
        selected_speaker = select_playback_device(playback, self.preferred_speaker)

        packages = {
            "faster_whisper": package_available("faster_whisper"),
            "numpy": package_available("numpy"),
        }
        whisper_path = discover_whisper_model()
        piper_binary, piper_model = discover_piper()

        status = AudioProbe(
            microphone_available=bool(selected_mic and tools["arecord"]),
            speaker_available=bool(selected_speaker and tools["aplay"]),
            selected_microphone=selected_mic.id if selected_mic else None,
            selected_speaker=selected_speaker.id if selected_speaker else None,
            requested_microphone=self.preferred_microphone,
            requested_speaker=self.preferred_speaker,
            capture_devices=capture,
            playback_devices=playback,
            tools=tools,
            packages=packages,
            stt_backend="faster-whisper" if packages["faster_whisper"] and whisper_path else "unavailable",
            stt_detail=whisper_path or "faster-whisper model not found",
            tts_backend="piper" if piper_binary and piper_model else "unavailable",
            tts_detail=f"{piper_binary} {piper_model}" if piper_binary and piper_model else "piper binary/model not found",
            min_rms=self.min_rms,
            last_recording=self.probe_status.last_recording,
            last_transcript=self.probe_status.last_transcript,
            last_tts=self.probe_status.last_tts,
            last_playback=self.probe_status.last_playback,
        )
        with self.lock:
            self.probe_status = status
        return status

    def status(self) -> dict[str, Any]:
        with self.lock:
            return self.probe_status.to_dict()

    def set_microphone(self, device: str | None) -> dict[str, Any]:
        clean = str(device or "").strip() or None
        self.preferred_microphone = clean
        return self.probe().to_dict()

    def set_speaker(self, device: str | None) -> dict[str, Any]:
        clean = str(device or "").strip() or None
        self.preferred_speaker = clean
        return self.probe().to_dict()

    def record(self, duration_s: float = 3.0) -> dict[str, Any]:
        status = self.probe_status
        if not status.microphone_available or not status.selected_microphone:
            result = {"ok": False, "detail": "microphone unavailable", "path": None}
            self._set_recording(result)
            return result

        duration = max(0.5, min(float(duration_s), 8.0))
        arecord_seconds = max(1, int(round(duration)))
        path = Path(tempfile.gettempdir()) / f"pluto_listen_{int(time.time() * 1000)}.wav"
        cmd = [
            "arecord",
            "-q",
            "-D",
            status.selected_microphone,
            "-f",
            "S16_LE",
            "-r",
            str(self.sample_rate),
            "-c",
            str(self.channels),
            "-d",
            str(arecord_seconds),
            str(path),
        ]
        started_at = timestamp_now()
        started = time.monotonic()
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=duration + 6)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            ended_at = timestamp_now()
            ok = proc.returncode == 0 and path.exists() and path.stat().st_size > 44
            signal = wav_signal_stats(path) if ok else {}
            result = {
                "ok": ok,
                "detail": "recorded" if ok else (proc.stderr.strip() or "recording failed"),
                "path": str(path) if path.exists() else None,
                "duration_s": duration,
                "elapsed_ms": elapsed_ms,
                "bytes": path.stat().st_size if path.exists() else 0,
                "device": status.selected_microphone,
                "signal": signal,
                "started_at": started_at,
                "ended_at": ended_at,
            }
        except Exception as exc:
            result = {
                "ok": False,
                "detail": str(exc),
                "path": None,
                "duration_s": duration,
                "device": status.selected_microphone,
                "started_at": started_at,
                "ended_at": timestamp_now(),
                "elapsed_ms": (time.monotonic() - started) * 1000.0,
            }
        self._set_recording(result)
        return result

    def transcribe(self, wav_path: str | None) -> dict[str, Any]:
        started_at = timestamp_now()
        started_total = time.monotonic()
        if not wav_path:
            result = {
                "ok": False,
                "detail": "no recording path",
                "text": "",
                "started_at": started_at,
                "ended_at": timestamp_now(),
                "elapsed_ms": (time.monotonic() - started_total) * 1000.0,
            }
            self._set_transcript(result)
            return result

        model_path = discover_whisper_model()
        if not model_path:
            result = {
                "ok": False,
                "detail": "faster-whisper model not found",
                "text": "",
                "started_at": started_at,
                "ended_at": timestamp_now(),
                "elapsed_ms": (time.monotonic() - started_total) * 1000.0,
            }
            self._set_transcript(result)
            return result

        try:
            signal = wav_signal_stats(Path(wav_path))
            if signal and signal.get("rms", 0.0) < self.min_rms:
                result = {
                    "ok": True,
                    "detail": "silence skipped",
                    "text": "",
                    "elapsed_ms": 0.0,
                    "signal": signal,
                    "min_rms": self.min_rms,
                    "confidence": None,
                    "started_at": started_at,
                    "ended_at": timestamp_now(),
                }
                self._set_transcript(result)
                return result

            from faster_whisper import WhisperModel  # type: ignore

            started = time.monotonic()
            if self._whisper_model is None or self._whisper_model_path != model_path:
                self._whisper_model = WhisperModel(model_path, device="cpu", compute_type="int8", local_files_only=True)
                self._whisper_model_path = model_path
            load_ms = (time.monotonic() - started) * 1000.0
            started_transcribe = time.monotonic()
            segments, info = self._whisper_model.transcribe(
                wav_path,
                language="en",
                beam_size=1,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            segment_list = list(segments)
            text = " ".join(segment.text.strip() for segment in segment_list).strip()
            elapsed_ms = (time.monotonic() - started_transcribe) * 1000.0
            confidence = getattr(info, "language_probability", None)
            result = {
                "ok": True,
                "detail": "transcribed",
                "text": text,
                "elapsed_ms": elapsed_ms,
                "model_load_ms": load_ms,
                "model": model_path,
                "duration_s": getattr(info, "duration", None),
                "confidence": confidence,
                "segment_count": len(segment_list),
                "started_at": started_at,
                "ended_at": timestamp_now(),
                "signal": signal,
            }
        except Exception as exc:
            result = {
                "ok": False,
                "detail": str(exc),
                "text": "",
                "model": model_path,
                "started_at": started_at,
                "ended_at": timestamp_now(),
                "elapsed_ms": (time.monotonic() - started_total) * 1000.0,
                "confidence": None,
            }
        self._set_transcript(result)
        return result

    def listen(self, duration_s: float = 3.0) -> dict[str, Any]:
        listen_started_at = timestamp_now()
        listen_started = time.monotonic()
        recording = self.record(duration_s)
        transcribe_started_at = timestamp_now()
        transcribe_started = time.monotonic()
        transcript = self.transcribe(recording.get("path")) if recording.get("ok") else {"ok": False, "detail": recording.get("detail"), "text": ""}
        transcribe_latency_ms = (time.monotonic() - transcribe_started) * 1000.0
        listen_latency_ms = (time.monotonic() - listen_started) * 1000.0
        return {
            "ok": bool(recording.get("ok")) and bool(transcript.get("ok")),
            "recording": recording,
            "transcript": transcript,
            "timing": {
                "listen_started_at": listen_started_at,
                "listen_ended_at": timestamp_now(),
                "listen_latency_ms": listen_latency_ms,
                "record_latency_ms": recording.get("elapsed_ms"),
                "record_started_at": recording.get("started_at"),
                "record_ended_at": recording.get("ended_at"),
                "transcribe_started_at": transcribe_started_at,
                "transcribe_ended_at": transcript.get("ended_at"),
                "transcribe_latency_ms": transcript.get("elapsed_ms", transcribe_latency_ms),
                "transcribe_wall_latency_ms": transcribe_latency_ms,
                "model_load_ms": transcript.get("model_load_ms"),
            },
        }

    def speak_async(self, text: str, playback_device: str | None = None) -> dict[str, Any]:
        clean_text = str(text or "").strip()
        if not clean_text:
            return {"ok": False, "detail": "empty text", "text": clean_text}
        piper_binary, piper_model = discover_piper()
        status = self.probe_status
        device = playback_device or status.selected_speaker
        if not piper_binary or not piper_model:
            result = {"ok": False, "detail": "piper unavailable", "text": clean_text}
            self._set_tts(result)
            return result
        if not device or not shutil.which("aplay"):
            result = {"ok": False, "detail": "speaker/aplay unavailable", "text": clean_text}
            self._set_tts(result)
            return result
        thread = threading.Thread(target=self.speak, args=(text, playback_device), daemon=True)
        thread.start()
        return {"ok": True, "detail": "speech started", "text": clean_text, "device": device}

    def speak(self, text: str, playback_device: str | None = None) -> dict[str, Any]:
        clean_text = str(text or "").strip()
        if not clean_text:
            result = {"ok": False, "detail": "empty text"}
            self._set_tts(result)
            return result

        total_started_at = timestamp_now()
        total_started = time.monotonic()
        self.ensure_max_volume()
        prepare_ended_at = timestamp_now()
        piper_binary, piper_model = discover_piper()
        status = self.probe_status
        device = playback_device or status.selected_speaker
        if not piper_binary or not piper_model:
            result = {"ok": False, "detail": "piper unavailable", "text": clean_text, "started_at": total_started_at, "ended_at": timestamp_now()}
            self._set_tts(result)
            return result
        if not device or not shutil.which("aplay"):
            result = {"ok": False, "detail": "speaker/aplay unavailable", "text": clean_text, "started_at": total_started_at, "ended_at": timestamp_now()}
            self._set_tts(result)
            return result

        wav_path = self.cache_dir / f"{hashlib.sha1(clean_text.encode('utf-8')).hexdigest()}.wav"
        started = time.monotonic()
        generated = False
        cache_hit = wav_path.exists()
        synthesis_started_at = None
        synthesis_ended_at = None
        play_started_at = None
        play_ended_at = None
        try:
            if not wav_path.exists():
                synthesis_started_at = timestamp_now()
                proc = subprocess.run(
                    [piper_binary, "--model", piper_model, "--output_file", str(wav_path)],
                    input=clean_text + "\n",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=25,
                )
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr.strip() or "piper failed")
                generated = True
                synthesis_ended_at = timestamp_now()
            gen_ms = (time.monotonic() - started) * 1000.0
            play_started_at = timestamp_now()
            play_started = time.monotonic()
            proc = subprocess.run(["aplay", "-q", "-D", device, str(wav_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
            play_ended_at = timestamp_now()
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or "aplay failed")
            result = {
                "ok": True,
                "detail": "spoken",
                "text": clean_text,
                "path": str(wav_path),
                "generated": generated,
                "generate_ms": gen_ms,
                "play_ms": (time.monotonic() - play_started) * 1000.0,
                "device": device,
                "started_at": total_started_at,
                "ended_at": timestamp_now(),
                "prepare_ended_at": prepare_ended_at,
                "synthesis_started_at": synthesis_started_at,
                "synthesis_ended_at": synthesis_ended_at,
                "playback_started_at": play_started_at,
                "playback_ended_at": play_ended_at,
                "total_latency_ms": (time.monotonic() - total_started) * 1000.0,
                "cache_hit": cache_hit,
            }
        except Exception as exc:
            result = {
                "ok": False,
                "detail": str(exc),
                "text": clean_text,
                "path": str(wav_path),
                "device": device,
                "started_at": total_started_at,
                "ended_at": timestamp_now(),
                "prepare_ended_at": prepare_ended_at,
                "synthesis_started_at": synthesis_started_at,
                "synthesis_ended_at": synthesis_ended_at,
                "playback_started_at": play_started_at,
                "playback_ended_at": play_ended_at,
                "total_latency_ms": (time.monotonic() - total_started) * 1000.0,
                "cache_hit": cache_hit,
            }
        self._set_tts(result)
        return result

    def play_file_async(self, path: str | None, playback_device: str | None = None) -> dict[str, Any]:
        file_path = Path(str(path or ""))
        if not file_path.exists():
            result = {"ok": False, "detail": "audio file missing", "path": str(file_path)}
            self._set_playback(result)
            return result

        self.ensure_max_volume()
        status = self.probe_status
        device = playback_device or status.selected_speaker
        if not device or not shutil.which("aplay"):
            result = {"ok": False, "detail": "speaker/aplay unavailable", "path": str(file_path)}
            self._set_playback(result)
            return result
        if not shutil.which("ffmpeg"):
            result = {"ok": False, "detail": "ffmpeg unavailable for audio file playback", "path": str(file_path), "device": device}
            self._set_playback(result)
            return result

        self.stop_playback(reason="restart playback")
        thread = threading.Thread(target=self._play_file, args=(file_path, device), daemon=True)
        thread.start()
        result = {"ok": True, "detail": "playback started", "path": str(file_path), "device": device}
        self._set_playback(result)
        return result

    def stop_playback(self, reason: str = "stop requested") -> dict[str, Any]:
        stopped = 0
        with self._play_lock:
            procs = list(self._play_procs)
            self._play_procs.clear()
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
                stopped += 1
        result = {"ok": True, "detail": reason, "stopped_processes": stopped}
        self._set_playback(result)
        return result

    def _play_file(self, path: Path, device: str) -> None:
        started = time.monotonic()
        ffmpeg = None
        aplay = None
        try:
            ffmpeg = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-f", "wav", "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            aplay = subprocess.Popen(
                ["aplay", "-q", "-D", device],
                stdin=ffmpeg.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if ffmpeg.stdout is not None:
                ffmpeg.stdout.close()
            with self._play_lock:
                self._play_procs = [proc for proc in (ffmpeg, aplay) if proc is not None]
            _, aplay_err = aplay.communicate()
            _, ffmpeg_err = ffmpeg.communicate(timeout=1)
            ok = aplay.returncode == 0 and ffmpeg.returncode == 0
            detail = "playback finished" if ok else (aplay_err or ffmpeg_err or b"playback failed").decode("utf-8", errors="replace").strip()
            result = {
                "ok": ok,
                "detail": detail,
                "path": str(path),
                "device": device,
                "elapsed_ms": (time.monotonic() - started) * 1000.0,
            }
        except Exception as exc:
            result = {"ok": False, "detail": str(exc), "path": str(path), "device": device}
        finally:
            for proc in (aplay, ffmpeg):
                if proc is not None and proc.poll() is None:
                    proc.terminate()
            with self._play_lock:
                self._play_procs = []
        self._set_playback(result)

    def _set_recording(self, result: dict[str, Any]) -> None:
        with self.lock:
            self.probe_status.last_recording = result

    def _set_transcript(self, result: dict[str, Any]) -> None:
        with self.lock:
            self.probe_status.last_transcript = result

    def _set_tts(self, result: dict[str, Any]) -> None:
        with self.lock:
            self.probe_status.last_tts = result

    def _set_playback(self, result: dict[str, Any]) -> None:
        with self.lock:
            self.probe_status.last_playback = result


def run_text(command: list[str], timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return proc.stdout
    except Exception:
        return ""


def timestamp_now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def parse_alsa_devices(output: str, kind: str) -> list[AudioDevice]:
    devices: list[AudioDevice] = []
    for line in output.splitlines():
        match = CAPTURE_RE.search(line.strip())
        if not match:
            continue
        card_id = match.group("card_id").strip()
        card_name = match.group("card_name").strip()
        device = match.group("device").strip()
        device_name = match.group("device_name").strip()
        alsa_id = f"plughw:CARD={card_id},DEV={device}"
        name = f"{card_name} / {device_name}"
        devices.append(
            AudioDevice(
                id=alsa_id,
                name=name,
                kind=kind,
                card=match.group("card").strip(),
                device=device,
                detail=line.strip(),
                preferred=is_preferred_audio(name, kind),
            )
        )
    return devices


def is_preferred_audio(name: str, kind: str) -> bool:
    text = name.lower()
    if kind == "capture":
        return any(token in text for token in ("headset", "headphone", "camera", "webcam", "usb", "mic", "microphone"))
    return any(token in text for token in ("speaker", "usb", "headset"))


def device_matches(device: AudioDevice, preferred: str | None) -> bool:
    if not preferred:
        return False
    needle = preferred.lower()
    return needle in device.id.lower() or needle in device.name.lower() or needle in device.detail.lower()


def select_capture_device(devices: list[AudioDevice], preferred: str | None = None) -> AudioDevice | None:
    for device in devices:
        if device_matches(device, preferred):
            device.preferred = True
            return device
    for device in devices:
        if any(token in device.name.lower() for token in ("headset", "headphone")):
            device.preferred = True
            return device
    for device in devices:
        if device.preferred:
            return device
    return devices[0] if devices else None


def select_playback_device(devices: list[AudioDevice], preferred: str | None = None) -> AudioDevice | None:
    for device in devices:
        if device_matches(device, preferred):
            device.preferred = True
            return device
    for device in devices:
        if device.preferred:
            return device
    return None


def package_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def wav_signal_stats(path: str | Path) -> dict[str, float | int]:
    try:
        with wave.open(str(path), "rb") as wav:
            frames = wav.readframes(wav.getnframes())
            sample_width = wav.getsampwidth()
            frame_count = wav.getnframes()
            channels = wav.getnchannels()
        if sample_width != 2 or not frames:
            return {"rms": 0.0, "peak": 0.0, "frames": frame_count, "channels": channels}
        samples = array("h")
        samples.frombytes(frames)
        if not samples:
            return {"rms": 0.0, "peak": 0.0, "frames": frame_count, "channels": channels}
        squares = sum(float(sample) * float(sample) for sample in samples)
        rms = math.sqrt(squares / len(samples)) / 32768.0
        peak = max(abs(sample) for sample in samples) / 32768.0
        return {"rms": round(rms, 6), "peak": round(peak, 6), "frames": frame_count, "channels": channels}
    except Exception:
        return {}


def discover_whisper_model() -> str | None:
    env = os.environ.get("PLUTO_WHISPER_MODEL")
    candidates = [
        env,
        "/home/pi/.cache/huggingface/hub/models--Systran--faster-whisper-tiny/snapshots/d90ca5fe260221311c53c58e660288d3deb8d356",
        "/home/pi/.cache/whisper/models--Systran--faster-whisper-tiny/snapshots/d90ca5fe260221311c53c58e660288d3deb8d356",
        "/home/pi/pluto-v2/models/whisper/models--Systran--faster-whisper-base/snapshots/ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
    ]
    for candidate in candidates:
        if candidate and Path(candidate, "model.bin").exists():
            return candidate
    return None


def discover_piper() -> tuple[str | None, str | None]:
    binary = os.environ.get("PLUTO_PIPER_BIN") or shutil.which("piper") or "/home/pi/pluto-v2/piper/piper"
    model = os.environ.get("PLUTO_PIPER_MODEL") or "/home/pi/pluto-v2/models/en_US-lessac-medium.onnx"
    if not binary or not Path(binary).exists():
        return None, model if Path(model).exists() else None
    if not model or not Path(model).exists():
        return binary, None
    return binary, model
