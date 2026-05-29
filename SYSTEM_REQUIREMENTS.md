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
BOOT-xxx       Bootstrap/setup requirement
HW-xxx         Hardware detection requirement
WEB-xxx        Operator website requirement
MEM-xxx        Feature memory and design record requirement
AUD-xxx        Audio and speech requirement
ARM-xxx        Stepper arm requirement
VNV-xxx        Verification and validation coverage requirement
STATE-x        Robot state
STATE-x.y      State requirement
STATE-x.y.z    State subrequirement
STATE-xR.y     Locked return/recovery substate requirement when needed
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
| SYS-009 | Pluto shall provide an automatic Raspberry Pi setup path that installs, configures, validates, and reports the system state. | Pi | Bootstrap verification |
| SYS-010 | Pluto shall provide actionable diagnostics when automatic setup cannot recover a required subsystem. | Pi | Fault injection |
| SYS-011 | Pluto shall provide an operator website identified as project `PLUTO`. | Pi | Website test |
| SYS-012 | Pluto shall keep a feature memory record for every implemented requirement or feature. | Project | Memory record review |
| SYS-013 | Pluto shall treat audio/speech as a measurable subsystem with noise, latency, and fallback requirements. | Pi | Audio verification |
| SYS-014 | Pluto shall treat the NEMA stepper arm as a bounded actuator with explicit safety limits. | Pi + STM32 | Arm verification |

## Safety Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| SAFE-001 | STM32 shall stop wheel commands if Pi heartbeat times out. | STM32 | Stop heartbeat |
| SAFE-002 | STM32 shall stop forward motion if obstacle is inside stop threshold. | STM32 | Obstacle test |
| SAFE-003 | STM32 shall reject corrupt hoverboard feedback packets. | STM32 | Checksum test |
| SAFE-004 | Pi shall send `CMD:STOP` before entering or leaving motion modes. | Pi | Mode transition log |
| SAFE-005 | Manual mode shall require deliberate operator input for movement. | Pi | Manual UI test |
| SAFE-006 | Motors shall first be tested with wheels lifted off the ground. | Human/test process | Test record |
| SAFE-007 | STM32 shall command zero wheel speed when hoverboard battery is below critical voltage. | STM32 | Low-voltage test |
| SAFE-008 | Pi shall mark low battery as a safety warning before critical cutoff. | Pi | Battery threshold test |
| SAFE-009 | Pi shall use camera-based human/obstacle perception as a secondary safety layer in WELCOME and DANCE when vision is available. | Pi | Vision safety test |
| SAFE-010 | Vision safety shall not replace STM32 obstacle stop logic; it shall only reduce or stop Pi motion commands earlier. | Pi + STM32 | Architecture/safety review |

## Timing Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| TIME-001 | STM32 shall respond to `CMD:PING` within 100 ms when USB CDC is connected and firmware main loop is running. | STM32 | Timing test |
| TIME-002 | Pi shall send STM32 heartbeat at least every 500 ms while any non-error state is active. | Pi | Serial timing log |
| TIME-003 | STM32 shall stop wheel commands within 1000 ms if valid Pi heartbeat is absent. | STM32 | Timeout test |
| TIME-004 | STM32 shall refresh ultrasonic measurements for each installed sensor at least every 250 ms. | STM32 | OBS timing log |
| TIME-005 | Forward obstacle stop decision shall take effect within 150 ms after an obstacle enters stop threshold, excluding sensor blind spots. | STM32 | Obstacle timing test |
| TIME-006 | Pi shall process critical `ALERT:` messages within 200 ms of receipt. | Pi | Alert timing test |
| TIME-007 | Manual drive command latency from operator input to serial write shall be below 150 ms on the Raspberry Pi. | Pi | Manual latency test |
| TIME-008 | WELCOME trigger confirmation shall occur within 1500 ms after a stable wave/intent signal is detected. | Pi | Vision timing test |
| TIME-009 | Local simple question response in WELCOME_TALK should begin within 1000 ms after speech recognition result is available. | Pi | Interaction timing test |

## Power Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| PWR-001 | Logic power shall be isolated from hoverboard motor power except for required common ground reference. | Electrical | Wiring inspection |
| PWR-002 | Pi shall monitor STM32-reported hoverboard battery voltage when available. | Pi | `TEL:BAT` log |
| PWR-003 | STM32 shall treat hoverboard battery below 34.0 V as critical low voltage for the current firmware baseline. | STM32 | Firmware/config review |
| PWR-004 | On critical low voltage, STM32 shall force wheel speed and steer commands to zero. | STM32 | Low-voltage test |
| PWR-005 | Pi shall warn the operator before critical cutoff when battery warning threshold is reached. | Pi | Warning test |
| PWR-006 | Pi shall not enter WELCOME, DANCE, or MANUAL if battery status is critical. | Pi | Mode transition test |
| PWR-007 | Power thresholds shall be configurable and documented before field testing. | Project | Config review |

## Bootstrap And Self-Setup Requirements

Auto setup is a hard requirement. The Raspberry Pi side shall be able to prepare
itself for operation from a fresh clone or partially broken local environment.

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| BOOT-001 | Pi shall provide one primary setup command for installing and validating Pluto software. | Pi | Fresh install test |
| BOOT-002 | Setup shall be idempotent; running it multiple times shall not damage an already working install. | Pi | Repeat setup test |
| BOOT-003 | Setup shall detect the operating system, Python version, and required package manager availability. | Pi | Environment probe |
| BOOT-004 | Setup shall create or repair the Python virtual environment. | Pi | Venv test |
| BOOT-005 | Setup shall install or repair required Python dependencies. | Pi | Import test |
| BOOT-006 | Setup shall install or repair required Linux packages when permitted. | Pi | Package test |
| BOOT-007 | Setup shall configure the Pi user for serial device access. | Pi | Group membership test |
| BOOT-008 | Setup shall create or repair required system services only after their commands pass validation. | Pi | Service validation test |
| BOOT-009 | Setup shall not hide failures; every failed step shall report command, reason, and suggested next action. | Pi | Fault injection |
| BOOT-010 | Setup shall produce a final pass/fail report with detected hardware and missing hardware. | Pi | Report review |
| BOOT-011 | Setup shall support an offline mode that validates already-installed dependencies without requiring internet. | Pi | Offline test |
| BOOT-012 | Setup shall write logs to a predictable local path. | Pi | Log file check |
| BOOT-013 | Setup shall never enable autonomous motion as part of installation. | Pi + STM32 | Safety review |
| BOOT-014 | Setup shall send `CMD:STOP` after connecting to STM32 during validation. | Pi + STM32 | Serial log |
| BOOT-015 | Setup shall distinguish between optional and required hardware. | Pi | Hardware report |

## Hardware Detection Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| HW-001 | Pi shall scan serial ports and identify STM32 by `ID:STM32_MOTOR`, `ACK:PING`, `TEL:`, or `OBS:`. | Pi | Serial probe |
| HW-002 | Pi shall scan serial ports and identify Uno by `ID:UNO_LCD`. | Pi | Serial probe |
| HW-003 | Pi shall not assume `/dev/ttyACM0` is always STM32. | Pi | Multi-device test |
| HW-004 | Pi shall detect USB camera availability when camera features are enabled. | Pi | Camera probe |
| HW-005 | Pi shall detect audio output availability when speech/dance audio is enabled. | Pi | Audio probe |
| HW-006 | Pi shall detect microphone availability when speech recognition is enabled. | Pi | Microphone probe |
| HW-007 | Pi shall classify STM32 as required for motion states. | Pi | Hardware report |
| HW-008 | Pi shall classify Uno as required for face/LCD output but not for motor safety. | Pi | Hardware report |
| HW-009 | Pi shall classify camera, microphone, and speaker as feature-dependent hardware. | Pi | Hardware report |
| HW-010 | Pi shall continue booting into a safe reduced state if optional hardware is missing. | Pi | Missing optional test |
| HW-011 | Pi shall refuse motion states if STM32 is missing or unidentified. | Pi | Missing STM32 test |
| HW-012 | Pi shall produce a clear hardware fault reason when required hardware is missing. | Pi | Fault report |

