# Feature Memory: Uno LCD Serial Probe

Status: firmware implemented, awaiting hardware validation

Last updated: 2026-06-08

Last validated: not yet validated on hardware

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
IF-UNO-001
IF-UNO-002
IF-UNO-003
IF-UNO-004
IF-UNO-005
HW-002
STATE-0.21
STATE-1.3
STATE-1.14.3
```

Verification tests:

```text
VER-IDLE-002
Phase 2 Uno connected test
Phase 2 Uno disconnected test
Phase 2 STM32 plus Uno connected test
```

## Design Intent

Prove that the Raspberry Pi can identify and command the Arduino Uno that owns
Pluto's LCD face and simple text display.

This feature is prepared before the LCD hardware arrives so the integration
path is ready and traceable.

## Design Decision

The implementation includes:

- a standalone Python CLI tool at `tools/uno_probe.py`
- Arduino face firmware at `arduino/uno_lcd_face/uno_lcd_face.ino`

The probe scans serial ports, waits for the Arduino USB reset window,
identifies `ID:UNO_LCD`, sends a small set of face/mode/text commands, and
requires ACK responses. The firmware draws animated LCD expressions and keeps
the protocol bounded to display-only behavior.

This is separate from the website and mode manager because the display
controller must be independently validated before IDLE, WELCOME, DANCE, or
ERROR depend on it.

## Interfaces

Inputs:

- USB serial connection from Raspberry Pi or laptop to Arduino Uno.
- Optional explicit port passed with `--port`.

Outputs:

- Human-readable PASS/FAIL report.
- Optional JSON report with `--json`.
- Uno commands:
  - `MODE:BOOT`
  - `FACE:IDLE`
  - `FACE:HAPPY`
  - `FACE:THINKING`
  - `TEXT:PLUTO PHASE 2`
  - `MODE:IDLE`

External dependencies:

- Python 3.
- `pyserial`.
- Uno firmware at `arduino/uno_lcd_face/uno_lcd_face.ino`.
- LCD connected to Uno for visual verification.

## Configuration

Configuration values, defaults, limits, and files:

| Name | Default | Allowed Range | Reason |
| --- | --- | --- | --- |
| `--baud` | `115200` | serial baud accepted by Uno firmware | Standard Pluto serial speed |
| `--probe-timeout` | `3.0` | seconds | Allows Arduino USB reset and identity print |
| `--command-timeout-ms` | `500` | positive integer ms | Gives LCD firmware time to acknowledge updates |

## Runtime Behavior

Normal behavior:

1. Enumerate candidate serial ports.
2. Open each port safely.
3. Wait for Arduino USB serial reset.
4. Read boot output and send identity probes if needed.
5. Identify Uno by `ID:UNO_LCD`.
6. Send mode, face, and text commands.
7. Require ACK responses.
8. Print `PHASE 2 RESULT: PASS` only if identity and all command ACKs pass.

## How To Run

Install dependency:

```bash
python3 -m pip install pyserial
```

List candidate ports:

```bash
python3 tools/uno_probe.py --list
```

Run auto-detection:

```bash
python3 tools/uno_probe.py
```

Run explicit port:

```bash
python3 tools/uno_probe.py --port /dev/ttyACM1
```

Run JSON output for later automation:

```bash
python3 tools/uno_probe.py --json
```

## How To Debug

Checklist:

1. Confirm Uno is connected by USB.
2. Confirm Uno firmware baud rate is `115200`.
3. Confirm Uno prints `ID:UNO_LCD` on boot or replies to `ID?`.
4. Confirm commands return `ACK:MODE`, `ACK:FACE`, and `ACK:TEXT`.
5. Confirm LCD wiring separately if ACKs pass but screen does not change.
6. If STM32 is also connected, confirm the tool chooses the Uno port.

Useful commands:

```bash
python3 tools/uno_probe.py --list
python3 tools/uno_probe.py --port /dev/ttyACM1 --json
dmesg | tail -50
ls -l /dev/ttyACM* /dev/ttyUSB*
```

## Expected Evidence

Passing output should include:

```text
PLUTO PHASE 2 - UNO LCD SERIAL VALIDATION
Uno port:      /dev/ttyACM1
Identity:      ID:UNO_LCD
MODE:BOOT           PASS
FACE:IDLE           PASS
FACE:HAPPY          PASS
FACE:THINKING       PASS
TEXT:PLUTO PHASE 2  PASS
MODE:IDLE           PASS
PHASE 2 RESULT: PASS
```

Human visual evidence when LCD is connected:

```text
LCD shows boot/idle mode.
LCD changes to idle, happy, and thinking faces.
LCD displays PLUTO PHASE 2 text.
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-IDLE-002 | Run tool with Uno and LCD connected | `ID:UNO_LCD`, `MODE:IDLE`, idle face displayed | not run on hardware |
| PHASE2-UNO-CONNECTED | Run `python3 tools/uno_probe.py` | Tool detects Uno and prints `PHASE 2 RESULT: PASS` | not run on hardware |
| PHASE2-UNO-DISCONNECTED | Run with Uno unplugged | Tool reports Uno not detected and exits nonzero | not run on hardware |
| PHASE2-STM32-ALSO-CONNECTED | Run with STM32 and Uno connected | Tool chooses Uno port, not STM32 | not run on hardware |
| PHASE2-LCD-VISUAL | Observe LCD during probe | Mode, face, and text changes are visible | not run on hardware |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| No serial ports found | USB cable missing or permission issue | `--list` prints nothing | Reconnect USB, check cable, add user to `dialout` |
| Uno not detected | Wrong firmware or wrong port | No `ID:UNO_LCD` | Flash Uno LCD firmware and run explicit `--port` |
| Commands not acknowledged | Uno parser mismatch | Command line shows missing ACK | Match Uno firmware ACK format to tool contract |
| ACKs pass but LCD does not change | LCD wiring or display library issue | Tool passes but display unchanged | Debug Uno LCD wiring and standalone display sketch |
| STM32 selected by mistake | Weak identity handling | Warnings show STM32 `TEL:` or `OBS:` lines | Use explicit `--port` and keep Uno identity unique |

## Safety Notes

This feature cannot move Pluto. It sends only LCD/mode/face/text commands to
the Uno protocol. Uno disconnect is allowed to degrade the face/display system
but must not affect STM32 motor safety.

## Open Questions

- Resolved: Uno returns full ACKs such as `ACK:FACE:HAPPY`. The probe still
  accepts short ACKs for backwards compatibility.
- Should Uno report firmware/protocol version with its identity?
- Resolved for current RAM Electronics LCD: use `MCUFRIEND_kbv` with
  `Adafruit_GFX` for the 480x320 ILI9486/ST7796-style 8-bit shield.

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-06-08 | Added dynamic Arduino LCD face firmware | Supports the RAM Electronics 3.5 inch TFT shield and Pluto serial protocol |
| 2026-05-26 | Initial implementation memory | Phase 2 initiated before LCD hardware arrives |
