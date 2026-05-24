# Pluto Architecture Notes

Status: first study draft.

These notes capture the current intended architecture. They are not final yet.
The main design principle is that only the Raspberry Pi makes high-level
decisions. The Arduino boards should stay simple and predictable.

## Board Responsibilities

### Raspberry Pi

The Raspberry Pi is Pluto's main brain.

It owns:

- USB camera
- Microphone
- USB speaker
- Speech recognition
- Text-to-speech
- LLM conversation
- Human detection
- Wave detection
- Mode manager
- Web or button control
- Commands sent to STM32F401 Black Pill
- Commands sent to Arduino Uno

The Pi should not directly control the hoverboard UART. Linux can lag, and
motor control needs a local safety layer.

### STM32F401 Black Pill

The STM32F401 Black Pill is the motor and safety controller.

It owns:

- Hoverboard UART
- Motor commands
- Emergency stop
- Ultrasonic obstacle checking
- Hoverboard feedback
- Safety timeout

Core behavior:

```text
If Pi sends command: move.
If Pi stops sending commands: stop.
If ultrasonic sees obstacle: stop.
If hoverboard feedback is bad: stop.
```

The STM32 must be paranoid. If the Pi crashes, Pluto stops.

### Arduino Uno

The Uno is the LCD / face / UI controller.

It owns:

- LCD display
- Face expressions
- Mode display
- Simple animations
- Status messages
- Optional LCD shield buttons

The Uno must not control motors.

## Communication Layout

The Raspberry Pi will use several USB devices:

```text
Raspberry Pi USB -> STM32F401 Black Pill  (motor safety serial)
Raspberry Pi USB -> Arduino Uno           (LCD / face serial)
Raspberry Pi USB -> USB camera            (vision)
Raspberry Pi USB -> USB speaker           (audio output)
```

The STM32 and Uno appear as serial devices. Expected Linux names:

```text
/dev/ttyUSB0
/dev/ttyUSB1
/dev/ttyACM0
/dev/ttyACM1
```

The USB camera will usually appear as:

```text
/dev/video0
```

The USB speaker will appear through the Linux audio system, not as a serial
device.

Later, each board should identify itself:

```text
ID:STM32_MOTOR
ID:UNO_LCD
```

## STM32F401 Black Pill Pin Plan

Exact pins can still change after checking the board pinout and chosen STM32
framework. Current clean draft:

| Function                  | STM32 Pin |
| ------------------------- | --------: |
| Hoverboard RX into STM32  |       PA10 |
| Hoverboard TX from STM32  |        PA9 |
| Front ultrasonic TRIG     |        PA0 |
| Front ultrasonic ECHO     |        PA1 |
| Left ultrasonic TRIG      |        PA2 |
| Left ultrasonic ECHO      |        PA3 |
| Right ultrasonic TRIG     |        PA4 |
| Right ultrasonic ECHO     |        PA5 |
| Optional emergency button |        PB0 |
| Buzzer/status LED         |        PC13 |

Important electrical note:

The STM32F401 Black Pill uses 3.3V logic, which matches the likely hoverboard
STM32 UART logic level better than a 5V Arduino Nano.

STM32 TX to hoverboard RX:

```text
STM32 PA9 TX -> Hoverboard RX
```

Hoverboard TX to STM32 RX:

```text
Hoverboard TX -> STM32 PA10 RX
GND            -> STM32 GND
```

Common ground is mandatory between STM32 and hoverboard.

Do not feed 5V signals into STM32 GPIO pins.

## Ultrasonic Safety

HC-SR04 ECHO is 5V.

- Unsafe for STM32 GPIO without voltage divider or level shifter.
- Unsafe for Raspberry Pi GPIO without voltage divider.

Current plan: connect ultrasonics to the STM32, but each ECHO line must be
shifted down to 3.3V before entering the STM32.

Example ECHO divider:

```text
HC-SR04 ECHO -- 1k ohm --+-- STM32 ECHO pin
                         |
                       2k ohm
                         |
                        GND
```

## Uno Serial Commands

Pi to Uno:

```text
FACE:HAPPY
FACE:THINKING
FACE:TALKING
FACE:DANCE
TEXT:Welcome to Pluto!
MODE:GAME
WARN:Obstacle front
```

Optional Uno to Pi:

```text
BTN:WELCOME
BTN:DANCE
BTN:GAME
BTN:STOP
ID:UNO_LCD
```

## Modes

The Pi owns the mode manager.

Initial mode list:

```text
IDLE
WELCOME
TALK
FOLLOW_WAVE
DANCE
GAME
MANUAL
ERROR
```

Emergency stop can happen from any mode.

## Pi to STM32 Protocol

```text
CMD:STOP
CMD:DRIVE:<speed>,<steer>
CMD:MODE:<mode>
CMD:LIMIT:<maxSpeed>
CMD:PING
```

Examples:

```text
CMD:DRIVE:80,0
CMD:DRIVE:0,100
CMD:STOP
CMD:LIMIT:120
CMD:MODE:DANCE
```

## STM32 to Pi Protocol

```text
ID:STM32_MOTOR
TEL:BAT:<voltage>,SPD:<speed>,DIST:<distance>,TEMP:<temp>
OBS:F:<cm>,L:<cm>,R:<cm>
ALERT:OBSTACLE_FRONT
ALERT:PI_TIMEOUT
ALERT:HOVERBOARD_ERROR
ACK:STOP
ACK:DRIVE
```

## Pi to Uno Protocol

```text
FACE:<expression>
TEXT:<message>
MODE:<mode>
WARN:<message>
```

## Raspberry Pi Software Shape

Planned Python structure:

```text
pluto/
  main.py
  mode_manager.py
  serial_stm32.py
  serial_uno.py
  vision.py
  speech.py
  llm_talk.py
  tts.py
  safety.py
  config.py
  modes/
    idle.py
    welcome.py
    talk.py
    follow_wave.py
    dance.py
    game.py
```

## Coding Order

Do not code all modes at once.

Preferred order:

```text
1. STM32 hoverboard + ultrasonic safety code
2. Pi serial connection to STM32
3. Uno LCD serial display code
4. Pi mode manager
5. Manual mode
6. Welcome mode
7. Talk mode
8. Wave-follow mode
9. Dance mode
10. Game mode
```

First target:

```text
Pi sends forward / backward / left / right / stop.
STM32 moves the hoverboard safely.
Uno displays current mode and status.
```
