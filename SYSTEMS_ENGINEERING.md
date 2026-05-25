# Pluto Systems Engineering Plan

Status: working plan.

This document defines how Pluto code should be implemented, validated,
verified, and debugged. The goal is to stop guessing and build the robot one
bounded subsystem at a time.

## Engineering Principle

Pluto is a distributed robot system:

- Raspberry Pi decides.
- STM32F401 protects and moves.
- Arduino Uno displays.

No board should depend on another board behaving perfectly. Every interface must
have heartbeat, timeout, identity, and observable telemetry.

## Source Of Truth

The main architecture files are:

```text
README.md
ARCHITECTURE.md
MODES.md
SYSTEMS_ENGINEERING.md
SYSTEM_REQUIREMENTS.md
```

Before implementation, each subsystem must have:

- Responsibility.
- Inputs and outputs.
- Command protocol.
- Failure behavior.
- Test method.
- Debug evidence.

Bootstrap is treated as a subsystem. Any new dependency, service, hardware
device, or operating-system assumption must include setup, detection, recovery,
and diagnostic requirements in `SYSTEM_REQUIREMENTS.md`.

## Current Architecture Summary

### Raspberry Pi

Role: high-level brain.

Owns:

- Mode manager.
- Vision and wave detection.
- Speech recognition.
- TTS.
- LLM or simple answer layer.
- Web or local control interface.
- Serial commands to STM32.
- Serial commands to Uno.

Must not:

- Directly drive hoverboard UART.
- Directly depend on Linux timing for motor safety.

### STM32F401 Black Pill

Role: motor and safety controller.

Owns:

- Hoverboard UART.
- Motor command limiting.
- Emergency stop.
- Ultrasonic obstacle safety.
- Pi heartbeat timeout.
- Hoverboard feedback parsing.
- Local stop behavior if anything is wrong.

Hard rule:

```text
If the Pi is silent, confused, late, or disconnected, STM32 stops Pluto.
```

### Arduino Uno

Role: LCD / face / simple UI controller.

Owns:

- Face expressions.
- LCD mode display.
- Simple animations.
- Status text.

Must not:

- Control motors.
- Override STM32 safety.

## Interface Control

All board-to-board communication must be text based at first. Binary protocols
can come later only when the text protocol is proven.

### Pi To STM32

Required commands:

```text
CMD:PING
CMD:STOP
CMD:DRIVE:<speed>,<steer>
CMD:LIMIT:<maxSpeed>
CMD:MODE:<mode>
```

Future commands:

```text
CMD:ARM:<steps>,<speed>
CMD:RETURN
CMD:RESET_ODOM
CMD:RESET_HOME
```

Rules:

- Pi sends `CMD:PING` at least every 500 ms.
- STM32 stops motors if no valid Pi command arrives within the timeout.
- Pi must send `CMD:STOP` before changing major modes.
- STM32 must acknowledge safety-critical commands.

### STM32 To Pi

Required messages:

```text
ID:STM32_MOTOR
ACK:<command>
TEL:BAT:<voltage>,SPD:<speed>,DIST:<distance>,TEMP:<temp>
OBS:F:<cm>,L:<cm>,R:<cm>
ALERT:<reason>
```

Rules:

- STM32 sends `ID:STM32_MOTOR` on boot.
- STM32 sends telemetry at a fixed rate.
- STM32 sends alerts for obstacle, timeout, hoverboard error, and emergency stop.
- Pi must verify the device identity before treating a serial port as motor
  control.

### Pi To Uno

Required commands:

```text
ID?
FACE:<expression>
TEXT:<message>
MODE:<mode>
WARN:<message>
```

Rules:

- Uno must identify itself as `ID:UNO_LCD`.
- Pi must never send motor commands to Uno.

## Pin Interface Control

Pin mapping must be verified against both documentation and firmware before
wiring.

Current firmware pin map in `pluto32stm/Core/Src/main.c`:

| Function | STM32 Pin |
| --- | ---: |
| Hoverboard TX from STM32 | PA9 |
| Hoverboard RX into STM32 | PA10 |
| USB CDC D- | PA11 |
| USB CDC D+ | PA12 |
| Front-left ultrasonic TRIG | PA0 |
| Front-left ultrasonic ECHO | PA1 |
| Front ultrasonic TRIG | PA4 |
| Front ultrasonic ECHO | PA5 |
| Front-right ultrasonic TRIG | PA6 |
| Front-right ultrasonic ECHO | PA7 |
| Stepper STEP | PB8 |
| Stepper DIR | PB9 |
| Stepper EN | PB10 |
| Emergency button | PB0 |
| Status LED | PC13 |

Open issue:

```text
ARCHITECTURE.md has an older ultrasonic pin draft. Before wiring, update it or
change firmware so both match exactly.
```

## Build Order

Implementation must proceed in this order.

