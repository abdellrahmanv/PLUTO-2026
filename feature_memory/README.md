# Pluto Feature Memory

This folder stores design and debug memory for implemented Pluto features.

Feature memory is mandatory. A feature is not done until its memory file exists
or an existing memory file is updated.

Each memory file should answer:

- What requirement IDs does this implement?
- What design was chosen?
- Why was it chosen?
- What interfaces does it use?
- How do we run it?
- How do we debug it?
- What logs or telemetry prove it is working?
- What are the known failure modes?
- What are the safety assumptions?
- What verification tests prove it?

Use `TEMPLATE.md` for new feature memory files.

Suggested filename format:

```text
REQ-ID_short_feature_name.md
```

Examples:

```text
IF-STM32-001_stm32_serial_probe.md
STATE-1_idle_mode.md
WEB-002_camera_feed.md
BOOT-001_auto_setup.md
```

