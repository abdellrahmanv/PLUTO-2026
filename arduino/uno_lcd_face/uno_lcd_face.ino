/*
  Pluto Uno LCD state selector.

  Hardware:
  - Arduino Uno
  - 3.5 inch 480x320 TFT shield, 8-bit parallel bus
  - ILI9486/ST7796-style shield supported by MCUFRIEND_kbv

  Required libraries:
  - Adafruit GFX Library
  - MCUFRIEND_kbv
  - Adafruit TouchScreen

  Serial commands at 115200 baud:
  - ID?
  - PING
  - TOUCH?
  - TOUCH:DEBUG:ON
  - TOUCH:DEBUG:OFF
  - MODE:<state>
  - TEXT:<message>
  - WARN:<message>
  - FACE:<gesture>

  Touch commands emitted to Raspberry Pi:
  - BTN:IDLE
  - BTN:WELCOME
  - BTN:DANCE
  - BTN:EMERGENCY_STOP
*/

#include <Adafruit_GFX.h>
#include <MCUFRIEND_kbv.h>
#include <TouchScreen.h>

static const uint8_t XP = 8;
static const uint8_t XM = A2;
static const uint8_t YP = A3;
static const uint8_t YM = 9;
static const int TOUCH_MIN_PRESSURE = 120;
static const int TOUCH_MAX_PRESSURE = 1000;
static const int TOUCH_MIN_X = 120;
static const int TOUCH_MAX_X = 920;
static const int TOUCH_MIN_Y = 90;
static const int TOUCH_MAX_Y = 940;
static const unsigned long STARTUP_UI_DELAY_MS = 4500;

static const uint16_t BLACK = 0x0000;
static const uint16_t WHITE = 0xFFFF;
static const uint16_t CYAN = 0x07FF;
static const uint16_t BLUE = 0x031F;
static const uint16_t NAVY = 0x000F;
static const uint16_t PURPLE = 0x781F;
static const uint16_t PINK = 0xF81F;
static const uint16_t GREEN = 0x07E0;
static const uint16_t YELLOW = 0xFFE0;
static const uint16_t ORANGE = 0xFD20;
static const uint16_t RED = 0xF800;
static const uint16_t GRAY = 0x8410;
static const uint16_t DARK = 0x1082;

struct StateTile {
  const char *name;
  const char *label;
  uint16_t color;
};

StateTile states[] = {
  {"IDLE", "Idle", CYAN},
  {"WELCOME", "Welcome", GREEN},
  {"DANCE", "Dance", YELLOW},
  {"EMERGENCY_STOP", "Emergency Stop", RED},
};

static const uint8_t STATE_COUNT = sizeof(states) / sizeof(states[0]);

MCUFRIEND_kbv tft;
TouchScreen touch = TouchScreen(XP, YP, XM, YM, 300);

char modeText[18] = "IDLE";
char statusText[44] = "Touch command for Raspberry Pi";
char serialLine[72];
uint8_t serialLen = 0;
uint8_t selectedIndex = 0;
uint8_t currentGesture = 0;
uint8_t lastGesture = 255;

uint16_t screenW = 480;
uint16_t screenH = 320;
unsigned long lastPulseMs = 0;
unsigned long lastTouchMs = 0;
unsigned long lastTouchDebugMs = 0;
unsigned long lastSerialCommandMs = 0;
uint8_t pulse = 0;
int pendingTouchIndex = -1;
uint8_t pendingTouchCount = 0;
bool touchDebug = false;
bool redrawAll = true;
bool redrawStatus = true;
bool redrawSelection = true;
bool redrawFaceParts = true;
bool blinkNow = false;
bool lastBlinkDrawn = false;
int eyeOffset = 0;
int lastEyeOffset = 99;
int mouthPhase = 0;
int lastMouthPhase = 99;
int faceBeat = 0;
int lastFaceBeat = 99;
unsigned long lastBlinkMs = 0;
unsigned long nextBlinkMs = 2400;
unsigned long lastFaceFrameMs = 0;

