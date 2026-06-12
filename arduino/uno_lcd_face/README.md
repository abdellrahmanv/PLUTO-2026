# Pluto Uno LCD State Selector Firmware

This sketch turns the Arduino Uno and 3.5 inch TFT shield into Pluto's state
selection display.

## Libraries

Install these from Arduino IDE Library Manager:

```text
Adafruit GFX Library
MCUFRIEND_kbv
Adafruit TouchScreen
```

## Upload

1. Open `arduino/uno_lcd_face/uno_lcd_face.ino`.
2. Select `Arduino Uno`.
3. Select the Uno COM port.
4. Upload.
5. Open Serial Monitor at `115200` baud with newline enabled.

On boot:

```text
ID:UNO_LCD
```

## Commands

```text
ID?
PING
TOUCH?
TOUCH:DEBUG:ON
TOUCH:DEBUG:OFF
MODE:IDLE
MODE:WELCOME
MODE:TALK
MODE:DANCE
MODE:MANUAL
MODE:GAME
MODE:FACE
MODE:ERROR
MODE:STOP
FACE:IDLE
FACE:HAPPY
FACE:THINKING
FACE:TALKING
FACE:DANCE
FACE:SLEEPY
TEXT:PLUTO PHASE 2
WARN:Obstacle front
```

Touching a tile should print:

```text
BTN:WELCOME
```

Touching `FACE` opens Pluto's dynamic gesture face. In the face screen:

```text
Tap face area -> cycles IDLE/HAPPY/THINKING/TALKING/DANCE/SLEEPY
Tap MENU      -> returns to state selection
```

Touch debug is off by default. Send this in Serial Monitor to enable raw touch
readings:

```text
TOUCH:DEBUG:ON
```

Then touches also print:

```text
TOUCH:RAW:520,618,411;XY:298,158;IDX:3
```

If there are no `TOUCH:RAW` lines, the touch library is missing or the shield
uses different touch pins. If `TOUCH:RAW` appears but the wrong tile is chosen,
adjust the `TOUCH_MIN_*` and `TOUCH_MAX_*` constants in the sketch.
