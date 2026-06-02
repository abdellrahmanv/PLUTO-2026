/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : PLUTO ROBOT — STM32F401 Black Pill
  *                   Motor Safety Controller — Firmware v1.0
  *                   Spirit Robotics
  ******************************************************************************
  * PIN MAP:
  *   PA9   → Hoverboard TX (USART1)
  *   PA10  → Hoverboard RX (USART1)
  *   PA11  → USB D-  (CDC to Raspberry Pi)
  *   PA12  → USB D+  (CDC to Raspberry Pi)
  *   PA0   → HC-SR04 Front-Left  TRIG
  *   PA1   → HC-SR04 Front-Left  ECHO
  *   PA4   → HC-SR04 Front       TRIG
  *   PA5   → HC-SR04 Front       ECHO
  *   PA6   → HC-SR04 Front-Right TRIG
  *   PA7   → HC-SR04 Front-Right ECHO
  *   PB8   → NEMA Arm 1 STEP
  *   PB9   → NEMA Arm 1 DIR
  *   PB10  → NEMA Arm 1 EN  (LOW = enabled)
  *   PB12  → NEMA Arm 2 STEP
  *   PB13  → NEMA Arm 2 DIR
  *   PB14  → NEMA Arm 2 EN  (LOW = enabled)
  *   PB0   → Emergency button (INPUT_PULLUP)
  *   PC13  → Status LED (active LOW)
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "usart.h"
#include "usb_device.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "usbd_cdc_if.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
#pragma pack(push, 1)
typedef struct {
  uint16_t start;
  int16_t  steer;
  int16_t  speed;
  uint16_t checksum;
} FOCCmd;

typedef struct {
  uint16_t start;
  int16_t  cmd1;
  int16_t  cmd2;
  int16_t  speedR;
  int16_t  speedL;
  int16_t  batVoltage;
  int16_t  boardTemp;
  uint16_t checksum;
} FOCFeedback;
#pragma pack(pop)
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

// ── Physical constants ──────────────────────────────────────
#define WHEEL_CIRC          53.4f
#define TRACK_WIDTH         54.0f
#define SPEED_SCALE         1.0f

// ── Safety thresholds ───────────────────────────────────────
#define OBSTACLE_STOP_CM    60
#define OBSTACLE_SLOW_CM    100
#define PI_TIMEOUT_MS       1000
#define HOME_THRESHOLD_CM   15
#define RETURN_SPEED        -25
#define BAT_MIN_VOLTAGE     34.0f
#define HB_ERROR_MAX        3

// ── GPIO macros ─────────────────────────────────────────────
#define TRIG_FL_PORT        GPIOA
#define TRIG_FL_PIN         GPIO_PIN_0
#define ECHO_FL_PORT        GPIOA
#define ECHO_FL_PIN         GPIO_PIN_1

#define TRIG_F_PORT         GPIOA
#define TRIG_F_PIN          GPIO_PIN_4
#define ECHO_F_PORT         GPIOA
#define ECHO_F_PIN          GPIO_PIN_5

#define TRIG_FR_PORT        GPIOA
#define TRIG_FR_PIN         GPIO_PIN_6
#define ECHO_FR_PORT        GPIOA
#define ECHO_FR_PIN         GPIO_PIN_7

#define STEP_PORT           GPIOB
#define STEP_PIN_NUM        GPIO_PIN_8
#define DIR_PORT            GPIOB
#define DIR_PIN_NUM         GPIO_PIN_9
#define EN_PORT             GPIOB
#define EN_PIN_NUM          GPIO_PIN_10

#define STEP2_PORT          GPIOB
#define STEP2_PIN_NUM       GPIO_PIN_12
#define DIR2_PORT           GPIOB
#define DIR2_PIN_NUM        GPIO_PIN_13
#define EN2_PORT            GPIOB
#define EN2_PIN_NUM         GPIO_PIN_14