const char *gestures[] = {
  "IDLE",
  "HAPPY",
  "THINKING",
  "TALKING",
  "DANCE",
  "SLEEPY",
};
static const uint8_t GESTURE_COUNT = sizeof(gestures) / sizeof(gestures[0]);

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println(F("ID:UNO_LCD"));

  uint16_t id = tft.readID();
  if (id == 0x0000 || id == 0xFFFF) {
    id = 0x9486;
  }
  tft.begin(id);
  tft.setRotation(1);
  screenW = tft.width();
  screenH = tft.height();

  setMode("IDLE");
  redrawAll = true;
}

void loop() {
  readSerial();
  readTouch();
  animateSelection();
}

void readSerial() {
  while (Serial.available() > 0) {
    char ch = (char)Serial.read();
    if (ch == '\r') {
      continue;
    }
    if (ch == '\n') {
      serialLine[serialLen] = '\0';
      if (serialLen > 0) {
        handleCommand(serialLine);
      }
      serialLen = 0;
      continue;
    }
    if (serialLen < sizeof(serialLine) - 1) {
      serialLine[serialLen++] = ch;
    }
  }
}

void handleCommand(char *line) {
  trimLine(line);
  lastSerialCommandMs = millis();

  if (strcmp(line, "ID?") == 0) {
    Serial.println(F("ID:UNO_LCD"));
    return;
  }
  if (strcmp(line, "PING") == 0) {
    Serial.println(F("ACK:PING"));
    return;
  }
  if (strcmp(line, "TOUCH?") == 0) {
    Serial.println(F("TOUCH:ENABLED"));
    return;
  }
  if (strcmp(line, "TOUCH:DEBUG:ON") == 0) {
    touchDebug = true;
    Serial.println(F("ACK:TOUCH:DEBUG:ON"));
    return;
  }
  if (strcmp(line, "TOUCH:DEBUG:OFF") == 0) {
    touchDebug = false;
    Serial.println(F("ACK:TOUCH:DEBUG:OFF"));
    return;
  }
  if (startsWith(line, "MODE:")) {
    setMode(line + 5);
    Serial.print(F("ACK:MODE:"));
    Serial.println(modeText);
    return;
  }
  if (startsWith(line, "FACE:")) {
    setGesture(line + 5);
    setMode("FACE");
    Serial.print(F("ACK:FACE:"));
    Serial.println(gestures[currentGesture]);
    return;
  }
  if (startsWith(line, "TEXT:")) {
    copyStatus(line + 5);
    Serial.print(F("ACK:TEXT:"));
    Serial.println(statusText);
    redrawStatus = true;
    return;
  }
  if (startsWith(line, "WARN:")) {
    copyStatus(line + 5);
    setGesture("THINKING");
    setMode("FACE");
    Serial.print(F("ACK:WARN:"));
    Serial.println(statusText);
    redrawStatus = true;
    return;
  }

  Serial.print(F("ERR:UNKNOWN:"));
  Serial.println(line);
}

void readTouch() {
  TSPoint point = touch.getPoint();
  pinMode(XM, OUTPUT);
  pinMode(YP, OUTPUT);

  unsigned long now = millis();
  if (now < STARTUP_UI_DELAY_MS) {
    return;
  }

  if (point.z < TOUCH_MIN_PRESSURE || point.z > TOUCH_MAX_PRESSURE) {
    pendingTouchIndex = -1;
    pendingTouchCount = 0;
    return;
  }

  int x = map(point.y, TOUCH_MIN_Y, TOUCH_MAX_Y, screenW, 0);
  int y = map(point.x, TOUCH_MIN_X, TOUCH_MAX_X, screenH, 0);
  int index = isFaceMode() ? faceTouchIndexAt(x, y) : tileIndexAt(x, y);

  if (touchDebug && now - lastTouchDebugMs > 180) {
    lastTouchDebugMs = now;
    Serial.print(F("TOUCH:RAW:"));
    Serial.print(point.x);
    Serial.print(F(","));
    Serial.print(point.y);
    Serial.print(F(","));
    Serial.print(point.z);
    Serial.print(F(";XY:"));
    Serial.print(x);
    Serial.print(F(","));
    Serial.print(y);
    Serial.print(F(";IDX:"));
    Serial.println(index);
  }

  if (now - lastTouchMs < 450) {
    return;
  }

  if (index != pendingTouchIndex) {
    pendingTouchIndex = index;
    pendingTouchCount = 1;
    return;
  }
  if (pendingTouchCount < 3) {
    pendingTouchCount++;
    return;
  }

  lastTouchMs = now;

  if (index < 0) {
    copyStatus("Touch outside tile");
    redrawStatus = true;
    return;
  }

  if (isFaceMode()) {
    handleFaceTouch(index);
  } else {
    const char *command = states[index].name;
    setMode(command);
    if (strcmp(command, "EMERGENCY_STOP") == 0) {
      copyStatus("Emergency stop sent");
    } else {
      copyStatus("Command sent to Pi");
    }
    Serial.print(F("BTN:"));
    Serial.println(command);
  }
  pendingTouchIndex = -1;
  pendingTouchCount = 0;
}

