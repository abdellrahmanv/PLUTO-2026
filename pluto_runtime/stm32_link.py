"""Persistent STM32 serial link for Pluto IDLE/runtime phases.

Edited by: Antigravity (DeepMind AI Assistant)
Date: 2026-05-30
Phase 1: Added send_return, send_reset_home, send_arm methods and
ACK parsing for ACK:RETURN, ACK:RETURN_COMPLETE, ACK:RESET_HOME,
ACK:ARM, and ACK:ARM_DONE. No live motion behavior enabled.
"""

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
    drive_count: int = 0
    ack_drive_count: int = 0
    last_drive_command: str | None = None
    last_drive_sent: float | None = None
    # --- Phase 1: return / reset_home / arm tracking ---
    return_count: int = 0
    ack_return_count: int = 0
    return_active: bool = False
    return_complete: bool = False
    return_complete_at: float | None = None
    reset_home_count: int = 0
    ack_reset_home_count: int = 0
    arm_count: int = 0
    ack_arm_count: int = 0
    arm_done: bool = False
    arm_done_at: float | None = None
    ack_arm_done_count: int = 0
    last_arm_command: str | None = None
    # --- end Phase 1 fields ---
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

    def send_stop(self, wait_ack: bool = True, timeout_s: float = 0.45, retries: int = 3) -> dict[str, Any]:
        attempts = max(1, int(retries))
        last_detail = "not sent"
        for attempt in range(1, attempts + 1):
            with self._lock:
                before = self._status.ack_stop_count
            ok, detail = self.send_command("CMD:STOP")
            last_detail = detail
            if not ok or not wait_ack:
                return {"ok": ok, "detail": detail, "attempts": attempt}

            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                with self._lock:
                    if self._status.ack_stop_count > before:
                        return {"ok": True, "detail": "ACK:STOP", "attempts": attempt}
                time.sleep(0.01)
            last_detail = f"STOP sent but ACK:STOP not received within {int(timeout_s * 1000)} ms"
        return {"ok": False, "detail": last_detail, "attempts": attempts}

    def send_drive(self, speed: int, steer: int, wait_ack: bool = True, timeout_s: float = 0.2) -> dict[str, Any]:
        with self._lock:
            before = self._status.ack_drive_count
        command = f"CMD:DRIVE:{int(speed)},{int(steer)}"
        ok, detail = self.send_command(command)
        if not ok or not wait_ack:
            return {"ok": ok, "detail": detail, "command": command}

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._status.ack_drive_count > before:
                    return {"ok": True, "detail": "ACK:DRIVE", "command": command}
            time.sleep(0.01)
        return {"ok": False, "detail": "DRIVE sent but ACK:DRIVE not received within 200 ms", "command": command}

    # --- Phase 1: return / reset_home / arm commands ---

    def send_return(self, wait_ack: bool = True, timeout_s: float = 0.45) -> dict[str, Any]:
        """Send CMD:RETURN. STM32 begins odometry-guided return to home.

        The STM32 sends ACK:RETURN immediately, and later sends
        ACK:RETURN_COMPLETE when distanceToHome < HOME_THRESHOLD_CM.
        This method waits only for the immediate ACK:RETURN.
        Monitor return_complete via get_status() for completion.
        """
        with self._lock:
            before = self._status.ack_return_count
            self._status.return_complete = False
            self._status.return_complete_at = None
            self._status.return_active = True
        ok, detail = self.send_command("CMD:RETURN")
        if not ok or not wait_ack:
            return {"ok": ok, "detail": detail, "command": "CMD:RETURN"}

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._status.ack_return_count > before:
                    return {"ok": True, "detail": "ACK:RETURN", "command": "CMD:RETURN"}
            time.sleep(0.01)
        return {"ok": False, "detail": f"RETURN sent but ACK:RETURN not received within {int(timeout_s * 1000)} ms", "command": "CMD:RETURN"}

    def send_reset_home(self, wait_ack: bool = True, timeout_s: float = 0.45) -> dict[str, Any]:
        """Send CMD:RESET_HOME. STM32 saves current pose as home base.

        Must be called before WELCOME_APPROACH so the STM32 knows
        where to return to after the interaction.
        """
        with self._lock:
            before = self._status.ack_reset_home_count
        ok, detail = self.send_command("CMD:RESET_HOME")
        if not ok or not wait_ack:
            return {"ok": ok, "detail": detail, "command": "CMD:RESET_HOME"}

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._status.ack_reset_home_count > before:
                    return {"ok": True, "detail": "ACK:RESET_HOME", "command": "CMD:RESET_HOME"}
            time.sleep(0.01)
        return {"ok": False, "detail": f"RESET_HOME sent but ACK:RESET_HOME not received within {int(timeout_s * 1000)} ms", "command": "CMD:RESET_HOME"}

    def send_arm(self, steps: int, speed: int = 200, wait_ack: bool = True, timeout_s: float = 0.45) -> dict[str, Any]:
        """Send CMD:ARM:<steps>,<speed>. STM32 moves the NEMA stepper.

        [!] WARNING: This is a low-level primitive control command. It DOES NOT perform
        any bounds checking, collision detection, or physical limit protection.
        Improper steps/speed parameters can cause the stepper motor to override
        physical boundaries, resulting in mechanical strain, gear damage, or structural
        failure of the robot's arm mechanism. Callers MUST ensure that target parameters
        are validated, bounded, and safe before invoking.

        The STM32 sends ACK:ARM immediately on receipt, then sends
        ACK:ARM_DONE asynchronously when all steps are completed.
        This method waits only for the immediate ACK:ARM.
        Monitor arm_done via get_status() for completion.
        """
        with self._lock:
            before = self._status.ack_arm_count
            self._status.arm_done = False
            self._status.arm_done_at = None
        command = f"CMD:ARM:{int(steps)},{int(speed)}"
        ok, detail = self.send_command(command)
        if not ok or not wait_ack:
            return {"ok": ok, "detail": detail, "command": command}

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._status.ack_arm_count > before:
                    return {"ok": True, "detail": "ACK:ARM", "command": command}
            time.sleep(0.01)
        return {"ok": False, "detail": f"ARM sent but ACK:ARM not received within {int(timeout_s * 1000)} ms", "command": command}

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
                    self._status.return_active = False
                elif command.startswith("CMD:DRIVE:"):
                    self._status.drive_count += 1
                    self._status.last_drive_command = command
                    self._status.last_drive_sent = time.time()
                    self._status.return_active = False
                elif command == "CMD:RETURN":
                    self._status.return_count += 1
                elif command == "CMD:RESET_HOME":
                    self._status.reset_home_count += 1
                elif command.startswith("CMD:ARM:"):
                    self._status.arm_count += 1
                    self._status.last_arm_command = command
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
            elif line == "ACK:DRIVE":
                self._status.ack_drive_count += 1
            elif line == "ACK:RETURN":
                self._status.ack_return_count += 1
            elif line == "ACK:RETURN_COMPLETE":
                self._status.return_complete = True
                self._status.return_complete_at = now_wall
                self._status.return_active = False
            elif line == "ACK:RESET_HOME":
                self._status.ack_reset_home_count += 1
            elif line == "ACK:ARM":
                self._status.ack_arm_count += 1
            elif line == "ACK:ARM_DONE":
                self._status.arm_done = True
                self._status.arm_done_at = now_wall
                self._status.ack_arm_done_count += 1
            elif line.startswith("TEL:"):
                self._status.telemetry = parse_tel_line(line)
            elif line.startswith("OBS:"):
                self._status.obstacles = parse_obs_line(line)
            elif line.startswith("ALERT:"):
                self._status.alerts.insert(0, line)
                self._status.alerts = self._status.alerts[:20]


def status_to_dict(status: Stm32RuntimeStatus) -> dict[str, Any]:
    return asdict(status)
