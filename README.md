# Pluto Grad 22-5

This repository is for the Pluto graduation robot project.

Current study direction:

- Raspberry Pi is the main brain and mode manager.
- STM32F401 Black Pill is the motor and safety controller.
- Arduino Uno is the LCD / face / UI controller.
- The Pi decides what Pluto should do.
- The Arduinos execute simple, bounded commands.

The architecture is still allowed to change. For now, keep the system simple,
safe, and easy to test one layer at a time.

## Engineering Method

Pluto code should be implemented with a systems-engineering workflow:

- define the interface,
- implement one layer,
- verify it on the bench,
- add telemetry and logs,
- then integrate the next layer.

See `SYSTEMS_ENGINEERING.md` before adding new robot behavior.

System requirements and state decomposition live in `SYSTEM_REQUIREMENTS.md`.