void trimLine(char *line) {
  uint8_t len = strlen(line);
  while (len > 0 && line[len - 1] == ' ') {
    line[--len] = '\0';
  }
  while (*line == ' ') {
    memmove(line, line + 1, strlen(line));
  }
}

bool startsWith(const char *value, const char *prefix) {
  return strncmp(value, prefix, strlen(prefix)) == 0;
}

void copyStatus(const char *value) {
  strncpy(statusText, value, sizeof(statusText) - 1);
  statusText[sizeof(statusText) - 1] = '\0';
}

void setMode(const char *value) {
  strncpy(modeText, value, sizeof(modeText) - 1);
  modeText[sizeof(modeText) - 1] = '\0';

  int found = findState(modeText);
  if (found >= 0) {
    selectedIndex = found;
    redrawSelection = true;
    redrawAll = true;
  }

  redrawStatus = true;
}

void setGesture(const char *value) {
  for (uint8_t i = 0; i < GESTURE_COUNT; i++) {
    if (strcmp(gestures[i], value) == 0) {
      currentGesture = i;
      redrawAll = true;
      return;
    }
  }
  currentGesture = 0;
  redrawAll = true;
}

bool isFaceMode() {
  return strcmp(modeText, "FACE") == 0;
}

int findState(const char *name) {
  for (uint8_t i = 0; i < STATE_COUNT; i++) {
    if (strcmp(states[i].name, name) == 0) {
      return i;
    }
  }
  return -1;
}

void animateSelection() {
  unsigned long now = millis();
  if (redrawAll && now < STARTUP_UI_DELAY_MS) {
    return;
  }

  if (isFaceMode()) {
    animateFace();
    return;
  }

  if (redrawAll) {
    drawScreen();
    redrawAll = false;
    redrawSelection = false;
    redrawStatus = false;
    return;
  }

  if (now - lastSerialCommandMs < 700) {
    return;
  }

  if (redrawSelection) {
    pulse = (pulse + 1) % 12;
    drawTile(selectedIndex);
    redrawSelection = false;
  }

  if (redrawStatus) {
    drawHeader();
    drawStatus();
    redrawStatus = false;
  }
}

void drawScreen() {
  if (isFaceMode()) {
    drawFaceScreen();
    return;
  }

  tft.fillScreen(BLACK);
  drawHeader();
  for (uint8_t i = 0; i < STATE_COUNT; i++) {
    drawTile(i);
  }
  drawStatus();
}

void animateFace() {
  if (redrawAll) {
    drawFaceScreen();
    redrawAll = false;
    redrawFaceParts = false;
    redrawStatus = false;
    return;
  }

  blinkNow = false;
  faceBeat = 0;
  eyeOffset = 0;
  if (currentGesture == 2) {
    eyeOffset = 4;
  }
  mouthPhase = currentGesture == 3 ? 2 : 0;
  if (currentGesture == 4) {
    eyeOffset = 3;
  }

  bool changed = redrawFaceParts || blinkNow || lastBlinkDrawn || eyeOffset != lastEyeOffset || mouthPhase != lastMouthPhase || faceBeat != lastFaceBeat || currentGesture != lastGesture;
  if (!changed) {
    return;
  }

  drawFaceParts();
  lastEyeOffset = eyeOffset;
  lastMouthPhase = mouthPhase;
  lastFaceBeat = faceBeat;
  lastGesture = currentGesture;
  lastBlinkDrawn = blinkNow;
  redrawFaceParts = false;
}

