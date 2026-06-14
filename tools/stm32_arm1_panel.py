#!/usr/bin/env python3
"""Interactive STM32 live readings + Arm 1 jog panel for PLUTO.

This tool is intentionally conservative:
- It keeps the STM32 heartbeat alive with CMD:PING.
- It streams TEL / OBS / IMU / ACK / ALERT lines.
- It only sends bounded Arm 1 jog commands unless the operator types raw.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from dataclasses import dataclass, field

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("pyserial is required: pip install pyserial", file=sys.stderr)
    raise


STM32_USB_VID_PID = "0483:5740"


@dataclass
class PanelState:
    tel: dict[str, str] = field(default_factory=dict)
    obs: dict[str, str] = field(default_factory=dict)
    imu: dict[str, str] = field(default_factory=dict)
    last_raw: str = ""
    last_ack: str = "none"
    last_alert: str = "none"
    last_command: str = "none"
    arm_steps: int = 800
    arm_speed: int = 50
    raw_mode: bool = False


def find_port(preferred: str | None) -> str:
    ports = list(serial.tools.list_ports.comports())
    if preferred:
        return preferred
    for port in ports:
        text = f"{port.description} {port.hwid}".upper()
        if STM32_USB_VID_PID in text or "STM" in text or "STMICRO" in text:
            return port.device
    if ports:
        return ports[0].device
    raise SystemExit("No serial ports found. Connect the STM32 USB cable first.")


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


def fmt_distance(values: dict[str, str], key: str) -> str:
    raw = values.get(key, "999")
    try:
        value = float(raw)
    except ValueError:
        return f"{key}: ?"
    if value >= 999:
        return f"{key}: ---"
    return f"{key}: {value:5.1f}cm"


def command_reader(out: queue.Queue[str]) -> None:
    while True:
        try:
            text = input()
        except EOFError:
            out.put("q")
            return
        out.put(text.strip())


def send_line(ser: serial.Serial, state: PanelState, line: str) -> None:
    if not line.endswith("\n"):
        line += "\n"
    ser.write(line.encode("ascii", errors="ignore"))
    state.last_command = line.strip()


def print_help() -> None:
    print(
        """
Commands:
  + / u             jog Arm 1 positive by current steps
  - / d             jog Arm 1 negative by current steps
  move <steps>      jog Arm 1 by exact signed steps, example: move -250
  move2 <steps>     jog Arm 2 by exact signed steps, example: move2 5000
  steps <n>         set jog step amount, example: steps 150
  speed <n>         set Arm speed, example: speed 250
  stop / s          send CMD:STOP
  ping / p          send CMD:PING
  raw <command>     send exact command, example: raw CMD:ARM:100,200
  rawmode           toggle printing every raw STM32 line
  help / h          show this menu
  quit / q          exit

Arm commands used by this panel:
  CMD:ARM:<steps>,<speed>
  CMD:ARM2:<steps>,<speed>
