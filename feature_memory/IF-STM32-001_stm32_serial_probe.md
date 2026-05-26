# Feature Memory: STM32 Serial Probe

Status: implemented, awaiting hardware validation

Last updated: 2026-05-26

Last validated: not yet validated on hardware

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
IF-STM32-001
IF-STM32-002
IF-STM32-004
IF-STM32-005
IF-STM32-006
IF-STM32-007
IF-STM32-008
IF-STM32-010
TIME-001
HW-001
```

Verification tests:

```text
VER-IDLE-008
Phase 1 STM32 connected test
Phase 1 STM32 disconnected test
Phase 1 STM32 plus Uno connected test
```

## Design Intent

Prove that the Raspberry Pi can find and validate the STM32 motor safety
controller before any higher-level Pluto behavior is allowed to use it.

This feature is the spine check. If it fails, Pluto must not enter movement
features.

## Design Decision

The implementation is a standalone Python CLI tool at `tools/stm32_probe.py`.
It scans serial ports instead of assuming `/dev/ttyACM0`, sends only safe
commands, measures `CMD:PING` timing, sends `CMD:STOP`, and checks for `TEL:`
and `OBS:` lines.

This was chosen over embedding the check inside the website or mode manager
because Phase 1 needs to be independently testable and debuggable.

## Interfaces

Inputs:

- USB CDC serial connection from Raspberry Pi or laptop to STM32 Black Pill.
- Optional explicit port passed with `--port`.

Outputs:

- Human-readable PASS/FAIL report.
- Optional JSON report with `--json`.
- `CMD:PING` sent to STM32.
- `CMD:STOP` sent to STM32.

External dependencies:

- Python 3.
- `pyserial`.
- STM32 firmware that speaks Pluto serial protocol.

## Configuration

Configuration values, defaults, limits, and files:

| Name | Default | Allowed Range | Reason |
| --- | --- | --- | --- |
| `--baud` | `115200` | serial baud accepted by firmware | Matches STM32 USB CDC test speed |
| `--ping-timeout-ms` | `100` | positive integer ms | Implements `TIME-001` and `IF-STM32-010` |
| `--ping-count` | `5` | positive integer | Catches unstable serial behavior |
| `--probe-timeout` | `2.0` | seconds | Gives STM32 time to emit identity/telemetry |
| `--telemetry-timeout` | `2.0` | seconds | Gives STM32 time to emit `TEL:` and `OBS:` |

## Runtime Behavior

Normal behavior:

1. Enumerate candidate serial ports.
2. Open each port safely.
3. Drain old serial input.
4. Send `CMD:PING`.
5. Identify STM32 by `ID:STM32_MOTOR`, `ACK:PING`, `TEL:`, `OBS:`, or `ALERT:`.
6. Validate the chosen STM32 port.
7. Send `CMD:STOP`.
8. Measure five `CMD:PING` -> `ACK:PING` round trips.
9. Wait for `TEL:` and `OBS:`.
10. Send final `CMD:STOP`.
11. Print `PHASE 1 RESULT: PASS` only if all required checks pass.

## How To Run

Install dependency:

```bash
python3 -m pip install pyserial
```

List candidate ports:

```bash
python3 tools/stm32_probe.py --list
```

Run auto-detection:

```bash
python3 tools/stm32_probe.py
```

Run explicit port:

```bash
python3 tools/stm32_probe.py --port /dev/ttyACM0
```

Run JSON output for later automation:

```bash
python3 tools/stm32_probe.py --json
```

## How To Debug

Checklist:

1. Confirm the STM32 heartbeat LED is running.
2. Confirm Black Pill USB is connected to the Pi or laptop.
3. Confirm the serial device exists with `ls /dev/ttyACM* /dev/ttyUSB*`.
4. Run `python3 tools/stm32_probe.py --list`.
5. Run `python3 tools/stm32_probe.py --port <device>`.
6. If ping fails, confirm STM32 firmware contains `CMD:PING` -> `ACK:PING`.
7. If telemetry fails, confirm STM32 firmware emits `TEL:` and `OBS:` every 100 ms.
8. If Uno is also connected, confirm the selected port is the one reporting STM32 lines.

Useful commands:

```bash
python3 tools/stm32_probe.py --list
python3 tools/stm32_probe.py --port /dev/ttyACM0 --json
dmesg | tail -50
ls -l /dev/ttyACM* /dev/ttyUSB*
```

## Expected Evidence

Passing output should include:

```text
PLUTO PHASE 1 - STM32 SERIAL VALIDATION
STM32 port:    /dev/ttyACM0
STOP ACK:      PASS
TEL line:      TEL:...
OBS line:      OBS:...
PING timing:
  1. PASS <100 ms
PHASE 1 RESULT: PASS
```

Failing output must include a specific failure reason and human next checks.

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-IDLE-008 | Run `python3 tools/stm32_probe.py` with STM32 connected | All `ACK:PING` latencies are within 100 ms | not run on hardware |
| PHASE1-STM32-CONNECTED | STM32 connected by USB CDC | Tool detects STM32 and prints `PHASE 1 RESULT: PASS` | not run on hardware |
| PHASE1-STM32-DISCONNECTED | Run with STM32 unplugged | Tool prints required-hardware failure and exits nonzero | not run on hardware |
| PHASE1-UNO-ALSO-CONNECTED | Run with STM32 and Uno connected | Tool chooses STM32 port, not Uno | not run on hardware |
| PHASE1-SAFE-COMMANDS | Inspect tool command writes | Tool sends only `CMD:PING` and `CMD:STOP` | code inspection complete |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| No serial ports found | USB cable missing or permission issue | `--list` prints nothing | Reconnect USB, check cable, add user to `dialout` on Pi |
| STM32 not detected | Wrong firmware or wrong port | No `ID:`, `ACK:PING`, `TEL:`, or `OBS:` | Reflash STM32 firmware and run explicit `--port` |
| `ACK:PING` over 100 ms | Firmware blocked or USB serial unstable | Ping timing lines show failure | Check STM32 main loop, USB CDC receive hook, CPU blocking code |
| Missing `TEL:` | Firmware telemetry disabled | Probe passes ping but telemetry missing | Inspect STM32 telemetry interval and serial send path |
| Missing `OBS:` | Firmware obstacle report disabled | Probe passes ping but obstacle missing | Inspect STM32 obstacle send path |
| Wrong device selected | Another USB serial device replies unexpectedly | Warning lines show unexpected text | Use explicit `--port` and improve identity string |

## Safety Notes

This feature fails safe. It never sends movement commands. It sends `CMD:STOP`
before timed validation and again at the end.

No website, mode manager, dance, welcome, manual drive, or autonomous behavior
may depend on STM32 until this feature passes.

## Open Questions

- Should the STM32 include a stronger identity response such as firmware
  version and protocol version?
- Should future runtime heartbeat use the same timing measurement format as
  this probe?

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-05-26 | Initial implementation memory | Phase 1 initiated |
