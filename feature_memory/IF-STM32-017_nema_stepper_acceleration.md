# Feature Memory: NEMA Stepper Motor Control & Acceleration

Status: draft

Last updated: 2026-06-14

Last validated: not yet validated on hardware

Owner: Antigravity

## Requirement Trace

Implemented requirements:

```text
IF-STM32-015 (NEMA Stepper Arm Motion Tracking)
IF-STM32-016 (Second NEMA Channel Tracking)
STATE-4.14   (NEMA Stepper Arm Interface)
```

Verification tests:

```text
VER-NEMA-001 (Constant-speed arm movement, forward/reverse)
VER-NEMA-002 (Trapezoidal acceleration profile, 90° in 3s)
VER-NEMA-003 (Backward compatibility — omit accel param)
```

## Design Intent

Provide full dynamic control of two independent NEMA 23 stepper motors (Arm 1
and Arm 2) from the Raspberry Pi via the STM32 serial link, including:

- Variable step count (distance/angle)
- Variable max speed
- Variable acceleration/deceleration (trapezoidal profile)

All three parameters are sent dynamically over serial so the STM32 firmware does
NOT need to be re-flashed when tuning motion profiles.

## Design Decision

**Trapezoidal velocity profile** implemented entirely inside the STM32 firmware
(`main.c`). The Raspberry Pi sends a single command with all parameters; the
STM32 internally calculates the acceleration ramp, cruise phase, and
deceleration ramp. This avoids USB latency issues that would arise from
Python-side micro-stepping control.

- When `accel == 0`, the motor runs at constant speed (backward compatible).
- When `accel > 0`, the motor uses a trapezoidal (or triangular, if too few
  steps) velocity profile.

**v2.0 Timing & Scheduling Refactoring:**
To prevent other subsystems (like blocking HC-SR04 sonar echo loops, software I2C reads, and USB transmissions) from causing jitter or stalling the motors, the execution model was upgraded from polling to a **real-time, event-driven interrupt architecture**:
- **TIM3 hardware timer interrupt** (PreemptPriority 0, highest) generates STEP pulses and computes acceleration ramps dynamically.
- **EXTI interrupts** (PA1/5/7, PreemptPriority 1) capture sonar echo rising/falling edge timestamps asynchronously using the DWT cycle counter.
- **USART1 interrupts** (PreemptPriority 2) buffer incoming hoverboard bytes into a circular ring buffer.
- **USB CDC interrupts** (PreemptPriority 3) buffer Pi command strings into a circular ring buffer, avoiding the v1.0 data race.
- The main loop acts purely as a non-blocking orchestrator.

## Interfaces

### Serial Command Protocol

| Command | Format | Example |
| --- | --- | --- |
| Arm 1 move | `CMD:ARM:<steps>,<speed>[,<accel>]` | `CMD:ARM:400,400,400` |
| Arm 2 move | `CMD:ARM2:<steps>,<speed>[,<accel>]` | `CMD:ARM2:-400,400,400` |
| Stop all   | `CMD:STOP` | `CMD:STOP` |

### Parameter Ranges

| Parameter | Type | Range | Default | Notes |
| --- | --- | --- | --- | --- |
| steps | int32 | -2,147,483,648 to +2,147,483,647 | (required) | Positive = forward, negative = reverse, 0 = immediate stop |
| speed | uint32 | 1 – 3000 sps | 200 | Firmware caps at 3000; 0 defaults to 200 |
| accel | uint32 | 0 – 3000 sps² | 0 | 0 = constant speed (no ramp); >0 = trapezoidal profile |

### ACK Protocol

| ACK | Meaning |
| --- | --- |
| `ACK:ARM` / `ACK:ARM2` | Command received, motion started |
| `ACK:ARM_DONE` / `ACK:ARM2_DONE` | All steps completed, motor disabled |

### Pi-Side API