## Self-Recovery Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| REC-001 | Pi shall retry STM32 serial detection before declaring STM32 unavailable. | Pi | Delayed plug-in test |
| REC-002 | Pi shall retry Uno serial detection before declaring Uno unavailable. | Pi | Delayed plug-in test |
| REC-003 | Pi shall restart Pluto user services if they crash. | Pi | Service crash test |
| REC-004 | Pi shall reconnect to STM32 after USB unplug/replug without reboot when possible. | Pi | Reconnect test |
| REC-005 | Pi shall keep STM32 in safe stop while recovering connections. | Pi + STM32 | Serial log |
| REC-006 | Pi shall escalate to ERROR if a required subsystem cannot recover. | Pi | Fault injection |
| REC-007 | Pi shall include last successful step and failed step in recovery logs. | Pi | Log review |

## Operator Website Requirements

The website is Pluto's operator console. It observes the system, requests state
transitions, and exposes diagnostics. It shall not bypass the mode manager or
STM32 safety layer.

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| WEB-001 | Website shall clearly identify the project as `PLUTO`. | Pi | UI inspection |
| WEB-002 | Website shall show live camera feed when camera hardware is available. | Pi | Camera UI test |
| WEB-003 | Website shall show camera unavailable status when camera feed cannot start. | Pi | Camera unplug test |
| WEB-004 | Website shall show current system state. | Pi | State UI test |
| WEB-005 | Website shall show current substate when a state has substates. | Pi | WELCOME substate test |
| WEB-006 | Website shall show allowed next states based on current state and safety gates. | Pi | Transition UI test |
| WEB-007 | Website shall allow operator to request a next state, not directly force internal state variables. | Pi | Mode manager test |
| WEB-008 | Website shall block unavailable or unsafe state choices. | Pi | Safety gate test |
| WEB-009 | Website shall show STM32 connection status. | Pi | Serial disconnect test |
| WEB-010 | Website shall show Uno connection status. | Pi | Serial disconnect test |
| WEB-011 | Website shall show battery voltage/status when available. | Pi | Telemetry UI test |
| WEB-012 | Website shall show obstacle readings/status when available. | Pi | Telemetry UI test |
| WEB-013 | Website shall show current fault/warning reason when any subsystem reports one. | Pi | Fault injection |
| WEB-014 | Website shall provide an emergency stop control visible from every page/view. | Pi | UI inspection |
| WEB-015 | Emergency stop from website shall send `CMD:STOP` and request ERROR or safe stop state. | Pi + STM32 | E-stop UI test |
| WEB-016 | Website shall provide controlled system shutdown command. | Pi | Shutdown test |
| WEB-017 | Shutdown command shall require confirmation before execution. | Pi | UI test |
| WEB-018 | Shutdown command shall send `CMD:STOP` before shutting down Pi. | Pi + STM32 | Serial log |
| WEB-019 | Website shall show bootstrap/self-test report. | Pi | Report UI test |
| WEB-020 | Website shall show clear instructions for missing required hardware. | Pi | Missing hardware test |
| WEB-021 | Website shall expose logs or latest events needed for debugging. | Pi | Log UI test |
| WEB-022 | Website shall not expose raw motor commands outside MANUAL or diagnostic mode. | Pi | Route/API test |
| WEB-023 | Website shall remain responsive enough for operator use while camera preview is active. | Pi | UI latency test |
| WEB-024 | Website shall be usable from phone or laptop screen sizes. | Pi | Responsive UI test |
| WEB-025 | Website shall present state names using the same names as requirements: BOOTSTRAP, IDLE, MANUAL, WELCOME, DANCE, ERROR, GAME_LATER. | Pi | UI inspection |

### Website Timing Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| WEB-TIME-001 | Website shall update displayed current state within 500 ms of mode manager state change. | Pi | UI timing test |
| WEB-TIME-002 | Website shall update STM32 connection status within 1000 ms of connect/disconnect detection. | Pi | Disconnect timing test |
| WEB-TIME-003 | Camera preview should display at least 1 FPS in IDLE when enabled. | Pi | FPS test |
| WEB-TIME-004 | Emergency stop button action shall send stop request within 150 ms of operator activation. | Pi | E-stop latency test |

### Website Safety Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| WEB-SAFE-001 | Website shall never be the only safety layer for motor stop. | Pi + STM32 | Architecture review |
| WEB-SAFE-002 | Website shall not allow MANUAL, WELCOME, or DANCE if STM32 is unavailable. | Pi | Safety gate test |
| WEB-SAFE-003 | Website shall not allow MANUAL, WELCOME, or DANCE if battery status is critical. | Pi | Battery gate test |
| WEB-SAFE-004 | Website shall not allow new mode selection during WELCOME_RETURN except emergency stop. | Pi | Return gate test |

## Audio And Speech Requirements

Audio and speech are environmental subsystems. They must be validated against
robot noise, motor vibration, speaker feedback, and room noise.

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| AUD-001 | Pi shall detect microphone availability before enabling speech states. | Pi | Microphone probe |
| AUD-002 | Pi shall detect speaker/audio output availability before enabling speech or DANCE audio. | Pi | Audio probe |
| AUD-003 | Speech features shall have a configurable minimum microphone signal quality threshold. | Pi | Audio quality test |
| AUD-004 | Speech features shall report low confidence or low signal quality instead of guessing. | Pi | Noisy-room test |
| AUD-005 | Speech features shall tolerate hoverboard/arm motor noise by pausing motion, filtering audio, or falling back to text/simple prompt. | Pi | Motor-noise test |
| AUD-006 | Pluto shall not start WELCOME_TALK if microphone is unavailable unless a text/manual fallback is enabled. | Pi | Missing mic test |
| AUD-007 | Pluto shall not start DANCE audio if speaker is unavailable; DANCE shall be blocked or run silent only if explicitly allowed. | Pi | Missing speaker test |
| AUD-008 | TTS/speaker volume shall be configurable. | Pi | Config review |
| AUD-009 | TTS/speaker output should be understandable at the expected interaction distance. | Pi | Listening test |
| AUD-010 | Speech recognition shall log confidence, recognized text, and selected response path. | Pi | Speech log review |
| AUD-011 | If microphone captures robot motor noise above configured threshold, Pi shall reduce motion, pause listening, or warn operator. | Pi | Motor-noise test |
| AUD-012 | Audio failure shall not affect STM32 heartbeat or motor safety. | Pi + STM32 | Audio fault test |
| AUD-013 | WELCOME_TALK v1 shall limit recognized text passed to the answer layer to 9 words maximum. | Pi | Word-limit test |
| AUD-014 | WELCOME_TALK v1 shall limit spoken/generated answers to 9 words maximum. | Pi | Response bank test |
| AUD-015 | WELCOME_TALK v1 shall use deterministic local keyword/intent matching before any LLM path. | Pi | Response source log |
| AUD-016 | Ollama/LLM fallback shall be disabled by default until measured latency is acceptable. | Pi | Config and latency test |
| AUD-017 | If LLM fallback is enabled, Pi shall enforce timeout, input word limit, output word limit, and fallback behavior. | Pi | LLM fault test |
| AUD-018 | If recognized speech exceeds the configured word limit, Pluto shall ask for a shorter question instead of sending it to LLM. | Pi | Long utterance test |
| AUD-019 | WELCOME_TALK v1 shall be fully offline and shall not depend on API keys or cloud speech services. | Pi | Offline run test |
| AUD-020 | WELCOME_TALK v1.5 may add local Ollama/Qwen fallback only after benchmark evidence is recorded. | Pi | Benchmark review |
| AUD-021 | WELCOME_TALK v1.5 shall keep keyword/intent matching as the first response path even if Ollama is enabled. | Pi | Response source log |
| AUD-022 | Pi shall prefer the webcam/camera microphone when it is detected as an ALSA capture device. | Pi | Audio probe |
| AUD-023 | Website shall expose audio status, selected microphone, selected speaker, and STT/TTS backend. | Pi | UI/API test |
| AUD-024 | Website and tools shall allow selecting a preferred microphone device for headset-microphone testing. | Pi | Headset mic test |

