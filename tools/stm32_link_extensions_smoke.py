#!/usr/bin/env python3
"""Smoke tests for Phase 1 STM32 link extensions.

Edited by: Antigravity (DeepMind AI Assistant)
Date: 2026-05-30
Tests: send_return, send_reset_home, send_arm command formatting,
ACK line parsing for all new types, async completion tracking,
return_active lifecycle, and state reset behavior using FakeSerial.
No hardware required.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pluto_runtime.stm32_link import Stm32RuntimeStatus, Stm32SerialLink


class FakeSerial:
    """Mock serial port for testing command transmission."""
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.closed: bool = False

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_status_defaults() -> None:
    """New status fields must have safe zero/False defaults."""
    status = Stm32RuntimeStatus()
    assert status.return_count == 0
    assert status.ack_return_count == 0
    assert status.return_active is False
    assert status.return_complete is False
    assert status.return_complete_at is None
    assert status.reset_home_count == 0
    assert status.ack_reset_home_count == 0
    assert status.arm_count == 0
    assert status.ack_arm_count == 0
    assert status.arm_done is False
    assert status.arm_done_at is None
    assert status.ack_arm_done_count == 0
    assert status.last_arm_command is None
    print("  status_defaults PASS")


def test_ack_return_parsing() -> None:
    """_handle_line must parse ACK:RETURN and increment counter."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    assert link._status.ack_return_count == 0
    link._handle_line("ACK:RETURN")
    assert link._status.ack_return_count == 1
    assert link._status.return_complete is False  # not complete yet
    link._handle_line("ACK:RETURN")
    assert link._status.ack_return_count == 2
    print("  ack_return_parsing PASS")


def test_ack_return_complete_parsing() -> None:
    """_handle_line must parse ACK:RETURN_COMPLETE and set/reset flags."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    link._status.return_active = True
    assert link._status.return_complete is False
    assert link._status.return_complete_at is None

    link._handle_line("ACK:RETURN_COMPLETE")
    assert link._status.return_complete is True
    assert link._status.return_active is False
    assert link._status.return_complete_at is not None
    assert isinstance(link._status.return_complete_at, float)
    print("  ack_return_complete_parsing PASS")


def test_ack_reset_home_parsing() -> None:
    """_handle_line must parse ACK:RESET_HOME and increment counter."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    assert link._status.ack_reset_home_count == 0
    link._handle_line("ACK:RESET_HOME")
    assert link._status.ack_reset_home_count == 1
    print("  ack_reset_home_parsing PASS")


def test_ack_arm_parsing() -> None:
    """_handle_line must parse ACK:ARM (immediate) and increment counter."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    assert link._status.ack_arm_count == 0
    assert link._status.arm_done is False
    link._handle_line("ACK:ARM")
    assert link._status.ack_arm_count == 1
    assert link._status.arm_done is False  # not done yet, just acknowledged
    print("  ack_arm_parsing PASS")


def test_ack_arm_done_parsing() -> None:
    """_handle_line must parse ACK:ARM_DONE and set completion flag + timestamp."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    assert link._status.arm_done is False
    assert link._status.arm_done_at is None
    assert link._status.ack_arm_done_count == 0
    link._handle_line("ACK:ARM_DONE")
    assert link._status.arm_done is True
    assert link._status.arm_done_at is not None
    assert link._status.ack_arm_done_count == 1
    print("  ack_arm_done_parsing PASS")


def test_arm_sequence() -> None:
    """Full ARM sequence: ACK:ARM then later ACK:ARM_DONE."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    link._status.arm_count = 1
    link._status.last_arm_command = "CMD:ARM:200,300"
    link._status.arm_done = False
    link._status.arm_done_at = None

    link._handle_line("ACK:ARM")
    assert link._status.ack_arm_count == 1
    assert link._status.arm_done is False

    link._handle_line("ACK:ARM_DONE")
    assert link._status.arm_done is True
    assert link._status.arm_done_at is not None
    assert link._status.ack_arm_done_count == 1
    print("  arm_sequence PASS")


def test_return_complete_resets_on_new_return() -> None:
    """return_complete must reset when a new CMD:RETURN is conceptually sent."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    fake_ser = FakeSerial()
    link._serial = fake_ser
    link._status.available = True

    # First return
    link.send_return(wait_ack=False)
    assert link._status.return_active is True
    assert link._status.return_complete is False

    link._handle_line("ACK:RETURN")
    link._handle_line("ACK:RETURN_COMPLETE")
    assert link._status.return_complete is True
    assert link._status.return_active is False
    assert link._status.return_complete_at is not None

    # New return resets status
    link.send_return(wait_ack=False)
    assert link._status.return_complete is False
    assert link._status.return_complete_at is None
    assert link._status.return_active is True

    link._handle_line("ACK:RETURN")
    link._handle_line("ACK:RETURN_COMPLETE")
    assert link._status.return_complete is True
    assert link._status.return_active is False
    assert link._status.ack_return_count == 2
    print("  return_complete_resets PASS")


