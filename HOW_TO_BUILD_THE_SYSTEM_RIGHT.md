# How To Build The System Right

Status: working build method.

This document defines how Pluto should be implemented without turning the robot
into a pile of untraceable patches.

## Core Rule

Do not build Pluto all at once.

Build one feature at a time:

```text
1. Requirements
2. Feature memory
3. One feature implementation
4. Feature test tool
5. Bench validation
6. Debug notes
7. Mark feature validated
8. Move to next feature
9. Final setup connects already-proven pieces
```

The final setup file should not be magic. It should only install, detect,
configure, validate, and start features that were already built and tested
separately.

## Feature Definition Of Done

A feature is not done until all of these are true:

```text
1. Requirement IDs exist.
2. Interfaces are documented.
3. Safety behavior is explicit.
4. Feature memory exists or is updated.
5. Code is implemented.
6. A test tool or test method exists.
7. Expected logs/telemetry are known.
8. Failure modes are documented.
9. Bench validation has been run when hardware is involved.
10. The result is recorded.
```

## Required Files Per Feature

For every feature, create or update:

```text
SYSTEM_REQUIREMENTS.md
feature_memory/<REQ-ID>_<feature_name>.md
source code
test or validation script
```

Example:

```text
Requirement:
  IF-STM32-001

Memory:
  feature_memory/IF-STM32-001_stm32_serial_probe.md

Test:
  tools/stm32_probe.py
```

## Build Order

### Phase 0 - Bootstrap Foundation

Goal:

```text
The Raspberry Pi can prepare itself, detect hardware, and explain failures.
```

Features:

- repo setup
- Python environment
- hardware detector
- diagnostic report generator
- feature memory system
- no autonomous motion

Validation:

```text
Fresh clone -> setup -> report PASS/FAIL
Run setup twice -> no damage
Missing STM32 -> clear fault
Missing optional camera -> reduced capability
```

### Phase 1 - STM32 Serial Validation

Goal:

```text
Prove the Pi can identify and talk to the motor safety controller.
```

Features:

- scan serial ports
- identify `ID:STM32_MOTOR`
- send `CMD:PING`
- verify `ACK:PING` within timing requirement
- send `CMD:STOP`
- read `TEL:` and `OBS:`

Validation:

```text
STM32 connected    -> detected
STM32 disconnected -> clear required-hardware fault
Uno also connected -> still chooses STM32 correctly
CMD:PING           -> ACK within 100 ms
```

Phase 1 implementation files:

```text
feature_memory/IF-STM32-001_stm32_serial_probe.md
tools/stm32_probe.py
tools/README.md
```

Phase 1 command:

```bash
python3 tools/stm32_probe.py
```

### Phase 2 - Uno Serial Validation

Goal:

```text
Prove the Pi can identify and command the face/LCD controller.
```

Features:

- scan serial ports
- identify `ID:UNO_LCD`
- send `FACE:<expression>`
- send `MODE:<mode>`
- send `TEXT:<message>`

Validation:

```text
Uno connected       -> detected
Uno disconnected    -> warning, not motor failure
FACE:HAPPY          -> LCD changes
MODE:IDLE           -> LCD displays mode
```

Phase 2 implementation files:

```text
feature_memory/IF-UNO-001_uno_lcd_serial_probe.md
tools/uno_probe.py
tools/README.md
```

Phase 2 command:

```bash
python3 tools/uno_probe.py
```

### Phase 3 - Website Shell

Goal:

```text
Create the PLUTO operator console without motor control first.
```

Features:

- project identity `PLUTO`
- current state display
- allowed next-state display
- bootstrap report display
- hardware status display
- logs/events display
- emergency stop placeholder wired to safe command path

Validation:

```text
Open website -> PLUTO visible
Current state shown
STM32/Uno/camera status shown
Unsafe next states blocked
No raw motor command route exists outside allowed modes
```

Phase 3 implementation files:

```text
feature_memory/WEB-001_operator_console_shell.md
pluto_runtime/web_shell.py
tools/web_shell_smoke.py
```