#define EMERG_PORT          GPIOB
#define EMERG_PIN           GPIO_PIN_0
#define LED_PORT            GPIOC
#define LED_PIN             GPIO_PIN_13

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */

// ── Hoverboard state ────────────────────────────────────────
int16_t  cmdSpeed         = 0;
int16_t  cmdSteer         = 0;
float    batV             = 0.0f;
float    tmpC             = 0.0f;
int16_t  rpmR             = 0;
int16_t  rpmL             = 0;
uint8_t  hbChecksumErrors = 0;

// ── Packet parser ───────────────────────────────────────────
uint8_t  pkt[16];
uint8_t  pktIdx           = 0;
uint8_t  synced           = 0;
uint8_t  rxByte           = 0;

// ── Odometry ────────────────────────────────────────────────
float    posX             = 0.0f;
float    posY             = 0.0f;
float    heading          = 0.0f;
float    distCm           = 0.0f;
float    homeX            = 0.0f;
float    homeY            = 0.0f;
float    homeHdg          = 0.0f;
uint32_t lastOdoTime      = 0;

// ── Ultrasonic ──────────────────────────────────────────────
float    dist_FL          = 999.0f;
float    dist_F           = 999.0f;
float    dist_FR          = 999.0f;
uint32_t lastSonarTime    = 0;
uint8_t  sonarIndex       = 0;

// ── Safety ──────────────────────────────────────────────────
uint32_t lastRPiCmd       = 0;
uint8_t  emergStop        = 0;
uint8_t  returning        = 0;
uint8_t  piTimedOut       = 0;

// ── Stepper / NEMA arms ─────────────────────────────────────
uint8_t  stepperRunning[2]  = {0, 0};
int32_t  stepsTarget[2]     = {0, 0};
int32_t  stepsCount[2]      = {0, 0};
uint32_t stepInterval_us[2] = {2000, 2000};
uint32_t lastStepTime_us[2] = {0, 0};

// ── Timing ──────────────────────────────────────────────────
uint32_t lastHBSend       = 0;
uint32_t lastTelSend      = 0;
uint32_t lastLedToggle    = 0;
uint8_t  ledState         = 0;

// ── RPi serial buffer ───────────────────────────────────────
char     rpiBuffer[64];
uint8_t  rpiIdx           = 0;
uint8_t  usbRxBuf[64];
uint32_t usbRxLen         = 0;

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */
void sendFOC(int16_t steer, int16_t speed);
void decodeFeedback(uint8_t* p);
void readHoverboard(void);
float measureDistance(GPIO_TypeDef* trigPort, uint16_t trigPin,
                      GPIO_TypeDef* echoPort, uint16_t echoPin);
void readSonars(void);
uint8_t obstacleAhead(void);
void stepperEnable(uint8_t arm);
void stepperDisable(uint8_t arm);
void stepperMove(uint8_t arm, int32_t steps, uint32_t speed_sps);
void stepperStop(uint8_t arm);
void stepperStopAll(void);
void runStepper(void);
void applyMotorSafety(void);
float distanceToHome(void);
void navigateToHome(void);
void parseCommand(char* cmd);
void readRPi(void);
void sendTelemetry(void);
void sendUSB(const char* msg);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

// ── Microsecond delay using DWT cycle counter ───────────────
void DWT_Init(void) {
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0;
  DWT->CTRL  |= DWT_CTRL_CYCCNTENA_Msk;
}

void delay_us(uint32_t us) {
  uint32_t start = DWT->CYCCNT;
  uint32_t ticks = us * (HAL_RCC_GetHCLKFreq() / 1000000);
  while ((DWT->CYCCNT - start) < ticks);
}

uint32_t micros(void) {
  return DWT->CYCCNT / (HAL_RCC_GetHCLKFreq() / 1000000);
}

// ── Send string via USB CDC ─────────────────────────────────
void sendUSB(const char* msg) {
  for (uint8_t attempt = 0; attempt < 10; attempt++) {
    if (CDC_Transmit_FS((uint8_t*)msg, strlen(msg)) == USBD_OK) {
      return;
    }
    HAL_Delay(1);
  }
}

