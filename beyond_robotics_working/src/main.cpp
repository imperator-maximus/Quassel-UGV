
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
 * @brief Arduino setup function - ULTRA MINIMAL FOR CRASH TESTING
 */
void setup() {
    // CRITICAL FIX: IWatchdog.begin() is BROKEN on STM32L431!
    // Using direct HAL IWDG programming to bypass faulty library

    // DIRECT HAL IWDG INITIALIZATION FIRST (bypass broken IWatchdog library)
    // CORRECTED SEQUENCE: Configure IWDG with maximum timeout
    // LSI frequency ~32kHz, Prescaler 256, Reload 4095 = ~32 seconds timeout

    // Step 1: Enable write access to IWDG registers
    IWDG->KR = 0x5555;    // Enable register access

    // Step 2: Configure prescaler and reload value (while registers are unlocked)
    IWDG->PR = 0x06;      // Prescaler 256 (maximum)
    IWDG->RLR = 0xFFF;    // Reload value 4095 (maximum)

    // Step 3: Start the watchdog (this LOCKS the configuration registers!)
    IWDG->KR = 0xCCCC;    // Start watchdog - registers now LOCKED

    // Step 4: Reload watchdog (only this command works after start)
    IWDG->KR = 0xAAAA;    // Reload watchdog

    // Initialize LED for heartbeat monitoring
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);

    // CRITICAL: app_setup() might be required for hardware stability!
    // Initialize bootloader support (must be first after watchdog) - RE-ENABLED
    app_setup();

    // TEST LED IMMEDIATELY AFTER app_setup()
    for (int i = 0; i < 10; i++) {
        digitalWrite(LED_BUILTIN, HIGH);
        for (volatile uint32_t j = 0; j < 1000000; j++) { IWDG->KR = 0xAAAA; }
        digitalWrite(LED_BUILTIN, LOW);
        for (volatile uint32_t j = 0; j < 1000000; j++) { IWDG->KR = 0xAAAA; }
    }

    // Initialize serial communication
    Serial.begin(SERIAL_BAUD_RATE);

    // Print system information
    printSystemInfo();

    // Initialize all system components (MOTOR CONTROLLER + DroneCAN)
    DEBUG_PRINTLN("🔧 Initializing system components...");
    if (!initializeSystem()) {
        DEBUG_PRINTLN("❌ System initialization failed");
        while (true) {
            IWDG->KR = 0xAAAA;  // Feed watchdog in error loop
            delay(1000);
        }
    }
    DEBUG_PRINTLN("✅ System initialization complete!");

    DEBUG_PRINTLN("🚀 System initialization complete!");
    DEBUG_PRINTLN("Entering main loop...");

    // Main loop with DroneCAN (Beyond Robotics compatible)
    while (true) {
        const uint32_t now = millis();

        // Feed watchdog FIRST - prevent hardware reset
        IWDG->KR = 0xAAAA;  // Direct register access instead of IWatchdog.reload()

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

        // Feed watchdog again at end of loop
        IWDG->KR = 0xAAAA;  // Direct register access
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
