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

## STATE-2: MANUAL

Intent:

```text
Pluto accepts direct operator movement commands while STM32 safety remains in
full control.
```

MANUAL is the first motion state to implement because it proves the command
chain before autonomous behavior is added.

### State Entry Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-2.1 | Pi shall enter MANUAL only from IDLE or ERROR recovery. | Pi | Mode transition log |
| STATE-2.2 | Pi shall verify STM32 is available before entering MANUAL. | Pi | `ID:STM32_MOTOR` log |
| STATE-2.3 | Pi shall send `CMD:STOP` before enabling manual controls. | Pi + STM32 | `ACK:STOP` |
| STATE-2.4 | Pi shall send `MODE:MANUAL` to Uno when entering MANUAL. | Pi + Uno | LCD mode display |
| STATE-2.5 | Pi shall initialize manual speed/steer intent to zero. | Pi | Mode state log |

### Active Behavior Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-2.10 | MANUAL shall keep STM32 heartbeat active. | Pi | `CMD:PING` log |
| STATE-2.11 | MANUAL shall accept operator forward, backward, left, right, and stop inputs. | Pi | Manual input test |
| STATE-2.12 | MANUAL shall convert operator input to bounded `CMD:DRIVE:<speed>,<steer>` commands. | Pi | Command log |
| STATE-2.13 | MANUAL shall repeat active drive commands at a fixed rate while input is held. | Pi | Command timing log |
| STATE-2.14 | MANUAL shall send `CMD:STOP` immediately when input is released. | Pi | Release test |
| STATE-2.15 | MANUAL shall display active manual status on Uno. | Pi + Uno | LCD observation |
| STATE-2.16 | MANUAL shall continuously read STM32 telemetry and alerts. | Pi | `TEL:` and `ALERT:` log |

### Manual Control Subrequirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-2.12.1 | Pi shall clamp speed to configured manual maximum. | Pi | Boundary test |
| STATE-2.12.2 | Pi shall clamp steer to configured manual maximum. | Pi | Boundary test |
| STATE-2.12.3 | Pi shall support a low-speed test limit for first hoverboard validation. | Pi | Config test |
| STATE-2.12.4 | Pi shall log every nonzero drive command with timestamp. | Pi | Log review |
| STATE-2.12.5 | Pi shall not send movement commands if STM32 identity is unknown. | Pi | Serial probe test |

### Safety Behavior Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-2.20 | STM32 shall remain final authority over motion in MANUAL. | STM32 | Obstacle/timeout test |
| STATE-2.21 | If STM32 reports obstacle alert, Pi shall show warning and avoid increasing forward intent. | Pi | Obstacle test |
| STATE-2.22 | If STM32 reports timeout, Pi shall enter ERROR. | Pi | Timeout test |
| STATE-2.23 | If operator presses stop, Pi shall send `CMD:STOP` and remain in MANUAL with zero intent. | Pi | Stop button test |
| STATE-2.24 | If emergency stop occurs, Pi shall exit to ERROR. | Pi + STM32 | E-stop test |

### Exit Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-2.30 | MANUAL shall exit to IDLE when operator selects idle. | Pi | Mode log |
| STATE-2.31 | MANUAL shall exit to ERROR on critical safety fault. | Pi | Alert log |
| STATE-2.32 | MANUAL shall not exit directly to WELCOME or DANCE while nonzero motion intent exists. | Pi | Transition test |
| STATE-2.33 | MANUAL shall send `CMD:STOP` before any exit. | Pi + STM32 | `ACK:STOP` |

### Fault Behavior Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-2.40 | If STM32 disconnects in MANUAL, Pi shall stop sending drive commands and enter ERROR. | Pi | Disconnect test |
| STATE-2.41 | If Uno disconnects in MANUAL, Pi shall continue STM32 heartbeat and show log warning. | Pi | Disconnect test |
| STATE-2.42 | If operator input stream fails, Pi shall send `CMD:STOP`. | Pi | Input fault test |

## STATE-2 Verification Plan

| ID | Test | Expected Evidence |
| --- | --- | --- |
| VER-MANUAL-001 | Enter MANUAL from IDLE. | `CMD:STOP`, `MODE:MANUAL`, zero intent |
| VER-MANUAL-002 | Hold forward input with wheels lifted. | repeated `CMD:DRIVE`, `ACK:DRIVE` |
| VER-MANUAL-003 | Release forward input. | `CMD:STOP`, wheels stop |
| VER-MANUAL-004 | Command above speed limit. | clamped command in log |
| VER-MANUAL-005 | Place obstacle in front and command forward. | STM32 blocks forward motion |
| VER-MANUAL-006 | Unplug STM32 during MANUAL. | ERROR state, no further drive commands |