## Stepper Arm Requirements

The NEMA/stepper arm is an actuator. It must be bounded, observable, and safe.

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| ARM-001 | Stepper arm commands shall use bounded `CMD:ARM:<steps>,<speed>` values. | Pi + STM32 | Command bounds test |
| ARM-002 | Pi shall not send arm commands until STM32 identity is verified. | Pi | Serial probe test |
| ARM-003 | Arm step count limits shall be configurable before hardware tests. | Pi | Config review |
| ARM-004 | Arm speed limits shall be configurable before hardware tests. | Pi | Config review |
| ARM-005 | Arm movement shall be disabled by default during BOOTSTRAP and IDLE. | Pi + STM32 | State log |
| ARM-006 | Arm movement in WELCOME shall be slow and gesture-like only. | Pi + STM32 | Command log |
| ARM-007 | Arm movement in DANCE shall stay within a configured safe range. | Pi + STM32 | Command bounds test |
| ARM-008 | Arm movement shall stop on emergency stop, STM32 timeout, or critical alert. | STM32 | Fault test |
| ARM-009 | If physical limit switches are not installed, software limits shall be conservative and documented. | Project | Design review |
| ARM-010 | If physical limit switches are installed later, STM32 shall treat them as safety inputs. | STM32 | Limit switch test |
| ARM-011 | Pi shall not command arm movement while WELCOME_RETURN is active unless explicitly required for safe posture. | Pi | Return test |
| ARM-012 | Arm failures shall not block wheel stop commands. | STM32 | Fault injection |

## Feature Memory Requirements

Every implemented feature shall leave behind a design and debug memory record.
This is required so Pluto can be restarted, transferred, audited, or debugged at
the deepest implementation point without depending on one person's memory.

Feature memory files live under:

```text
feature_memory/
```

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| MEM-001 | Every new implemented feature shall have a feature memory file before it is considered done. | Project | Memory record review |
| MEM-002 | Every feature memory file shall list the requirement IDs it implements. | Project | Trace review |
| MEM-003 | Every feature memory file shall describe the design intent and why that design was chosen. | Project | Design review |
| MEM-004 | Every feature memory file shall describe interfaces used by the feature. | Project | Interface review |
| MEM-005 | Every feature memory file shall describe how to run or exercise the feature. | Project | Runbook review |
| MEM-006 | Every feature memory file shall describe how to debug the feature when it fails. | Project | Debug review |
| MEM-007 | Every feature memory file shall list expected logs, telemetry, or observable evidence. | Project | Evidence review |
| MEM-008 | Every feature memory file shall list known failure modes and likely root causes. | Project | Fault review |
| MEM-009 | Every feature memory file shall list safety assumptions and fail-safe behavior. | Project | Safety review |
| MEM-010 | Every feature memory file shall list verification tests linked to `VER-*` IDs. | Project | Verification review |
| MEM-011 | Every code change implementing a requirement shall update an existing memory file or create a new one. | Project | Pull request/review |
| MEM-012 | Memory files shall be written in plain Markdown and kept in the repository. | Project | Repo review |
| MEM-013 | Memory files shall include a "Last validated" field when hardware tests are performed. | Project | Test record review |
| MEM-014 | Memory files shall include unresolved questions or open risks when the design is incomplete. | Project | Risk review |

### Feature Memory Record Format

Every feature memory file shall use this structure:

```text
# Feature Memory: <Feature Name>

Status:
Last updated:
Last validated:
Owner:

## Requirement Trace
## Design Intent
## Design Decision
## Interfaces
## Runtime Behavior
## Configuration
## How To Run
## How To Debug
## Expected Evidence
## Verification Tests
## Failure Modes
## Safety Notes
## Open Questions
## Change History
```

Required fields:

| Field | Requirement |
| --- | --- |
| Status | `draft`, `implemented`, `validated`, or `deprecated` |
| Last updated | date of latest design/code update |
| Last validated | date and hardware context of latest validation, or `not yet validated on hardware` |
| Owner | person/team responsible for maintaining the feature |
| Requirement Trace | exact `SYS`, `SAFE`, `IF`, `STATE`, `WEB`, `BOOT`, `HW`, `AUD`, `ARM`, or `MEM` IDs |
| Design Decision | chosen approach and rejected alternatives |
| Interfaces | commands, messages, files, hardware, services, APIs, and dependencies |
| How To Debug | ordered debug checklist and useful commands |
| Expected Evidence | logs, telemetry, UI state, or hardware behavior proving success |
| Verification Tests | linked `VER-*` tests and pass/fail evidence |
| Failure Modes | failure, likely cause, diagnostic, and recovery |
| Safety Notes | how the feature fails safe |
| Change History | dated list of design/code changes |

## Verification Coverage Requirements