def test_arm_done_resets_on_new_arm() -> None:
    """arm_done must reset when a new CMD:ARM is conceptually sent."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    fake_ser = FakeSerial()
    link._serial = fake_ser
    link._status.available = True

    link.send_arm(steps=100, wait_ack=False)
    assert link._status.arm_done is False

    link._handle_line("ACK:ARM")
    link._handle_line("ACK:ARM_DONE")
    assert link._status.arm_done is True

    # New arm command resets completion status
    link.send_arm(steps=200, wait_ack=False)
    assert link._status.arm_done is False
    assert link._status.arm_done_at is None

    link._handle_line("ACK:ARM")
    assert link._status.arm_done is False
    link._handle_line("ACK:ARM_DONE")
    assert link._status.arm_done is True
    assert link._status.ack_arm_done_count == 2
    print("  arm_done_resets PASS")


def test_command_tracking_with_mock() -> None:
    """send_command must format new commands correctly and update status using mock serial."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    fake_ser = FakeSerial()
    link._serial = fake_ser
    link._status.available = True

    # 1. Test RETURN
    res = link.send_return(wait_ack=False)
    assert res["ok"] is True
    assert fake_ser.written[-1] == b"CMD:RETURN\n"
    assert link._status.return_count == 1
    assert link._status.return_active is True

    # 2. Test RESET_HOME
    res = link.send_reset_home(wait_ack=False)
    assert res["ok"] is True
    assert fake_ser.written[-1] == b"CMD:RESET_HOME\n"
    assert link._status.reset_home_count == 1

    # 3. Test ARM
    res = link.send_arm(steps=150, speed=100, wait_ack=False)
    assert res["ok"] is True
    assert fake_ser.written[-1] == b"CMD:ARM:150,100\n"
    assert link._status.arm_count == 1
    assert link._status.last_arm_command == "CMD:ARM:150,100"

    print("  command_tracking_with_mock PASS")


def test_return_active_lifecycle() -> None:
    """return_active lifecycle: True on RETURN, False on COMPLETE or STOP/DRIVE."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    fake_ser = FakeSerial()
    link._serial = fake_ser
    link._status.available = True

    # Start return
    link.send_return(wait_ack=False)
    assert link._status.return_active is True

    # 1. Complete return
    link._handle_line("ACK:RETURN_COMPLETE")
    assert link._status.return_active is False

    # Start return again
    link.send_return(wait_ack=False)
    assert link._status.return_active is True

    # 2. Interrupted by STOP
    link.send_stop(wait_ack=False)
    assert link._status.return_active is False

    # Start return again
    link.send_return(wait_ack=False)
    assert link._status.return_active is True

    # 3. Interrupted by DRIVE
    link.send_drive(speed=100, steer=0, wait_ack=False)
    assert link._status.return_active is False

    print("  return_active_lifecycle PASS")


def test_existing_acks_still_work() -> None:
    """Existing ACK:PING, ACK:STOP, ACK:DRIVE must still parse correctly."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    link._handle_line("ACK:PING")
    assert link._status.ack_ping_count == 1
    link._handle_line("ACK:STOP")
    assert link._status.ack_stop_count == 1
    link._handle_line("ACK:DRIVE")
    assert link._status.ack_drive_count == 1
    print("  existing_acks PASS")


def test_telemetry_and_obs_still_work() -> None:
    """TEL: and OBS: lines must still parse correctly."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    link._handle_line("TEL:BAT:36.2,SPD:0.0,DIST:0,TEMP:28.5,X:12.5,Y:-4.0,H:90.0,HOME:15.2,RET:1")
    assert link._status.telemetry.get("BAT") == 36.2
    assert link._status.telemetry.get("SPD") == 0.0
    assert link._status.telemetry.get("X") == 12.5
    assert link._status.telemetry.get("Y") == -4.0
    assert link._status.telemetry.get("H") == 90.0
    assert link._status.telemetry.get("HOME") == 15.2
    assert link._status.telemetry.get("RET") == 1.0
    link._handle_line("OBS:FL:120,F:95,FR:200")
    assert link._status.obstacles.get("F") == 95.0
    assert link._status.obstacles.get("FL") == 120.0
    print("  telemetry_and_obs PASS")


def test_alerts_still_work() -> None:
    """ALERT: lines must still parse correctly."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    link._handle_line("ALERT:PI_TIMEOUT")
    assert len(link._status.alerts) == 1
    assert link._status.alerts[0] == "ALERT:PI_TIMEOUT"
    print("  alerts PASS")


def test_get_status_includes_new_fields() -> None:
    """get_status() snapshot must include all new Phase 1 fields."""
    link = Stm32SerialLink("COM_FAKE", baud=115200)
    link._handle_line("ACK:RETURN")
    link._handle_line("ACK:ARM")
    link._handle_line("ACK:ARM_DONE")
    link._handle_line("ACK:RESET_HOME")
    status = link.get_status()
    assert status.ack_return_count == 1
    assert status.ack_arm_count == 1
    assert status.arm_done is True
    assert status.arm_done_at is not None
    assert status.ack_arm_done_count == 1
    assert status.ack_reset_home_count == 1
    assert hasattr(status, "return_active")
    print("  get_status_new_fields PASS")


def main() -> int:
    print("STM32_LINK_EXTENSIONS_SMOKE")
    test_status_defaults()
    test_ack_return_parsing()
    test_ack_return_complete_parsing()
    test_ack_reset_home_parsing()
    test_ack_arm_parsing()
    test_ack_arm_done_parsing()
    test_arm_sequence()
    test_return_complete_resets_on_new_return()
    test_arm_done_resets_on_new_arm()
    test_command_tracking_with_mock()
    test_return_active_lifecycle()
    test_existing_acks_still_work()
    test_telemetry_and_obs_still_work()
    test_alerts_still_work()
    test_get_status_includes_new_fields()
    print("STM32_LINK_EXTENSIONS_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