| Function | File | Signature |
| --- | --- | --- |
| `send_arm()` | `pluto_runtime/stm32_link.py` | `send_arm(steps, speed=200, accel=0, ...)` |
| `send_arm2()` | `pluto_runtime/stm32_link.py` | `send_arm2(steps, speed=200, accel=0, ...)` |
| `manual_arm()` | `pluto_runtime/web_shell.py` | `manual_arm(arm, steps, speed, accel=0)` |

### Web UI

| Element | ID | Description |
| --- | --- | --- |
| Arm steps input | `manualArmSteps` | Number of steps (1–10000) |
| Arm speed input | `manualArmSpeed` | Max speed in sps (1–3000) |
| Accel input | `manualArmAccel` | Acceleration in sps² (0–3000) |
| Arm1 90° Test | `arm90test1` | Sends 400 steps @ 200 sps, 100 accel, then reverses |
| Arm2 90° Test | `arm90test2` | Same for Arm 2 |

## Configuration

### STM32 Firmware (`pluto32stm/Core/Src/main.c`)

| Name | Default | Allowed Range | Reason |
| --- | --- | --- | --- |
| `STEPPER_COMMON_ANODE` | 0 | 0 or 1 | 0 = Common Cathode (TB6600 PUL-/DIR- to GND) |
| `STEPPER_EN_USED` | 1 | 0 or 1 | 1 = Use ENABLE pin to silence motor at idle |
| `STEPPER_EN_ACTIVE` | `GPIO_PIN_RESET` | SET/RESET | LOW = motor enabled |
| `STEPPER_EN_IDLE` | `GPIO_PIN_SET` | SET/RESET | HIGH = motor disabled/silent |
| `STEPPER_PULSE_US` | 50 | 5–100 µs | Pulse width for STEP pin |
| Speed ceiling | 3000 sps | firmware hard limit | Prevents missed steps |
| Min ramp speed | 100 sps | firmware internal | Floor speed during accel/decel ramp |

### TB6600 Driver DIP Switch Settings (Current Setup)

| Switch | Position | Meaning |
| --- | --- | --- |
| SW1 | OFF | Microstepping select |
| SW2 | OFF | Microstepping select |
| SW3 | ON | 1/8 microstepping (1600 steps/rev) |
| SW4 | ON | Current select |
| SW5 | OFF | Current select |
| SW6 | ON | ~1.0A – 1.2A current |

### Physical Constants

| Constant | Value | Notes |
| --- | --- | --- |
| Steps per revolution | 1600 | NEMA 23 + 1/8 microstepping |
| Steps per 90° | 400 | 1600 / 4 |

## Runtime Behavior

### Constant Speed Mode (accel = 0)
1. Pi sends `CMD:ARM:5000,800`
2. STM32 replies `ACK:ARM`
3. Motor runs at exactly 800 steps/s for 5000 steps
4. STM32 sends `ACK:ARM_DONE`, disables ENABLE pin

### Trapezoidal Acceleration Mode (accel > 0)
1. Pi sends `CMD:ARM:400,200,100`
2. STM32 replies `ACK:ARM`
3. Motor starts at 100 sps and accelerates at 100 sps²
4. If enough steps, motor reaches cruise speed (200 sps), holds it
5. Motor decelerates at 100 sps² for the last N steps
6. STM32 sends `ACK:ARM_DONE`, disables ENABLE pin

### Triangle Profile
If the total steps are too few to reach max speed, the firmware automatically
switches to a triangle profile (accelerate to midpoint, then decelerate).

### Independence
Arm 1 and Arm 2 are fully independent — they can run simultaneously with
different step counts, speeds, and accelerations.

## How To Run

### Via Website (Raspberry Pi)
1. Open the PLUTO Mission Control dashboard in a browser
2. Switch to MANUAL mode
3. Set steps, speed, and acceleration values
4. Click `Arm1 +`, `Arm1 -`, `Arm2 +`, or `Arm2 -`
5. Or click `Arm1 90° Test` / `Arm2 90° Test` for the preset test

### Via Python Script (Direct USB)
```bash
python tools/test_reverse.py --steps 400 --speed 400
python tools/test_bounds.py
```

