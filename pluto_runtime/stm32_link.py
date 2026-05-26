"""Persistent STM32 serial link for Pluto IDLE/runtime phases."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any


def parse_key_values(line: str) -> dict[str, float | str]:
    out: dict[str, float | str] = {}
    for item in line.split(","):
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        try:
            out[key] = float(value)
        except ValueError:
            out[key] = value
    return out


def parse_tel_line(line: str) -> dict[str, float | str]:
    if not line.startswith("TEL:"):
        return {}
    return parse_key_values(line[4:])


def parse_obs_line(line: str) -> dict[str, float | str]:
    if not line.startswith("OBS:"):
        return {}
    return parse_key_values(line[4:])


@dataclass
class Stm32RuntimeStatus:
    available: bool = False
    running: bool = False
    port: str | None = None
    heartbeat_interval_s: float = 0.4
    connected_since: float | None = None
    last_seen: float | None = None
    last_line: str | None = None
    last_command: str | None = None
    last_ping_sent: float | None = None
    last_ping_ack: float | None = None
    last_ping_latency_ms: float | None = None
    ping_count: int = 0
    ack_ping_count: int = 0
    stop_count: int = 0
    ack_stop_count: int = 0
    line_count: int = 0
    telemetry: dict[str, float | str] = field(default_factory=dict)
    obstacles: dict[str, float | str] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)
    error: str | None = None


class Stm32SerialLink:
    """Keeps STM32 heartbeat alive and records telemetry without motion."""

    def __init__(self, port: str, baud: int = 115200, heartbeat_interval_s: float = 0.4) -> None:
        self.port = port
        self.baud = baud
        self.heartbeat_interval_s = heartbeat_interval_s
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial = None
        self._pending_ping_sent: float | None = None
        self._status = Stm32RuntimeStatus(port=port, heartbeat_interval_s=heartbeat_interval_s)

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="stm32-runtime-link", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            ser = self._serial
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def send_stop(self, wait_ack: bool = True, timeout_s: float = 0.2) -> dict[str, Any]:
        with self._lock:
            before = self._status.ack_stop_count
        ok, detail = self.send_command("CMD:STOP")
        if not ok or not wait_ack:
            return {"ok": ok, "detail": detail}

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._status.ack_stop_count > before:
                    return {"ok": True, "detail": "ACK:STOP"}
            time.sleep(0.01)
        return {"ok": False, "detail": "STOP sent but ACK:STOP not received within 200 ms"}

    def send_command(self, command: str) -> tuple[bool, str]:
        command = command.strip()
        if not command:
            return False, "empty command"
        with self._lock:
            ser = self._serial
            if ser is None:
                return False, "serial link is not open"
            try:
                ser.write((command + "\n").encode("ascii"))
                ser.flush()
                self._status.last_command = command
                if command == "CMD:PING":
                    self._status.ping_count += 1
                    self._status.last_ping_sent = time.time()
                    self._pending_ping_sent = time.monotonic()
                elif command == "CMD:STOP":
                    self._status.stop_count += 1
                return True, "sent"
            except Exception as exc:
                self._status.error = str(exc)
                self._status.available = False
                return False, str(exc)

    def get_status(self) -> Stm32RuntimeStatus:
        with self._lock:
            data = asdict(self._status)
        status = Stm32RuntimeStatus()
        for key, value in data.items():
            setattr(status, key, value)
        return status

    def _run(self) -> None:
        try:
            import serial  # type: ignore

            ser = serial.Serial(port=self.port, baudrate=self.baud, timeout=0.02, write_timeout=0.1)
            with self._lock:
                self._serial = ser
                now = time.time()
                self._status.available = True
                self._status.running = True
                self._status.connected_since = now
                self._status.last_seen = now
                self._status.error = None
            self.send_stop(wait_ack=False)
            next_ping = time.monotonic()

            while not self._stop_event.is_set():
                now_mono = time.monotonic()
                if now_mono >= next_ping:
                    self.send_command("CMD:PING")
                    next_ping = now_mono + self.heartbeat_interval_s

                try:
                    raw = ser.readline()
                except Exception as exc:
                    with self._lock:
                        self._status.error = str(exc)
                        self._status.available = False
                        self._status.running = False
                    break

                if raw:
                    line = raw.decode("utf-8", errors="replace").strip()
                    self._handle_line(line)
                else:
                    time.sleep(0.005)
        except Exception as exc:
            with self._lock:
                self._status.error = str(exc)
                self._status.available = False
                self._status.running = False
        finally:
            with self._lock:
                ser = self._serial
                self._serial = None
                self._status.running = False
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass

    def _handle_line(self, line: str) -> None:
        now_wall = time.time()
        now_mono = time.monotonic()
        with self._lock:
            self._status.last_line = line
            self._status.last_seen = now_wall
            self._status.line_count += 1
            self._status.available = True

            if line == "ACK:PING":
                self._status.ack_ping_count += 1
                self._status.last_ping_ack = now_wall
                if self._pending_ping_sent is not None:
                    self._status.last_ping_latency_ms = (now_mono - self._pending_ping_sent) * 1000.0
                    self._pending_ping_sent = None
            elif line == "ACK:STOP":
                self._status.ack_stop_count += 1
            elif line.startswith("TEL:"):
                self._status.telemetry = parse_tel_line(line)
            elif line.startswith("OBS:"):
                self._status.obstacles = parse_obs_line(line)
            elif line.startswith("ALERT:"):
                self._status.alerts.insert(0, line)
                self._status.alerts = self._status.alerts[:20]


def status_to_dict(status: Stm32RuntimeStatus) -> dict[str, Any]:
    return asdict(status)
