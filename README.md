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