### Via Serial Terminal
```
CMD:ARM:400,400,400
CMD:ARM2:-400,400,400
```

## How To Debug

Checklist:

1. Is the STM32 USB cable connected? Check `COM8` (Windows) or `/dev/ttyACM0` (Pi).
2. Is the TB6600 driver powered? Check 12V/24V supply.
3. Are PUL-/DIR- wired to GND (common cathode)?
4. Is the ENABLE pin connected? If motor vibrates but doesn't spin, check EN wiring.
5. Check DIP switches: SW1=OFF, SW2=OFF, SW3=ON for 1/8 microstepping.
6. Open `/api/status` on the website and check `arm_done` fields.
7. Check for `ALERT:HOVERBOARD_ERROR` flooding — this is normal when the hoverboard is disconnected.

Useful commands:

```bash
# List available COM ports
python -c "import serial.tools.list_ports; [print(p) for p in serial.tools.list_ports.comports()]"

# Quick manual test
python -c "import serial,time; s=serial.Serial('COM8',115200); time.sleep(1); s.write(b'CMD:ARM:400,200,100\n'); time.sleep(4); s.close()"
```

## Expected Evidence

```text
TX: CMD:ARM:400,200,100
RX: ACK:ARM
(motor accelerates smoothly, turns 90°, decelerates smoothly — ~3 seconds)
RX: ACK:ARM_DONE
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-NEMA-001 | `test_reverse.py --steps 5000 --speed 800` | Motor moves forward 5000 steps then back 5000 steps at constant speed | PASS (2026-06-13) |
| VER-NEMA-002 | Website "Arm1 90° Test" button | Motor accelerates, turns 90°, decelerates in ~3s, then reverses | not run |
| VER-NEMA-003 | `CMD:ARM:1000,500` (no accel param) | Motor runs at constant 500 sps (backward compatible) | not run |
| VER-NEMA-004 | `test_bounds.py` | Speed capped at 3000, default speed 200, zero steps instant done | not run |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Motor vibrates but doesn't spin | Wrong signal polarity or too-high speed | Check `STEPPER_COMMON_ANODE` macro, reduce speed | Set `STEPPER_COMMON_ANODE 0` for common cathode |
| Motor is silent | ENABLE pin logic inverted | Disconnect EN wire; if motor works, flip `STEPPER_EN_ACTIVE` | Swap `GPIO_PIN_SET` / `GPIO_PIN_RESET` |
| Motor stalls mid-motion | Acceleration too aggressive or current too low | Reduce accel, increase TB6600 current DIP switches | Lower accel to 200, increase current to 2.0A |
| No ACK received | Serial port busy or STM32 not responding | Check COM port, reset STM32 | Press black RESET button on STM32 |
| Steps overshoot | Microstepping mismatch | Verify TB6600 DIP matches firmware assumption (1/8) | Re-check SW1-SW3 |

## Safety Notes

- `send_arm()` and `send_arm2()` are low-level primitives. Callers MUST enforce
  bounds before invoking.
- No physical limit switches are installed yet. Excessive steps can cause
  mechanical damage to the arm mechanism.
- Emergency stop (`CMD:STOP`) immediately halts both arms.
- The ENABLE pin is released after motion completes, removing holding torque.

## Open Questions

- Should we add limit switches or encoders for closed-loop position feedback?
- What is the maximum safe acceleration for the physical arm under load?
- Should the 90° angle be calibrated per-arm if they have different gear ratios?

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-06-13 | Initial stepper motor bring-up: common cathode, enable pin | Motor was vibrating; fixed signal polarity |
| 2026-06-14 | Added trapezoidal acceleration profile to STM32 firmware | Humanoid arm motion requires smooth start/stop |
| 2026-06-14 | Updated `stm32_link.py` with `accel` parameter | Dynamic acceleration from Pi without re-flashing |
| 2026-06-14 | Added 90° test buttons to web dashboard | Quick testing via Raspberry Pi website |
