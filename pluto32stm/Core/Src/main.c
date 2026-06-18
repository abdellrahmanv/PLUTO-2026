/* ============================================================================
 * PLUTO ROBOT — STM32F401 Black Pill
 * Firmware v2.0 — Real Architecture
 * Spirit Robotics
 * ============================================================================
 *
 * EXECUTION MODEL:
 *   Every subsystem owns its own timing. Main loop is orchestration only.
 *   Nothing in the main loop blocks or times pulses.
 *
 * INTERRUPT PRIORITY TABLE (lower number = higher priority):
 *   PreemptPriority 0 — TIM3 (Stepper ISR)         ← highest, untouchable
 *   PreemptPriority 1 — EXTI1/5/7 (Sonar Echo)     ← fast capture
 *   PreemptPriority 2 — USART1 (Hoverboard)        ← stream decode
 *   PreemptPriority 3 — USB OTG FS                 ← command intake
 *   PreemptPriority 15 — SysTick (HAL)             ← lowest
 *
 * OWNERSHIP MAP:
 *   TIM3 ISR        → stepper pulse generation, ramp, step counting
 *   EXTI1/5/7 ISR   → sonar echo timing (DWT capture)
 *   USART1 ISR      → hoverboard byte stream intake
 *   USB CDC ISR     → ring buffer write
 *   Main Loop       → command parse, safety, FOC send, telemetry, odometry
 *
 * PIN MAP:
 *   PA9   → Hoverboard TX (USART1)
 *   PA10  → Hoverboard RX (USART1)
 *   PA11  → USB D-  (CDC to Raspberry Pi)
 *   PA12  → USB D+  (CDC to Raspberry Pi)
 *   PA0   → HC-SR04 Front-Left  TRIG
 *   PA1   → HC-SR04 Front-Left  ECHO  ← EXTI1
 *   PA4   → HC-SR04 Front       TRIG
 *   PA5   → HC-SR04 Front       ECHO  ← EXTI5
 *   PA6   → HC-SR04 Front-Right TRIG
 *   PA7   → HC-SR04 Front-Right ECHO  ← EXTI7 (shared with EXTI9_5)
 *   PB8   → NEMA Arm 1 STEP
 *   PB9   → NEMA Arm 1 DIR
 *   PB10  → NEMA Arm 1 EN  (LOW = enabled)
 *   PB12  → NEMA Arm 2 STEP
 *   PB13  → NEMA Arm 2 DIR
 *   PB14  → NEMA Arm 2 EN  (LOW = enabled)
 *   PB0   → Emergency button (INPUT_PULLUP)
 *   PC13  → Status LED (active LOW)
 * ============================================================================
 */

#include "main.h"
#include "usart.h"
#include "usb_device.h"
#include "gpio.h"
#include "usbd_cdc_if.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* ============================================================================
 * STRUCTS
 * ============================================================================ */
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

/* ============================================================================
 * CONSTANTS
 * ============================================================================ */
#define WHEEL_CIRC          53.4f
#define TRACK_WIDTH         54.0f
#define SPEED_SCALE         1.0f

#define OBSTACLE_STOP_CM    60
#define OBSTACLE_SLOW_CM    100
#define PI_TIMEOUT_MS       1000
#define HOME_THRESHOLD_CM   15
#define RETURN_SPEED        -25
#define BAT_MIN_VOLTAGE     34.0f
#define HB_ERROR_MAX        3

// Stepper constants
#define STEPPER_MAX_SPS     3000
#define STEPPER_MIN_SPS     2000
#define STEPPER_MAX_STEPS   12000L

// TB6600 common-anode configuration
#define STEPPER_PULSE_US       50U
#define STEPPER_COMMON_ANODE   1U
#define STEPPER_EN_USED        1U

#if STEPPER_COMMON_ANODE
#define STEPPER_STEP_ACTIVE    GPIO_PIN_RESET
#define STEPPER_STEP_IDLE      GPIO_PIN_SET
#define STEPPER_DIR_POSITIVE   GPIO_PIN_RESET
#define STEPPER_DIR_NEGATIVE   GPIO_PIN_SET
#else
#define STEPPER_STEP_ACTIVE    GPIO_PIN_SET
#define STEPPER_STEP_IDLE      GPIO_PIN_RESET
#define STEPPER_DIR_POSITIVE   GPIO_PIN_SET
#define STEPPER_DIR_NEGATIVE   GPIO_PIN_RESET
#endif

#define STEPPER_EN_ACTIVE      GPIO_PIN_RESET
#define STEPPER_EN_IDLE        GPIO_PIN_SET

// TIM3 base tick at 1MHz (1us per tick)
#define TIM3_PRESCALER      (84 - 1)   // 84MHz / 84 = 1MHz tick

// Sonar
#define SONAR_TRIGGER_US    10
#define SONAR_CYCLE_MS      60          // one sonar per 60ms → full scan = 180ms
#define SONAR_TIMEOUT_CYCLES (84000000 / 1000 * 30)  // 30ms in cycles

// IMU / MPU6050
#define IMU_REG_PWR_MGMT_1  0x6B
#define IMU_REG_WHO_AM_I    0x75
#define IMU_REG_DATA_START  0x3B

#define IMU_SCL_GPIO_Port   GPIOB
#define IMU_SCL_Pin         GPIO_PIN_6
#define IMU_SDA_GPIO_Port   GPIOB
#define IMU_SDA_Pin         GPIO_PIN_7

