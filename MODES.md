# Pluto Modes

## IDLE MODE

```text
IDLE MODE
═════════

ACTIVE:
  ✅ LCD face (idle + blink) via Uno
  ✅ Web server (mode selection + camera feed)
  ✅ Vision Lite (feeds web UI, 1-2 FPS)
  ✅ STM32 heartbeat (PING + telemetry)

INACTIVE:
  ❌ Speech / wake word
  ❌ LLM / TTS
  ❌ Motor commands
  ❌ Vision Full

EXIT TRIGGERS:
  1. User selects mode on web → that mode
  2. Emergency stop → ERROR
```

