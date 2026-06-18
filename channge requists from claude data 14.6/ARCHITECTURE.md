# PLUTO STM32 Firmware v2.0 — Architecture Reference
## Spirit Robotics

---

## What Changed and Why

### v1.0 Problem
Single-threaded cooperative polling loop. Everything ran in sequence inside `while(1)`.
If any function blocked — even for 1ms — stepper pulses were delayed.
Sonar blocking (up to 60ms) caused stepper stalls. USB had a race condition.
micros() wrapped every 51 seconds.

### v2.0 Solution
**Every subsystem owns its own timing.**
Main loop is pure orchestration — it reads state and makes decisions.
It never blocks. It never times pulses.

---

## Interrupt Priority Table

| Priority | IRQ | What It Does |
|----------|-----|-------------|
| 0 (highest) | TIM3 | Stepper pulse generation + ramp |
| 1 | EXTI1, EXTI9_5 | Sonar echo capture (DWT timestamp) |
| 2 | USART1 | Hoverboard byte → hbRing |
| 3 | USB OTG FS | USB byte → usbRing |
| 15 (lowest) | SysTick | HAL_GetTick() |

**Rule:** Higher priority ISR can preempt lower priority ISR.
TIM3 at priority 0 means stepper pulses are NEVER delayed by anything.

---

## Subsystem 1: Stepper — TIM3 ISR

**Owner:** TIM3 hardware timer interrupt
**Main loop role:** arm the ISR, check done flag, send ACK

### How it works
- TIM3 configured at 1MHz tick (prescaler = 84-1)
- Period set to `1,000,000 / speed_sps` microseconds
- Each TIM3 overflow ISR fires → generates one STEP pulse
- Two arms interleaved: arm0 on even calls, arm1 on odd calls
- Ramp built into ISR: period decreases over first `STEPPER_ACCEL_STEPS` steps, increases over last `STEPPER_ACCEL_STEPS` steps

### Ownership contract
```
main writes:  stepsTarget, targetPeriod_us, currentPeriod_us, stepsCount=0
main sets:    running = 1  (last, after __DSB barrier)
ISR reads:    running, stepsTarget, targetPeriod_us
ISR writes:   stepsCount, currentPeriod_us, doneFlag, running (clears when done)
main reads:   running (to check if busy), doneFlag (to send ACK)
```

### Why __DSB before setting running=1
Data Synchronization Barrier ensures all prior writes are committed to memory
before the ISR can see `running = 1`. Without it, compiler or CPU reordering
could set `running` before `stepsTarget` is written.

### The 2us pulse
```c
HAL_GPIO_WritePin(step, SET);
volatile uint32_t d = 168; while(d--);  // 168 cycles = 2us at 84MHz
HAL_GPIO_WritePin(step, RESET);
```
This is inside the ISR — it's the only delay_us call that's acceptable there
because it's so short (168 cycles) that no other ISR at lower priority is
waiting that matters.

---

## Subsystem 2: Sonar — EXTI ISR

**Owner:** EXTI1 (PA1), EXTI9_5 (PA5, PA7) interrupt callbacks
**Main loop role:** fire TRIG pulse every 60ms per sonar, read distCm

### How it works
1. `sonarUpdate()` in main loop fires one TRIG pulse (10us blocking — acceptable)
2. Sets `sonar[i].phase = SONAR_CAPTURING`
3. EXTI ISR fires on RISING edge → records `DWT->CYCCNT` as echoStart
4. EXTI ISR fires on FALLING edge → records echoEnd, computes distance, sets fresh=1
5. Main loop reads `sonar[i].distCm` freely — no lock needed (float write is atomic on M4)

### Distance formula in ISR
```c
uint32_t cycles = echoEnd - echoStart;
// DWT->CYCCNT wraps at 2^32 but subtraction handles wrap correctly
// (unsigned arithmetic)
distCm = (cycles / 84_000_000.0f) * 17_000.0f;
// = time_seconds * speed_of_sound_cm_per_s / 2
```

### Why this beats blocking polling
Old: `measureDistance()` blocked up to 60ms per sonar = 180ms per full scan
New: TRIG pulse = 10us (only blocking call), echo captured in ISR = 0ms main loop cost
Full scan time: same 180ms, but main loop is free for 179.97ms of it.

### EXTI9_5 shared vector
PA5 and PA7 both map to EXTI9_5_IRQHandler.
The handler calls both:
```c
void EXTI9_5_IRQHandler(void) {
    HAL_GPIO_EXTI_IRQHandler(GPIO_PIN_5);
    HAL_GPIO_EXTI_IRQHandler(GPIO_PIN_7);
}
```
HAL routes each to `HAL_GPIO_EXTI_Callback(GPIO_Pin)` where we match by pin.

---