/* ============================================================================
 * GPIO MACROS
 * ============================================================================ */
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

/* ============================================================================
 * USB RING BUFFER
 * ============================================================================ */
#define USB_RING_SIZE       256   // must be power of 2
#define USB_RING_MASK       (USB_RING_SIZE - 1)

volatile uint8_t  usbRing[USB_RING_SIZE];
volatile uint16_t usbRingHead = 0;   // written by ISR only
volatile uint16_t usbRingTail = 0;   // read/written by main loop only
volatile uint8_t  usbRxOverflow = 0;

/* ============================================================================
 * HOVERBOARD UART RING BUFFER
 * ============================================================================ */
#define HB_RING_SIZE        64
#define HB_RING_MASK        (HB_RING_SIZE - 1)

volatile uint8_t  hbRing[HB_RING_SIZE];
volatile uint16_t hbRingHead = 0;
volatile uint16_t hbRingTail = 0;
uint8_t           hbRxByte   = 0;   // single-byte UART interrupt receiver

/* ============================================================================
 * STEPPER STATE — shared between main and TIM3 ISR
 * ============================================================================ */
typedef struct {
    volatile uint8_t  running;          // ISR clears when done
    volatile int32_t  stepsTarget;
    volatile int32_t  stepsCount;
    volatile uint32_t currentPeriod_us; // TIM3 period for this arm
    volatile uint32_t targetPeriod_us;
    volatile uint8_t  doneFlag;         // ISR sets, main reads+clears to send ACK
    GPIO_TypeDef*     stepPort;
    uint16_t          stepPin;
    GPIO_TypeDef*     enPort;
    uint16_t          enPin;
    // Dynamic acceleration variables
    volatile float    speedCurrent_sps;
    volatile float    speedMax_sps;
    volatile uint32_t accel_sps2;
    volatile int32_t  decelSteps;
} StepperState;

StepperState stepper[2];
TIM_HandleTypeDef htim3;

/* ============================================================================
 * SONAR STATE — written by EXTI ISR, read by main loop
 * ============================================================================ */
typedef enum {
    SONAR_IDLE = 0,
    SONAR_TRIGGERED,
    SONAR_CAPTURING
} SonarPhase;

typedef struct {
    volatile SonarPhase phase;
    volatile uint32_t   echoStart;   // DWT cycles
    volatile uint32_t   echoEnd;
    volatile float      distCm;
    volatile uint8_t    fresh;       // ISR sets, main reads+clears
    GPIO_TypeDef*       trigPort;
    uint16_t            trigPin;
    GPIO_TypeDef*       echoPort;
    uint16_t            echoPin;
    uint16_t            extiPin;     // for GPIO_Pin matching in callback
} SonarState;

SonarState sonar[3];

uint8_t  sonarIndex   = 0;
uint32_t lastSonarMs  = 0;

/* ============================================================================
 * HOVERBOARD STATE
 * ============================================================================ */
int16_t  cmdSpeed         = 0;
int16_t  cmdSteer         = 0;
float    batV             = 0.0f;
float    tmpC             = 0.0f;
int16_t  rpmR             = 0;
int16_t  rpmL             = 0;
uint8_t  hbChecksumErrors = 0;

// Packet parser state (main loop)
uint8_t  pkt[16];
uint8_t  pktIdx  = 0;
uint8_t  synced  = 0;

/* ============================================================================
 * ODOMETRY
 * ============================================================================ */
float    posX    = 0.0f;
float    posY    = 0.0f;
float    heading = 0.0f;
float    distCm  = 0.0f;
float    homeX   = 0.0f;
float    homeY   = 0.0f;
float    homeHdg = 0.0f;
uint32_t lastOdoTime = 0;

/* ============================================================================
 * SAFETY FLAGS
 * ============================================================================ */
uint32_t lastRPiCmd = 0;
uint8_t  emergStop  = 0;
uint8_t  returning  = 0;
uint8_t  piTimedOut = 0;

/* ============================================================================
 * IMU STATE
 * ============================================================================ */
uint8_t  imuPresent        = 0;
uint8_t  imuAddr           = 0;
uint8_t  imuWhoAmI         = 0;
int16_t  imuAx             = 0;
int16_t  imuAy             = 0;
int16_t  imuAz             = 0;
int16_t  imuGx             = 0;
int16_t  imuGy             = 0;
int16_t  imuGz             = 0;
float    imuTempC          = 0.0f;
uint32_t lastImuRead       = 0;

/* ============================================================================
 * TIMING
 * ============================================================================ */
uint32_t lastHBSend  = 0;
uint32_t lastTelSend = 0;
uint32_t lastLedToggle = 0;
uint8_t  ledState    = 0;

/* ============================================================================
 * RPi COMMAND BUFFER (main loop only)
 * ============================================================================ */
char    rpiBuffer[64];
uint8_t rpiIdx = 0;

/* ============================================================================
 * FUNCTION PROTOTYPES
 * ============================================================================ */
void     SystemClock_Config(void);
void     DWT_Init(void);
void     delay_us(uint32_t us);
void     sendUSB(const char* msg);

// Stepper
void     stepperInit(void);
void     stepperEnable(uint8_t idx);
void     stepperDisable(uint8_t idx);
void     stepperMove(uint8_t idx, int32_t steps, uint32_t speed_sps, uint32_t accel);
void     stepperStop(uint8_t idx);
void     stepperStopAll(void);
void     stepperCheckDone(void);