## STATE-3: WELCOME

Intent:

```text
Pluto responds to a confirmed human invitation, approaches safely, greets,
answers simple questions, then returns to base before accepting another mode.
```

WELCOME combines wave detection, approach, talk, and return-to-base into one
controlled interaction loop.

### Internal Substates

```text
WELCOME_DETECT
WELCOME_APPROACH
WELCOME_ARRIVED
WELCOME_TALK
WELCOME_RETURN
WELCOME_DONE
```

### State Entry Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.1 | Pi shall enter WELCOME only from IDLE. | Pi | Mode transition log |
| STATE-3.2 | Pi shall require a confirmed welcome trigger before entering WELCOME. | Pi | Trigger log |
| STATE-3.3 | Pi shall verify STM32 is available before approach. | Pi | `ID:STM32_MOTOR` log |
| STATE-3.4 | Pi shall send `MODE:WELCOME` to Uno. | Pi + Uno | LCD mode display |
| STATE-3.5 | Pi shall save current odometry/base reference before approach if return-to-base is enabled. | Pi + STM32 | `CMD:RESET_HOME` or odom log |

### Trigger Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.10 | WELCOME trigger shall be based on confirmed human intent, not a single noisy frame. | Pi | Debounce log |
| STATE-3.11 | WELCOME v1 may use operator/web trigger instead of full vision wave detection. | Pi | Manual trigger test |
| STATE-3.12 | Future wave detection shall require multiple frames above confidence threshold. | Pi | Vision test |
| STATE-3.13 | If multiple people trigger, Pi shall select one active target and keep attention locked. | Pi | Crowd test |

### Approach Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.20 | WELCOME_APPROACH shall move slowly toward the selected target. | Pi + STM32 | Command log |
| STATE-3.21 | WELCOME_APPROACH shall keep STM32 obstacle safety active. | STM32 | Obstacle test |
| STATE-3.22 | WELCOME_APPROACH shall stop if target is lost beyond timeout. | Pi | Target loss test |
| STATE-3.23 | WELCOME_APPROACH shall stop at configured greeting distance. | Pi | Distance test |
| STATE-3.24 | WELCOME_APPROACH shall not exceed configured welcome speed limit. | Pi | Command clamp log |
| STATE-3.25 | If path is blocked, Pluto shall stop and optionally request space. | Pi + STM32 | Obstacle alert log |

### Arrival And Talk Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.30 | On arrival, Pi shall send `CMD:STOP`. | Pi + STM32 | `ACK:STOP` |
| STATE-3.31 | Uno shall show happy or welcoming face on arrival. | Pi + Uno | LCD observation |
| STATE-3.32 | Pluto shall greet with a short line. | Pi | Audio/log test |
| STATE-3.33 | Pluto shall answer simple questions with fast local responses in v1. | Pi | Response latency test |
| STATE-3.34 | Pluto may use LLM fallback only if enabled and latency is acceptable. | Pi | Config test |
| STATE-3.35 | During TALK, wheel commands shall remain zero. | Pi + STM32 | Serial log |

### Return Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.40 | If person leaves or session ends, WELCOME shall enter WELCOME_RETURN. | Pi | Mode substate log |
| STATE-3.41 | During WELCOME_RETURN, Pi shall reject all other mode requests except emergency stop. | Pi | Transition test |
| STATE-3.42 | Return shall use STM32 odometry or a bounded return command. | Pi + STM32 | Return log |
| STATE-3.43 | Obstacle safety shall remain active during return. | STM32 | Obstacle test |
| STATE-3.44 | WELCOME shall exit to IDLE only after return is complete or explicitly aborted safely. | Pi | Mode log |

### Fault Behavior Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.50 | If STM32 disconnects during WELCOME, Pi shall enter ERROR. | Pi | Disconnect test |
| STATE-3.51 | If target is lost during approach, Pi shall stop and return or idle based on distance. | Pi | Vision loss test |
| STATE-3.52 | If speech fails during TALK, Pluto shall show text/face fallback and remain safe. | Pi + Uno | Speech fault test |
| STATE-3.53 | If return fails, Pi shall stop and enter ERROR. | Pi + STM32 | Return fault test |

## STATE-3 Verification Plan

