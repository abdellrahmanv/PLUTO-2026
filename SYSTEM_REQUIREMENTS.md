# Pluto System Requirements

Status: working requirements baseline.

This document decomposes Pluto from system-level requirements into states,
state requirements, subrequirements, and verification methods.

The goal is traceability:

```text
System need -> state behavior -> subsystem requirement -> test evidence
```

## Requirement ID Rules

Use stable IDs:

```text
SYS-xxx        System-level requirement
IF-xxx         Interface requirement
SAFE-xxx       Safety requirement
STATE-x        Robot state
STATE-x.y      State requirement
STATE-x.y.z    State subrequirement
VER-x          Verification item
```

Requirement words:

- `shall` means required.
- `should` means preferred.
- `may` means optional.

Every requirement should have:

- Owner.
- Verification method.
- Pass evidence.

## System-Level Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| SYS-001 | Pluto shall use Raspberry Pi as the high-level decision maker. | Pi | Architecture review |
| SYS-002 | Pluto shall use STM32F401 as the motor and safety controller. | STM32 | Interface test |
| SYS-003 | Pluto shall use Arduino Uno only for face/LCD/UI output. | Uno | Interface test |
| SYS-004 | Pluto shall fail safe if Raspberry Pi stops sending valid heartbeat. | STM32 | Timeout test |
| SYS-005 | Pluto shall expose observable telemetry for every active subsystem. | All | Log review |
| SYS-006 | Pluto shall implement one active mode/state at a time. | Pi | Mode manager test |
| SYS-007 | Pluto shall support emergency stop from any state. | Pi + STM32 | E-stop test |
| SYS-008 | Pluto shall be testable one subsystem at a time before full integration. | All | Verification checklist |

## Safety Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| SAFE-001 | STM32 shall stop wheel commands if Pi heartbeat times out. | STM32 | Stop heartbeat |
| SAFE-002 | STM32 shall stop forward motion if obstacle is inside stop threshold. | STM32 | Obstacle test |
| SAFE-003 | STM32 shall reject corrupt hoverboard feedback packets. | STM32 | Checksum test |
| SAFE-004 | Pi shall send `CMD:STOP` before entering or leaving motion modes. | Pi | Mode transition log |
| SAFE-005 | Manual mode shall require deliberate operator input for movement. | Pi | Manual UI test |
| SAFE-006 | Motors shall first be tested with wheels lifted off the ground. | Human/test process | Test record |

## Interface Requirements

### Pi To STM32

| ID | Requirement | Verification |
| --- | --- | --- |
| IF-STM32-001 | Pi shall identify STM32 before sending movement commands. | Serial probe |
| IF-STM32-002 | Pi shall send `CMD:PING` at least every 500 ms while active. | Serial log |
| IF-STM32-003 | Pi shall send wheel movement as `CMD:DRIVE:<speed>,<steer>`. | Command log |
| IF-STM32-004 | Pi shall send `CMD:STOP` for immediate stop. | ACK + motor stop |
| IF-STM32-005 | STM32 shall reply with `ID:STM32_MOTOR` on boot or probe. | Serial log |
| IF-STM32-006 | STM32 shall reply with `ACK:<command>` for accepted commands. | Serial log |
| IF-STM32-007 | STM32 shall report telemetry with `TEL:` messages. | Serial log |
| IF-STM32-008 | STM32 shall report obstacle distance with `OBS:` messages. | Serial log |
| IF-STM32-009 | STM32 shall report faults with `ALERT:` messages. | Fault injection |

### Pi To Uno

| ID | Requirement | Verification |
| --- | --- | --- |
| IF-UNO-001 | Pi shall identify Uno before sending LCD/face commands. | Serial probe |
| IF-UNO-002 | Uno shall reply with `ID:UNO_LCD`. | Serial log |
| IF-UNO-003 | Pi shall send face changes as `FACE:<expression>`. | LCD observation |
| IF-UNO-004 | Pi shall send text as `TEXT:<message>`. | LCD observation |
| IF-UNO-005 | Uno disconnect shall not affect STM32 safety. | Disconnect test |

## System Decomposition

```text
Pluto System
├── State 1: IDLE
├── State 2: MANUAL
├── State 3: WELCOME
├── State 4: DANCE
├── State 5: ERROR
└── State 6: GAME_LATER
```

Only State 1 is decomposed in this baseline. Other states will be decomposed
before implementation.

## STATE-1: IDLE

Intent:

```text
Pluto is awake, safe, observant, and visually alive, but not moving.
```

### State Entry Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-1.1 | Pi shall enter IDLE after boot only after STM32 and Uno health checks pass or are explicitly marked unavailable. | Pi | Startup log |
| STATE-1.2 | Pi shall send `CMD:STOP` to STM32 when entering IDLE. | Pi + STM32 | `ACK:STOP` |
| STATE-1.3 | Pi shall send `MODE:IDLE` to Uno when entering IDLE. | Pi + Uno | LCD mode display |
| STATE-1.4 | Pi shall reset active motion intent to zero when entering IDLE. | Pi | Mode state log |