void drawFaceScreen() {
  tft.fillScreen(BLACK);
  tft.fillRect(0, 0, screenW, 48, NAVY);
  tft.setTextSize(2);
  tft.setTextColor(WHITE);
  tft.setCursor(14, 12);
  tft.print(F("PLUTO FACE"));
  tft.setTextColor(PURPLE);
  tft.setCursor(screenW - 150, 12);
  tft.print(gestures[currentGesture]);

  tft.fillRoundRect(10, screenH - 42, 100, 32, 7, DARK);
  tft.drawRoundRect(10, screenH - 42, 100, 32, 7, CYAN);
  tft.setTextColor(CYAN);
  tft.setCursor(28, screenH - 32);
  tft.print(F("MENU"));

  tft.setTextColor(WHITE);
  tft.setCursor(130, screenH - 32);
  tft.print(F("Tap face: gesture"));

  lastEyeOffset = 99;
  lastMouthPhase = 99;
  lastFaceBeat = 99;
  lastGesture = 255;
  redrawFaceParts = true;
  drawFaceBody();
  drawFaceParts();
}

void drawFaceBody() {
  int cx = screenW / 2;
  tft.fillRoundRect(54, 70, screenW - 108, 185, 30, blend(PURPLE, BLACK));
  tft.drawRoundRect(54, 70, screenW - 108, 185, 30, PURPLE);
  tft.drawRoundRect(58, 74, screenW - 116, 177, 26, WHITE);
  tft.drawLine(cx - 108, 70, cx - 128, 54, PURPLE);
  tft.drawLine(cx + 108, 70, cx + 128, 54, PURPLE);
  tft.fillRoundRect(30, 135, 24, 64, 10, blend(PURPLE, BLACK));
  tft.fillRoundRect(screenW - 54, 135, 24, 64, 10, blend(PURPLE, BLACK));
}

void drawFaceParts() {
  int cx = screenW / 2;
  int eyeY = 135;
  int leftX = cx - 82;
  int rightX = cx + 82;

  tft.fillRoundRect(leftX - 54, eyeY - 44, 108, 88, 18, blend(PURPLE, BLACK));
  tft.fillRoundRect(rightX - 54, eyeY - 44, 108, 88, 18, blend(PURPLE, BLACK));
  tft.fillRect(cx - 92, 172, 184, 62, blend(PURPLE, BLACK));
  drawFaceAccents();

  drawEye(leftX, eyeY, false);
  drawEye(rightX, eyeY, true);
  drawMouth(cx, 202);
}

void drawFaceAccents() {
  int cx = screenW / 2;
  uint16_t accent = gestureColor();
  int glow = 4 + (faceBeat % 4);

  tft.fillRect(cx - 148, 42, 40, 30, BLACK);
  tft.fillRect(cx + 108, 42, 40, 30, BLACK);
  tft.drawLine(cx - 108, 70, cx - 128, 54, PURPLE);
  tft.drawLine(cx + 108, 70, cx + 128, 54, PURPLE);
  tft.fillCircle(cx - 128, 54, glow, accent);
  tft.fillCircle(cx + 128, 54, glow, accent);

  tft.fillRect(cx - 150, 174, 42, 32, blend(PURPLE, BLACK));
  tft.fillRect(cx + 108, 174, 42, 32, blend(PURPLE, BLACK));
  if (currentGesture == 1 || currentGesture == 3 || currentGesture == 4) {
    tft.fillCircle(cx - 128, 190, 8 + (faceBeat % 2), PINK);
    tft.fillCircle(cx + 128, 190, 8 + (faceBeat % 2), PINK);
  }

  tft.fillRect(cx - 128, 86, 256, 24, blend(PURPLE, BLACK));
  if (currentGesture == 2) {
    tft.drawLine(cx - 124, 101, cx - 52, 88, YELLOW);
    tft.drawLine(cx + 52, 88, cx + 124, 101, YELLOW);
  } else if (currentGesture == 4) {
    tft.drawLine(cx - 124, 90 + (faceBeat % 3), cx - 52, 92, YELLOW);
    tft.drawLine(cx + 52, 92, cx + 124, 90 + ((faceBeat + 1) % 3), YELLOW);
  } else {
    tft.drawLine(cx - 120, 95, cx - 52, 93, CYAN);
    tft.drawLine(cx + 52, 93, cx + 120, 95, CYAN);
  }

  if (currentGesture == 4) {
    int sx = faceBeat % 2 ? cx - 156 : cx + 156;
    int sy = 90 + (faceBeat % 5) * 18;
    tft.fillRect(cx - 174, 80, 36, 116, blend(PURPLE, BLACK));
    tft.fillRect(cx + 138, 80, 36, 116, blend(PURPLE, BLACK));
    drawSpark(sx, sy, accent);
  }
}