// Sonar
void     sonarInit(void);
void     sonarTrigger(uint8_t idx);
void     sonarUpdate(void);
uint8_t  obstacleAhead(void);

// Hoverboard
void     hbUartInit(void);
void     sendFOC(int16_t steer, int16_t speed);
void     decodeFeedback(uint8_t* p);
void     readHoverboard(void);

// RPi
void     readRPi(void);
void     parseCommand(char* cmd);
uint8_t  parseArmPayload(const char* payload, int32_t* steps, uint32_t* speed_sps);
void     sendTelemetry(void);

// Safety / navigation
void     applyMotorSafety(void);
float    distanceToHome(void);
void     navigateToHome(void);

// IMU
void     imuBusInit(void);
uint8_t  imuInit(void);
void     readIMU(void);

/* ============================================================================
 * DWT MICROSECOND UTILITIES
 * ============================================================================ */
void DWT_Init(void) {
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL  |= DWT_CTRL_CYCCNTENA_Msk;
}

// Blocking microsecond delay
void delay_us(uint32_t us) {
    uint32_t start = DWT->CYCCNT;
    uint32_t ticks = us * (SystemCoreClock / 1000000UL);
    while ((DWT->CYCCNT - start) < ticks);
}

/* ============================================================================
 * USB TRANSMIT
 * ============================================================================ */
void sendUSB(const char* msg) {
    for (uint8_t attempt = 0; attempt < 10; attempt++) {
        if (CDC_Transmit_FS((uint8_t*)msg, strlen(msg)) == USBD_OK) return;
        HAL_Delay(1);
    }
}

/* ============================================================================
 * STEPPER — TIM3 ISR ARCHITECTURE
 * ============================================================================ */
