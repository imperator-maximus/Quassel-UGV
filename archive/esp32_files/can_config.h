/**
 * ESP32 CAN Configuration
 *
 * This file contains the pin definitions and configuration for CAN communication
 * on the ESP32 according to DroneCAN 1.0 specifications.
 *
 * Note: ESP32 CAN pins are fixed by hardware:
 * - GPIO5 = CAN TX (Pin 5 auf dem Freenove Breakout Board)
 * - GPIO4 = CAN RX (Pin 4 auf dem Freenove Breakout Board)
 *
 * Wichtig: Diese Pins sind fest mit dem CAN-Controller des ESP32 verbunden
 * und können nicht geändert werden. Auf dem Freenove Breakout Board sind
 * diese Pins deutlich beschriftet.
 */

#ifndef CAN_CONFIG_H
#define CAN_CONFIG_H

// ESP32 CAN pins (fixed by hardware)
#define CAN_TX_PIN GPIO_NUM_5  // Pin 5 auf dem Freenove Board
#define CAN_RX_PIN GPIO_NUM_4  // Pin 4 auf dem Freenove Board

// CAN bus configuration
#define CAN_BITRATE 500000  // 500 kbps für bessere Kompatibilität

#endif // CAN_CONFIG_H
