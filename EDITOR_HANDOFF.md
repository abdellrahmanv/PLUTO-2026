# Message To Future Pluto Editors

Status: active collaboration guide.

If you are editing this repository, assume another engineer or Codex may need
to continue after you. Leave the project easier to understand than you found it.

## First Rule

Do not build random patches directly into the robot.

Pluto is a real moving system. A small software mistake can become real motion.
Every change must be traceable, testable, and reversible.

## Read These First

Before changing code, read:

```text
README.md
ARCHITECTURE.md
SYSTEMS_ENGINEERING.md
SYSTEM_REQUIREMENTS.md
HOW_TO_BUILD_THE_SYSTEM_RIGHT.md
```

If your change touches an existing feature, also read its memory file:

```text
feature_memory/
```

## Required Workflow

For every feature or meaningful change:

```text
1. Check current git status.
2. Identify the requirement ID.
3. Update or add requirements if behavior changes.
4. Update or add feature memory.
5. Implement one bounded change.
6. Add or update a validation tool.
7. Run the relevant tests.
8. Record what passed, failed, or remains blocked.
9. Leave the repo in a clear state for the next editor.
```

If a feature has no requirement ID, do not silently implement it. Add the
requirement first.

## Safety Rules

Never enable real autonomous motion by default.

Dry-run comes first for any motion feature:

```text
WELCOME_APPROACH -> dry-run before CMD:DRIVE
DANCE            -> dry-run before CMD:DRIVE or CMD:ARM
RETURN           -> dry-run before return motion
```

Real motion requires all of these:

```text
1. Requirement IDs exist.
2. Feature memory exists.
3. Dry-run evidence passes.
4. STOP guard is verified.
5. Wheels-lifted test is done first.
6. Human reviewer explicitly approves live motion.
```

Do not bypass STM32 safety. The Pi may propose motion, but the STM32 must remain
the motor safety controller.

## Current Validation Gate

Run this before claiming the repo is healthy:

```bash
python3 tools/validate_features.py
```

On the Raspberry Pi with hardware connected:

```bash
/home/pi/yolo/env/bin/python tools/validate_features.py --hardware --audio --require-audio
```

Expected result is a feature-by-feature table. A feature is not considered
healthy just because the website opens.

## Hardware Rules

Do not assume Linux device names are stable.

Wrong:

```text
Assume /dev/ttyACM0 is always STM32.
```

Right:

```text
Probe serial identity.
Require ID:STM32_MOTOR before motor safety control.
Treat Uno as optional until connected and validated.
```

Required hardware:

```text
STM32 motor safety controller
```

Optional hardware for current phases:

```text
Uno LCD controller
camera
microphone
speaker
preloaded dance audio
NEMA arm subsystem
```

Optional does not mean ignored. It means the system must report clearly when it
is missing.

## Feature Memory Rule

Every implemented requirement needs a memory trail.

Use this pattern:

```text
feature_memory/<REQ-ID>_<feature_name>.md
```

The memory file must explain:

```text
Purpose
Requirements covered
Design
Safety behavior
Debugging checklist
Verification command
Known limitations
```

This is how another editor can debug deep behavior later without guessing.

## Tests To Prefer

Use the existing tools before inventing new ones:

```text
tools/validate_features.py
tools/web_shell_smoke.py
tools/stm32_probe.py
tools/idle_runtime_smoke.py
tools/manual_state_smoke.py
tools/error_state_smoke.py
tools/welcome_wave_smoke.py
tools/welcome_approach_smoke.py
tools/welcome_talk_smoke.py
tools/dance_smoke.py
tools/audio_io_smoke.py
tools/uno_probe.py
```

If you add a feature, add a tool or test method that proves it independently.

## Code Style

Keep changes boring and local.

Prefer:

```text
small modules
plain dataclasses for status
explicit reason strings
safe default values
visible website status
bounded commands
clear failure messages
```

Avoid:

```text
hidden global behavior
magic startup scripts
unbounded loops
silent fallbacks
automatic motion during install
large rewrites mixed with feature work
```

## Website Changes

If a feature affects runtime behavior, the website should show the evidence.

Useful fields:

```text
active/inactive
dry_run/live
target ID
reason
last command proposal
STOP guard result
hardware availability
latency or timing when relevant
```

The operator should not need to inspect code to know why Pluto stopped or
refused a mode.

## Raspberry Pi Deployment

Before editing on the Pi:

```bash
cd ~/PLUTO-2026
git status
git pull --ff-only
```

If local Pi changes exist, do not overwrite them casually. Capture what changed
and decide whether to keep, commit, or discard with human approval.

After deploying:

```bash
/home/pi/yolo/env/bin/python tools/validate_features.py --hardware --audio --require-audio
```

Then restart the website only after validation.

## Conflict Protocol

If you touch a file another editor recently changed:

```text
1. Read the file before editing.
2. Keep their intent unless it is unsafe or explicitly superseded.
3. Do not revert unrelated work.
4. Make the smallest compatible change.
5. Leave a note in final output or feature memory.
```

If two approaches conflict, prefer the one with:

```text
clearer requirements
safer failure behavior
better validation evidence
less live-motion risk
```

## Handoff Note Template

When you finish, leave a short note like this:

```text
Changed:
- Files edited:
- Requirement IDs:
- Feature memory:

Validated:
- Commands run:
- Result:
- Hardware used:

Still blocked:
- What is missing:
- What the next editor should check:

Safety:
- Does this send CMD:DRIVE?
- Does this send CMD:ARM?
- Is it dry-run or live?
```

## Current Safety Reality

At the time of this guide:

```text
WELCOME_APPROACH is dry-run.
DANCE is dry-run.
MANUAL is bounded operator control.
STM32 heartbeat and STOP guard are validated.
Audio and camera are validated on the Pi.
Uno/LCD is not validated until hardware is connected.
Real autonomous approach, return, and dance motion are not enabled.
```

Keep it that honest.