void drawEye(int x, int y, bool rightEye) {
  if (blinkNow || currentGesture == 5) {
    tft.fillRoundRect(x - 44, y - 5, 88, 11, 5, WHITE);
    return;
  }

  int w = currentGesture == 1 || currentGesture == 4 ? 94 : 86;
  int h = currentGesture == 1 || currentGesture == 4 ? 66 : 58;
  tft.fillRoundRect(x - w / 2, y - h / 2, w, h, 17, WHITE);
  tft.drawRoundRect(x - w / 2, y - h / 2, w, h, 17, PURPLE);

  int pupilX = x + eyeOffset * 5;
  int pupilY = y;
  if (currentGesture == 2 && rightEye) {
    pupilY -= 8;
  }
  tft.fillCircle(pupilX, pupilY, 16, BLACK);
  tft.fillCircle(pupilX + 5, pupilY - 6, 4, WHITE);
}

void drawMouth(int x, int y) {
  if (currentGesture == 3) {
    int open = 14 + mouthPhase * 7;
    tft.fillRoundRect(x - 48, y - open / 2, 96, open, 12, WHITE);
    tft.fillRoundRect(x - 34, y - open / 2 + 6, 68, open - 12, 8, BLACK);
    return;
  }

  if (currentGesture == 1 || currentGesture == 4) {
    tft.fillRoundRect(x - 66, y - 15, 132, 30, 15, WHITE);
    tft.fillRect(x - 68, y - 22, 136, 18, blend(PURPLE, BLACK));
    return;
  }

  if (currentGesture == 2) {
    tft.fillRoundRect(x - 38, y - 6, 76, 12, 6, WHITE);
    tft.fillCircle(x + 62, y - 15, 5, YELLOW);
    return;
  }

  if (currentGesture == 5) {
    tft.fillRoundRect(x - 44, y - 4, 88, 8, 4, WHITE);
    return;
  }

  tft.fillRoundRect(x - 48, y - 7, 96, 14, 7, WHITE);
}

void drawSpark(int x, int y, uint16_t color) {
  tft.drawFastHLine(x - 9, y, 18, color);
  tft.drawFastVLine(x, y - 9, 18, color);
  tft.drawLine(x - 6, y - 6, x + 6, y + 6, color);
  tft.drawLine(x - 6, y + 6, x + 6, y - 6, color);
}

uint16_t gestureColor() {
  if (currentGesture == 1) return GREEN;
  if (currentGesture == 2) return YELLOW;
  if (currentGesture == 3) return PINK;
  if (currentGesture == 4) return ORANGE;
  if (currentGesture == 5) return BLUE;
  return CYAN;
}

void drawHeader() {
  tft.fillRect(0, 0, screenW, 50, NAVY);
  tft.fillRect(0, 48, screenW, 2, states[selectedIndex].color);
  tft.setTextColor(WHITE);
  tft.setTextSize(2);
  tft.setCursor(16, 12);
  tft.print(F("PLUTO COMMANDS"));

  tft.setTextColor(states[selectedIndex].color);
  tft.setCursor(screenW - 190, 12);
  tft.print(modeText);
}