Requirements must stay testable. Growth without verification is not acceptable.

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| VNV-001 | Every `shall` requirement shall have a verification method. | Project | Requirements review |
| VNV-002 | Every implemented requirement shall be linked to at least one verification test, review, inspection, or analysis method. | Project | Trace review |
| VNV-003 | Every safety requirement shall have an executable or inspectable verification path before field testing. | Project | Safety review |
| VNV-004 | Every state shall have a verification plan before implementation. | Project | State review |
| VNV-005 | Every requirement category added to this document shall have a trace section or explicit verification strategy. | Project | Requirements review |
| VNV-006 | Verification results from hardware tests shall be recorded in feature memory. | Project | Memory review |
| VNV-007 | Requirements that cannot yet be verified shall be marked as open risk in the related feature memory. | Project | Risk review |

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
| IF-STM32-010 | STM32 shall respond to `CMD:PING` within 100 ms. | Timing test |
| IF-STM32-011 | STM32 telemetry shall include battery voltage when hoverboard feedback is valid. | Telemetry test |
| IF-STM32-012 | STM32 shall include enough alert reason text for Pi to choose IDLE, ERROR, or continue. | Fault injection |

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
├── State 0: BOOTSTRAP
├── State 1: IDLE
├── State 2: MANUAL
├── State 3: WELCOME
├── State 4: DANCE
├── State 5: ERROR
└── State 6: GAME_LATER
```

BOOTSTRAP is the required setup and self-test state before normal operation.

## STATE-0: BOOTSTRAP

Intent:

```text
Pluto prepares and validates the Raspberry Pi runtime, detects required
hardware, repairs what it can, and reports exactly what is wrong if it cannot
continue.
```

BOOTSTRAP is not a user-facing personality mode. It is the engineering state
that makes the rest of the robot reliable.

### State Entry Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-0.1 | BOOTSTRAP shall run on first setup and may run at every Pi boot. | Pi | Boot log |
| STATE-0.2 | BOOTSTRAP shall start with all motion intent set to zero. | Pi | State log |
| STATE-0.3 | BOOTSTRAP shall not enter motion states directly. | Pi | Transition test |
| STATE-0.4 | BOOTSTRAP shall record start time, software version, and git commit when available. | Pi | Bootstrap report |

### Setup Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-0.10 | BOOTSTRAP shall verify Python runtime and virtual environment. | Pi | Environment report |
| STATE-0.11 | BOOTSTRAP shall install or repair dependencies when internet/package access is available. | Pi | Dependency test |
| STATE-0.12 | BOOTSTRAP shall skip destructive reinstall if the environment is already valid. | Pi | Repeat setup test |
| STATE-0.13 | BOOTSTRAP shall configure serial permissions for the active Pi user. | Pi | Group membership test |
| STATE-0.14 | BOOTSTRAP shall validate service definitions before enabling them. | Pi | Service validation |
| STATE-0.15 | BOOTSTRAP shall support a diagnostic-only mode that changes nothing. | Pi | Dry-run test |

### Hardware Detection Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-0.20 | BOOTSTRAP shall probe serial ports for STM32 identity. | Pi | `ID:STM32_MOTOR` log |
| STATE-0.21 | BOOTSTRAP shall probe serial ports for Uno identity. | Pi | `ID:UNO_LCD` log |
| STATE-0.22 | BOOTSTRAP shall probe camera if any enabled state depends on vision. | Pi | Camera probe |
| STATE-0.23 | BOOTSTRAP shall probe speaker if any enabled state depends on audio output. | Pi | Audio probe |
| STATE-0.24 | BOOTSTRAP shall probe microphone if any enabled state depends on speech input. | Pi | Microphone probe |
| STATE-0.25 | BOOTSTRAP shall classify hardware as required, optional, or unavailable. | Pi | Hardware report |

### Self-Repair Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-0.30 | BOOTSTRAP shall retry transient failures before marking hardware unavailable. | Pi | Retry log |
| STATE-0.31 | BOOTSTRAP shall attempt to repair missing Python dependencies. | Pi | Dependency repair test |
| STATE-0.32 | BOOTSTRAP shall attempt to restart failed Pluto services. | Pi | Service crash test |
| STATE-0.33 | BOOTSTRAP shall attempt to reconnect serial devices after delayed enumeration. | Pi | Delayed USB test |
| STATE-0.34 | BOOTSTRAP shall not attempt repair actions that can move motors. | Pi + STM32 | Safety review |

### Safety Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-0.40 | If STM32 is detected, BOOTSTRAP shall send `CMD:STOP`. | Pi + STM32 | `ACK:STOP` |
| STATE-0.41 | BOOTSTRAP shall refuse MANUAL, WELCOME, or DANCE if STM32 is missing. | Pi | Transition test |
| STATE-0.42 | BOOTSTRAP shall refuse motion states if battery status is critical. | Pi | Battery test |
| STATE-0.43 | BOOTSTRAP shall enter ERROR if required hardware cannot be validated. | Pi | Fault test |
| STATE-0.44 | BOOTSTRAP may enter IDLE with reduced capability if only optional hardware is missing. | Pi | Optional missing test |

### Reporting Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-0.50 | BOOTSTRAP shall produce a human-readable report. | Pi | Report review |
| STATE-0.51 | Report shall include pass/fail for STM32, Uno, camera, microphone, speaker, Python dependencies, and services. | Pi | Report review |
| STATE-0.52 | Report shall include exact failed command or probe when a check fails. | Pi | Fault injection |
| STATE-0.53 | Report shall include suggested next action for each failed required check. | Pi | Fault injection |
| STATE-0.54 | Report shall be available in logs and through the operator interface when available. | Pi | Log/UI test |
| STATE-0.55 | BOOTSTRAP shall validate website dependencies if website feature is enabled. | Pi | Website bootstrap test |

### Exit Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-0.60 | BOOTSTRAP shall exit to IDLE when required checks pass. | Pi | Boot flow test |
| STATE-0.61 | BOOTSTRAP shall exit to ERROR when required checks fail after recovery attempts. | Pi | Fault flow test |
| STATE-0.62 | BOOTSTRAP shall not exit to MANUAL, WELCOME, or DANCE directly. | Pi | Transition test |

## STATE-0 Verification Plan

| ID | Test | Expected Evidence |
| --- | --- | --- |
| VER-BOOT-001 | Run setup on fresh Pi clone. | dependencies installed, report PASS/FAIL |
| VER-BOOT-002 | Run setup twice. | second run succeeds without damaging install |
| VER-BOOT-003 | Boot with STM32 connected. | STM32 identified, `CMD:STOP`, IDLE allowed |
| VER-BOOT-004 | Boot without STM32. | clear missing STM32 fault, motion states blocked |
| VER-BOOT-005 | Boot without Uno. | reduced capability or warning, STM32 heartbeat still possible |
| VER-BOOT-006 | Boot without camera. | vision features disabled or warning reported |
| VER-BOOT-007 | Break a service definition. | setup reports service validation failure |
| VER-BOOT-008 | Remove Python dependency. | setup repairs dependency or reports package failure |
| VER-BOOT-009 | Run diagnostic-only mode. | no changes made, full report produced |
| VER-BOOT-010 | Enable website feature during bootstrap. | website dependencies valid, report includes website |

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
| STATE-1.17 | IDLE website view shall show camera preview if enabled and available. | Pi | Website camera test |
| STATE-1.18 | IDLE website view shall show current state as `IDLE` and allowed next states. | Pi | Website state test |

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
| VER-IDLE-008 | Measure STM32 ping response time in IDLE. | `ACK:PING` within 100 ms |
| VER-IDLE-009 | Open website in IDLE. | project `PLUTO`, camera preview/status, current state, next states |

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
| STATE-2.17 | MANUAL website view shall show manual controls only while MANUAL is active. | Pi | Website mode test |

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
| VER-MANUAL-007 | Measure operator input to serial command latency. | command written within 150 ms |
| VER-MANUAL-008 | Open website in MANUAL. | manual controls visible, current state MANUAL |

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
| STATE-3.12.1 | Wave detection shall not directly command wheels or arm movement. | Pi | Command log |
| STATE-3.12.2 | Wave detection shall only request WELCOME entry through the mode manager. | Pi | Mode log |
| STATE-3.12.3 | Wave detection v1 shall require repeated side-to-side upper-body/hand-region motion before confirming intent. | Pi | Vision debug log |
| STATE-3.12.4 | Wave detection shall use a confirmation window and cooldown to prevent rapid repeat triggers. | Pi | Trigger debounce test |
| STATE-3.12.5 | Wave detection shall expose debug evidence: target ID, side, score, confidence, and confirmation reason. | Pi | Debug log review |
| STATE-3.12.6 | If pose or wave dependencies are unavailable, WELCOME shall fall back to operator/web trigger. | Pi | Missing dependency test |
| STATE-3.12.7 | Wave detection shall be implemented inside `WELCOME_DETECT`, not as a separate robot mode. | Pi | Mode/substate log |
| STATE-3.12.8 | WELCOME wave v1 shall use lightweight existing camera detections before adding heavy pose dependencies. | Pi | Wave smoke test |
| STATE-3.12.9 | WELCOME wave v1 shall expose pixel-motion evidence from the upper human crop so real hand waves can be tuned without loading a pose model. | Pi | Wave debug log |
| STATE-3.12.10 | WELCOME wave v1 shall reuse the desktop prototype's rule gates where practical: raised hand region, horizontal amplitude, x direction changes, horizontal-dominates-vertical ratio, confirmation streak, and cooldown. | Pi | Wave smoke test |
| STATE-3.12.11 | WELCOME wave v1 shall use optical flow on a small upper-human crop to estimate hand motion under Raspberry Pi resource limits. | Pi | Wave debug log |
| STATE-3.12.12 | WELCOME wave v1 shall maintain lightweight track IDs for multiple visible people and evaluate wave evidence per track. | Pi | Multi-person wave smoke test |
| STATE-3.12.13 | After a person waves, WELCOME wave v1 shall visually lock only that track with a red box and suppress other person boxes while the lock is active. | Pi | Camera overlay review |
| STATE-3.12.14 | The website wave test control shall arm a real wave wait window; it shall not force WELCOME or red lock without confirmed wave evidence. | Pi | Website arm-wave test |
| STATE-3.12.15 | WELCOME wave v1 shall not lock or enter WELCOME from broad person-box movement or generic optical-flow movement alone. | Pi | False-positive smoke test |
| STATE-3.12.16 | WELCOME wave v1 shall prefer quantized pose keypoints for wrist/shoulder evidence when the pose model and LiteRT runtime are available. | Pi | Pose wave smoke test |
| STATE-3.12.17 | WELCOME wave v1 shall treat optical-flow motion as debug evidence only unless explicitly enabled by a future requirement. | Pi | False-positive smoke test |
| STATE-3.12.18 | WELCOME wave v1 shall prevent duplicate website polling from reusing the same camera frame as new wave history. | Pi | Duplicate-frame test |
| STATE-3.12.19 | WELCOME wave v1 shall expose pose backend status and pose inference latency in website/camera status. | Pi | Website pose status test |
| STATE-3.12.20 | WELCOME wave v1 shall sample pose-wave evidence continuously in the runtime background, not only when the website refreshes. | Pi | Live wave timing test |
| STATE-3.12.21 | WELCOME wave v1 shall expose its active arm-motion thresholds in the website status for field tuning. | Pi | Website threshold review |
| STATE-3.12.22 | After WELCOME wave lock, the red target box shall stay spatially anchored to the confirmed waver if lightweight track IDs temporarily swap. | Pi | Two-person lock smoke test |
| STATE-3.12.23 | If the locked waver leaves the camera scene, the red wave lock shall clear instead of transferring to another visible person. | Pi | Waver-exit smoke test |
| STATE-3.12.24 | In low-light vision quality, WELCOME wave shall report degraded vision and avoid confirming new wave targets. | Pi | Low-light gate test |
| STATE-3.13 | If multiple people trigger, Pi shall select one active target and keep attention locked. | Pi | Crowd test |
| STATE-3.14 | Pi shall ignore additional welcome triggers while WELCOME is already active. | Pi | Crowd/transition test |
| STATE-3.15 | Pi shall record selected target ID or target source for debugging. | Pi | Trigger log |

### Crowd Handling Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.16 | In a multi-person scene, Pi shall select exactly one active welcome target. | Pi | Crowd test |
| STATE-3.17 | Target selection should prefer confirmed direct interaction over closest person. | Pi | Scenario test |
| STATE-3.18 | Target selection should prefer closest confirmed waver when multiple people wave. | Pi | Scenario test |
| STATE-3.19 | Once selected, the active target shall remain locked for at least 10 seconds unless lost or emergency stop occurs. | Pi | Attention lock test |
| STATE-3.19.1 | Pluto may acknowledge crowd presence through face/text without changing active target. | Pi + Uno | Crowd UI test |
| STATE-3.19.2 | Pi shall estimate crowd size when vision is available. | Pi | Crowd perception test |
| STATE-3.19.3 | Pi shall distinguish active target from background people when confidence allows. | Pi | Crowd perception test |
| STATE-3.19.4 | Pi shall record target selection score inputs for debugging. | Pi | Debug log review |
| STATE-3.19.5 | Pi shall not switch target only because another person briefly appears closer. | Pi | Attention stability test |
| STATE-3.19.6 | Crowd energy may influence face/text/dance intensity, but shall not bypass safety gates. | Pi + Uno | Crowd energy test |
| STATE-3.19.7 | If crowd perception is unavailable, WELCOME shall fall back to operator-triggered or single-target behavior. | Pi | Missing vision test |

### Approach Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.20 | WELCOME_APPROACH shall move slowly toward the selected target. | Pi + STM32 | Command log |
| STATE-3.21 | WELCOME_APPROACH shall keep STM32 obstacle safety active. | STM32 | Obstacle test |
| STATE-3.22 | WELCOME_APPROACH shall stop if target is lost beyond timeout. | Pi | Target loss test |
| STATE-3.23 | WELCOME_APPROACH shall stop at configured greeting distance. | Pi | Distance test |
| STATE-3.24 | WELCOME_APPROACH shall not exceed configured welcome speed limit. | Pi | Command clamp log |
| STATE-3.25 | If path is blocked, Pluto shall stop and optionally request space. | Pi + STM32 | Obstacle alert log |
| STATE-3.26 | WELCOME_APPROACH maximum speed shall be configured before testing and shall start at a low validation value. | Pi | Config review |
| STATE-3.27 | WELCOME_APPROACH shall stop no closer than 80 cm from the selected person in v1. | Pi | Distance test |
| STATE-3.28 | If the selected person moves during approach, Pi shall update target direction only if the target remains confidently tracked. | Pi | Moving target test |
| STATE-3.29 | If the selected person moves closer than greeting distance, Pi shall stop and transition to WELCOME_ARRIVED. | Pi | Moving target test |
| STATE-3.29.1 | If target tracking is uncertain, Pi shall command `CMD:STOP` before recalculating approach. | Pi + STM32 | Target uncertainty test |
| STATE-3.29.2 | WELCOME_APPROACH shall not command reverse motion unless explicitly required by avoidance or abort behavior. | Pi | Command log |
| STATE-3.29.3 | WELCOME_APPROACH shall use optimized vision perception when available to slow or stop before reaching humans or obstacles. | Pi | Vision safety test |
| STATE-3.29.4 | WELCOME vision safety should use threaded capture, low resolution, frame skipping, detection hold, and tracked boxes to keep latency bounded. | Pi | CPU/FPS log |
| STATE-3.29.5 | If vision and ultrasonic obstacle estimates disagree, Pi shall choose the safer slower command until confidence recovers. | Pi + STM32 | Sensor disagreement test |
| STATE-3.29.6 | Phase 10 WELCOME_APPROACH shall run in dry-run mode until target, obstacle, STOP guard, and proposed-motion evidence are reviewed. | Pi | Dry-run smoke test |
| STATE-3.29.7 | Phase 10 WELCOME_APPROACH shall not send `CMD:DRIVE`; it may only send `CMD:STOP` as a guard while computing proposed motion. | Pi + STM32 | Serial command log |
| STATE-3.29.8 | WELCOME_APPROACH dry-run shall use the locked wave target ID and shall not retarget to another person without a new confirmed wave. | Pi | Two-person dry-run test |
| STATE-3.29.9 | WELCOME_APPROACH dry-run shall expose target ID, distance class, steering intent, obstacle status, proposed motion, and reason on the website. | Pi | Website status review |
| STATE-3.29.10 | WELCOME_APPROACH dry-run shall propose STOP when the target is missing, vision is degraded, greeting distance is reached, or obstacle telemetry blocks the path. | Pi | Planner smoke test |
| STATE-3.29.11 | WELCOME_APPROACH dry-run shall keep a STOP guard active while WELCOME_APPROACH is evaluated. | Pi + STM32 | STOP guard log |
| STATE-3.29.12 | WELCOME_APPROACH shall not classify greeting distance from a person box clipped by the top or bottom of the camera frame. | Pi | Clipped-box smoke test |
| STATE-3.29.13 | WELCOME_APPROACH shall expose box clipping evidence so distance-estimation errors can be debugged. | Pi | Website/status review |

### Arrival And Talk Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.30 | On arrival, Pi shall send `CMD:STOP`. | Pi + STM32 | `ACK:STOP` |
| STATE-3.31 | Uno shall show happy or welcoming face on arrival. | Pi + Uno | LCD observation |
| STATE-3.32 | Pluto shall greet with a short line. | Pi | Audio/log test |
| STATE-3.33 | Pluto shall answer simple questions with fast local responses in v1. | Pi | Response latency test |
| STATE-3.34 | Pluto may use LLM fallback only if enabled and latency is acceptable. | Pi | Config test |
| STATE-3.35 | During TALK, wheel commands shall remain zero. | Pi + STM32 | Serial log |
| STATE-3.36 | WELCOME_TALK shall verify audio input/output availability or use configured fallback. | Pi | Audio probe |
| STATE-3.37 | WELCOME_TALK shall log recognized text, confidence, response source, and response latency. | Pi | Speech log review |
| STATE-3.38 | WELCOME gestures using the arm shall remain within WELCOME arm limits. | Pi + STM32 | Arm command log |

### Simple Talk Subrequirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.33.1 | WELCOME_TALK v1 shall treat keyword/intent matching as the primary answer engine. | Pi | Response source log |
| STATE-3.33.2 | WELCOME_TALK v1 shall reject or safely handle questions longer than 9 recognized words. | Pi | Word-limit test |
| STATE-3.33.3 | WELCOME_TALK v1 shall keep each spoken answer at or below 9 words unless explicitly configured otherwise. | Pi | Response bank test |
| STATE-3.33.4 | WELCOME_TALK shall use a local fallback answer when no keyword/intent match is found. | Pi | Unknown question test |
| STATE-3.33.5 | WELCOME_TALK shall not call Ollama/LLM unless enabled by configuration and bounded by timeout. | Pi | LLM config test |
| STATE-3.33.6 | WELCOME_TALK v1 shall use only local/offline components for recognition, answer selection, and output. | Pi | Offline run test |
| STATE-3.33.7 | WELCOME_TALK v1.5 shall treat Ollama/Qwen as a fallback path, not as the primary conversation engine. | Pi | Response source log |
| STATE-3.33.8 | WELCOME_TALK v1.5 shall have a benchmark gate before it can be enabled on the robot. | Project + Pi | Benchmark review |
| STATE-3.33.9 | WELCOME_TALK v1 shall include a broad keyword bank before any LLM fallback is enabled. | Pi | Response bank test |
| STATE-3.33.10 | Website WELCOME_TALK shall support text ask, ask-and-speak, and camera-mic listen controls. | Pi | UI/API test |
| STATE-3.33.11 | WELCOME_TALK v1 shall answer configured demo identity facts exactly, including location, builders, and simple weather. | Pi | Response bank test |
| STATE-3.33.12 | WELCOME_TALK v1 shall include an offline MSA University knowledge bank sourced from official university pages. | Pi | MSA response bank test |

### WELCOME_TALK Version Roadmap

| Version | Scope | Allowed Engines | Not Allowed | Exit Criteria |
| --- | --- | --- | --- | --- |
| v1 | Small latency, good-enough welcome talk | offline STT, keyword/fuzzy intent, canned responses, cached/local TTS or text fallback | cloud APIs, API keys, primary LLM response path | short question answered locally within target latency |
| v1.5 | Better awareness without losing speed | all v1 engines plus optional local Ollama/Qwen fallback | unbounded LLM prompts, long answers, LLM-only mode | benchmark proves fallback is bounded and safe |

### Return Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.40 | If person leaves or session ends, WELCOME shall enter WELCOME_RETURN. | Pi | Mode substate log |
| STATE-3.41 | During WELCOME_RETURN, Pi shall reject all other mode requests except emergency stop. | Pi | Transition test |
| STATE-3.42 | Return shall use STM32 odometry or a bounded return command. | Pi + STM32 | Return log |
| STATE-3.43 | Obstacle safety shall remain active during return. | STM32 | Obstacle test |
| STATE-3.44 | WELCOME shall exit to IDLE only after return is complete or explicitly aborted safely. | Pi | Mode log |
| STATE-3.45 | WELCOME_RETURN shall begin with `CMD:STOP` before any return motion command. | Pi + STM32 | Serial log |
| STATE-3.46 | WELCOME_RETURN maximum speed shall be less than or equal to WELCOME_APPROACH maximum speed. | Pi | Command bounds |
| STATE-3.47 | WELCOME_RETURN shall use a completion threshold before declaring base reached. | Pi + STM32 | Return distance log |
| STATE-3.48 | If return path is blocked, Pluto shall stop and remain in WELCOME_RETURN or enter ERROR based on timeout. | Pi + STM32 | Obstacle return test |
| STATE-3.49 | WELCOME_RETURN shall have a maximum allowed duration before faulting to ERROR. | Pi | Return timeout test |

### Return Navigation Subrequirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3.42.1 | Pi or STM32 shall define base as the pose recorded before WELCOME approach in v1. | Pi + STM32 | Odom log |
| STATE-3.42.2 | Return navigation shall be bounded by distance and time, not infinite retry. | Pi | Timeout test |
| STATE-3.42.3 | Return completion shall require both low commanded speed and position within threshold. | Pi + STM32 | Return log |
| STATE-3.42.4 | Return shall be considered degraded if odometry is unavailable or invalid. | Pi | Fault injection |
| STATE-3.42.5 | Degraded return shall stop Pluto and request operator assistance instead of guessing. | Pi + Uno | Fault behavior test |
| STATE-3.42.6 | Return arrival threshold shall be configured before testing and shall start no smaller than 15 cm. | Pi + STM32 | Config review |
| STATE-3.42.7 | Return shall tolerate bounded odometry drift and report estimated drift when available. | Pi + STM32 | Drift test |
| STATE-3.42.8 | Return shall stop if estimated heading error cannot be reduced within configured time. | Pi + STM32 | Heading fault test |
| STATE-3.42.9 | Return shall not declare success while commanded wheel speed is nonzero. | Pi + STM32 | Return log |
| STATE-3.42.10 | Return shall log start pose, target/base pose, final pose, duration, and completion reason. | Pi + STM32 | Return log review |

### WELCOME_RETURN Standalone Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-3R.1 | WELCOME_RETURN shall be treated as a locked substate of WELCOME. | Pi | Substate log |
| STATE-3R.2 | WELCOME_RETURN shall block IDLE, MANUAL, DANCE, WELCOME, and GAME_LATER requests until complete. | Pi | Transition test |
| STATE-3R.3 | WELCOME_RETURN shall allow emergency stop and ERROR transition. | Pi | E-stop test |
| STATE-3R.4 | WELCOME_RETURN shall begin only after wheel motion is stopped. | Pi + STM32 | Serial log |
| STATE-3R.5 | WELCOME_RETURN shall use lower or equal speed limits compared with WELCOME_APPROACH. | Pi | Command bounds |
| STATE-3R.6 | WELCOME_RETURN shall use obstacle safety at all times. | STM32 | Obstacle test |
| STATE-3R.7 | WELCOME_RETURN shall enter ERROR if return timeout expires. | Pi | Timeout test |
| STATE-3R.8 | WELCOME_RETURN shall request operator assistance if odometry is degraded. | Pi + Uno | Fault behavior test |

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
| VER-WELCOME-008 | Multiple people wave. | one target selected, target lock logged |
| VER-WELCOME-009 | Person moves during approach. | target update or safe stop logged |
| VER-WELCOME-010 | Return path blocked. | stop behavior, timeout or waiting behavior |
| VER-WELCOME-011 | Return exceeds duration limit. | ERROR state with return fault reason |
| VER-WELCOME-012 | WELCOME in multi-person scene. | crowd size, selected target, target lock logged |
| VER-WELCOME-013 | WELCOME_TALK with motor noise. | low confidence/fallback or motion pause logged |
| VER-WELCOME-014 | WELCOME arm gesture. | bounded `CMD:ARM`, no wheel movement during talk |
| VER-WELCOME-015 | Human or obstacle appears in approach path with vision enabled. | Pi slows/stops before command crosses safety margin |

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
| STATE-4.16 | DANCE arm movements shall remain inside DANCE arm limits. | Pi + STM32 | Arm bounds test |
| STATE-4.17 | DANCE shall not command arm movement if arm subsystem is unavailable or unvalidated. | Pi | Hardware gate test |

### Dance Safety Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| STATE-4.20 | DANCE shall reduce or stop motion if any obstacle is inside slow threshold. | Pi + STM32 | Obstacle test |
| STATE-4.21 | DANCE shall immediately stop wheel motion if obstacle is inside stop threshold. | STM32 | Obstacle test |
| STATE-4.22 | DANCE shall not use large translation range in v1. | Pi | Command bounds |
| STATE-4.23 | DANCE shall stop if audio system fails. | Pi | Audio fault test |
| STATE-4.24 | DANCE shall stop if STM32 reports any critical alert. | Pi | Alert test |
| STATE-4.25 | DANCE shall stop arm motion before or at the same time as wheel stop on critical fault. | Pi + STM32 | Fault test |
| STATE-4.26 | DANCE shall use optimized vision perception when available to detect humans or obstacles entering the dance envelope. | Pi | Vision safety test |
| STATE-4.27 | DANCE vision safety should use threaded capture, low resolution, frame skipping, detection hold, and tracked boxes to keep latency bounded. | Pi | CPU/FPS log |
| STATE-4.28 | If vision detects a human or obstacle near the dance envelope, Pi shall shrink, pause, or stop dance motion. | Pi + STM32 | Dance obstacle test |

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
| VER-DANCE-006 | Run DANCE with arm enabled. | bounded arm commands, stop on fault |
| VER-DANCE-007 | Run DANCE with speaker missing. | DANCE blocked or explicit silent mode |
| VER-DANCE-008 | Human or obstacle enters dance envelope with vision enabled. | motion shrinks, pauses, or stops |

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
| STATE-5.14 | ERROR website view shall show fault reason, failed subsystem, and allowed recovery action. | Pi | Website fault test |
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
| VER-ERROR-006 | Open website in ERROR. | fault reason and recovery action visible |

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

## Operator Website Verification Plan

| ID | Test | Expected Evidence |
| --- | --- | --- |
| VER-WEB-001 | Open website home page. | `PLUTO` visible as project identity |
| VER-WEB-002 | Open website with camera connected. | live camera feed visible |
| VER-WEB-003 | Open website with camera disconnected. | camera unavailable status visible |
| VER-WEB-004 | Change mode from IDLE to MANUAL through website. | mode request logged, current state updates |
| VER-WEB-005 | Attempt unsafe mode while STM32 missing. | choice blocked, clear reason shown |
| VER-WEB-006 | Press emergency stop from website. | `CMD:STOP` sent within 150 ms |
| VER-WEB-007 | Request system shutdown from website. | confirmation required, `CMD:STOP` before shutdown |
| VER-WEB-008 | View bootstrap report from website. | hardware pass/fail and suggested actions visible |
| VER-WEB-009 | Open website on phone viewport. | controls and status readable without overlap |
| VER-WEB-010 | Verify manual raw motor routes are unavailable outside MANUAL. | rejected request |

## Audio Verification Plan

| ID | Test | Expected Evidence |
| --- | --- | --- |
| VER-AUD-001 | Probe microphone. | available/unavailable reported clearly |
| VER-AUD-002 | Probe speaker. | available/unavailable reported clearly |
| VER-AUD-003 | Test speech with hoverboard/arm noise present. | confidence logged; fallback or pause occurs |
| VER-AUD-004 | Run WELCOME_TALK with microphone missing. | text/manual fallback or mode block |
| VER-AUD-005 | Run DANCE with speaker missing. | DANCE blocked or explicit silent mode |

## Arm Verification Plan

| ID | Test | Expected Evidence |
| --- | --- | --- |
| VER-ARM-001 | Send bounded arm command. | `CMD:ARM`, `ACK:ARM`, movement within configured limit |
| VER-ARM-002 | Send command above arm step limit. | command rejected or clamped |
| VER-ARM-003 | Trigger emergency stop during arm movement. | arm movement stops |
| VER-ARM-004 | Attempt arm movement in IDLE. | blocked unless diagnostic mode enabled |
| VER-ARM-005 | Attempt DANCE arm movement when arm unavailable. | blocked with clear reason |

## Cross-State Transition Requirements

| ID | Requirement | Owner | Verification |
| --- | --- | --- | --- |
| TRANS-001 | Every state transition shall be logged with previous state, next state, reason, and timestamp. | Pi | Log review |
| TRANS-002 | Every transition into a motion state shall require STM32 available. | Pi | Transition test |
| TRANS-003 | Every transition out of a motion state shall send `CMD:STOP`. | Pi + STM32 | Serial log |
| TRANS-004 | ERROR may interrupt any state. | Pi | Fault injection |
| TRANS-005 | WELCOME_RETURN shall block all non-error transitions until complete. | Pi | Return test |
| TRANS-006 | GAME_LATER shall not be reachable in v1. | Pi | Mode list test |
| TRANS-007 | Motion states shall be blocked if battery status is critical. | Pi | Battery transition test |
| TRANS-008 | Normal runtime shall begin with BOOTSTRAP before IDLE. | Pi | Boot flow test |
| TRANS-009 | BOOTSTRAP shall be the only state allowed to perform setup/repair actions. | Pi | State audit |
| TRANS-010 | Website state requests shall pass through mode manager transition validation. | Pi | Mode manager test |

## Requirement-To-Interface Trace

| State | STM32 Commands | STM32 Inputs | Uno Commands | Website Behavior | Other Inputs |
| --- | --- | --- | --- | --- | --- |
| BOOTSTRAP | `CMD:PING`, `CMD:STOP` | `ID`, `ACK`, `TEL`, `OBS`, `ALERT` | `ID?` or probe, optional `MODE:BOOT` | show bootstrap report if available | OS packages, Python env, serial devices, camera, audio |
| IDLE | `CMD:PING`, `CMD:STOP` | `ID`, `TEL`, `OBS`, `ALERT` | `MODE:IDLE`, `FACE:IDLE` | camera feed/status, current state, allowed next states | optional low-rate camera |
| MANUAL | `CMD:PING`, `CMD:DRIVE`, `CMD:STOP` | `ACK`, `TEL`, `OBS`, `ALERT` | `MODE:MANUAL`, `WARN` | manual controls, telemetry, emergency stop | operator controls |
| WELCOME | `CMD:PING`, `CMD:DRIVE`, `CMD:STOP`, `CMD:RETURN`, `CMD:RESET_HOME` | `ACK`, `TEL`, `OBS`, `ALERT` | `MODE:WELCOME`, `FACE:HAPPY`, `TEXT` | current substate, return lock status, emergency stop | vision/speech/crowd target |
| DANCE | `CMD:PING`, `CMD:DRIVE`, `CMD:STOP`, optional `CMD:ARM` | `ACK`, `OBS`, `ALERT` | `MODE:DANCE`, `FACE:DANCE` | dance start/stop/status, emergency stop | audio file, operator start |
| ERROR | `CMD:STOP`, `CMD:PING` | `ID`, `TEL`, `ALERT` | `MODE:ERROR`, `WARN` | fault reason, diagnostics, allowed recovery | reset request |
| GAME_LATER | none in v1 | none in v1 | `TEXT:Game later` | unavailable message | operator request |

## Timing-To-Test Trace

| Timing ID | Related Requirements | Verification |
| --- | --- | --- |
| TIME-001 | IF-STM32-010, STATE-1.10, STATE-2.10 | `VER-IDLE-008` |
| TIME-002 | IF-STM32-002, SAFE-001 | heartbeat log |
| TIME-003 | SAFE-001 | Pi heartbeat timeout test |
| TIME-004 | IF-STM32-008, STATE-1.12 | OBS timing log |
| TIME-005 | SAFE-002, STATE-3.21, STATE-4.21 | obstacle timing test |
| TIME-006 | STATE-5.1, STATE-5.4 | alert handling log |
| TIME-007 | STATE-2.12, STATE-2.13 | `VER-MANUAL-007` |
| TIME-008 | STATE-3.10, STATE-3.12 | welcome trigger timing test |
| TIME-009 | STATE-3.33 | interaction timing test |

## Power-To-Test Trace

| Power ID | Related Requirements | Verification |
| --- | --- | --- |
| PWR-001 | SYS-008 | wiring inspection |
| PWR-002 | IF-STM32-011 | telemetry log |
| PWR-003 | SAFE-007 | firmware/config review |
| PWR-004 | SAFE-007 | low-voltage stop test |
| PWR-005 | SAFE-008 | warning threshold test |
| PWR-006 | TRANS-007 | battery transition test |
| PWR-007 | Implementation Gate | config review |

## Bootstrap-To-Test Trace

| Bootstrap ID | Related Requirements | Verification |
| --- | --- | --- |
| BOOT-001 | SYS-009, STATE-0.1 | `VER-BOOT-001` |
| BOOT-002 | STATE-0.12 | `VER-BOOT-002` |
| BOOT-003 | STATE-0.10 | environment probe |
| BOOT-004 | STATE-0.10, STATE-0.31 | venv test |
| BOOT-005 | STATE-0.11, STATE-0.31 | import test |
| BOOT-006 | STATE-0.11 | package test |
| BOOT-007 | STATE-0.13 | serial permission test |
| BOOT-008 | STATE-0.14, STATE-0.32 | service validation test |
| BOOT-009 | STATE-0.52, STATE-0.53 | fault injection |
| BOOT-010 | STATE-0.50, STATE-0.51 | report review |
| BOOT-011 | STATE-0.15 | offline/diagnostic test |
| BOOT-012 | STATE-0.54 | log file check |
| BOOT-013 | STATE-0.34, STATE-0.40 | safety review |
| BOOT-014 | STATE-0.40 | STM32 serial log |
| BOOT-015 | STATE-0.25 | hardware report |

## Hardware-To-Test Trace

| Hardware ID | Related Requirements | Verification |
| --- | --- | --- |
| HW-001 | STATE-0.20, IF-STM32-001 | STM32 probe test |
| HW-002 | STATE-0.21, IF-UNO-001 | Uno probe test |
| HW-003 | STATE-0.20 | multi-device serial test |
| HW-004 | STATE-0.22 | camera probe |
| HW-005 | STATE-0.23 | speaker probe |
| HW-006 | STATE-0.24 | microphone probe |
| HW-007 | STATE-0.41 | missing STM32 test |
| HW-008 | STATE-0.44 | missing Uno test |
| HW-009 | STATE-0.44 | optional hardware test |
| HW-010 | STATE-0.44 | reduced capability test |
| HW-011 | STATE-0.41 | motion block test |
| HW-012 | STATE-0.52, STATE-0.53 | fault report review |

## Website-To-Test Trace

| Website ID | Related Requirements | Verification |
| --- | --- | --- |
| WEB-001 | SYS-011 | `VER-WEB-001` |
| WEB-002 | HW-004, STATE-1.17 | `VER-WEB-002` |
| WEB-003 | HW-004, STATE-0.22 | `VER-WEB-003` |
| WEB-004 | TRANS-001 | `VER-WEB-004` |
| WEB-005 | WELCOME substates | WELCOME substate UI test |
| WEB-006 | TRANS-010 | transition UI test |
| WEB-007 | TRANS-010 | `VER-WEB-004` |
| WEB-008 | WEB-SAFE-002, WEB-SAFE-003, WEB-SAFE-004 | `VER-WEB-005` |
| WEB-009 | HW-001 | STM32 disconnect UI test |
| WEB-010 | HW-002 | Uno disconnect UI test |
| WEB-011 | PWR-002 | telemetry UI test |
| WEB-012 | IF-STM32-008 | obstacle UI test |
| WEB-013 | STATE-5.14 | `VER-ERROR-006` |
| WEB-014 | SYS-007 | UI inspection |
| WEB-015 | SAFE-004 | `VER-WEB-006` |
| WEB-016 | system shutdown | `VER-WEB-007` |
| WEB-017 | system shutdown | confirmation UI test |
| WEB-018 | SAFE-004 | shutdown serial log |
| WEB-019 | STATE-0.54 | `VER-WEB-008` |
| WEB-020 | HW-012 | missing hardware UI test |
| WEB-021 | SYS-005 | log UI test |
| WEB-022 | SAFE-005 | `VER-WEB-010` |
| WEB-023 | WEB-TIME-001, WEB-TIME-003 | UI latency test |
| WEB-024 | operator usability | `VER-WEB-009` |
| WEB-025 | state naming | UI inspection |

## Feature-Memory-To-Test Trace

| Memory ID | Related Requirements | Verification |
| --- | --- | --- |
| MEM-001 | SYS-012, Implementation Gate | memory file exists |
| MEM-002 | all implemented requirements | trace review |
| MEM-003 | design intent | design review |
| MEM-004 | interface control | interface review |
| MEM-005 | runbook | run review |
| MEM-006 | debug method | debug review |
| MEM-007 | SYS-005 | evidence review |
| MEM-008 | fault handling | fault review |
| MEM-009 | SAFE requirements | safety review |
| MEM-010 | verification plan | `VER-*` trace review |
| MEM-011 | code changes | code review |
| MEM-012 | repository documentation | repo review |
| MEM-013 | hardware validation | test record review |
| MEM-014 | risk tracking | risk review |

## Audio-To-Test Trace

| Audio ID | Related Requirements | Verification |
| --- | --- | --- |
| AUD-001 | HW-006, STATE-3.36 | `VER-AUD-001` |
| AUD-002 | HW-005, STATE-4.3 | `VER-AUD-002` |
| AUD-003 | STATE-3.37 | audio quality test |
| AUD-004 | STATE-3.52 | `VER-AUD-003` |
| AUD-005 | STATE-3.36, STATE-3.37 | `VER-AUD-003` |
| AUD-006 | STATE-3.36 | `VER-AUD-004` |
| AUD-007 | STATE-4.23 | `VER-AUD-005` |
| AUD-008 | configuration | config review |
| AUD-009 | interaction quality | listening test |
| AUD-010 | MEM-007 | speech log review |
| AUD-011 | motor-noise handling | `VER-AUD-003` |
| AUD-012 | SYS-004 | audio fault test |
| AUD-013 | STATE-3.33.2 | word-limit test |
| AUD-014 | STATE-3.33.3 | response bank test |
| AUD-015 | STATE-3.33.1 | response source log |
| AUD-016 | STATE-3.33.5 | config and latency test |
| AUD-017 | STATE-3.33.5 | LLM fault test |
| AUD-018 | STATE-3.33.2 | long utterance test |
| AUD-019 | STATE-3.33.6 | offline run test |
| AUD-020 | STATE-3.33.8 | benchmark review |
| AUD-021 | STATE-3.33.7 | response source log |

## Arm-To-Test Trace

| Arm ID | Related Requirements | Verification |
| --- | --- | --- |
| ARM-001 | STATE-4.14, STATE-4.16 | `VER-ARM-001`, `VER-ARM-002` |
| ARM-002 | IF-STM32-001 | serial probe test |
| ARM-003 | configuration | config review |
| ARM-004 | configuration | config review |
| ARM-005 | STATE-1.41 | `VER-ARM-004` |
| ARM-006 | STATE-3.38 | `VER-WELCOME-014` |
| ARM-007 | STATE-4.16 | `VER-DANCE-006` |
| ARM-008 | STATE-4.25 | `VER-ARM-003` |
| ARM-009 | MEM-009 | safety review |
| ARM-010 | future hardware | limit switch test |
| ARM-011 | STATE-3R.2 | return test |
| ARM-012 | SAFE-004 | fault injection |

## V&V-Coverage-To-Test Trace

| V&V ID | Related Requirements | Verification |
| --- | --- | --- |
| VNV-001 | all `shall` requirements | requirements review |
| VNV-002 | implementation gate | trace review |
| VNV-003 | SAFE requirements | safety review |
| VNV-004 | state requirements | state review |
| VNV-005 | requirement categories | requirements review |
| VNV-006 | MEM-013 | memory review |
| VNV-007 | MEM-014 | risk review |

## Implementation Gate

Before code for a state begins:

1. State requirements must exist in this file.
2. Interfaces used by that state must be listed in the trace table.
3. Verification tests must exist.
4. Safety behavior must be explicit.
5. Any mismatch between docs, firmware, and wiring must be resolved.
6. Bootstrap impact must be defined for any new dependency or hardware device.
7. Website impact must be defined for any new state, fault, or operator action.
8. Feature memory must exist or be updated for every implemented requirement.

The next code implementation should start with the validation tools required to
prove `IF-STM32-*` and `IF-UNO-*`, not with high-level behavior.