// ── Hoverboard FOC — send command ───────────────────────────
void sendFOC(int16_t steer, int16_t speed) {
  FOCCmd cmd;
  cmd.start    = 0xABCD;
  cmd.steer    = steer;
  cmd.speed    = speed;
  cmd.checksum = cmd.start ^ cmd.steer ^ cmd.speed;
  HAL_UART_Transmit(&huart1, (uint8_t*)&cmd, sizeof(cmd), 10);
}

// ── Hoverboard FOC — decode feedback + odometry ─────────────
void decodeFeedback(uint8_t* p) {
  FOCFeedback* fb = (FOCFeedback*)p;

  // verify checksum — drop corrupt packets
  uint16_t calc = fb->start    ^ fb->cmd1  ^ fb->cmd2 ^
                  fb->speedR   ^ fb->speedL ^
                  fb->batVoltage ^ fb->boardTemp;
  if (calc != fb->checksum) {
    hbChecksumErrors++;
    return;
  }
  hbChecksumErrors = 0;

  rpmR = fb->speedR;
  rpmL = fb->speedL;
  batV = fb->batVoltage / 100.0f;
  tmpC = fb->boardTemp  / 10.0f;

  // odometry
  uint32_t now = HAL_GetTick();
  float dt = (now - lastOdoTime) / 1000.0f;
  lastOdoTime = now;
  if (dt <= 0.0f || dt > 0.5f) return;

  float vR = -(rpmR * SPEED_SCALE / 60.0f) * WHEEL_CIRC;
  float vL = -(rpmL * SPEED_SCALE / 60.0f) * WHEEL_CIRC;
  float v     = (vR + vL) / 2.0f;
  float omega = (vR - vL) / TRACK_WIDTH;

  posX    += v * cosf(heading) * dt;
  posY    += v * sinf(heading) * dt;
  heading += omega * dt;

  while (heading >  3.14159f) heading -= 2.0f * 3.14159f;
  while (heading < -3.14159f) heading += 2.0f * 3.14159f;

  distCm += fabsf(v) * dt;
}

// ── Hoverboard FOC — parse serial stream ────────────────────
void readHoverboard(void) {
  uint8_t b;
  while (HAL_UART_Receive(&huart1, &b, 1, 0) == HAL_OK) {
    if (!synced) {
      if (pktIdx == 0) {
        if (b == 0xCD) { pkt[0] = b; pktIdx = 1; }
      } else if (pktIdx == 1) {
        if      (b == 0xAB) { pkt[1] = b; pktIdx = 2; synced = 1; }
        else if (b == 0xCD) { pkt[0] = b; pktIdx = 1; }
        else                { pktIdx = 0; }
      }
    } else {
      pkt[pktIdx++] = b;
      if (pktIdx >= 16) {
        decodeFeedback(pkt);
        pktIdx = 0;
        synced = 0;
      }
    }
  }
}

// ── Ultrasonic — measure one sensor ─────────────────────────
float measureDistance(GPIO_TypeDef* trigPort, uint16_t trigPin,
                      GPIO_TypeDef* echoPort, uint16_t echoPin) {
  // send 10us trigger pulse
  HAL_GPIO_WritePin(trigPort, trigPin, GPIO_PIN_RESET);
  delay_us(2);
  HAL_GPIO_WritePin(trigPort, trigPin, GPIO_PIN_SET);
  delay_us(10);
  HAL_GPIO_WritePin(trigPort, trigPin, GPIO_PIN_RESET);

  // wait for echo HIGH with timeout
  uint32_t timeout = HAL_GetTick() + 30;
  while (HAL_GPIO_ReadPin(echoPort, echoPin) == GPIO_PIN_RESET) {
    if (HAL_GetTick() > timeout) return 999.0f;
  }

  uint32_t start = micros();

  // wait for echo LOW with timeout
  timeout = HAL_GetTick() + 30;
  while (HAL_GPIO_ReadPin(echoPort, echoPin) == GPIO_PIN_SET) {
    if (HAL_GetTick() > timeout) return 999.0f;
  }

  uint32_t duration = micros() - start;
  return (duration * 0.034f) / 2.0f;
}