"""
    )


def handle_command(text: str, ser: serial.Serial, state: PanelState) -> bool:
    if not text:
        return True
    lower = text.lower()

    if lower in {"q", "quit", "exit"}:
        return False
    if lower in {"h", "help", "?"}:
        print_help()
        return True
    if lower in {"p", "ping"}:
        send_line(ser, state, "CMD:PING")
        return True
    if lower in {"s", "stop"}:
        send_line(ser, state, "CMD:STOP")
        return True
    if lower in {"rawmode", "raw-mode"}:
        state.raw_mode = not state.raw_mode
        print(f"\nRaw line printing: {'ON' if state.raw_mode else 'OFF'}")
        return True
    if lower in {"+", "u", "up"}:
        send_line(ser, state, f"CMD:ARM:{state.arm_steps},{state.arm_speed}")
        return True
    if lower in {"-", "d", "down"}:
        send_line(ser, state, f"CMD:ARM:{-state.arm_steps},{state.arm_speed}")
        return True

    parts = text.split()
    if len(parts) == 2 and parts[0].lower() == "steps":
        state.arm_steps = max(0, min(2147483647, abs(int(parts[1]))))
        print(f"\nArm jog steps set to {state.arm_steps}")
        return True
    if len(parts) == 2 and parts[0].lower() == "speed":
        state.arm_speed = max(1, min(3000, abs(int(parts[1]))))
        print(f"\nArm speed set to {state.arm_speed}")
        return True
    if len(parts) == 2 and parts[0].lower() == "move":
        steps = max(-2147483648, min(2147483647, int(parts[1])))
        send_line(ser, state, f"CMD:ARM:{steps},{state.arm_speed}")
        return True
    if len(parts) == 2 and parts[0].lower() == "move2":
        steps = max(-2147483648, min(2147483647, int(parts[1])))
        send_line(ser, state, f"CMD:ARM2:{steps},{state.arm_speed}")
        return True
    if lower.startswith("raw "):
        send_line(ser, state, text[4:].strip())
        return True

    print(f"\nUnknown command: {text}. Type help.")
    return True


def render(state: PanelState) -> None:
    obs = "  ".join(
        [
            fmt_distance(state.obs, "FL"),
            fmt_distance(state.obs, "F"),
            fmt_distance(state.obs, "FR"),
        ]
    )
    imu = (
        f"OK:{state.imu.get('OK', '?')} "
        f"AX:{state.imu.get('AX', '?')} AY:{state.imu.get('AY', '?')} AZ:{state.imu.get('AZ', '?')} "
        f"GZ:{state.imu.get('GZ', '?')}"
    )
    tel = (
        f"BAT:{state.tel.get('BAT', '?')} "
        f"SPD:{state.tel.get('SPD', '?')} "
        f"DIST:{state.tel.get('DIST', '?')} "
        f"X:{state.tel.get('X', '?')} Y:{state.tel.get('Y', '?')} H:{state.tel.get('H', '?')}"
    )
    print(
        "\r"
        f"OBS [{obs}] | IMU [{imu}] | TEL [{tel}] | "
        f"ARM1 steps:{state.arm_steps} speed:{state.arm_speed} | "
        f"CMD:{state.last_command} | ACK:{state.last_ack} | ALERT:{state.last_alert}      ",
        end="",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None, help="Serial port, e.g. COM8 or /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--speed", type=int, default=50)
    args = parser.parse_args()

    port = find_port(args.port)
    state = PanelState(arm_steps=max(0, abs(args.steps)), arm_speed=max(1, abs(args.speed)))
    commands: queue.Queue[str] = queue.Queue()

    print("PLUTO STM32 terminal panel")
    print(f"Port: {port} @ {args.baud}")
    print("Safety: clear the arm before jogging. Type help for controls.\n")
    print_help()

    thread = threading.Thread(target=command_reader, args=(commands,), daemon=True)
    thread.start()

    with serial.Serial(port, args.baud, timeout=0.05, write_timeout=0.2) as ser:
        time.sleep(0.8)
        ser.reset_input_buffer()
        send_line(ser, state, "CMD:PING")
        next_ping = time.monotonic() + 0.5
        next_screen = 0.0

        running = True
        while running:
            now = time.monotonic()
            if now >= next_ping:
                try:
                    send_line(ser, state, "CMD:PING")
                except Exception as exc:
                    print(f"\nSerial write failed: {exc}")
                next_ping = now + 0.5

            while not commands.empty():
                try:
                    running = handle_command(commands.get_nowait(), ser, state)
                except Exception as exc:
                    print(f"\nCommand failed: {exc}")

            line = ser.readline().decode(errors="replace").strip()
            if line:
                state.last_raw = line
                if state.raw_mode:
                    print(f"\n{line}")
                if line.startswith("TEL:"):
                    state.tel = parse_values(line, "TEL:")
                elif line.startswith("OBS:"):
                    state.obs = parse_values(line, "OBS:")
                elif line.startswith("IMU:"):
                    state.imu = parse_values(line, "IMU:")
                elif line.startswith("ACK:"):
                    state.last_ack = line
                elif line.startswith("ALERT:"):
                    state.last_alert = line

            if now >= next_screen:
                render(state)
                next_screen = now + 0.15

    print("\nPanel closed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
