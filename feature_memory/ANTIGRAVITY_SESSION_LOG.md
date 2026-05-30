# Feature Memory: Antigravity Session Engineering Log

Status: implemented
Last updated: 2026-05-30
Last validated: 2026-05-30, dry-run simulated via stm32_link_extensions_smoke.py
Owner: Antigravity (DeepMind AI Assistant)

## Requirement Trace
- [IF-STM32-013](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L370) (Odometry Home Return Tracking)
- [IF-STM32-014](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L371) (Reset Home Position Tracking)
- [IF-STM32-015](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L372) (NEMA Stepper Arm Motion Tracking)
- [STATE-3.5](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L650) (Base Reference Save)
- [STATE-3.42](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L710) (Return Guided by Odometry)
- [STATE-4.14](file:///c:/Users/Asus/Desktop/pluto-grad-22-5/SYSTEM_REQUIREMENTS.md#L830) (NEMA Stepper Arm Interface)

## Design Intent
To wire the Raspberry Pi runtime's persistent STM32 serial link to support pre-existing firmware commands (`CMD:RETURN`, `CMD:RESET_HOME`, and `CMD:ARM`) and their corresponding asynchronous ACKs. This makes the system ready for welcome approach, interaction, and dance personalities while keeping actual motor motion dry-run by default.

---

## Complete List of Changes Made

### 1. Pi-Side Serial Link (`pluto_runtime/stm32_link.py`)
Modified `Stm32RuntimeStatus`, `Stm32SerialLink`, and command handling:
- **`return_active` Tracking**: Added `return_active: bool = False` status field to trace active return-to-base odometry sequences.
- **Safety Preemption**:
  - `send_return()` transitions `return_active` to `True`.
  - Handling of `ACK:RETURN_COMPLETE` transitions `return_active` to `False`.
  - Transmission of any movement or stop command (`CMD:DRIVE`, `CMD:STOP`) transitions `return_active` to `False` to prevent state desynchronization.
- **Low-Level Stepper Protection**: Documented severe mechanical warnings inside `send_arm()` to notify editors that no physical limits/bounds checks exist in this primitive.
- **Command Transmission and ACK Parsing**:
  - Added methods: `send_return()`, `send_reset_home()`, and `send_arm()`.
  - Extended command classification to log new transmission counts.
  - Added parser support in `_handle_line()` for `ACK:RETURN`, `ACK:RETURN_COMPLETE`, `ACK:RESET_HOME`, `ACK:ARM`, and `ACK:ARM_DONE`.

### 2. Interface Requirement Mapping (`SYSTEM_REQUIREMENTS.md`)
Created three interface requirements with unique, unallocated IDs to bridge firmware command logic:
- `IF-STM32-013`: `Pi shall support sending CMD:RETURN for odometry-guided home return and tracking ACK:RETURN / ACK:RETURN_COMPLETE.` (Verification: Command log)
- `IF-STM32-014`: `Pi shall support sending CMD:RESET_HOME to mark current coordinates as home position.` (Verification: Command log)
- `IF-STM32-015`: `Pi shall support sending NEMA stepper movement as CMD:ARM:<steps>,<speed> and tracking completion via ACK:ARM_DONE.` (Verification: Command log)

### 3. Re-architected Mock Serial Tests (`tools/stm32_link_extensions_smoke.py`)
Completely rewrote the smoke test suite to avoid direct counter injection:
- Created a `FakeSerial` mock implementing standard write, flush, and close methods.
- Wired the mock to intercept actual ASCII transmissions from `send_command()`.
- Validated exact formatted strings (e.g. `b"CMD:ARM:150,100\n"`).
- Verified comprehensive `return_active` state transitions and command preemption lifecycles.
- All 15 test cases run locally and pass.

### 4. Cleanup of Duplicate Feature Memory
Deleted the obsolete file `feature_memory/IF-STM32-002_stm32_link_extensions.md` (as `IF-STM32-002` was already registered for the heartbeat command) and replaced it with `feature_memory/IF-STM32-013_stm32_link_extensions.md` using the correct template.

---

## Detailed Code Diffs

### `pluto_runtime/stm32_link.py`
```diff
@@ -1,4 +1,11 @@
-"""Persistent STM32 serial link for Pluto IDLE/runtime phases."""
+"""Persistent STM32 serial link for Pluto IDLE/runtime phases.
+
+Edited by: Antigravity (DeepMind AI Assistant)
+Date: 2026-05-30
+Phase 1: Added send_return, send_reset_home, send_arm methods and
+ACK parsing for ACK:RETURN, ACK:RETURN_COMPLETE, ACK:RESET_HOME,
+ACK:ARM, and ACK:ARM_DONE. No live motion behavior enabled.
+"""
 
 from __future__ import annotations
 
@@ -58,6 +65,21 @@ class Stm32RuntimeStatus:
     ack_drive_count: int = 0
     last_drive_command: str | None = None
     last_drive_sent: float | None = None
+    # --- Phase 1: return / reset_home / arm tracking ---
+    return_count: int = 0
+    ack_return_count: int = 0
+    return_active: bool = False
+    return_complete: bool = False
+    return_complete_at: float | None = None
+    reset_home_count: int = 0
+    ack_reset_home_count: int = 0
+    arm_count: int = 0
+    ack_arm_count: int = 0
+    arm_done: bool = False
+    arm_done_at: float | None = None
+    ack_arm_done_count: int = 0
+    last_arm_command: str | None = None
+    # --- end Phase 1 fields ---
     line_count: int = 0
     telemetry: dict[str, float | str] = field(default_factory=dict)
     obstacles: dict[str, float | str] = field(default_factory=dict)
@@ -135,6 +157,85 @@ class Stm32SerialLink:
             time.sleep(0.01)
         return {"ok": False, "detail": "DRIVE sent but ACK:DRIVE not received within 200 ms", "command": command}
 
+    # --- Phase 1: return / reset_home / arm commands ---
+
+    def send_return(self, wait_ack: bool = True, timeout_s: float = 0.45) -> dict[str, Any]:
+        """Send CMD:RETURN. STM32 begins odometry-guided return to home.
+
+        The STM32 sends ACK:RETURN immediately, and later sends
+        ACK:RETURN_COMPLETE when distanceToHome < HOME_THRESHOLD_CM.
+        This method waits only for the immediate ACK:RETURN.
+        Monitor return_complete via get_status() for completion.
+        """
+        with self._lock:
+            before = self._status.ack_return_count
+            self._status.return_complete = False
+            self._status.return_complete_at = None
+            self._status.return_active = True
+        ok, detail = self.send_command("CMD:RETURN")
+        if not ok or not wait_ack:
+            return {"ok": ok, "detail": detail, "command": "CMD:RETURN"}
+
+        deadline = time.monotonic() + timeout_s
+        while time.monotonic() < deadline:
+            with self._lock:
+                if self._status.ack_return_count > before:
+                    return {"ok": True, "detail": "ACK:RETURN", "command": "CMD:RETURN"}
+            time.sleep(0.01)
+        return {"ok": False, "detail": f"RETURN sent but ACK:RETURN not received within {int(timeout_s * 1000)} ms", "command": "CMD:RETURN"}
+
+    def send_reset_home(self, wait_ack: bool = True, timeout_s: float = 0.45) -> dict[str, Any]:
+        """Send CMD:RESET_HOME. STM32 saves current pose as home base.
+
+        Must be called before WELCOME_APPROACH so the STM32 knows
+        where to return to after the interaction.
+        """
+        with self._lock:
+            before = self._status.ack_reset_home_count
+        ok, detail = self.send_command("CMD:RESET_HOME")
+        if not ok or not wait_ack:
+            return {"ok": ok, "detail": detail, "command": "CMD:RESET_HOME"}
+
+        deadline = time.monotonic() + timeout_s
+        while time.monotonic() < deadline:
+            with self._lock:
+                if self._status.ack_reset_home_count > before:
+                    return {"ok": True, "detail": "ACK:RESET_HOME", "command": "CMD:RESET_HOME"}
+            time.sleep(0.01)
+        return {"ok": False, "detail": f"RESET_HOME sent but ACK:RESET_HOME not received within {int(timeout_s * 1000)} ms", "command": "CMD:RESET_HOME"}
+
+    def send_arm(self, steps: int, speed: int = 200, wait_ack: bool = True, timeout_s: float = 0.45) -> dict[str, Any]:
+        """Send CMD:ARM:<steps>,<speed>. STM32 moves the NEMA stepper.
+
+        [!] WARNING: This is a low-level primitive control command. It DOES NOT perform
+        any bounds checking, collision detection, or physical limit protection.
+        Improper steps/speed parameters can cause the stepper motor to override
+        physical boundaries, resulting in mechanical strain, gear damage, or structural
+        failure of the robot's arm mechanism. Callers MUST ensure that target parameters
+        are validated, bounded, and safe before invoking.
+
+        The STM32 sends ACK:ARM immediately on receipt, then sends
+        ACK:ARM_DONE asynchronously when all steps are completed.
+        This method waits only for the immediate ACK:ARM.
+        Monitor arm_done via get_status() for completion.
+        """
+        with self._lock:
+            before = self._status.ack_arm_count
+            self._status.arm_done = False
+            self._status.arm_done_at = None
+        command = f"CMD:ARM:{int(steps)},{int(speed)}"
+        ok, detail = self.send_command(command)
+        if not ok or not wait_ack:
+            return {"ok": ok, "detail": detail, "command": command}
+
+        deadline = time.monotonic() + timeout_s
+        while time.monotonic() < deadline:
+            with self._lock:
+                if self._status.ack_arm_count > before:
+                    return {"ok": True, "detail": "ACK:ARM", "command": command}
+            time.sleep(0.01)
+        return {"ok": False, "detail": f"ARM sent but ACK:ARM not received within {int(timeout_s * 1000)} ms", "command": command}
+
     def send_command(self, command: str) -> tuple[bool, str]:
         command = command.strip()
         if not command:
@@ -153,10 +254,19 @@ class Stm32SerialLink:
                     self._pending_ping_sent = time.monotonic()
                 elif command == "CMD:STOP":
                     self._status.stop_count += 1
+                    self._status.return_active = False
                 elif command.startswith("CMD:DRIVE:"):
                     self._status.drive_count += 1
                     self._status.last_drive_command = command
                     self._status.last_drive_sent = time.time()
+                    self._status.return_active = False
+                elif command == "CMD:RETURN":
+                    self._status.return_count += 1
+                elif command == "CMD:RESET_HOME":
+                    self._status.reset_home_count += 1
+                elif command.startswith("CMD:ARM:"):
+                    self._status.arm_count += 1
+                    self._status.last_arm_command = command
                 return True, "sent"
             except Exception as exc:
                 self._status.error = str(exc)
@@ -242,6 +352,20 @@ class Stm32SerialLink:
                 self._status.ack_stop_count += 1
             elif line == "ACK:DRIVE":
                 self._status.ack_drive_count += 1
+            elif line == "ACK:RETURN":
+                self._status.ack_return_count += 1
+            elif line == "ACK:RETURN_COMPLETE":
+                self._status.return_complete = True
+                self._status.return_complete_at = now_wall
+                self._status.return_active = False
+            elif line == "ACK:RESET_HOME":
+                self._status.ack_reset_home_count += 1
+            elif line == "ACK:ARM":
+                self._status.ack_arm_count += 1
+            elif line == "ACK:ARM_DONE":
+                self._status.arm_done = True
+                self._status.arm_done_at = now_wall
+                self._status.ack_arm_done_count += 1
             elif line.startswith("TEL:"):
                 self._status.telemetry = parse_tel_line(line)
             elif line.startswith("OBS:"):
```

### `SYSTEM_REQUIREMENTS.md`
```diff
@@ -367,6 +367,9 @@
 | IF-STM32-011 | STM32 telemetry shall include battery voltage when hoverboard feedback is valid. | Telemetry test |
 | IF-STM32-012 | STM32 shall include enough alert reason text for Pi to choose IDLE, ERROR, or continue. | Fault injection |
+| IF-STM32-013 | Pi shall support sending `CMD:RETURN` for odometry-guided home return and tracking `ACK:RETURN` / `ACK:RETURN_COMPLETE`. | Command log |
+| IF-STM32-014 | Pi shall support sending `CMD:RESET_HOME` to mark current coordinates as home position. | Command log |
+| IF-STM32-015 | Pi shall support sending NEMA stepper movement as `CMD:ARM:<steps>,<speed>` and tracking completion via `ACK:ARM_DONE`. | Command log |
```

---

## Verification Evidence & Evidence Runbook

### Verification Scripts Run
1. `python tools/stm32_link_extensions_smoke.py` -> Verified all 15 custom serial mock tests.
2. `python tools/welcome_approach_smoke.py` -> Verified no regressions in welcome approach logic.
3. `python tools/dance_smoke.py` -> Verified no regressions in dance routines.
4. `python tools/mode_manager_smoke.py` -> Verified no regressions in general mode selection state machine.

### Expected Logs / Evidence
```text
STM32_LINK_EXTENSIONS_SMOKE
  status_defaults PASS
  ack_return_parsing PASS
  ack_return_complete_parsing PASS
  ack_reset_home_parsing PASS
  ack_arm_parsing PASS
  ack_arm_done_parsing PASS
  arm_sequence PASS
  return_complete_resets PASS
  arm_done_resets PASS
  command_tracking_with_mock PASS
  return_active_lifecycle PASS
  existing_acks PASS
  telemetry_and_obs PASS
  alerts PASS
  get_status_new_fields PASS
STM32_LINK_EXTENSIONS_SMOKE PASS
```

---

## Safety Notes & Risk Mitigation

1. **Stepper Structural Danger**: `send_arm()` moves physical parts without limits. The caller is responsible for checking step boundaries before commanding steps to avoid stepper/robot mechanical breakdown.
2. **Odometry Home Drift**: The robot's return sequence uses only firmware-side wheel odometry which will drift over time. Live returns should only be triggered after the base reference has been correctly registered using `CMD:RESET_HOME`.

---

## Change History
- 2026-05-30: Session completed by Antigravity (DeepMind AI Assistant).