// ── Ultrasonic — fire sequentially ──────────────────────────
void readSonars(void) {
  uint32_t now = HAL_GetTick();
  if (now - lastSonarTime < 60) return;
  lastSonarTime = now;

  switch (sonarIndex) {
    case 0:
      dist_FL = measureDistance(TRIG_FL_PORT, TRIG_FL_PIN,
                                ECHO_FL_PORT, ECHO_FL_PIN);
      break;
    case 1:
      dist_F  = measureDistance(TRIG_F_PORT,  TRIG_F_PIN,
                                ECHO_F_PORT,  ECHO_F_PIN);
      break;
    case 2:
      dist_FR = measureDistance(TRIG_FR_PORT, TRIG_FR_PIN,
                                ECHO_FR_PORT, ECHO_FR_PIN);
      break;
  }
  sonarIndex = (sonarIndex + 1) % 3;
}

uint8_t obstacleAhead(void) {
  return (dist_F  < OBSTACLE_STOP_CM ||
          dist_FL < OBSTACLE_STOP_CM ||
          dist_FR < OBSTACLE_STOP_CM);
}

// ── Stepper control ─────────────────────────────────────────
void stepperEnable(uint8_t arm)  {
  if (arm == 2) HAL_GPIO_WritePin(EN2_PORT, EN2_PIN_NUM, GPIO_PIN_RESET);
  else          HAL_GPIO_WritePin(EN_PORT,  EN_PIN_NUM,  GPIO_PIN_RESET);
}

void stepperDisable(uint8_t arm) {
  if (arm == 2) HAL_GPIO_WritePin(EN2_PORT, EN2_PIN_NUM, GPIO_PIN_SET);
  else          HAL_GPIO_WritePin(EN_PORT,  EN_PIN_NUM,  GPIO_PIN_SET);
}

void stepperMove(uint8_t arm, int32_t steps, uint32_t speed_sps) {
  if (arm < 1 || arm > 2) arm = 1;
  uint8_t idx = arm - 1;

  // steps and speed are intentionally variable. Pi decides bounded values.
  if (speed_sps == 0) speed_sps = 200;
  if (speed_sps > 3000) speed_sps = 3000; // firmware hard ceiling
  stepInterval_us[idx] = 1000000UL / speed_sps;
  stepsTarget[idx]     = labs(steps);
  stepsCount[idx]      = 0;

  if (stepsTarget[idx] == 0) {
    stepperRunning[idx] = 0;
    stepperDisable(arm);
    sendUSB(arm == 2 ? "ACK:ARM2_DONE\r\n" : "ACK:ARM_DONE\r\n");
    return;
  }

  if (arm == 2) {
    HAL_GPIO_WritePin(DIR2_PORT, DIR2_PIN_NUM,
                      steps > 0 ? GPIO_PIN_SET : GPIO_PIN_RESET);
  } else {
    HAL_GPIO_WritePin(DIR_PORT, DIR_PIN_NUM,
                      steps > 0 ? GPIO_PIN_SET : GPIO_PIN_RESET);
  }

  stepperEnable(arm);
  stepperRunning[idx] = 1;
}

void stepperStop(uint8_t arm) {
  if (arm < 1 || arm > 2) arm = 1;
  uint8_t idx = arm - 1;
  stepperRunning[idx] = 0;
  stepperDisable(arm);
}

void stepperStopAll(void) {
  stepperStop(1);
  stepperStop(2);
}

