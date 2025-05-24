/**
 * @file TestMode.cpp
 * @brief Implementation of TestMode class
 * @author Beyond Robotics DroneCAN Implementation
 * @version 1.0
 * @date 2024
 */

#include "test/TestMode.h"
#include "motor_controller/MotorController.h"
#include "dronecan_handler/DroneCAN_Handler.h"

TestMode::TestMode(MotorController& motor_controller, DroneCAN_Handler& dronecan_handler)
    : motor_controller_(motor_controller)
    , dronecan_handler_(dronecan_handler)
    , enabled_(false)
    , last_test_time_(0)
    , test_pwm_value_(PWM_NEUTRAL)
    , test_direction_up_(true)
{
}

TestMode::~TestMode() {
    setEnabled(false);
}

bool TestMode::initialize() {
#ifdef ENABLE_TEST_MODE
    enabled_ = true;
    test_pwm_value_ = PWM_NEUTRAL;
    test_direction_up_ = true;
    
    DEBUG_PRINTLN("=== Test Mode Initialization ===");
    DEBUG_PRINT("Test ESC interval: ");
    DEBUG_PRINT(TEST_ESC_INTERVAL_MS);
    DEBUG_PRINTLN("ms");
    DEBUG_PRINT("Test PWM range: ");
    DEBUG_PRINT(TEST_PWM_MIN);
    DEBUG_PRINT(" - ");
    DEBUG_PRINTLN(TEST_PWM_MAX);
    DEBUG_PRINTLN("✅ Test mode enabled");
    
    return true;
#else
    enabled_ = false;
    DEBUG_PRINTLN("Test mode disabled (ENABLE_TEST_MODE not defined)");
    return false;
#endif
}

void TestMode::update() {
    if (!enabled_) return;
    
    uint32_t now = millis();
    
    // Send test ESC commands at regular intervals
    if (now - last_test_time_ >= TEST_ESC_INTERVAL_MS) {
        last_test_time_ = now;
        sendTestESCCommand();
    }
}

void TestMode::setEnabled(bool enabled) {
    enabled_ = enabled;
    
    if (enabled) {
        DEBUG_PRINTLN("🧪 Test mode ENABLED");
    } else {
        DEBUG_PRINTLN("🧪 Test mode DISABLED");
    }
}

bool TestMode::isEnabled() const {
    return enabled_;
}

void TestMode::sendTestESCCommand() {
    if (!enabled_) return;
    
    // Create test ESC command
    uavcan_equipment_esc_RawCommand pkt{};
    
    // Set same test PWM value for all motors
    for (int i = 0; i < NUM_MOTORS; i++) {
        pkt.cmd.data[i] = pwmToRawCommand(test_pwm_value_);
    }
    pkt.cmd.len = NUM_MOTORS;
    
    // Send via DroneCAN
    uint8_t buffer[UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_MAX_SIZE];
    uint32_t len = uavcan_equipment_esc_RawCommand_encode(&pkt, buffer);
    static uint8_t transfer_id;
    
    canardBroadcast(&dronecan_handler_.getDroneCAN().canard,
                    UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_SIGNATURE,
                    UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_ID,
                    &transfer_id,
                    CANARD_TRANSFER_PRIORITY_HIGH,
                    buffer,
                    len);
    
    DEBUG_PRINT(ICON_SEND " Test ESC: PWM=");
    DEBUG_PRINT(test_pwm_value_);
    DEBUG_PRINT(" Raw=");
    DEBUG_PRINTLN(pkt.cmd.data[0]);
    
    // Also directly apply to motor controller for immediate testing
    int16_t raw_commands[NUM_MOTORS];
    for (int i = 0; i < NUM_MOTORS; i++) {
        raw_commands[i] = pkt.cmd.data[i];
    }
    motor_controller_.setMotorCommands(raw_commands, NUM_MOTORS);
    
    // Update test PWM value for next iteration
    updateTestPWMValue();
}

void TestMode::runMotorValidation() {
    if (!enabled_) return;
    
    DEBUG_PRINTLN("🧪 Running motor validation sequence...");
    
    // Test each motor individually
    for (int motor = 0; motor < NUM_MOTORS; motor++) {
        DEBUG_PRINT("Testing motor ");
        DEBUG_PRINT(motor + 1);
        DEBUG_PRINTLN("...");
        
        // Test PWM sweep for this motor
        for (uint16_t pwm = TEST_PWM_MIN; pwm <= TEST_PWM_MAX; pwm += TEST_PWM_STEP) {
            motor_controller_.setMotorPWM(motor, pwm);
            delay(500); // Hold each value for 500ms
            
            DEBUG_PRINT("  PWM: ");
            DEBUG_PRINTLN(pwm);
        }
        
        // Return to neutral
        motor_controller_.setMotorPWM(motor, PWM_NEUTRAL);
        delay(1000);
    }
    
    DEBUG_PRINTLN("✅ Motor validation complete");
}

void TestMode::printStatus() const {
    if (!enabled_) return;
    
    DEBUG_PRINT("🧪 Test Mode: PWM=");
    DEBUG_PRINT(test_pwm_value_);
    DEBUG_PRINT(", Direction=");
    DEBUG_PRINT(test_direction_up_ ? "UP" : "DOWN");
    DEBUG_PRINT(", Next in ");
    DEBUG_PRINT(TEST_ESC_INTERVAL_MS - (millis() - last_test_time_));
    DEBUG_PRINTLN("ms");
}

void TestMode::updateTestPWMValue() {
    // Cycle PWM value between TEST_PWM_MIN and TEST_PWM_MAX
    if (test_direction_up_) {
        test_pwm_value_ += TEST_PWM_STEP;
        if (test_pwm_value_ >= TEST_PWM_MAX) {
            test_direction_up_ = false;
        }
    } else {
        test_pwm_value_ -= TEST_PWM_STEP;
        if (test_pwm_value_ <= TEST_PWM_MIN) {
            test_direction_up_ = true;
        }
    }
}

int16_t TestMode::pwmToRawCommand(uint16_t pwm_value) const {
    // Convert PWM (PWM_MIN to PWM_MAX) to DroneCAN range (-8192 to 8191)
    return map(pwm_value, PWM_MIN, PWM_MAX, -8192, 8191);
}