void stepperInit(void) {
    // ARM 0 — PB8 STEP, PB10 EN
    stepper[0].stepPort       = STEP_PORT;
    stepper[0].stepPin        = STEP_PIN_NUM;
    stepper[0].enPort         = EN_PORT;
    stepper[0].enPin          = EN_PIN_NUM;
    stepper[0].running        = 0;
    stepper[0].doneFlag       = 0;

    // ARM 1 — PB12 STEP, PB14 EN
    stepper[1].stepPort       = STEP2_PORT;
    stepper[1].stepPin        = STEP2_PIN_NUM;
    stepper[1].enPort         = EN2_PORT;
    stepper[1].enPin          = EN2_PIN_NUM;
    stepper[1].running        = 0;
    stepper[1].doneFlag       = 0;

    // Configure TIM3
    __HAL_RCC_TIM3_CLK_ENABLE();

    htim3.Instance               = TIM3;
    htim3.Init.Prescaler         = TIM3_PRESCALER;   // 1MHz tick
    htim3.Init.CounterMode       = TIM_COUNTERMODE_UP;
    htim3.Init.Period            = 5000;             // 5ms default (200 SPS idle)
    htim3.Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
    htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;

    HAL_TIM_Base_Init(&htim3);

    // Priority 0 — highest priority on system
    HAL_GPIO_WritePin(EN_PORT, EN_PIN_NUM, STEPPER_EN_IDLE);
    HAL_GPIO_WritePin(EN2_PORT, EN2_PIN_NUM, STEPPER_EN_IDLE);
    HAL_GPIO_WritePin(STEP_PORT, STEP_PIN_NUM, STEPPER_STEP_IDLE);
    HAL_GPIO_WritePin(STEP2_PORT, STEP2_PIN_NUM, STEPPER_STEP_IDLE);

    HAL_NVIC_SetPriority(TIM3_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(TIM3_IRQn);

    HAL_TIM_Base_Start_IT(&htim3);
}

// TIM3 ISR — handles pulse timing and generation
void TIM3_IRQHandler(void) {
    if (__HAL_TIM_GET_FLAG(&htim3, TIM_FLAG_UPDATE) &&
        __HAL_TIM_GET_IT_SOURCE(&htim3, TIM_IT_UPDATE)) {

        __HAL_TIM_CLEAR_IT(&htim3, TIM_IT_UPDATE);

        static uint8_t armTurn = 0;  // interleave arms to share timer
        uint8_t idx = armTurn;
        armTurn = 1 - armTurn;

        if (!stepper[idx].running) return;

        // Dynamic acceleration/deceleration calculations
        if (stepper[idx].accel_sps2 > 0) {
            float dt = stepper[idx].currentPeriod_us / 1000000.0f;
            int32_t stepsRemaining = stepper[idx].stepsTarget - stepper[idx].stepsCount;
            
            if (stepsRemaining <= stepper[idx].decelSteps) {
                stepper[idx].speedCurrent_sps -= stepper[idx].accel_sps2 * dt;
                if (stepper[idx].speedCurrent_sps < 100.0f) {
                    stepper[idx].speedCurrent_sps = 100.0f;
                }
            } else if (stepper[idx].speedCurrent_sps < stepper[idx].speedMax_sps) {
                stepper[idx].speedCurrent_sps += stepper[idx].accel_sps2 * dt;
                if (stepper[idx].speedCurrent_sps > stepper[idx].speedMax_sps) {
                    stepper[idx].speedCurrent_sps = stepper[idx].speedMax_sps;
                }
            }
            stepper[idx].currentPeriod_us = 1000000UL / (uint32_t)stepper[idx].speedCurrent_sps;
        }

        // Update timer auto-reload value
        __HAL_TIM_SET_AUTORELOAD(&htim3, stepper[idx].currentPeriod_us);

        // Generate STEP pulse using configured active/idle states
        HAL_GPIO_WritePin(stepper[idx].stepPort, stepper[idx].stepPin, STEPPER_STEP_ACTIVE);
        delay_us(STEPPER_PULSE_US);
        HAL_GPIO_WritePin(stepper[idx].stepPort, stepper[idx].stepPin, STEPPER_STEP_IDLE);

        stepper[idx].stepsCount++;

        if (stepper[idx].stepsCount >= stepper[idx].stepsTarget) {
            stepper[idx].running  = 0;
            stepper[idx].doneFlag = 1;
            stepperDisable(idx);
        }
    }
}

void stepperEnable(uint8_t idx) {
    if (idx == 1) HAL_GPIO_WritePin(EN2_PORT, EN2_PIN_NUM, STEPPER_EN_ACTIVE);
    else          HAL_GPIO_WritePin(EN_PORT,  EN_PIN_NUM,  STEPPER_EN_ACTIVE);
}

void stepperDisable(uint8_t idx) {
    if (idx == 1) {
        HAL_GPIO_WritePin(STEP2_PORT, STEP2_PIN_NUM, STEPPER_STEP_IDLE);
        HAL_GPIO_WritePin(EN2_PORT, EN2_PIN_NUM, STEPPER_EN_IDLE);
    } else {
        HAL_GPIO_WritePin(STEP_PORT, STEP_PIN_NUM, STEPPER_STEP_IDLE);
        HAL_GPIO_WritePin(EN_PORT, EN_PIN_NUM, STEPPER_EN_IDLE);
    }
}

void stepperMove(uint8_t idx, int32_t steps, uint32_t speed_sps, uint32_t accel) {
    if (idx > 1) return;

    if (speed_sps < STEPPER_MIN_SPS) speed_sps = STEPPER_MIN_SPS;
    if (speed_sps > STEPPER_MAX_SPS) speed_sps = STEPPER_MAX_SPS;

    // Set direction using configured direction macro
    GPIO_TypeDef* dirPort = (idx == 0) ? DIR_PORT  : DIR2_PORT;
    uint16_t      dirPin  = (idx == 0) ? DIR_PIN_NUM : DIR2_PIN_NUM;
    HAL_GPIO_WritePin(dirPort, dirPin, steps > 0 ? STEPPER_DIR_POSITIVE : STEPPER_DIR_NEGATIVE);

    // Arm the ISR state
    stepper[idx].stepsTarget      = labs(steps);
    stepper[idx].stepsCount       = 0;
    stepper[idx].speedMax_sps     = (float)speed_sps;
    stepper[idx].accel_sps2       = accel;
    stepper[idx].doneFlag         = 0;

    if (accel > 0) {
        stepper[idx].speedCurrent_sps = 100.0f;
        int32_t stepsToMax = (speed_sps * speed_sps) / (2 * accel);
        if (stepper[idx].stepsTarget < 2 * stepsToMax) {
            stepper[idx].decelSteps = stepper[idx].stepsTarget / 2;
        } else {
            stepper[idx].decelSteps = stepsToMax;
        }
    } else {
        stepper[idx].speedCurrent_sps = (float)speed_sps;
        stepper[idx].decelSteps = 0;
    }

    stepper[idx].currentPeriod_us = 1000000UL / (uint32_t)stepper[idx].speedCurrent_sps;
    stepper[idx].targetPeriod_us  = 1000000UL / speed_sps;

    stepperEnable(idx);

    // Memory barrier ensures writes complete before ISR sees running flag
    __DSB();
    stepper[idx].running = 1;
}

void stepperStop(uint8_t idx) {
    stepper[idx].running = 0;
    stepperDisable(idx);
}

void stepperStopAll(void) {
    stepperStop(0);
    stepperStop(1);
}

// Checks if ISR completed movements, and sends ACKs to USB
void stepperCheckDone(void) {
    if (stepper[0].doneFlag) {
        stepper[0].doneFlag = 0;
        sendUSB("ACK:ARM_DONE\r\n");
    }
    if (stepper[1].doneFlag) {
        stepper[1].doneFlag = 0;
        sendUSB("ACK:ARM2_DONE\r\n");
    }
}

/* ============================================================================
 * SONAR — EXTI ARCHITECTURE
 * ============================================================================ */
void sonarInit(void) {
    sonar[0].trigPort = TRIG_FL_PORT; sonar[0].trigPin = TRIG_FL_PIN;
    sonar[0].echoPort = ECHO_FL_PORT; sonar[0].echoPin = ECHO_FL_PIN;
    sonar[0].extiPin  = GPIO_PIN_1;
    sonar[0].distCm   = 999.0f;
    sonar[0].phase    = SONAR_IDLE;

    sonar[1].trigPort = TRIG_F_PORT;  sonar[1].trigPin = TRIG_F_PIN;
    sonar[1].echoPort = ECHO_F_PORT;  sonar[1].echoPin = ECHO_F_PIN;
    sonar[1].extiPin  = GPIO_PIN_5;
    sonar[1].distCm   = 999.0f;
    sonar[1].phase    = SONAR_IDLE;

    sonar[2].trigPort = TRIG_FR_PORT; sonar[2].trigPin = TRIG_FR_PIN;
    sonar[2].echoPort = ECHO_FR_PORT; sonar[2].echoPin = ECHO_FR_PIN;
    sonar[2].extiPin  = GPIO_PIN_7;
    sonar[2].distCm   = 999.0f;
    sonar[2].phase    = SONAR_IDLE;

    // Reconfigure echo pins as EXTI both-edge triggered
    GPIO_InitTypeDef g = {0};
    g.Mode  = GPIO_MODE_IT_RISING_FALLING;
    g.Pull  = GPIO_PULLDOWN;
    g.Speed = GPIO_SPEED_FREQ_HIGH;

    g.Pin = GPIO_PIN_1;
    HAL_GPIO_Init(GPIOA, &g);
    g.Pin = GPIO_PIN_5;
    HAL_GPIO_Init(GPIOA, &g);
    g.Pin = GPIO_PIN_7;
    HAL_GPIO_Init(GPIOA, &g);

    // EXTI1 — PA1 (FL echo)
    HAL_NVIC_SetPriority(EXTI1_IRQn, 1, 0);
    HAL_NVIC_EnableIRQ(EXTI1_IRQn);

    // EXTI9_5 — PA5 (F echo) and PA7 (FR echo) share this vector
    HAL_NVIC_SetPriority(EXTI9_5_IRQn, 1, 0);
    HAL_NVIC_EnableIRQ(EXTI9_5_IRQn);
}

// EXTI callback — timed using DWT cycles (prevents clock wrap issues)
void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin) {
    for (uint8_t i = 0; i < 3; i++) {
        if (GPIO_Pin != sonar[i].extiPin) continue;
        if (sonar[i].phase != SONAR_CAPTURING) return;

        if (HAL_GPIO_ReadPin(sonar[i].echoPort, sonar[i].echoPin) == GPIO_PIN_SET) {
            sonar[i].echoStart = DWT->CYCCNT;
        } else {
            sonar[i].echoEnd = DWT->CYCCNT;
            uint32_t cycles = sonar[i].echoEnd - sonar[i].echoStart;
            if (cycles < SONAR_TIMEOUT_CYCLES) {
                // distance = (cycles / 84MHz) * 34000 cm/s / 2
                sonar[i].distCm = ((float)cycles / 84000000.0f) * 17000.0f;
            } else {
                sonar[i].distCm = 999.0f;
            }
            sonar[i].fresh = 1;
            sonar[i].phase = SONAR_IDLE;
        }
        return;
    }
}