Phase 3 command:

```bash
python3 -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

### Phase 4 - Camera Feed

Goal:

```text
Show live camera feed or a clear unavailable state.
```

Features:

- camera detection
- camera preview
- camera unavailable fallback
- low-rate preview in IDLE

Validation:

```text
Camera connected    -> feed visible
Camera disconnected -> clear unavailable message
Phone/laptop view   -> no layout overlap
```

Phase 4 implementation files:

```text
feature_memory/WEB-002_camera_feed_human_detection.md
pluto_runtime/camera.py
pluto_runtime/web_shell.py
tools/web_shell_smoke.py
```

Phase 4 closure decision:

```text
Phase 4 is done when camera feed and human presence are visible and stable.
Wave detection is not part of Phase 4. It is a WELCOME trigger feature because
it can request a state transition that later leads to approach motion.
```

Phase 4 command on Raspberry Pi:

```bash
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

### Phase 5 - Mode Manager

Goal:

```text
One state machine owns all mode transitions.
```

Features:

- BOOTSTRAP -> IDLE
- current state
- current substate
- allowed transitions
- blocked transitions
- transition logs
- stop guard requirements
- return lock gate
- error reset gate

Validation:

```text
BOOTSTRAP passes -> IDLE
STM32 missing    -> ERROR or reduced safe state
IDLE -> MANUAL   -> allowed when safe
ERROR -> DANCE   -> blocked
WELCOME_RETURN   -> blocks all normal modes
```

Phase 5 implementation files:

```text
feature_memory/STATE-CORE-001_mode_manager.md
pluto_runtime/mode_manager.py
pluto_runtime/web_shell.py
tools/mode_manager_smoke.py
tools/web_shell_smoke.py
```

### Phase 6 - IDLE

Goal:

```text
Pluto is awake, safe, visually alive, and not moving.
```

Features:

- STM32 heartbeat
- telemetry read
- obstacle read
- Uno idle face
- website current state
- camera lite if available
- no motor movement

Validation:

```text
Leave in IDLE 10 minutes -> no movement
STM32 heartbeat continues
Uno idle face displays
Website shows IDLE
Obstacle values update
```

Phase 6 implementation files:

```text
feature_memory/STATE-1_idle_runtime.md
pluto_runtime/stm32_link.py
pluto_runtime/web_shell.py
tools/idle_runtime_smoke.py
tools/web_shell_smoke.py
```

### Phase 7 - MANUAL

Goal:

```text
Operator can deliberately move Pluto while STM32 safety remains in control.
```

Features:

- bounded drive command
- hold-to-move behavior
- release-to-stop behavior
- emergency stop
- telemetry display
- obstacle safety
- raw drive route remains unavailable
- low-speed first validation limits

Validation:

```text
Wheels lifted first
Hold forward -> repeated CMD:DRIVE
Release      -> CMD:STOP
Obstacle     -> forward blocked
STM32 unplug -> ERROR
```

Phase 7 implementation files:

```text
feature_memory/STATE-2_manual_control.md
pluto_runtime/stm32_link.py
pluto_runtime/web_shell.py
tools/manual_state_smoke.py
tools/web_shell_smoke.py
```

### Phase 8 - ERROR

Goal:

```text
Faults become visible and safe, not mysterious.
```

Features:

- fault reason
- previous state
- no motion
- reset rules
- recovery path
- website fault display
- Uno warning display
- diagnostic fault injection
- critical alert escalation

Validation:

```text
Emergency stop -> ERROR
STM32 unplug   -> ERROR
Try DANCE      -> blocked
Fault cleared  -> reset allowed back to IDLE
```

Phase 8 implementation files:

```text
feature_memory/STATE-5_error_state.md
pluto_runtime/mode_manager.py
pluto_runtime/web_shell.py
tools/error_state_smoke.py
tools/web_shell_smoke.py
```

### Phase 9 - WELCOME

Goal:

```text
Pluto approaches a confirmed person, greets, talks simply, and returns safely.
```