| ID | Test | Expected Evidence |
| --- | --- | --- |
| VER-WELCOME-001 | Trigger WELCOME from IDLE. | `MODE:WELCOME`, substate `WELCOME_DETECT` |
| VER-WELCOME-002 | Approach with target visible. | bounded drive commands, obstacle telemetry |
| VER-WELCOME-003 | Block front path during approach. | `ALERT:OBSTACLE_FRONT`, stop behavior |
| VER-WELCOME-004 | Lose target during approach. | `CMD:STOP`, return or idle decision log |
| VER-WELCOME-005 | Arrive at greeting distance. | `CMD:STOP`, welcome face, greeting line |
| VER-WELCOME-006 | End session. | return starts, other mode requests blocked |
| VER-WELCOME-007 | Return complete. | `ACK:RETURN_COMPLETE`, state IDLE |

## STATE-4: DANCE

Intent:

```text
Pluto performs a bounded, slow, fixed-direction dance selected by the operator,
while never sacrificing obstacle safety.
```

### State Entry Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-4.1 | Pi shall enter DANCE only from IDLE. | Pi | Mode transition log |
| STATE-4.2 | DANCE shall be selected explicitly by operator/web control in v1. | Pi | Trigger test |
| STATE-4.3 | Pi shall verify STM32 and audio output before starting dance. | Pi | Health log |
| STATE-4.4 | Pi shall send `MODE:DANCE` and `FACE:DANCE` to Uno. | Pi + Uno | LCD observation |
| STATE-4.5 | Pi shall send `CMD:STOP` before beginning dance sequence. | Pi + STM32 | `ACK:STOP` |

### Active Behavior Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-4.10 | DANCE shall play a preloaded audio file. | Pi | Audio test |
| STATE-4.11 | DANCE shall use bounded motion patterns only. | Pi | Command log |
| STATE-4.12 | DANCE shall keep fixed facing direction in v1. | Pi + STM32 | Heading/observation |
| STATE-4.13 | DANCE shall use small forward/backward or sway movements only. | Pi + STM32 | Command bounds |
| STATE-4.14 | DANCE may move the NEMA arm with bounded stepper commands. | Pi + STM32 | `CMD:ARM` log |
| STATE-4.15 | DANCE shall continue STM32 heartbeat during audio playback. | Pi | Heartbeat log |

### Dance Safety Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-4.20 | DANCE shall reduce or stop motion if any obstacle is inside slow threshold. | Pi + STM32 | Obstacle test |
| STATE-4.21 | DANCE shall immediately stop wheel motion if obstacle is inside stop threshold. | STM32 | Obstacle test |
| STATE-4.22 | DANCE shall not use large translation range in v1. | Pi | Command bounds |
| STATE-4.23 | DANCE shall stop if audio system fails. | Pi | Audio fault test |
| STATE-4.24 | DANCE shall stop if STM32 reports any critical alert. | Pi | Alert test |

### Exit Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-4.30 | DANCE shall exit to IDLE when song ends. | Pi | Mode log |
| STATE-4.31 | DANCE shall exit to IDLE when operator stops dance. | Pi | Stop test |
| STATE-4.32 | DANCE shall exit to ERROR on emergency stop or critical safety fault. | Pi + STM32 | Alert log |
| STATE-4.33 | DANCE shall send `CMD:STOP` and stop audio before exit. | Pi + STM32 | Audio + serial log |

## STATE-4 Verification Plan

| ID | Test | Expected Evidence |
| --- | --- | --- |
| VER-DANCE-001 | Start DANCE from IDLE. | `MODE:DANCE`, audio starts, bounded commands |
| VER-DANCE-002 | Place obstacle during dance. | motion reduces/stops |
| VER-DANCE-003 | Stop dance manually. | audio stops, `CMD:STOP`, IDLE |
| VER-DANCE-004 | Let song finish. | `CMD:STOP`, IDLE |
| VER-DANCE-005 | Unplug STM32 during dance. | ERROR state |

## STATE-5: ERROR

Intent:

```text
Pluto is in a known safe state after a fault, with motion stopped and clear
debug information available.
```

ERROR is a state, not a crash.

### State Entry Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-5.1 | Pi shall enter ERROR on emergency stop, STM32 disconnect, critical alert, or unrecoverable mode failure. | Pi | Fault injection |
| STATE-5.2 | Pi shall send `CMD:STOP` when entering ERROR if STM32 is connected. | Pi + STM32 | `ACK:STOP` |
| STATE-5.3 | Pi shall send `MODE:ERROR` and warning text to Uno if connected. | Pi + Uno | LCD observation |
| STATE-5.4 | Pi shall record the fault reason and previous state. | Pi | Error log |
| STATE-5.5 | Pi shall reject all motion mode requests while ERROR is active. | Pi | Transition test |

### Active Behavior Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-5.10 | ERROR shall keep trying to read STM32 status if connected. | Pi | Serial log |
| STATE-5.11 | ERROR shall not send nonzero drive commands. | Pi | Serial log |
| STATE-5.12 | ERROR shall present clear operator-visible fault status. | Pi + Uno | UI/LCD observation |
| STATE-5.13 | ERROR may allow diagnostics commands that cannot move motors. | Pi | Diagnostic test |

