#!/usr/bin/env python3
"""Live STM32 telemetry monitor for PLUTO.

Prints compact live readings from the STM32 USB serial port.
Use while wiring sensors so changes are visible immediately.
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("pyserial is required: pip install pyserial", file=sys.stderr)
    raise


def find_port(preferred: str | None) -> str:
    ports = list(serial.tools.list_ports.comports())
    if preferred:
        return preferred
    for port in ports:
        text = f"{port.description} {port.hwid}".upper()
        if "0483:5740" in text or "STM" in text:
            return port.device
    if ports:
        return ports[0].device
    raise SystemExit("No serial ports found.")


def parse_values(line: str, prefix: str) -> dict[str, str]:
    if not line.startswith(prefix):
        return {}
    out: dict[str, str] = {}
    for part in line[len(prefix) :].split(","):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        out[key.strip()] = value.strip()
    return out


def fmt_obs(obs: dict[str, str]) -> str:
    def one(key: str) -> str:
        raw = obs.get(key, "999")
        try:
            value = float(raw)
        except ValueError:
            return f"{key}:?"
        if value >= 999:
            return f"{key}:---"
        return f"{key}:{value:5.0f}cm"

    return f"{one('FL')}  {one('F')}  {one('FR')}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None, help="Serial port, e.g. COM8 or /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--raw", action="store_true", help="Print all raw STM32 lines too")
    args = parser.parse_args()

    port = find_port(args.port)
    print(f"PLUTO STM32 live monitor")
    print(f"Port: {port} @ {args.baud}")
    print("Legend: --- means no ultrasonic echo / timeout")
    print("Press Ctrl+C to stop.\n")

    latest_tel: dict[str, str] = {}
    latest_obs: dict[str, str] = {}
    latest_imu: dict[str, str] = {}
    alerts: list[str] = []
    last_screen = 0.0

    with serial.Serial(port, args.baud, timeout=0.2, write_timeout=0.2) as ser:
        time.sleep(0.6)
        ser.reset_input_buffer()
        ser.write(b"CMD:PING\n")
        next_ping = time.monotonic() + 0.5
        while True:
            now = time.monotonic()
            if now >= next_ping:
                try:
                    ser.write(b"CMD:PING\n")
                except Exception:
                    pass
                next_ping = now + 0.5

            line = ser.readline().decode(errors="replace").strip()
            if not line:
                continue
            if args.raw:
                print(line)

            if line.startswith("TEL:"):
                latest_tel = parse_values(line, "TEL:")
            elif line.startswith("OBS:"):
                latest_obs = parse_values(line, "OBS:")
            elif line.startswith("IMU:"):
                latest_imu = parse_values(line, "IMU:")
            elif line.startswith("ALERT:"):
                alerts.insert(0, line)
                alerts = alerts[:3]

            if now - last_screen >= 0.18:
                last_screen = now
                obs_text = fmt_obs(latest_obs)
                imu_ok = latest_imu.get("OK", "?")
                imu_temp = latest_imu.get("TEMP", "?")
                ax = latest_imu.get("AX", "?")
                ay = latest_imu.get("AY", "?")
                az = latest_imu.get("AZ", "?")
                bat = latest_tel.get("BAT", "0")
                x = latest_tel.get("X", "0")
                y = latest_tel.get("Y", "0")
                h = latest_tel.get("H", "0")
                alert_text = " | ".join(alerts) if alerts else "none"
                print(
                    f"\rOBS  {obs_text}   "
                    f"IMU OK:{imu_ok} T:{imu_temp} AX:{ax} AY:{ay} AZ:{az}   "
                    f"POSE X:{x} Y:{y} H:{h} BAT:{bat}   "
                    f"ALERT:{alert_text}      ",
                    end="",
                    flush=True,
                )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