// ISR Handlers
void EXTI1_IRQHandler(void)   { HAL_GPIO_EXTI_IRQHandler(GPIO_PIN_1); }
void EXTI9_5_IRQHandler(void) {
    HAL_GPIO_EXTI_IRQHandler(GPIO_PIN_5);
    HAL_GPIO_EXTI_IRQHandler(GPIO_PIN_7);
}
void USART1_IRQHandler(void) {
    HAL_UART_IRQHandler(&huart1);
}

// Triggers sonar measurement
void sonarTrigger(uint8_t idx) {
    sonar[idx].phase = SONAR_CAPTURING;
    sonar[idx].fresh = 0;

    HAL_GPIO_WritePin(sonar[idx].trigPort, sonar[idx].trigPin, GPIO_PIN_RESET);
    delay_us(2);
    HAL_GPIO_WritePin(sonar[idx].trigPort, sonar[idx].trigPin, GPIO_PIN_SET);
    delay_us(10);
    HAL_GPIO_WritePin(sonar[idx].trigPort, sonar[idx].trigPin, GPIO_PIN_RESET);
}

// Rotates trigger to next sonar sequentially
void sonarUpdate(void) {
    uint32_t now = HAL_GetTick();
    if (now - lastSonarMs < SONAR_CYCLE_MS) return;
    lastSonarMs = now;

    if (sonar[sonarIndex].phase == SONAR_IDLE) {
        sonarTrigger(sonarIndex);
        sonarIndex = (sonarIndex + 1) % 3;
    }
}

uint8_t obstacleAhead(void) {
    return (sonar[1].distCm < OBSTACLE_STOP_CM ||
            sonar[0].distCm < OBSTACLE_STOP_CM ||
            sonar[2].distCm < OBSTACLE_STOP_CM);
}

/* ============================================================================
 * HOVERBOARD UART
 * ============================================================================ */
void hbUartInit(void) {
    // Enable USART1 Interrupt in NVIC with Priority 2
    HAL_NVIC_SetPriority(USART1_IRQn, 2, 0);
    HAL_NVIC_EnableIRQ(USART1_IRQn);

    // Start single-byte interrupt receive
    HAL_UART_Receive_IT(&huart1, &hbRxByte, 1);
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart) {
    if (huart->Instance == USART1) {
        hbRing[hbRingHead & HB_RING_MASK] = hbRxByte;
        hbRingHead++;
        HAL_UART_Receive_IT(&huart1, &hbRxByte, 1);
    }
}

void sendFOC(int16_t steer, int16_t speed) {
    FOCCmd cmd;
    cmd.start    = 0xABCD;
    cmd.steer    = steer;
    cmd.speed    = speed;
    cmd.checksum = cmd.start ^ cmd.steer ^ cmd.speed;
    HAL_UART_Transmit(&huart1, (uint8_t*)&cmd, sizeof(cmd), 10);
}