### Recovery Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-5.20 | ERROR shall require explicit operator reset to leave ERROR. | Pi | Reset test |
| STATE-5.21 | ERROR reset shall verify STM32 identity before returning to IDLE. | Pi | Serial probe |
| STATE-5.22 | ERROR reset shall send `CMD:STOP` before returning to IDLE. | Pi + STM32 | `ACK:STOP` |
| STATE-5.23 | If fault remains active, ERROR shall refuse reset. | Pi | Fault persistence test |

## STATE-5 Verification Plan

| ID | Test | Expected Evidence |
| --- | --- | --- |
| VER-ERROR-001 | Trigger emergency stop from IDLE. | ERROR state, `CMD:STOP` |
| VER-ERROR-002 | Trigger emergency stop from MANUAL. | ERROR state, motors stopped |
| VER-ERROR-003 | Unplug STM32 during motion state. | ERROR state, motion commands stop |
| VER-ERROR-004 | Attempt DANCE while in ERROR. | rejected transition |
| VER-ERROR-005 | Reset after fault cleared. | STM32 identity verified, IDLE |

## STATE-6: GAME_LATER

Intent:

```text
GAME is reserved for future interaction. It is documented so architecture does
not accidentally grow around an undefined feature.
```

GAME_LATER is not implemented in v1.

### Placeholder Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-6.1 | GAME_LATER shall not be available as an active mode in v1. | Pi | Mode list test |
| STATE-6.2 | Any game request in v1 shall produce a polite unavailable response. | Pi + Uno | UI/LCD test |
| STATE-6.3 | GAME_LATER shall not send motor commands. | Pi | Serial log |
| STATE-6.4 | GAME_LATER requirements shall be decomposed before implementation. | Project | Review |

## STATE-6 Verification Plan

| ID | Test | Expected Evidence |
| --- | --- | --- |
| VER-GAME-001 | Request GAME in v1. | unavailable response, no mode entry |
| VER-GAME-002 | Inspect command log after game request. | no motor command |

## Cross-State Transition Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| TRANS-001 | Every state transition shall be logged with previous state, next state, reason, and timestamp. | Pi | Log review |
| TRANS-002 | Every transition into a motion state shall require STM32 available. | Pi | Transition test |
| TRANS-003 | Every transition out of a motion state shall send `CMD:STOP`. | Pi + STM32 | Serial log |
| TRANS-004 | ERROR may interrupt any state. | Pi | Fault injection |
| TRANS-005 | WELCOME_RETURN shall block all non-error transitions until complete. | Pi | Return test |
| TRANS-006 | GAME_LATER shall not be reachable in v1. | Pi | Mode list test |

## Requirement-To-Interface Trace

| State | STM32 Commands | STM32 Inputs | Uno Commands | Other Inputs |
| --- | --- | --- | --- | --- |
| IDLE | `CMD:PING`, `CMD:STOP` | `ID`, `TEL`, `OBS`, `ALERT` | `MODE:IDLE`, `FACE:IDLE` | optional low-rate camera |
| MANUAL | `CMD:PING`, `CMD:DRIVE`, `CMD:STOP` | `ACK`, `TEL`, `OBS`, `ALERT` | `MODE:MANUAL`, `WARN` | operator controls |
| WELCOME | `CMD:PING`, `CMD:DRIVE`, `CMD:STOP`, `CMD:RETURN` | `ACK`, `TEL`, `OBS`, `ALERT` | `MODE:WELCOME`, `FACE:HAPPY`, `TEXT` | vision/speech |
| DANCE | `CMD:PING`, `CMD:DRIVE`, `CMD:STOP`, optional `CMD:ARM` | `ACK`, `OBS`, `ALERT` | `MODE:DANCE`, `FACE:DANCE` | audio file, operator start |
| ERROR | `CMD:STOP`, `CMD:PING` | `ID`, `TEL`, `ALERT` | `MODE:ERROR`, `WARN` | reset request |
| GAME_LATER | none in v1 | none in v1 | `TEXT:Game later` | operator request |

## Implementation Gate

Before code for a state begins:

1. State requirements must exist in this file.
2. Interfaces used by that state must be listed in the trace table.
3. Verification tests must exist.
4. Safety behavior must be explicit.
5. Any mismatch between docs, firmware, and wiring must be resolved.

The next code implementation should start with the validation tools required to
prove `IF-STM32-*` and `IF-UNO-*`, not with high-level behavior.