void runStepper(void) {
  uint32_t now = micros();
  for (uint8_t arm = 1; arm <= 2; arm++) {
    uint8_t idx = arm - 1;
    if (!stepperRunning[idx]) continue;
    if (now - lastStepTime_us[idx] >= stepInterval_us[idx]) {
      lastStepTime_us[idx] = now;
      if (arm == 2) {
        HAL_GPIO_WritePin(STEP2_PORT, STEP2_PIN_NUM, GPIO_PIN_SET);
        delay_us(2);
        HAL_GPIO_WritePin(STEP2_PORT, STEP2_PIN_NUM, GPIO_PIN_RESET);
      } else {
        HAL_GPIO_WritePin(STEP_PORT, STEP_PIN_NUM, GPIO_PIN_SET);
        delay_us(2);
        HAL_GPIO_WritePin(STEP_PORT, STEP_PIN_NUM, GPIO_PIN_RESET);
      }

      stepsCount[idx]++;
      if (stepsCount[idx] >= stepsTarget[idx]) {
        stepperRunning[idx] = 0;
        stepperDisable(arm);
        sendUSB(arm == 2 ? "ACK:ARM2_DONE\r\n" : "ACK:ARM_DONE\r\n");
      }
    }
  }
}

// ── Safety layer — runs every loop ──────────────────────────
void applyMotorSafety(void) {

  // emergency button — active LOW
  if (HAL_GPIO_ReadPin(EMERG_PORT, EMERG_PIN) == GPIO_PIN_RESET) {
    emergStop = 1;
  }

  // RPi timeout
  if (HAL_GetTick() - lastRPiCmd > PI_TIMEOUT_MS) {
    if (!piTimedOut) {
      piTimedOut = 1;
      sendUSB("ALERT:PI_TIMEOUT\r\n");
    }
    cmdSpeed = 0;
    cmdSteer = 0;
  } else {
    piTimedOut = 0;
  }

  // low battery
  if (batV > 1.0f && batV < BAT_MIN_VOLTAGE) {
    cmdSpeed = 0;
    cmdSteer = 0;
    sendUSB("ALERT:BATTERY_LOW\r\n");
  }

  // hoverboard comms error
  if (hbChecksumErrors >= HB_ERROR_MAX) {
    cmdSpeed = 0;
    cmdSteer = 0;
    sendUSB("ALERT:HOVERBOARD_ERROR\r\n");
  }

  // obstacle blocks forward motion
  if (cmdSpeed < 0 && obstacleAhead()) {
    cmdSpeed = 0;
    sendUSB("ALERT:OBSTACLE_FRONT\r\n");
  }

  // emergency stop — absolute override
  if (emergStop) {
    cmdSpeed = 0;
    cmdSteer = 0;
    stepperStopAll();
  }
}

// ── Return to base — odometry guided ────────────────────────
float distanceToHome(void) {
  float dx = posX - homeX;
  float dy = posY - homeY;
  return sqrtf(dx * dx + dy * dy);
}

void navigateToHome(void) {
  if (distanceToHome() < HOME_THRESHOLD_CM) {
    cmdSpeed  = 0;
    cmdSteer  = 0;
    returning = 0;
    posX      = homeX;
    posY      = homeY;
    heading   = homeHdg;
    sendUSB("ACK:RETURN_COMPLETE\r\n");
    return;
  }

  float dx          = homeX - posX;
  float dy          = homeY - posY;
  float targetAngle = atan2f(dy, dx);
  float error       = targetAngle - heading;

  while (error >  3.14159f) error -= 2.0f * 3.14159f;
  while (error < -3.14159f) error += 2.0f * 3.14159f;

  int16_t steer = (int16_t)(error * 120.0f);
  if (steer >  300) steer =  300;
  if (steer < -300) steer = -300;

  int16_t speed = RETURN_SPEED;

  if (obstacleAhead()) {
    speed = 0;
    steer = 0;
  }

  cmdSpeed = speed;
  cmdSteer = steer;
}