### Phase 0 - Documentation Lock

Goal: no ambiguity.

Done when:

- Pin map is final.
- Text protocols are final enough for bench tests.
- Safety thresholds are documented.
- Test cases exist.

### Phase 1 - STM32 Bring-Up

Goal: prove the motor safety controller alone.

Tests:

- Boot LED heartbeat.
- USB CDC enumerates.
- STM32 sends `ID:STM32_MOTOR`.
- `CMD:PING` returns `ACK:PING`.
- `CMD:STOP` returns `ACK:STOP`.
- Pi timeout triggers motor stop.

Debug evidence:

```text
Serial log showing ID, ACK, TEL, OBS, ALERT.
```

### Phase 2 - Ultrasonic Safety

Goal: prove obstacle data and stop behavior.

Tests:

- Each sensor reports plausible distance.
- Missing sensor reports safe fallback or explicit fault.
- Front obstacle blocks forward motion.
- Turning in place remains possible if safe.

Debug evidence:

```text
OBS:F:<cm>,L:<cm>,R:<cm>
ALERT:OBSTACLE_FRONT
```

### Phase 3 - Hoverboard UART

Goal: prove STM32 can command and read the hoverboard.

Tests:

- UART wiring verified: PA9 to hoverboard RX, PA10 to hoverboard TX, common GND.
- Hoverboard feedback checksum passes.
- Battery voltage appears in telemetry.
- Wheels lifted: slow forward, backward, left, right.
- `CMD:STOP` stops immediately.

Debug evidence:

```text
TEL:BAT:<real_voltage>,SPD:<nonzero>,DIST:<changing>,TEMP:<real_temp>
```

### Phase 4 - Pi Serial Layer

Goal: prove Pi can reliably command STM32.

Tests:

- Pi detects `ID:STM32_MOTOR`.
- Pi sends heartbeat.
- Pi reconnects if STM32 USB is unplugged and replugged.
- Pi never connects to Uno as if it were STM32.

Debug evidence:

```text
serial_stm32 logs: connected port, ID, ACK, telemetry, reconnect events.
```

### Phase 5 - Uno LCD Layer

Goal: prove display is separate and harmless.

Tests:

- Pi detects `ID:UNO_LCD`.
- `FACE:HAPPY` changes LCD face.
- `TEXT:<message>` displays text.
- Uno disconnect does not affect STM32 safety.

### Phase 6 - Mode Manager

Goal: central Pi state machine.

Modes for v1:

```text
IDLE
WELCOME
DANCE
MANUAL
ERROR
GAME_LATER
```

Rules:

- Only one mode active at a time.
- Emergency stop can interrupt any mode.
- Return-to-base must block other modes until complete.
- Mode transitions must be logged.

### Phase 7 - Human Interaction

Goal: behavior on top of a proven base.

Order:

1. Manual.
2. Idle.
3. Welcome.
4. Dance.
5. Game later.

## Verification Matrix

| Requirement | Verification Method | Pass Evidence |
| --- | --- | --- |
| STM32 stops if Pi is silent | Disconnect Pi heartbeat | `ALERT:PI_TIMEOUT`, speed zero |
| STM32 rejects corrupt hoverboard data | Inject or observe bad checksum | `ALERT:HOVERBOARD_ERROR` |
| Obstacle prevents forward motion | Place object in front | `ALERT:OBSTACLE_FRONT`, speed zero |
| Pi identifies STM32 | Serial scan | `ID:STM32_MOTOR` |
| Pi identifies Uno | Serial scan | `ID:UNO_LCD` |
| Manual command reaches STM32 | Send `CMD:DRIVE` | `ACK:DRIVE` |
| Stop works from any state | Send `CMD:STOP` | `ACK:STOP`, motors stopped |
| Mode transition is observable | Change mode | log line + Uno `MODE:<mode>` |

## Debug Strategy

### Rule 1 - Every Layer Has A Health Check

Examples:

```text
STM32: ID:STM32_MOTOR
Uno:   ID:UNO_LCD
Pi:    mode_manager heartbeat log
```

### Rule 2 - No Silent Failure

Every failure must become one of:

```text
ALERT:<reason>
WARN:<reason>
ERROR:<reason>
```

### Rule 3 - Logs Must Answer Three Questions

For every test:

```text
What command was sent?
What device received it?
What did the device report back?
```

### Rule 4 - Bench Before Robot

Order:

```text
USB only
Ultrasonics only
Hoverboard lifted
Stepper unloaded
Robot on blocks
Robot on ground
Human interaction
```

## Definition Of Done

A feature is done only when:

- It matches the architecture.
- It has a command/interface contract.
- It has at least one test.
- It has a debug log or telemetry path.
- It fails safe.
- It is documented.

A Raspberry Pi feature is done only when bootstrap can install or validate its
dependencies and can clearly report missing hardware or failed services.