### Active Behavior Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-1.10 | IDLE shall keep STM32 heartbeat active. | Pi | `CMD:PING` log |
| STATE-1.11 | IDLE shall read STM32 telemetry. | Pi | `TEL:` log |
| STATE-1.12 | IDLE shall read STM32 obstacle reports. | Pi | `OBS:` log |
| STATE-1.13 | IDLE shall keep wheel command at zero. | Pi + STM32 | `CMD:STOP` or zero drive log |
| STATE-1.14 | IDLE shall keep face/LCD alive with idle expression. | Uno | LCD observation |
| STATE-1.15 | IDLE shall run only low-cost vision if enabled. | Pi | CPU/log check |
| STATE-1.16 | IDLE shall keep the control interface available if enabled. | Pi | Local connection test |

### Face And LCD Subrequirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-1.14.1 | Uno shall display an idle face in IDLE. | Uno | Visual check |
| STATE-1.14.2 | Uno may animate blinking without Pi timing dependency. | Uno | Visual check |
| STATE-1.14.3 | Uno may show a thinking/curious expression when Pi requests it. | Pi + Uno | `FACE:THINKING` test |
| STATE-1.14.4 | IDLE face behavior shall not trigger motor movement. | Pi + STM32 | Motor command log |

### Vision Subrequirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-1.15.1 | Vision Lite shall not exceed the configured low frame rate. | Pi | FPS log |
| STATE-1.15.2 | Vision Lite may feed a web/local preview. | Pi | Preview test |
| STATE-1.15.3 | Vision Lite shall not run heavy recognition or full interaction pipeline. | Pi | CPU/log check |

### Speech Subrequirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-1.20 | IDLE v1 shall not run speech recognition. | Pi | Process/log check |
| STATE-1.21 | IDLE v1 shall not run LLM calls. | Pi | Network/log check |
| STATE-1.22 | IDLE v1 shall not run TTS except explicit debug/test speech. | Pi | Audio/log check |

### Exit Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-1.30 | IDLE shall exit to MANUAL when operator selects manual control. | Pi | Mode log |
| STATE-1.31 | IDLE shall exit to WELCOME when the welcome trigger is confirmed. | Pi | Mode log |
| STATE-1.32 | IDLE shall exit to DANCE only by explicit operator/web command. | Pi | Mode log |
| STATE-1.33 | IDLE shall exit to ERROR on emergency stop or critical safety fault. | Pi + STM32 | Alert log |
| STATE-1.34 | IDLE shall not exit based on a single noisy sensor frame. | Pi | Debounce test |

### Inactive Behavior Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-1.40 | IDLE shall not send nonzero wheel movement commands. | Pi | Serial log |
| STATE-1.41 | IDLE shall not move the NEMA arm except explicit diagnostic command. | Pi + STM32 | Serial log |
| STATE-1.42 | IDLE shall not begin WELCOME approach without confirmed trigger. | Pi | Trigger log |
| STATE-1.43 | IDLE shall not start DANCE automatically in v1. | Pi | Mode log |

### Fault Behavior Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-1.50 | If STM32 disconnects in IDLE, Pi shall mark motor controller unavailable. | Pi | Disconnect test |
| STATE-1.51 | If STM32 disconnects in IDLE, Pi shall not enter motion states. | Pi | Mode transition test |
| STATE-1.52 | If Uno disconnects in IDLE, Pi shall continue STM32 heartbeat. | Pi | Disconnect test |
| STATE-1.53 | If camera fails in IDLE, Pi shall keep safety heartbeat alive and report warning. | Pi | Camera unplug test |

## STATE-1 Verification Plan

| ID | Test | Expected Evidence |
| --- | --- | --- |
| VER-IDLE-001 | Boot into IDLE with STM32 connected. | `ID:STM32_MOTOR`, `ACK:STOP`, `CMD:PING` loop |
| VER-IDLE-002 | Boot into IDLE with Uno connected. | `ID:UNO_LCD`, `MODE:IDLE`, idle face |
| VER-IDLE-003 | Leave Pluto in IDLE for 10 minutes. | No motor movement, heartbeat alive |
| VER-IDLE-004 | Disconnect STM32 USB during IDLE. | Motor unavailable warning, no motion mode allowed |
| VER-IDLE-005 | Disconnect Uno during IDLE. | Warning only, STM32 heartbeat continues |
| VER-IDLE-006 | Place obstacle in front during IDLE. | `OBS:` changes, no movement triggered |
| VER-IDLE-007 | Trigger MANUAL from IDLE. | `CMD:STOP` then mode changes to MANUAL |

## Next Required Decompositions

Before coding these modes, create the same requirement tree:

```text
STATE-2: MANUAL
STATE-3: WELCOME
STATE-4: DANCE
STATE-5: ERROR
STATE-6: GAME_LATER
```

The next implementation should be only after `STATE-2: MANUAL` is decomposed
and its verification plan is accepted.