void drawTile(uint8_t index) {
  int x;
  int y;
  int w;
  int h;
  tileRect(index, &x, &y, &w, &h);

  bool selected = index == selectedIndex;
  uint16_t color = states[index].color;
  uint16_t fill = selected ? blend(color, BLACK) : DARK;
  uint16_t border = selected ? color : GRAY;
  uint8_t radius = selected ? 10 : 7;
  uint8_t lift = selected ? pulseOffset() : 0;

  tft.fillRoundRect(x - 2, y - 2, w + 4, h + 4, radius, BLACK);
  tft.fillRoundRect(x, y - lift, w, h, radius, fill);
  tft.drawRoundRect(x, y - lift, w, h, radius, border);

  if (selected) {
    tft.drawRoundRect(x + 3, y + 3 - lift, w - 6, h - 6, radius, WHITE);
    tft.fillCircle(x + w - 18, y + 18 - lift, 6 + (pulse % 3), color);
  }

  tft.setTextSize(2);
  tft.setTextColor(selected ? WHITE : color);
  tft.setCursor(x + 14, y + h / 2 - 8 - lift);
  tft.print(states[index].label);
}

uint8_t pulseOffset() {
  if (pulse < 3) return 0;
  if (pulse < 6) return 1;
  if (pulse < 9) return 2;
  return 1;
}

void drawStatus() {
  tft.fillRect(0, screenH - 42, screenW, 42, NAVY);
  tft.drawFastHLine(0, screenH - 42, screenW, states[selectedIndex].color);
  tft.setTextColor(WHITE);
  tft.setTextSize(2);
  tft.setCursor(14, screenH - 29);
  printClipped(statusText, 38);
}

void tileRect(uint8_t index, int *x, int *y, int *w, int *h) {
  int margin = 10;
  int gap = 12;
  int cols = 2;
  int rows = 2;
  int top = 62;
  int bottom = screenH - 54;
  int tileW = (screenW - margin * 2 - gap * (cols - 1)) / cols;
  int tileH = (bottom - top - gap * (rows - 1)) / rows;
  int col = index % cols;
  int row = index / cols;

  *x = margin + col * (tileW + gap);
  *y = top + row * (tileH + gap);
  *w = tileW;
  *h = tileH;
}

int tileIndexAt(int x, int y) {
  for (uint8_t i = 0; i < STATE_COUNT; i++) {
    int tx;
    int ty;
    int tw;
    int th;
    tileRect(i, &tx, &ty, &tw, &th);
    if (x >= tx && x <= tx + tw && y >= ty && y <= ty + th) {
      return i;
    }
  }
  return -1;
}

int faceTouchIndexAt(int x, int y) {
  if (x >= 10 && x <= 112 && y >= screenH - 45 && y <= screenH - 8) {
    return 0;
  }
  if (y >= 55 && y <= screenH - 55) {
    return 1;
  }
  return -1;
}

void handleFaceTouch(int action) {
  if (action == 0) {
    setMode("IDLE");
    copyStatus("State menu");
    Serial.println(F("BTN:IDLE"));
    return;
  }

  currentGesture = (currentGesture + 1) % GESTURE_COUNT;
  redrawAll = true;
}

void printClipped(const char *value, uint8_t maxChars) {
  for (uint8_t i = 0; value[i] != '\0' && i < maxChars; i++) {
    tft.print(value[i]);
  }
}

uint16_t blend(uint16_t a, uint16_t b) {
  uint8_t ar = (a >> 11) & 0x1F;
  uint8_t ag = (a >> 5) & 0x3F;
  uint8_t ab = a & 0x1F;
  uint8_t br = (b >> 11) & 0x1F;
  uint8_t bg = (b >> 5) & 0x3F;
  uint8_t bb = b & 0x1F;
  return ((ar * 2 + br) / 3) << 11 | ((ag * 2 + bg) / 3) << 5 | ((ab * 2 + bb) / 3);
}