## Subsystem 3: Hoverboard UART — Interrupt-driven Ring Buffer

**Owner:** USART1 RX interrupt
**Main loop role:** drain hbRing, decode packets

### How it works
```c
// In init:
HAL_UART_Receive_IT(&huart1, &hbRxByte, 1);

// HAL callback (ISR context):
void HAL_UART_RxCpltCallback(...) {
    hbRing[hbRingHead & MASK] = hbRxByte;
    hbRingHead++;
    HAL_UART_Receive_IT(&huart1, &hbRxByte, 1);  // re-arm immediately
}
```
No bytes can be missed. Re-arm happens inside the callback before returning.

### Main loop drains
```c
while (hbRingTail != hbRingHead) {
    uint8_t b = hbRing[hbRingTail & MASK];
    hbRingTail++;
    // packet decode logic
}
```

---

## Subsystem 4: USB CDC — Ring Buffer (no race condition)

**Owner (write):** CDC_Receive_FS ISR
**Owner (read):** main loop only

### v1.0 race condition
```c
// ISR:
memcpy(usbRxBuf, Buf, *Len);
usbRxLen = *Len;       // ← ISR writes this

// Main loop:
for (i = 0; i < usbRxLen; i++) { ... }
usbRxLen = 0;          // ← Main clears this
// If ISR fires between the for-loop and the clear → length wiped → command lost
```

### v2.0 fix
```c
// ISR:
usbRing[usbRingHead & MASK] = Buf[i];
usbRingHead++;          // ISR only ever increments head

// Main:
while (usbRingTail != usbRingHead) {
    byte = usbRing[usbRingTail & MASK];
    usbRingTail++;      // Main only ever increments tail
}
```
ISR and main never write the same variable. No critical section needed.
`uint16_t` reads/writes are atomic on Cortex-M4 (single LDR/STR instruction).

---

## micros() — Eliminated

v1.0 used `DWT->CYCCNT / 84` for microseconds.
Problem: division before wrap → modulo arithmetic breaks every 51 seconds.

v2.0 fix: **micros() is gone entirely.**
- Stepper timing owned by TIM3 hardware — no software timing
- Sonar timing uses raw `DWT->CYCCNT` subtraction (unsigned, wraps correctly)
- Everything else uses `HAL_GetTick()` (milliseconds, 32-bit, wraps every 49 days)

---

## What Main Loop Does Now

```
while(1) {
    readHoverboard()      // drain ring, decode packets
    readRPi()             // drain ring, parse commands
    sonarUpdate()         // maybe fire one TRIG (10us max)
    stepperCheckDone()    // check doneFlag, send ACK if set
    navigateToHome()      // if returning
    applyMotorSafety()    // safety checks
    sendFOC()             // every 20ms
    sendTelemetry()       // every 100ms
    heartbeatLED()        // state machine, no blocking
}
```

No blocking calls except the 10us sonar TRIG once every 60ms per sensor.
That is 0.017% CPU time. Everything else is free-running.

---

## Files Modified

| File | Change |
|------|--------|
| `main.c` | Full rewrite of execution model. Logic preserved. |
| `usbd_cdc_if.c` | CDC_Receive_FS now pushes to ring buffer instead of flat array |
| `gpio.c` | **No change needed.** Echo pins reconfigured to EXTI in sonarInit() |
| `usart.c` | **No change needed.** UART interrupt armed in hbUartInit() |

---

## Branch Strategy

```
main  (v1.0 — stable, your grad project defense)
└── arch/v2-real
    ├── Commit 1: USB ring buffer (usbd_cdc_if.c only)
    ├── Commit 2: UART ring buffer + hbUartInit
    ├── Commit 3: Sonar EXTI (sonarInit + gpio reconfig)
    └── Commit 4: Stepper TIM3 ISR (stepperInit + TIM3_IRQHandler)
```

Test each commit independently on hardware before merging the next.
Commit 1 and 2 are safe to merge fast — no hardware behavior change.
Commit 3 and 4 require oscilloscope verification.

---

## Hardware Verification Checklist

### Stepper TIM3 ISR
- [ ] Scope STEP pin — clean pulses at expected frequency
- [ ] Ramp: frequency increases over first 50 steps, decreases over last 50
- [ ] Run sonar simultaneously — verify no pulse jitter
- [ ] Run USB commands simultaneously — verify no missed steps

### Sonar EXTI
- [ ] Scope ECHO pin and verify EXTI fires on both edges
- [ ] Print distCm over USB — verify correct distances
- [ ] Confirm no main loop stall when sonar is disconnected (old code would block 30ms)

### USB Ring Buffer
- [ ] Send commands in rapid succession from Pi — verify no drops
- [ ] Verify ACK arrives for every command

---

*PLUTO Firmware v2.0 — Spirit Robotics*
