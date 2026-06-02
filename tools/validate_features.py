#!/usr/bin/env python3
"""Run Pluto feature validation one feature at a time.

This is the repeatable systems-engineering gate. It runs the safe smoke tests
that prove each implemented feature independently, then prints a compact
PASS/SKIP/FAIL table. Hardware checks are opt-in because they touch real ports,
but they still send only safe commands such as PING and STOP.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class FeatureCheck:
    feature_id: str
    name: str
    command: list[str]
    timeout_s: float = 60.0
    optional: bool = False
    hardware: bool = False


@dataclass
class FeatureResult:
    feature_id: str
    name: str
    status: str
    command: list[str]
    duration_s: float
    returncode: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    optional: bool = False
    hardware: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Pluto features one by one.")
    parser.add_argument("--hardware", action="store_true", help="Include safe STM32 hardware checks.")
    parser.add_argument("--audio", action="store_true", help="Include audio device availability checks.")
    parser.add_argument("--uno", action="store_true", help="Include optional Uno LCD serial checks.")
    parser.add_argument("--require-audio", action="store_true", help="Require microphone and speaker during audio checks.")
    parser.add_argument("--json-out", help="Write full validation report JSON to this path.")
    return parser.parse_args()


def checks(args: argparse.Namespace) -> list[FeatureCheck]:
    py = sys.executable
    items = [
        FeatureCheck("STATE-CORE-001", "Mode manager transitions", [py, "tools/mode_manager_smoke.py"]),
        FeatureCheck("WEB-001", "Operator website shell", [py, "tools/web_shell_smoke.py"], timeout_s=90),
        FeatureCheck("STATE-5", "ERROR state behavior", [py, "tools/error_state_smoke.py"], timeout_s=90),
        FeatureCheck("STATE-2", "MANUAL gates and raw route blocking", [py, "tools/manual_state_smoke.py"], timeout_s=90),
        FeatureCheck("STATE-3.33", "WELCOME_TALK keyword bank", [py, "tools/welcome_talk_smoke.py"], timeout_s=90),
        FeatureCheck("STATE-3.12", "WELCOME wave trigger", [py, "tools/welcome_wave_smoke.py"], timeout_s=90),
        FeatureCheck("STATE-3.29", "WELCOME_APPROACH dry run", [py, "tools/welcome_approach_smoke.py"]),
        FeatureCheck("IF-STM32-013", "STM32 return/reset/arm command wrapper", [py, "tools/stm32_link_extensions_smoke.py"]),
        FeatureCheck("STATE-4", "DANCE dry run", [py, "tools/dance_smoke.py"]),
        FeatureCheck("STATE-1", "IDLE parser/runtime smoke", [py, "tools/idle_runtime_smoke.py"], hardware=True),
    ]
    if args.hardware:
        items.append(FeatureCheck("IF-STM32-001", "STM32 serial safety link", [py, "tools/stm32_probe.py"], timeout_s=90, hardware=True))
        items.append(
            FeatureCheck(
                "STATE-1.HW",
                "IDLE heartbeat with required STM32",
                [py, "tools/idle_runtime_smoke.py", "--require-hardware"],
                timeout_s=90,
                hardware=True,
            )
        )
    if args.audio:
        command = [py, "tools/audio_io_smoke.py"]
        if args.require_audio:
            command.extend(["--require-microphone", "--require-speaker"])
        items.append(FeatureCheck("AUD-001", "Audio input/output availability", command, timeout_s=90, optional=not args.require_audio, hardware=True))
    if args.uno:
        items.append(FeatureCheck("IF-UNO-001", "Uno LCD serial link", [py, "tools/uno_probe.py"], timeout_s=90, optional=True, hardware=True))
    return items


def tail(text: str, max_lines: int = 10) -> str:
    lines = text.strip().splitlines()
    return "\n".join(lines[-max_lines:])


def run_check(check: FeatureCheck) -> FeatureResult:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            check.command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=check.timeout_s,
        )
        duration = time.monotonic() - started
        combined = f"{proc.stdout}\n{proc.stderr}"
        if proc.returncode == 0 and " SKIP" in combined:
            status = "SKIP"
        elif proc.returncode == 0:
            status = "PASS"
        elif check.optional:
            status = "OPTIONAL_FAIL"
        else:
            status = "FAIL"
        return FeatureResult(
            feature_id=check.feature_id,
            name=check.name,
            status=status,
            command=check.command,
            duration_s=duration,
            returncode=proc.returncode,
            stdout_tail=tail(proc.stdout),
            stderr_tail=tail(proc.stderr),
            optional=check.optional,
            hardware=check.hardware,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        return FeatureResult(
            feature_id=check.feature_id,
            name=check.name,
            status="OPTIONAL_FAIL" if check.optional else "FAIL",
            command=check.command,
            duration_s=duration,
            returncode=124,
            stdout_tail=tail(exc.stdout or ""),
            stderr_tail=f"timeout after {check.timeout_s:.0f}s",
            optional=check.optional,
            hardware=check.hardware,
        )


def print_table(results: list[FeatureResult]) -> None:
    print("PLUTO FEATURE VALIDATION")
    print(f"commit: {git_commit()}")
    print()
    print(f"{'STATUS':<14} {'ID':<16} {'FEATURE':<42} {'TIME'}")
    print("-" * 84)
    for result in results:
        print(f"{result.status:<14} {result.feature_id:<16} {result.name:<42} {result.duration_s:>5.1f}s")
    print()
    for result in results:
        if result.status in {"FAIL", "OPTIONAL_FAIL", "SKIP"}:
            print(f"[{result.status}] {result.feature_id} {result.name}")
            if result.stdout_tail:
                print(result.stdout_tail)
            if result.stderr_tail:
                print(result.stderr_tail)
            print()


def git_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main() -> int:
    args = parse_args()
    started = time.time()
    results = [run_check(check) for check in checks(args)]
    print_table(results)

    report = {
        "project": "PLUTO",
        "commit": git_commit(),
        "timestamp": started,
        "duration_s": time.time() - started,
        "results": [asdict(result) for result in results],
    }
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"report: {output}")

    failed = [item for item in results if item.status == "FAIL"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
