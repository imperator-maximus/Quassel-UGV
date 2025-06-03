/**
 * @file MotorController.cpp
 * @brief Implementation of MotorController class
 * @author Beyond Robotics DroneCAN Implementation
 * @version 1.0
 * @date 2024
 */

#include "motor_controller/MotorController.h"

// Global TIM1 handle for HAL PWM access
TIM_HandleTypeDef htim1_global;

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
    DEBUG_PRINTLN("🔧 PWM DIAGNOSTIC: Testing Servo.attach() for PA8/PA9...");

    // CRITICAL: Direct TIM1 PWM setup for PA9 (bypass Servo library)
    DEBUG_PRINTLN("🔧 Direct TIM1 PWM setup for PA9 - bypassing Servo library...");

    // Enable clocks
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_TIM1_CLK_ENABLE();

    // Configure PA8 as TIM1_CH1 alternate function
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin = GPIO_PIN_8;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF1_TIM1;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    // Configure PA9 as TIM1_CH2 alternate function
    GPIO_InitStruct.Pin = GPIO_PIN_9;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    // Configure TIM1 for 50Hz PWM (20ms period)
    htim1_global.Instance = TIM1;
    htim1_global.Init.Prescaler = 79;  // 80MHz / 80 = 1MHz
    htim1_global.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim1_global.Init.Period = 19999;  // 1MHz / 20000 = 50Hz (20ms)
    htim1_global.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim1_global.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    HAL_TIM_PWM_Init(&htim1_global);

    // Configure PWM channel 1 (PA8)
    TIM_OC_InitTypeDef sConfigOC = {0};
    sConfigOC.OCMode = TIM_OCMODE_PWM1;
    sConfigOC.Pulse = 1500;  // 1.5ms pulse (neutral)
    sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
    HAL_TIM_PWM_ConfigChannel(&htim1_global, &sConfigOC, TIM_CHANNEL_1);

    // Configure PWM channel 2 (PA9)
    HAL_TIM_PWM_ConfigChannel(&htim1_global, &sConfigOC, TIM_CHANNEL_2);

    // CRITICAL: TIM1 is Advanced Timer - needs Main Output Enable!
    __HAL_TIM_MOE_ENABLE(&htim1_global);

    // Start PWM on both channels
    HAL_TIM_PWM_Start(&htim1_global, TIM_CHANNEL_1);  // PA8
    HAL_TIM_PWM_Start(&htim1_global, TIM_CHANNEL_2);  // PA9

    // Force immediate update
    HAL_TIM_GenerateEvent(&htim1_global, TIM_EVENTSOURCE_UPDATE);

    DEBUG_PRINTLN("🔧 TIM1 PWM started with MOE enabled - PA8+PA9 should work now!");
    DEBUG_PRINTLN("🔧 PA8 should show ~0.25V for 1500μs PWM (TIM1_CH1)");
    DEBUG_PRINTLN("🔧 PA9 should show ~0.25V for 1500μs PWM (TIM1_CH2)");

    // Skip Servo.attach() - using direct HAL PWM
    DEBUG_PRINTLN("✅ BYPASSING Servo.attach() - using direct TIM1 PWM");
    DEBUG_PRINTLN("⚙️ Motor 1 initialized on PA8 (TIM1_CH1) via HAL");
    DEBUG_PRINTLN("⚙️ Motor 2 initialized on PA9 (TIM1_CH2) via HAL");

    // Set PWM values manually
    for (int i = 0; i < NUM_MOTORS; i++) {
        motor_pwm_values_[i] = PWM_NEUTRAL;
    }

    DEBUG_PRINTLN("📏 Measure voltages on PA8 and PA9 with multimeter");
    DEBUG_PRINTLN("   Expected: ~0.25V for 1500μs PWM");
    DEBUG_PRINTLN("   Problem: 0V indicates PWM not working despite successful attach");
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
    static uint32_t last_pwm_debug = 0;
    uint32_t now = millis();

    for (int i = 0; i < NUM_MOTORS; i++) {
        uint16_t output_pwm = motors_armed_ ? motor_pwm_values_[i] : PWM_NEUTRAL;

        // Debug PWM output every 5 seconds
        if (now - last_pwm_debug >= 5000) {
            DEBUG_PRINT("🔧 HAL PWM DEBUG: Motor ");
            DEBUG_PRINT(i + 1);
            DEBUG_PRINT(" Pin ");
            DEBUG_PRINT(MOTOR_PINS[i]);
            DEBUG_PRINT(" TIM1_CH");
            DEBUG_PRINT(i + 1);
            DEBUG_PRINT(" = ");
            DEBUG_PRINT(output_pwm);
            DEBUG_PRINTLN("μs");
        }

        // Use direct HAL TIM1 PWM instead of Servo library
        if (i == 0) {
            // PA8 = TIM1_CH1
            __HAL_TIM_SET_COMPARE(&htim1_global, TIM_CHANNEL_1, output_pwm);
        } else if (i == 1) {
            // PA9 = TIM1_CH2
            __HAL_TIM_SET_COMPARE(&htim1_global, TIM_CHANNEL_2, output_pwm);
        }
    }

    if (now - last_pwm_debug >= 5000) {
        last_pwm_debug = now;
    }
}
