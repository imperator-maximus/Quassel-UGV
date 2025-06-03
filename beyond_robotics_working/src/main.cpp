
/**
 * @file main.cpp
 * @brief Main application file for Beyond Robotics DroneCAN Motor Controller
 * @author Beyond Robotics DroneCAN Implementation
 * @version 1.0
 * @date 2024
 *
 * This is a clean, modular implementation of a DroneCAN motor controller
 * for the Beyond Robotics Dev Board (STM32L431).
 *
 * Features:
 * - 4-channel PWM motor control
 * - DroneCAN ESC command reception
 * - Battery information broadcasting
 * - Safety timeout system
 * - Test mode for development
 * - Orange Cube integration (Node ID 25)
 */

#include "project_common.h"
#include "config/config.h"
#include "motor_controller/MotorController.h"
#include "dronecan_handler/DroneCAN_Handler.h"
#include "test/TestMode.h"

// ============================================================================
// GLOBAL INSTANCES
// ============================================================================

/// Motor controller instance
MotorController motor_controller;

/// DroneCAN handler instance
DroneCAN_Handler dronecan_handler(motor_controller);

/// Test mode instance
TestMode test_mode(motor_controller, dronecan_handler);

// ============================================================================
// FUNCTION DECLARATIONS
// ============================================================================

/**
 * @brief Initialize all system components
 * @return true if all components initialized successfully
 */
bool initializeSystem();

/**
 * @brief Print system startup information
 */
void printSystemInfo();

/**
 * @brief Arduino setup function - initializes all system components
 */
void setup() {
    // Initialize bootloader support (must be first)
    app_setup();

    // Initialize serial communication
    Serial.begin(SERIAL_BAUD_RATE);

    // Print system information
    printSystemInfo();

    // Initialize all system components (MOTOR CONTROLLER + DroneCAN)
    DEBUG_PRINTLN("🔧 Initializing system components...");
    if (!initializeSystem()) {
        DEBUG_PRINTLN("❌ System initialization failed");
        while (true) delay(1000);
    }
    DEBUG_PRINTLN("✅ System initialization complete!");

    // Initialize watchdog timer
    IWatchdog.begin(WATCHDOG_TIMEOUT_US);

    DEBUG_PRINTLN("🚀 System initialization complete!");
    DEBUG_PRINTLN("Entering main loop...");

    // Main loop with DroneCAN (Beyond Robotics compatible)
    while (true) {
        const uint32_t now = millis();

        // Update DroneCAN handler
        dronecan_handler.update();

        // Update motor controller (PWM outputs)
        motor_controller.update();

        // Status output every 5 seconds
        static unsigned long last_status = 0;
        if (now - last_status > 5000) {
            DEBUG_PRINTLN("System running... " + String(now/1000) + "s - DroneCAN OK");
            last_status = now;
        }

        IWatchdog.reload();
    }
}

/**
 * @brief Arduino loop function - not used (main loop is in setup())
 */
void loop() {
    // Doesn't work coming from bootloader - use while loop in setup
}

// ============================================================================
// FUNCTION IMPLEMENTATIONS
// ============================================================================

bool initializeSystem() {
    DEBUG_PRINTLN("=== System Initialization ===");

    // Initialize motor controller
    if (!motor_controller.initialize()) {
        DEBUG_PRINTLN("❌ Motor controller initialization failed");
        return false;
    }

    // Initialize DroneCAN handler
    if (!dronecan_handler.initialize()) {
        DEBUG_PRINTLN("❌ DroneCAN handler initialization failed");
        return false;
    }

    // Initialize test mode
    if (!test_mode.initialize()) {
        DEBUG_PRINTLN("⚠️ Test mode initialization failed (may be disabled)");
        // Test mode failure is not critical
    }

    return true;
}

void printSystemInfo() {
    DEBUG_PRINTLN("=====================================");
    DEBUG_PRINTLN(PROJECT_NAME);
    DEBUG_PRINT("Version: ");
    DEBUG_PRINT(PROJECT_VERSION_MAJOR);
    DEBUG_PRINT(".");
    DEBUG_PRINTLN(PROJECT_VERSION_MINOR);
    DEBUG_PRINTLN("Beyond Robotics Dev Board (STM32L431)");
    DEBUG_PRINTLN("=====================================");
    DEBUG_PRINT("Serial Baud Rate: ");
    DEBUG_PRINTLN(SERIAL_BAUD_RATE);
    DEBUG_PRINT("DroneCAN Node ID: ");
    DEBUG_PRINTLN(DRONECAN_NODE_ID);
    DEBUG_PRINT("CAN Bitrate: ");
    DEBUG_PRINT(CAN_BITRATE);
    DEBUG_PRINTLN(" bps");
    DEBUG_PRINT("Number of Motors: ");
    DEBUG_PRINTLN(NUM_MOTORS);
    DEBUG_PRINTLN("Ready for Orange Cube integration!");
    DEBUG_PRINTLN("=====================================");
}