void decodeFeedback(uint8_t* p) {
    FOCFeedback* fb = (FOCFeedback*)p;
    uint16_t calc = fb->start ^ fb->cmd1 ^ fb->cmd2 ^
                    fb->speedR ^ fb->speedL ^
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

void readHoverboard(void) {
    while (hbRingTail != hbRingHead) {
        uint8_t b = hbRing[hbRingTail & HB_RING_MASK];
        hbRingTail++;

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

/* ============================================================================
 * RPi COMMAND PARSING
 * ============================================================================ */
void readRPi(void) {
    if (usbRxOverflow) {
        usbRxOverflow = 0;
        sendUSB("WARN:USB_RX_OVERFLOW\r\n");
    }

    while (usbRingTail != usbRingHead) {
        char c = (char)(usbRing[usbRingTail & USB_RING_MASK]);
        usbRingTail++;

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
}

uint8_t parseArmPayload(const char* payload, int32_t* steps, uint32_t* speed_sps) {
    char* comma = strchr(payload, ',');
    if (comma == NULL) return 0;

    *steps = atol(payload);
    *speed_sps = (uint32_t)atol(comma + 1);

    if (*steps > STEPPER_MAX_STEPS || *steps < -STEPPER_MAX_STEPS) return 0;
    if (*speed_sps < STEPPER_MIN_SPS || *speed_sps > STEPPER_MAX_SPS) return 0;

    return 1;
}

void parseCommand(char* cmd) {
    lastRPiCmd = HAL_GetTick();
    emergStop  = 0;

    if (strncmp(cmd, "CMD:STOP", 8) == 0) {
        cmdSpeed = 0; cmdSteer = 0; returning = 0;
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
        int32_t  steps = 0;
        uint32_t spd   = 0;
        if (!parseArmPayload(cmd + 8, &steps, &spd)) {
            sendUSB("ERR:ARM_BOUNDS\r\n");
            return;
        }
        sendUSB("ACK:ARM\r\n");
        if (steps != 0) stepperMove(0, steps, spd, 0);
    }
    else if (strncmp(cmd, "CMD:ARM2:", 9) == 0) {
        int32_t  steps = 0;
        uint32_t spd   = 0;
        if (!parseArmPayload(cmd + 9, &steps, &spd)) {
            sendUSB("ERR:ARM2_BOUNDS\r\n");
            return;
        }
        sendUSB("ACK:ARM2\r\n");
        if (steps != 0) stepperMove(1, steps, spd, 0);
    }
    else if (strncmp(cmd, "CMD:RETURN", 10) == 0) {
        returning = 1;
        sendUSB("ACK:RETURN\r\n");
    }
    else if (strncmp(cmd, "CMD:PING", 8) == 0) {
        sendUSB("ACK:PING\r\n");
    }
    else if (strncmp(cmd, "CMD:RESET_HOME", 14) == 0) {
        homeX = posX; homeY = posY; homeHdg = heading;
        sendUSB("ACK:RESET_HOME\r\n");
    }
    else if (strncmp(cmd, "CMD:RESET_ODOM", 14) == 0) {
        posX = 0; posY = 0; heading = 0; distCm = 0;
        homeX = 0; homeY = 0; homeHdg = 0;
        sendUSB("ACK:RESET_ODOM\r\n");
    }
}

/* ============================================================================
 * TELEMETRY
 * ============================================================================ */
void sendTelemetry(void) {
    char buf[192];
    float headingDeg = heading * 57.29578f;
    while (headingDeg >  180.0f) headingDeg -= 360.0f;
    while (headingDeg < -180.0f) headingDeg += 360.0f;

    snprintf(buf, sizeof(buf),
        "TEL:BAT:%.1f,SPD:%.1f,DIST:%.0f,TEMP:%.1f,X:%.1f,Y:%.1f,H:%.1f,HOME:%.1f,RET:%u\r\n",
        batV, fabsf((float)cmdSpeed) * 0.036f, distCm, tmpC,
        posX, posY, headingDeg, distanceToHome(), returning);
    sendUSB(buf);

    snprintf(buf, sizeof(buf),
        "OBS:FL:%.0f,F:%.0f,FR:%.0f\r\n",
        sonar[0].distCm, sonar[1].distCm, sonar[2].distCm);
    sendUSB(buf);

    snprintf(buf, sizeof(buf),
        "IMU:OK:%u,ADDR:0x%02X,WHO:0x%02X,AX:%d,AY:%d,AZ:%d,GX:%d,GY:%d,GZ:%d,TEMP:%.1f\r\n",
        imuPresent, imuAddr, imuWhoAmI, imuAx, imuAy, imuAz, imuGx, imuGy, imuGz, imuTempC);
    sendUSB(buf);
}

/* ============================================================================
 * SAFETY
 * ============================================================================ */
void applyMotorSafety(void) {
    if (HAL_GPIO_ReadPin(EMERG_PORT, EMERG_PIN) == GPIO_PIN_RESET)
        emergStop = 1;

    if (HAL_GetTick() - lastRPiCmd > PI_TIMEOUT_MS) {
        if (!piTimedOut) { piTimedOut = 1; sendUSB("ALERT:PI_TIMEOUT\r\n"); }
        cmdSpeed = 0; cmdSteer = 0;
    } else {
        piTimedOut = 0;
    }

    if (batV > 1.0f && batV < BAT_MIN_VOLTAGE) {
        cmdSpeed = 0; cmdSteer = 0;
        sendUSB("ALERT:BATTERY_LOW\r\n");
    }

    if (hbChecksumErrors >= HB_ERROR_MAX) {
        cmdSpeed = 0; cmdSteer = 0;
        sendUSB("ALERT:HOVERBOARD_ERROR\r\n");
    }

    if (cmdSpeed < 0 && obstacleAhead()) {
        cmdSpeed = 0;
        sendUSB("ALERT:OBSTACLE_FRONT\r\n");
    }

    if (emergStop) {
        cmdSpeed = 0; cmdSteer = 0;
        stepperStopAll();
    }
}

/* ============================================================================
 * NAVIGATION
 * ============================================================================ */
float distanceToHome(void) {
    float dx = posX - homeX;
    float dy = posY - homeY;
    return sqrtf(dx * dx + dy * dy);
}

void navigateToHome(void) {
    if (distanceToHome() < HOME_THRESHOLD_CM) {
        cmdSpeed = 0; cmdSteer = 0; returning = 0;
        posX = homeX; posY = homeY; heading = homeHdg;
        sendUSB("ACK:RETURN_COMPLETE\r\n");
        return;
    }
    float dx = homeX - posX;
    float dy = homeY - posY;
    float targetAngle = atan2f(dy, dx);
    float error = targetAngle - heading;
    while (error >  3.14159f) error -= 2.0f * 3.14159f;
    while (error < -3.14159f) error += 2.0f * 3.14159f;

    int16_t steer = (int16_t)(error * 120.0f);
    if (steer >  300) steer =  300;
    if (steer < -300) steer = -300;
    int16_t speed = obstacleAhead() ? 0 : RETURN_SPEED;
    cmdSpeed = speed; cmdSteer = steer;
}

/* ============================================================================
 * IMU MPU6050 DRIVER
 * ============================================================================ */
static int16_t be16(uint8_t hi, uint8_t lo) {
    return (int16_t)((uint16_t)hi << 8 | lo);
}

void imuBusInit(void) {
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    __HAL_RCC_GPIOB_CLK_ENABLE();
    HAL_GPIO_WritePin(IMU_SCL_GPIO_Port, IMU_SCL_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(IMU_SDA_GPIO_Port, IMU_SDA_Pin, GPIO_PIN_SET);
    GPIO_InitStruct.Pin = IMU_SCL_Pin|IMU_SDA_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_OD;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);
}

static void imuDelay(void) {
    delay_us(4);
}

static void imuScl(uint8_t high) {
    HAL_GPIO_WritePin(IMU_SCL_GPIO_Port, IMU_SCL_Pin, high ? GPIO_PIN_SET : GPIO_PIN_RESET);
    imuDelay();
}

static void imuSda(uint8_t high) {
    HAL_GPIO_WritePin(IMU_SDA_GPIO_Port, IMU_SDA_Pin, high ? GPIO_PIN_SET : GPIO_PIN_RESET);
    imuDelay();
}

static uint8_t imuReadSda(void) {
    return HAL_GPIO_ReadPin(IMU_SDA_GPIO_Port, IMU_SDA_Pin) == GPIO_PIN_SET;
}

static void imuStart(void) {
    imuSda(1);
    imuScl(1);
    imuSda(0);
    imuScl(0);
}

static void imuStop(void) {
    imuSda(0);
    imuScl(1);
    imuSda(1);
}

static uint8_t imuWriteByte(uint8_t value) {
    for (uint8_t bit = 0; bit < 8; bit++) {
        imuSda((value & 0x80) != 0);
        imuScl(1);
        imuScl(0);
        value <<= 1;
    }
    imuSda(1);
    imuScl(1);
    uint8_t ack = !imuReadSda();
    imuScl(0);
    return ack;
}

static uint8_t imuReadByte(uint8_t ack) {
    uint8_t value = 0;
    imuSda(1);
    for (uint8_t bit = 0; bit < 8; bit++) {
        value <<= 1;
        imuScl(1);
        if (imuReadSda()) value |= 1;
        imuScl(0);
    }
    imuSda(ack ? 0 : 1);
    imuScl(1);
    imuScl(0);
    imuSda(1);
    return value;
}

static uint8_t imuWriteReg(uint8_t addr7, uint8_t reg, uint8_t value) {
    imuStart();
    if (!imuWriteByte((addr7 << 1) | 0)) { imuStop(); return 0; }
    if (!imuWriteByte(reg)) { imuStop(); return 0; }
    if (!imuWriteByte(value)) { imuStop(); return 0; }
    imuStop();
    return 1;
}

static uint8_t imuReadRegs(uint8_t addr7, uint8_t reg, uint8_t* data, uint8_t len) {
    imuStart();
    if (!imuWriteByte((addr7 << 1) | 0)) { imuStop(); return 0; }
    if (!imuWriteByte(reg)) { imuStop(); return 0; }
    imuStart();
    if (!imuWriteByte((addr7 << 1) | 1)) { imuStop(); return 0; }
    for (uint8_t i = 0; i < len; i++) {
        data[i] = imuReadByte(i + 1 < len);
    }
    imuStop();
    return 1;
}

uint8_t imuInit(void) {
    uint8_t candidate[2] = {0x68, 0x69};
    for (uint8_t i = 0; i < 2; i++) {
        uint8_t who = 0;
        if (imuReadRegs(candidate[i], IMU_REG_WHO_AM_I, &who, 1)) {
            imuAddr = candidate[i];
            imuWhoAmI = who;
            imuWriteReg(imuAddr, IMU_REG_PWR_MGMT_1, 0x00);
            HAL_Delay(50);
            imuPresent = 1;
            return 1;
        }
    }
    imuPresent = 0;
    imuAddr = 0;
    imuWhoAmI = 0;
    return 0;
}

void readIMU(void) {
    uint32_t now = HAL_GetTick();
    if (now - lastImuRead < 100) return;
    lastImuRead = now;

    if (!imuPresent) {
        imuInit();
        return;
    }

    uint8_t data[14];
    if (!imuReadRegs(imuAddr, IMU_REG_DATA_START, data, sizeof(data))) {
        imuPresent = 0;
        return;
    }

    imuAx = be16(data[0], data[1]);
    imuAy = be16(data[2], data[3]);
    imuAz = be16(data[4], data[5]);
    int16_t tempRaw = be16(data[6], data[7]);
    imuGx = be16(data[8], data[9]);
    imuGy = be16(data[10], data[11]);
    imuGz = be16(data[12], data[13]);
    imuTempC = ((float)tempRaw / 340.0f) + 36.53f;
}

/* ============================================================================
 * MAIN
 * ============================================================================ */
int main(void) {
    HAL_Init();
    SystemClock_Config();
    MX_GPIO_Init();
    MX_USART1_UART_Init();
    MX_USB_DEVICE_Init();

    DWT_Init();

    // Init all subsystems
    stepperInit();   // configures and starts TIM3 ISR
    sonarInit();     // reconfigures echo pins to EXTI
    hbUartInit();    // arms UART interrupt receive

    // Timestamps
    lastOdoTime = HAL_GetTick();
    lastRPiCmd  = HAL_GetTick();

    // Steppers off at boot
    stepperDisable(0);
    stepperDisable(1);

    // All TRIG pins LOW
    HAL_GPIO_WritePin(TRIG_FL_PORT, TRIG_FL_PIN, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(TRIG_F_PORT,  TRIG_F_PIN,  GPIO_PIN_RESET);
    HAL_GPIO_WritePin(TRIG_FR_PORT, TRIG_FR_PIN, GPIO_PIN_RESET);

    // IMU config
    imuBusInit();
    imuInit();

    // Wait for USB enumeration
    HAL_Delay(1500);
    sendUSB("ID:STM32_MOTOR\r\n");

    // Boot blinks
    for (int i = 0; i < 3; i++) {
        HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
        HAL_Delay(120);
        HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
        HAL_Delay(120);
    }

    /* -----------------------------------------------------------------------
     * MAIN LOOP — ORCHESTRATION ONLY
     * ----------------------------------------------------------------------- */
    while (1) {
        // 1 — drain hoverboard UART ring, decode packets
        readHoverboard();

        // 2 — drain USB ring, parse RPi commands
        readRPi();

        // 3 — rotate sonar trigger (non-blocking — ISR handles echo)
        sonarUpdate();

        // 4 — check if steppers completed, send ACK
        stepperCheckDone();

        // 5 — navigate home if returning
        if (returning) navigateToHome();

        // 6 — read IMU if present (every 100ms)
        readIMU();

        // 7 — safety (always before FOC send)
        applyMotorSafety();

        // 8 — send FOC command every 20ms
        if (HAL_GetTick() - lastHBSend >= 20) {
            lastHBSend = HAL_GetTick();
            sendFOC(cmdSteer, cmdSpeed);
        }

        // 9 — telemetry every 100ms
        if (HAL_GetTick() - lastTelSend >= 100) {
            lastTelSend = HAL_GetTick();
            sendTelemetry();
        }

        // 10 — heartbeat LED (DUM-dum pattern)
        static uint32_t beatTimer = 0;
        static uint8_t  beatPhase = 0;
        static uint16_t pwmVal    = 0;
        uint32_t elapsed = HAL_GetTick() - beatTimer;

        if (!emergStop) {
            switch (beatPhase) {
                case 0:
                    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
                    if (elapsed >= 80) { beatPhase = 1; beatTimer = HAL_GetTick(); }
                    break;
                case 1:
                    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
                    if (elapsed >= 80) { beatPhase = 2; beatTimer = HAL_GetTick(); }
                    break;
                case 2:
                    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
                    if (elapsed >= 80) { beatPhase = 3; beatTimer = HAL_GetTick(); pwmVal = 0; }
                    break;
                case 3:
                    pwmVal += 3;
                    if (pwmVal > 100) pwmVal = 100;
                    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
                    delay_us((100 - pwmVal) * 4);
                    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
                    delay_us(pwmVal * 4);
                    if (pwmVal >= 100) { beatPhase = 4; beatTimer = HAL_GetTick(); }
                    break;
                case 4:
                    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
                    if (elapsed >= 700) { beatPhase = 0; beatTimer = HAL_GetTick(); }
                    break;
            }
        } else {
            if (HAL_GetTick() - lastLedToggle >= 80) {
                lastLedToggle = HAL_GetTick();
                ledState = !ledState;
                HAL_GPIO_WritePin(LED_PORT, LED_PIN,
                                  ledState ? GPIO_PIN_RESET : GPIO_PIN_SET);
            }
        }
    }
}

/* ============================================================================
 * SYSTEM CLOCK CONFIG — unchanged from v1.0
 * ============================================================================ */
void SystemClock_Config(void) {
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE2);

    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState       = RCC_HSE_ON;
    RCC_OscInitStruct.PLL.PLLState   = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource  = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLM       = 25;
    RCC_OscInitStruct.PLL.PLLN       = 336;
    RCC_OscInitStruct.PLL.PLLP       = RCC_PLLP_DIV4;
    RCC_OscInitStruct.PLL.PLLQ       = 7;
    HAL_RCC_OscConfig(&RCC_OscInitStruct);

    RCC_ClkInitStruct.ClockType      = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                                     | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource   = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider  = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
    HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2);
}

void Error_Handler(void) {
    __disable_irq();
    while (1) {}
}