// ── RPi command parser ───────────────────────────────────────
void parseCommand(char* cmd) {
  lastRPiCmd = HAL_GetTick();
  emergStop  = 0;

  if (strncmp(cmd, "CMD:STOP", 8) == 0) {
    cmdSpeed  = 0;
    cmdSteer  = 0;
    returning = 0;
    stepperStopAll();
    sendUSB("ACK:STOP\r\n");
  }
  else if (strncmp(cmd, "CMD:DRIVE:", 10) == 0) {
    if (!returning) {
      char*   p   = cmd + 10;
      int16_t spd = (int16_t)atoi(p);
      char*   comma = strchr(p, ',');
      int16_t str   = comma ? (int16_t)atoi(comma + 1) : 0;
      cmdSpeed = spd;
      cmdSteer = str;
    }
    sendUSB("ACK:DRIVE\r\n");
  }
  else if (strncmp(cmd, "CMD:ARM:", 8) == 0) {
    char*    p     = cmd + 8;
    int32_t  steps = atol(p);
    char*    comma = strchr(p, ',');
    uint32_t spd   = comma ? (uint32_t)atol(comma + 1) : 200;
    sendUSB("ACK:ARM\r\n");
    stepperMove(1, steps, spd);
  }
  else if (strncmp(cmd, "CMD:ARM2:", 9) == 0) {
    char*    p     = cmd + 9;
    int32_t  steps = atol(p);
    char*    comma = strchr(p, ',');
    uint32_t spd   = comma ? (uint32_t)atol(comma + 1) : 200;
    sendUSB("ACK:ARM2\r\n");
    stepperMove(2, steps, spd);
  }
  else if (strncmp(cmd, "CMD:RETURN", 10) == 0) {
    returning = 1;
    sendUSB("ACK:RETURN\r\n");
  }
  else if (strncmp(cmd, "CMD:PING", 8) == 0) {
    sendUSB("ACK:PING\r\n");
  }
  else if (strncmp(cmd, "CMD:RESET_HOME", 14) == 0) {
    homeX   = posX;
    homeY   = posY;
    homeHdg = heading;
    sendUSB("ACK:RESET_HOME\r\n");
  }
  else if (strncmp(cmd, "CMD:RESET_ODOM", 14) == 0) {
    posX = 0; posY = 0;
    heading = 0; distCm = 0;
    homeX = 0; homeY = 0; homeHdg = 0;
    sendUSB("ACK:RESET_ODOM\r\n");
  }
}

// ── Process incoming USB bytes ───────────────────────────────
void readRPi(void) {
  for (uint32_t i = 0; i < usbRxLen; i++) {
    char c = (char)usbRxBuf[i];
    if (c == '\n' || c == '\r') {
      if (rpiIdx > 0) {
        rpiBuffer[rpiIdx] = '\0';
        parseCommand(rpiBuffer);
        rpiIdx = 0;
      }
    } else {
      if (rpiIdx < 63) rpiBuffer[rpiIdx++] = c;
    }
  }
  usbRxLen = 0;
}

// ── USB receive callback (called by USB CDC driver) ──────────
// Add this to usbd_cdc_if.c in the CDC_Receive_FS function:
// extern uint8_t usbRxBuf[64];
// extern uint32_t usbRxLen;
// memcpy(usbRxBuf, Buf, *Len);
// usbRxLen = *Len;

