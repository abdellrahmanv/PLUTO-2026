"""Persistent STM32 serial link for Pluto IDLE/runtime phases.

Edited by: Antigravity (DeepMind AI Assistant)
Date: 2026-05-30
Phase 1: Added send_return, send_reset_home, send_arm methods and
ACK parsing for ACK:RETURN, ACK:RETURN_COMPLETE, ACK:RESET_HOME,
ACK:ARM, and ACK:ARM_DONE. No live motion behavior enabled.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any


ACCEL_SCALE = 16384.0
GYRO_SCALE = 131.0
GYRO_DEADZONE_DPS = 0.5
ACCEL_EMA_FACTOR = 0.1


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


def parse_imu_line(line: str) -> dict[str, float | str]:
    if not line.startswith("IMU:"):
        return {}
    return parse_key_values(line[4:])


class IMUCalibrator:
    """Static MPU6050 calibration copied from the visualizer, minus UI output."""

    def __init__(self, target_samples: int = 50) -> None:
        self.target_samples = max(0, int(target_samples))
        self.samples: list[dict[str, float | str]] = []
        self.offsets = {"AX": 0.0, "AY": 0.0, "AZ": 0.0, "GX": 0.0, "GY": 0.0, "GZ": 0.0}
        self.calibrated = self.target_samples == 0

    def add_sample(self, imu_data: dict[str, float | str]) -> bool:
        if self.calibrated:
            return True
        self.samples.append(imu_data)
        if len(self.samples) >= self.target_samples:
            self._compute_offsets()
            self.calibrated = True
        return self.calibrated

    def _compute_offsets(self) -> None:
        n = max(1, len(self.samples))
        self.offsets["GX"] = sum(float(s.get("GX", 0) or 0) for s in self.samples) / n
        self.offsets["GY"] = sum(float(s.get("GY", 0) or 0) for s in self.samples) / n
        self.offsets["GZ"] = sum(float(s.get("GZ", 0) or 0) for s in self.samples) / n
        self.offsets["AX"] = sum(float(s.get("AX", 0) or 0) for s in self.samples) / n
        self.offsets["AY"] = sum(float(s.get("AY", 0) or 0) for s in self.samples) / n
        self.offsets["AZ"] = (sum(float(s.get("AZ", 0) or 0) for s in self.samples) / n) - ACCEL_SCALE

    def calibrated_data(self, imu_data: dict[str, float | str]) -> dict[str, float | str]:
        if not self.calibrated:
            return dict(imu_data)
        calibrated = dict(imu_data)
        for key in ("AX", "AY", "AZ", "GX", "GY", "GZ"):
            calibrated[key] = float(imu_data.get(key, 0) or 0) - self.offsets[key]
        return calibrated


class MadgwickFilter:
    """6-DOF Madgwick orientation filter using gyro plus accelerometer."""

    def __init__(self, beta: float = 0.04) -> None:
        self.beta = beta
        self.q = [1.0, 0.0, 0.0, 0.0]

    def update(self, gx: float, gy: float, gz: float, ax: float, ay: float, az: float, dt: float) -> dict[str, float]:
        q0, q1, q2, q3 = self.q
        accel_norm = math.sqrt(ax * ax + ay * ay + az * az)
        if accel_norm == 0.0:
            return self.euler()
        ax, ay, az = ax / accel_norm, ay / accel_norm, az / accel_norm

        _2q0, _2q1, _2q2, _2q3 = 2.0 * q0, 2.0 * q1, 2.0 * q2, 2.0 * q3
        _4q0, _4q1, _4q2 = 4.0 * q0, 4.0 * q1, 4.0 * q2
        _8q1, _8q2 = 8.0 * q1, 8.0 * q2
        q0q0, q1q1, q2q2, q3q3 = q0 * q0, q1 * q1, q2 * q2, q3 * q3

        s0 = _4q0 * q2q2 + _2q2 * ax + _4q0 * q1q1 - _2q1 * ay
        s1 = _4q1 * q3q3 - _2q3 * ax + 4.0 * q0q0 * q1 - _2q0 * ay - _4q1 + _8q1 * q1q1 + _8q1 * q2q2 + _4q1 * az
        s2 = 4.0 * q0q0 * q2 + _2q0 * ax + _4q2 * q3q3 - _2q3 * ay - _4q2 + _8q2 * q1q1 + _8q2 * q2q2 + _4q2 * az
        s3 = 4.0 * q1q1 * q3 - _2q1 * ax + 4.0 * q2q2 * q3 - _2q2 * ay
        step_norm = math.sqrt(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3)
        if step_norm > 0.0:
            s0, s1, s2, s3 = s0 / step_norm, s1 / step_norm, s2 / step_norm, s3 / step_norm

        q_dot0 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz) - self.beta * s0
        q_dot1 = 0.5 * (q0 * gx + q2 * gz - q3 * gy) - self.beta * s1
        q_dot2 = 0.5 * (q0 * gy - q1 * gz + q3 * gx) - self.beta * s2
        q_dot3 = 0.5 * (q0 * gz + q1 * gy - q2 * gx) - self.beta * s3

        q0 += q_dot0 * dt
        q1 += q_dot1 * dt
        q2 += q_dot2 * dt
        q3 += q_dot3 * dt

        q_norm = math.sqrt(q0 * q0 + q1 * q1 + q2 * q2 + q3 * q3)
        if q_norm > 0.0:
            self.q = [q0 / q_norm, q1 / q_norm, q2 / q_norm, q3 / q_norm]
        return self.euler()

    def euler(self) -> dict[str, float]:
        q0, q1, q2, q3 = self.q
        roll = math.atan2(2.0 * (q0 * q1 + q2 * q3), 1.0 - 2.0 * (q1 * q1 + q2 * q2))
        sinp = 2.0 * (q0 * q2 - q3 * q1)
        pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)
        yaw = math.atan2(2.0 * (q0 * q3 + q1 * q2), 1.0 - 2.0 * (q2 * q2 + q3 * q3))
        return {"roll": round(math.degrees(roll), 2), "pitch": round(math.degrees(pitch), 2), "yaw": round(math.degrees(yaw), 2)}


class IMUProcessor:
    """Calibration, gyro dead-zone, accelerometer low-pass, and Madgwick fusion."""

    def __init__(self, calibrate_samples: int = 50, beta: float = 0.04) -> None:
        self.calibrator = IMUCalibrator(calibrate_samples)
        self.filter = MadgwickFilter(beta)
        self.last_time: float | None = None
        self.smooth_ax = 0.0
        self.smooth_ay = 0.0
        self.smooth_az = 1.0
        self.accel_initialized = False

    def update(self, imu_data: dict[str, float | str]) -> dict[str, Any]:
        if int(float(imu_data.get("OK", 0) or 0)) != 1:
            return {"available": False, "calibrating": False, "reason": "IMU reports offline"}
        if not self.calibrator.calibrated:
            self.calibrator.add_sample(imu_data)
            return {
                "available": True,
                "calibrating": True,
                "calibration_progress": len(self.calibrator.samples) / max(1, self.calibrator.target_samples),
                "filter": "madgwick",
            }

        now = time.monotonic()
        dt = 0.01 if self.last_time is None else now - self.last_time
        self.last_time = now
        if dt <= 0.0 or dt > 1.0:
            dt = 0.01

        cal = self.calibrator.calibrated_data(imu_data)
        ax_g = float(cal.get("AX", 0) or 0) / ACCEL_SCALE
        ay_g = float(cal.get("AY", 0) or 0) / ACCEL_SCALE
        az_g = float(cal.get("AZ", 0) or 0) / ACCEL_SCALE
        if not self.accel_initialized:
            self.smooth_ax, self.smooth_ay, self.smooth_az = ax_g, ay_g, az_g
            self.accel_initialized = True
        else:
            self.smooth_ax += ACCEL_EMA_FACTOR * (ax_g - self.smooth_ax)
            self.smooth_ay += ACCEL_EMA_FACTOR * (ay_g - self.smooth_ay)
            self.smooth_az += ACCEL_EMA_FACTOR * (az_g - self.smooth_az)

        gx_dps = self._deadzone(float(cal.get("GX", 0) or 0) / GYRO_SCALE)
        gy_dps = self._deadzone(float(cal.get("GY", 0) or 0) / GYRO_SCALE)
        gz_dps = self._deadzone(float(cal.get("GZ", 0) or 0) / GYRO_SCALE)
        orientation = self.filter.update(
            math.radians(gx_dps),
            math.radians(gy_dps),
            math.radians(gz_dps),
            self.smooth_ax,
            self.smooth_ay,
            self.smooth_az,
            dt,
        )
        return {
            "available": True,
            "filter": "madgwick",
            "calibrating": False,
            "calibration_progress": 1.0,
            "roll": orientation["roll"],
            "pitch": -orientation["pitch"],
            "yaw": orientation["yaw"],
            "gyro_dps": {"x": round(gx_dps, 3), "y": round(gy_dps, 3), "z": round(gz_dps, 3)},
            "accel_g_smoothed": {"x": round(self.smooth_ax, 4), "y": round(self.smooth_ay, 4), "z": round(self.smooth_az, 4)},
            "noise_handling": {
                "static_calibration_samples": self.calibrator.target_samples,
                "gyro_deadzone_dps": GYRO_DEADZONE_DPS,
                "accel_ema_factor": ACCEL_EMA_FACTOR,
                "madgwick_beta": self.filter.beta,
            },
        }

    @staticmethod
    def _deadzone(value_dps: float) -> float:
        return value_dps if abs(value_dps) > GYRO_DEADZONE_DPS else 0.0


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
    arm2_count: int = 0
    ack_arm2_count: int = 0
    arm2_done: bool = False
    arm2_done_at: float | None = None
    ack_arm2_done_count: int = 0
    last_arm2_command: str | None = None
    # --- end Phase 1 fields ---
    line_count: int = 0
    telemetry: dict[str, float | str] = field(default_factory=dict)
    obstacles: dict[str, float | str] = field(default_factory=dict)
    imu: dict[str, float | str] = field(default_factory=dict)
    imu_orientation: dict[str, Any] = field(default_factory=dict)
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
        self._imu_processor = IMUProcessor()
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

    @staticmethod
    def _clamp_arm_speed(speed: int) -> int:
        return max(2000, min(3000, int(speed)))

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

    def send_arm(self, steps: int, speed: int = 2000, wait_ack: bool = True, timeout_s: float = 0.45) -> dict[str, Any]:
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
        command = f"CMD:ARM:{int(steps)},{self._clamp_arm_speed(speed)}"
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

    def send_arm2(self, steps: int, speed: int = 2000, wait_ack: bool = True, timeout_s: float = 0.45) -> dict[str, Any]:
        """Send CMD:ARM2:<steps>,<speed> for the second NEMA driver.

        Same safety warning as send_arm(): this is a low-level primitive and
        callers must enforce bounds before invoking it.
        """
        with self._lock:
            before = self._status.ack_arm2_count
            self._status.arm2_done = False
            self._status.arm2_done_at = None
        command = f"CMD:ARM2:{int(steps)},{self._clamp_arm_speed(speed)}"
        ok, detail = self.send_command(command)
        if not ok or not wait_ack:
            return {"ok": ok, "detail": detail, "command": command}

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._status.ack_arm2_count > before:
                    return {"ok": True, "detail": "ACK:ARM2", "command": command}
            time.sleep(0.01)
        return {"ok": False, "detail": f"ARM2 sent but ACK:ARM2 not received within {int(timeout_s * 1000)} ms", "command": command}

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
                    self._status.last_drive_command = None
                    self._status.last_drive_sent = None
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
                elif command.startswith("CMD:ARM2:"):
                    self._status.arm2_count += 1
                    self._status.last_arm2_command = command
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
        import serial  # type: ignore

        while not self._stop_event.is_set():
            ser = None
            try:
                ser = serial.Serial(port=self.port, baudrate=self.baud, timeout=0.02, write_timeout=0.1)
                with self._lock:
                    self._serial = ser
                    now = time.time()
                    self._status.available = True
                    self._status.running = True
                    if self._status.connected_since is None:
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
                    if self._serial is ser:
                        self._serial = None
                    self._status.running = False
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass

            if not self._stop_event.is_set():
                time.sleep(0.25)

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
            elif line == "ACK:ARM2":
                self._status.ack_arm2_count += 1
            elif line == "ACK:ARM2_DONE":
                self._status.arm2_done = True
                self._status.arm2_done_at = now_wall
                self._status.ack_arm2_done_count += 1
            elif line.startswith("TEL:"):
                self._status.telemetry = parse_tel_line(line)
            elif line.startswith("OBS:"):
                self._status.obstacles = parse_obs_line(line)
            elif line.startswith("IMU:"):
                self._status.imu = parse_imu_line(line)
                self._status.imu_orientation = self._imu_processor.update(self._status.imu)
            elif line.startswith("ALERT:"):
                self._status.alerts.insert(0, line)
                self._status.alerts = self._status.alerts[:20]


def status_to_dict(status: Stm32RuntimeStatus) -> dict[str, Any]:
    return asdict(status)
