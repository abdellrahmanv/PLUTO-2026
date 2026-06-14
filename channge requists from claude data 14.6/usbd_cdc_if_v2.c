/* ============================================================================
 * usbd_cdc_if.c — v2.0
 * Spirit Robotics / PLUTO
 *
 * CHANGE FROM v1.0:
 *   CDC_Receive_FS no longer writes to usbRxBuf + sets usbRxLen.
 *   Instead it pushes bytes into usbRing (circular buffer).
 *   Main loop reads usbRingTail safely — no race condition possible.
 * ============================================================================ */

#include "usbd_cdc_if.h"

uint8_t UserRxBufferFS[APP_RX_DATA_SIZE];
uint8_t UserTxBufferFS[APP_TX_DATA_SIZE];

extern USBD_HandleTypeDef hUsbDeviceFS;

/* ── Ring buffer — defined in main.c, written here in ISR context ─────────── */
#define USB_RING_SIZE  256
#define USB_RING_MASK  (USB_RING_SIZE - 1)
extern volatile uint8_t  usbRing[USB_RING_SIZE];
extern volatile uint16_t usbRingHead;   // ISR writes this
// usbRingTail is owned by main loop — never touched here

static int8_t CDC_Init_FS(void);
static int8_t CDC_DeInit_FS(void);
static int8_t CDC_Control_FS(uint8_t cmd, uint8_t* pbuf, uint16_t length);
static int8_t CDC_Receive_FS(uint8_t* pbuf, uint32_t *Len);
static int8_t CDC_TransmitCplt_FS(uint8_t *pbuf, uint32_t *Len, uint8_t epnum);

USBD_CDC_ItfTypeDef USBD_Interface_fops_FS = {
    CDC_Init_FS,
    CDC_DeInit_FS,
    CDC_Control_FS,
    CDC_Receive_FS,
    CDC_TransmitCplt_FS
};

static int8_t CDC_Init_FS(void) {
    USBD_CDC_SetTxBuffer(&hUsbDeviceFS, UserTxBufferFS, 0);
    USBD_CDC_SetRxBuffer(&hUsbDeviceFS, UserRxBufferFS);
    return USBD_OK;
}

static int8_t CDC_DeInit_FS(void) {
    return USBD_OK;
}

static int8_t CDC_Control_FS(uint8_t cmd, uint8_t* pbuf, uint16_t length) {
    (void)cmd; (void)pbuf; (void)length;
    return USBD_OK;
}

/* ── RECEIVE — ISR CONTEXT ─────────────────────────────────────────────────
 * Push every received byte into the ring buffer.
 * head is uint16_t — write is atomic on Cortex-M4 (single STR instruction).
 * Main loop reads tail — no critical section needed.
 * Ring size 256 = power of 2, so mask wrapping is safe without division.
 * -------------------------------------------------------------------------- */
static int8_t CDC_Receive_FS(uint8_t* Buf, uint32_t *Len) {
    for (uint32_t i = 0; i < *Len; i++) {
        usbRing[usbRingHead & USB_RING_MASK] = Buf[i];
        usbRingHead++;
        // If head laps tail (overflow), tail will read stale data.
        // At 256 bytes this only happens if main loop stalls for >256 chars —
        // which cannot happen in this architecture since loop is non-blocking.
    }
    USBD_CDC_SetRxBuffer(&hUsbDeviceFS, &Buf[0]);
    USBD_CDC_ReceivePacket(&hUsbDeviceFS);
    return USBD_OK;
}

uint8_t CDC_Transmit_FS(uint8_t* Buf, uint16_t Len) {
    USBD_CDC_HandleTypeDef *hcdc =
        (USBD_CDC_HandleTypeDef*)hUsbDeviceFS.pClassData;
    if (hcdc->TxState != 0) return USBD_BUSY;
    USBD_CDC_SetTxBuffer(&hUsbDeviceFS, Buf, Len);
    return USBD_CDC_TransmitPacket(&hUsbDeviceFS);
}

static int8_t CDC_TransmitCplt_FS(uint8_t *Buf, uint32_t *Len, uint8_t epnum) {
    (void)Buf; (void)Len; (void)epnum;
    return USBD_OK;
}