// ── Telemetry to RPi ────────────────────────────────────────
void sendTelemetry(void) {
  char buf[192];
  float headingDeg = heading * 57.29578f;
  while (headingDeg >  180.0f) headingDeg -= 360.0f;
  while (headingDeg < -180.0f) headingDeg += 360.0f;

  snprintf(buf, sizeof(buf),
    "TEL:BAT:%.1f,SPD:%.1f,DIST:%.0f,TEMP:%.1f,X:%.1f,Y:%.1f,H:%.1f,HOME:%.1f,RET:%u\r\n",
    batV,
    fabsf((float)cmdSpeed) * 0.036f,
    distCm,
    tmpC,
    posX,
    posY,
    headingDeg,
    distanceToHome(),
    returning);
  sendUSB(buf);

  snprintf(buf, sizeof(buf),
    "OBS:FL:%.0f,F:%.0f,FR:%.0f\r\n",
    dist_FL, dist_F, dist_FR);
  sendUSB(buf);
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */
  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_USART1_UART_Init();
  MX_USB_DEVICE_Init();
  /* USER CODE BEGIN 2 */

  // init microsecond timer
  DWT_Init();

  // stamp boot time
  lastOdoTime = HAL_GetTick();
  lastRPiCmd  = HAL_GetTick();

  // steppers disabled at boot
  stepperDisable(1);
  stepperDisable(2);

  // all TRIG pins LOW
  HAL_GPIO_WritePin(TRIG_FL_PORT, TRIG_FL_PIN, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(TRIG_F_PORT,  TRIG_F_PIN,  GPIO_PIN_RESET);
  HAL_GPIO_WritePin(TRIG_FR_PORT, TRIG_FR_PIN, GPIO_PIN_RESET);

  // wait for USB CDC to enumerate on RPi
  HAL_Delay(1500);

  // identify to RPi
  sendUSB("ID:STM32_MOTOR\r\n");

  // boot confirmation — 3 LED blinks
  for (int i = 0; i < 3; i++) {
    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET); // ON
    HAL_Delay(120);
    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);   // OFF
    HAL_Delay(120);
  }

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    // 1 — read hoverboard feedback
    readHoverboard();

    // 2 — process RPi commands
    readRPi();

    // 3 — read ultrasonic sensors (sequential)
    readSonars();

    // 4 — run stepper pulses
    runStepper();

    // 5 — navigate home if returning
    if (returning) {
      navigateToHome();
    }

    // 6 — safety layer (always last before send)
    applyMotorSafety();

    // 7 — send FOC command every 20ms
    if (HAL_GetTick() - lastHBSend >= 20) {
      lastHBSend = HAL_GetTick();
      sendFOC(cmdSteer, cmdSpeed);
    }

    // 8 — send telemetry every 100ms
    if (HAL_GetTick() - lastTelSend >= 100) {
      lastTelSend = HAL_GetTick();
      sendTelemetry();
    }

    // 9 — heartbeat with fade
    // DUM-dum then slow fade to off
    static uint32_t beatTimer = 0;
    static uint8_t  beatPhase = 0;
    static uint16_t pwmVal    = 0;

    uint32_t elapsed = HAL_GetTick() - beatTimer;

    if (!emergStop) {
      switch (beatPhase) {
        case 0: // beat 1 ON
          HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
          if (elapsed >= 80) { beatPhase = 1; beatTimer = HAL_GetTick(); }
          break;
        case 1: // beat 1 OFF briefly
          HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
          if (elapsed >= 80) { beatPhase = 2; beatTimer = HAL_GetTick(); }
          break;
        case 2: // beat 2 ON
          HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
          if (elapsed >= 80) { beatPhase = 3; beatTimer = HAL_GetTick(); pwmVal = 0; }
          break;
        case 3: // slow fade OFF using software PWM
          pwmVal += 3;
          if (pwmVal > 100) pwmVal = 100;
          // software PWM — LED on for (100-pwmVal)% of 1ms
          HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
          delay_us((100 - pwmVal) * 4);
          HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
          delay_us(pwmVal * 4);
          if (pwmVal >= 100) { beatPhase = 4; beatTimer = HAL_GetTick(); }
          break;
        case 4: // long pause before next heartbeat
          HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
          if (elapsed >= 700) { beatPhase = 0; beatTimer = HAL_GetTick(); }
          break;
      }
    } else {
      // emergency — rapid flash
      if (HAL_GetTick() - lastLedToggle >= 80) {
        lastLedToggle = HAL_GetTick();
        ledState = !ledState;
        HAL_GPIO_WritePin(LED_PORT, LED_PIN,
                          ledState ? GPIO_PIN_RESET : GPIO_PIN_SET);
      }
    }
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE2);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 25;
  RCC_OscInitStruct.PLL.PLLN = 336;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV4;
  RCC_OscInitStruct.PLL.PLLQ = 7;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */
/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
