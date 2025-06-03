/**
 * @file config.h
 * @brief Configuration settings for Beyond Robotics DroneCAN Motor Controller
 * @author Beyond Robotics DroneCAN Implementation
 * @version 1.0
 * @date 2024
 */

#ifndef CONFIG_H
#define CONFIG_H

#include "project_common.h"

// ============================================================================
// DRONECAN CONFIGURATION
// ============================================================================

/// DroneCAN Node ID (must be unique on the network)
#define DRONECAN_NODE_ID 10

/// DroneCAN Node Name
#define DRONECAN_NODE_NAME "Beyond Robotix Motor Controller"

/// CAN Bus Bitrate (must match Orange Cube: 1000000 bps)
#define CAN_BITRATE 1000000

// ============================================================================
// MOTOR CONTROLLER CONFIGURATION
// ============================================================================

/// Number of motors/ESCs to control (2-channel setup - PA8+PA9 HAL PWM)
#define NUM_MOTORS 2

/// Motor control pins (Timer-capable pins on STM32L431)
/// PA8+PA9 using direct HAL TIM1 PWM (bypassing Servo library)
#define MOTOR_PIN_1 PA8
#define MOTOR_PIN_2 PA9
#define MOTOR_PIN_3 PA10
#define MOTOR_PIN_4 PA11

/// PWM signal timing (standard ESC values)
#define PWM_MIN 1000      ///< 1ms pulse width (minimum throttle)
#define PWM_MAX 2000      ///< 2ms pulse width (maximum throttle)
#define PWM_NEUTRAL 1500  ///< 1.5ms pulse width (neutral/stop)

/// Safety timeout for ESC commands (milliseconds)
#define ESC_TIMEOUT_MS 1000

// ============================================================================
// BATTERY MONITORING CONFIGURATION
// ============================================================================

/// Battery monitoring update rate (milliseconds)
#define BATTERY_UPDATE_INTERVAL_MS 100

/// Battery voltage ADC pin
#define BATTERY_VOLTAGE_PIN PA1

/// Battery current ADC pin
#define BATTERY_CURRENT_PIN PA0

/// Debug output interval for battery info (every N messages)
#define BATTERY_DEBUG_INTERVAL 100

// ============================================================================
// TEST MODE CONFIGURATION
// ============================================================================

/// Enable/disable test mode (comment out to disable)
// #define ENABLE_TEST_MODE  // DEAKTIVIERT für Produktion

/// Test ESC command interval (milliseconds)
#define TEST_ESC_INTERVAL_MS 3000

/// Test PWM range
#define TEST_PWM_MIN 1300
#define TEST_PWM_MAX 1700
#define TEST_PWM_STEP 100

// ============================================================================
// DEBUG CONFIGURATION
// ============================================================================

/// Serial baud rate for debug output
#define SERIAL_BAUD_RATE 115200

/// Motor status debug interval (milliseconds)
#define MOTOR_DEBUG_INTERVAL_MS 5000

/// Watchdog timeout (microseconds)
#define WATCHDOG_TIMEOUT_US 2000000

// ============================================================================
// DRONECAN PARAMETERS
// ============================================================================

/// Custom DroneCAN parameters for configuration
/// Note: This will be defined in DroneCAN_Handler.cpp to avoid header issues
extern const std::vector<DroneCAN::parameter> DRONECAN_PARAMETERS;

// ============================================================================
// HARDWARE PIN MAPPING
// ============================================================================

/// Motor pin array for easy iteration (2-channel setup - PA8+PA9 HAL PWM)
static const uint8_t MOTOR_PINS[NUM_MOTORS] = {
    MOTOR_PIN_1, MOTOR_PIN_2  // PA8 + PA9 via HAL TIM1
};

#endif // CONFIG_H
