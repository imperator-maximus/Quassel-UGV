/**
 * @file MotorController.cpp
 * @brief Implementation of MotorController class
 * @author Beyond Robotics DroneCAN Implementation
 * @version 1.0
 * @date 2024
 */

#include "motor_controller/MotorController.h"

MotorController::MotorController()
    : motors_armed_(false)
    , last_command_time_(0)
    , last_debug_time_(0)
{
    // Initialize PWM values to neutral
    for (int i = 0; i < NUM_MOTORS; i++) {
        motor_pwm_values_[i] = PWM_NEUTRAL;
    }
}

MotorController::~MotorController() {
    disarm();
}

bool MotorController::initialize() {
    DEBUG_PRINTLN("=== Motor Controller Initialization ===");

    // Initialize each motor servo
    for (int i = 0; i < NUM_MOTORS; i++) {
        if (!motors_[i].attach(MOTOR_PINS[i], PWM_MIN, PWM_MAX)) {
            DEBUG_PRINT("❌ Failed to attach motor ");
            DEBUG_PRINT(i + 1);
            DEBUG_PRINT(" on pin ");
            DEBUG_PRINTLN(MOTOR_PINS[i]);
            return false;
        }

        // Set to neutral position
        motors_[i].writeMicroseconds(PWM_NEUTRAL);
        motor_pwm_values_[i] = PWM_NEUTRAL;

        DEBUG_PRINT(ICON_MOTOR " Motor ");
        DEBUG_PRINT(i + 1);
        DEBUG_PRINT(" initialized on pin ");
        DEBUG_PRINTLN(MOTOR_PINS[i]);
    }

    DEBUG_PRINTLN("✅ Motors initialized - waiting for ESC commands...");
    return true;
}

void MotorController::update() {
    checkSafetyTimeout();
    updateMotorOutputs();

    // Debug output at regular intervals
    uint32_t now = millis();
    if (now - last_debug_time_ >= MOTOR_DEBUG_INTERVAL_MS) {
        last_debug_time_ = now;
        printStatus();
    }
}

void MotorController::setMotorCommands(const int16_t* raw_commands, uint8_t num_commands) {
    if (!raw_commands) return;

    // DEBUG: Print ESC command (limited to every 1 second to prevent serial overflow)
    static uint32_t last_esc_debug_time = 0;
    uint32_t current_time = millis();
    if (current_time - last_esc_debug_time >= 1000) {  // Only print every 1 second
        DEBUG_PRINT(ICON_ROCKET " ESC Command: [");

        uint8_t motors_to_update = min(num_commands, (uint8_t)NUM_MOTORS);
        for (uint8_t i = 0; i < motors_to_update; i++) {
            uint16_t pwm_value = rawCommandToPWM(raw_commands[i]);
            DEBUG_PRINT(pwm_value);
            if (i < motors_to_update - 1) DEBUG_PRINT(", ");
        }
        DEBUG_PRINTLN("]");
        last_esc_debug_time = current_time;
    }

    // Update motor values (always, regardless of debug output)
    uint8_t motors_to_update = min(num_commands, (uint8_t)NUM_MOTORS);
    for (uint8_t i = 0; i < motors_to_update; i++) {
        uint16_t pwm_value = rawCommandToPWM(raw_commands[i]);
        motor_pwm_values_[i] = pwm_value;
    }

    // Update command timestamp
    last_command_time_ = millis();

    // Auto-arm motors when receiving valid commands
    if (!motors_armed_) {
        arm();
        DEBUG_PRINTLN(ICON_LOCK " Motors ARMED by ESC command");
    }
}

void MotorController::setMotorPWM(uint8_t motor_index, uint16_t pwm_value) {
    if (!isValidMotorIndex(motor_index)) return;

    // Constrain PWM value to valid range
    pwm_value = constrain(pwm_value, PWM_MIN, PWM_MAX);
    motor_pwm_values_[motor_index] = pwm_value;

    // Update command timestamp
    last_command_time_ = millis();
}

uint16_t MotorController::getMotorPWM(uint8_t motor_index) const {
    if (!isValidMotorIndex(motor_index)) return PWM_NEUTRAL;
    return motor_pwm_values_[motor_index];
}

bool MotorController::isArmed() const {
    return motors_armed_;
}

void MotorController::arm() {
    motors_armed_ = true;
    last_command_time_ = millis();
}

void MotorController::disarm() {
    motors_armed_ = false;

    // Set all motors to neutral
    for (int i = 0; i < NUM_MOTORS; i++) {
        motor_pwm_values_[i] = PWM_NEUTRAL;
    }
}

uint32_t MotorController::getTimeSinceLastCommand() const {
    return millis() - last_command_time_;
}

void MotorController::printStatus() const {
    DEBUG_PRINT(ICON_MOTOR " Motors: ");
    DEBUG_PRINT(motors_armed_ ? "ARMED" : "DISARMED");
    DEBUG_PRINT(" PWM:[");

    for (int i = 0; i < NUM_MOTORS; i++) {
        DEBUG_PRINT(motors_armed_ ? motor_pwm_values_[i] : PWM_NEUTRAL);
        if (i < NUM_MOTORS - 1) DEBUG_PRINT(",");
    }
    DEBUG_PRINT("] Timeout:");
    DEBUG_PRINT(getTimeSinceLastCommand());
    DEBUG_PRINTLN("ms");
}

uint16_t MotorController::rawCommandToPWM(int16_t raw_command) const {
    // Convert from DroneCAN range (-8192 to 8191) to PWM (PWM_MIN to PWM_MAX)
    uint16_t pwm_value = map(raw_command, -8192, 8191, PWM_MIN, PWM_MAX);
    return constrain(pwm_value, PWM_MIN, PWM_MAX);
}

bool MotorController::isValidMotorIndex(uint8_t motor_index) const {
    return motor_index < NUM_MOTORS;
}

void MotorController::checkSafetyTimeout() {
    if (motors_armed_ && getTimeSinceLastCommand() > ESC_TIMEOUT_MS) {
        disarm();
        DEBUG_PRINTLN(ICON_WARNING " ESC timeout - motors DISARMED for safety");
    }
}

void MotorController::updateMotorOutputs() {
    for (int i = 0; i < NUM_MOTORS; i++) {
        uint16_t output_pwm = motors_armed_ ? motor_pwm_values_[i] : PWM_NEUTRAL;
        motors_[i].writeMicroseconds(output_pwm);
    }
}