Features:

- confirmed trigger
- wave trigger detection
- target selection
- approach
- obstacle handling
- arrival distance
- simple talk fallback
- 9-word talk input/output limits
- keyword-first answer strategy
- large deterministic keyword bank
- fully offline v1 talk path
- camera microphone detection
- local speech-to-text detection
- local Piper text-to-speech output
- website Listen and Ask+Speak controls
- optional local Ollama/Qwen v1.5 fallback gate
- return lock
- return completion
- crowd handling

Validation:

```text
Trigger WELCOME      -> target selected
Wave trigger         -> confirmed intent event, no direct motion
Approach             -> bounded motion
Obstacle             -> stop/request space
Person lost          -> stop/return decision
Talk                 -> wheels stay stopped
Talk answer          -> keyword-first, max 9 words
Talk v1              -> offline, no API keys, no cloud calls
Camera mic           -> detected as selected microphone
Audio smoke          -> record probe succeeds
Ask+Speak            -> response shown and TTS command starts
Talk v1.5            -> Ollama fallback only after benchmark
Return               -> other modes blocked
Return complete      -> IDLE
```

WELCOME wave trigger memory:

```text
feature_memory/STATE-3.12_welcome_wave_trigger_detection.md
```

WELCOME talk strategy memory:

```text
feature_memory/STATE-3.33_welcome_talk_strategy_study.md
```

WELCOME_TALK v1 implementation memory:

```text
feature_memory/STATE-3.33_welcome_talk_v1.md
feature_memory/AUD-001_audio_io_v1.md
tools/welcome_talk_smoke.py
tools/audio_io_smoke.py
```

WELCOME_TALK build split:

```text
v1:
  Build keyword/fuzzy intent matching first.
  Keep answers short, local, testable, and boring-fast.

v1.5:
  Add local Ollama/Qwen fallback only after benchmark evidence exists.
  Keyword/fuzzy matching remains the first path.
```

### Phase 10 - DANCE

Goal:

```text
Pluto performs bounded dance behavior without touching obstacles.
```

Features:

- explicit operator start
- preloaded audio
- bounded wheel movement
- fixed direction in v1
- optional bounded arm movement
- obstacle stop/reduce behavior
- stop on song end or operator stop

Validation:

```text
Start DANCE      -> audio and bounded commands
Obstacle         -> motion reduces/stops
Stop selected    -> audio stops, CMD:STOP
Speaker missing  -> blocked or explicit silent mode
STM32 alert      -> ERROR
```

### Phase 11 - Final Auto Setup

Goal:

```text
One setup path assembles already-proven features.
```

Final setup shall:

- install dependencies
- repair environment if possible
- detect STM32
- detect Uno
- detect camera/audio/mic
- classify hardware as required or optional
- validate services
- generate bootstrap report
- start PLUTO safely
- refuse motion if required safety hardware is missing

Final setup shall not:

- invent untested behavior
- enable autonomous motion during install
- hide failures
- assume `/dev/ttyACM0` is always STM32
- start motion states before BOOTSTRAP passes

Validation:

```text
Fresh Pi clone      -> setup works
Run setup twice     -> still works
STM32 missing       -> clear required fault
Camera missing      -> optional feature disabled
Service broken      -> exact service failure reported
System starts       -> BOOTSTRAP -> IDLE
```

## Integration Rule

A feature can only be integrated into the main runtime after it passes its own
feature validation.

Bad:

```text
Build website + serial + camera + modes + hotspot all at once.
```

Good:

```text
Build serial probe.
Validate serial probe.
Record memory.
Then build website status display.
Validate website status display.
Record memory.
Then connect them.
```

## Debug Rule

Every failure must answer:

```text
What failed?
Where did it fail?
What was expected?
What happened instead?
What should the human check next?
```

If a feature cannot answer those questions, it is not ready.

## Final Philosophy

Pluto should feel alive to humans, but internally it must be boring,
traceable, and predictable.

Build the spine first. Then the senses. Then the face. Then motion. Then
personality.
