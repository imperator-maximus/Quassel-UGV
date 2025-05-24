/**
 * @file MotorController.h
 * @brief Motor Controller class for managing PWM outputs to ESCs
 * @author Beyond Robotics DroneCAN Implementation
 * @version 1.0
 * @date 2024
 */

#ifndef MOTOR_CONTROLLER_H
#define MOTOR_CONTROLLER_H

#include "project_common.h"
#include "config/config.h"

/**
 * @class MotorController
 * @brief Manages PWM outputs for motor/ESC control with safety features
 * 
 * This class handles:
 * - PWM signal generation for ESCs
 * - Safety timeout monitoring
 * - Motor arming/disarming
 * - Command value mapping and validation
 */
class MotorController {
public:
    /**
     * @brief Constructor
     */
    MotorController();

    /**
     * @brief Destructor
     */
    ~MotorController();

    /**
     * @brief Initialize the motor controller
     * @return true if initialization successful, false otherwise
     */
    bool initialize();

    /**
     * @brief Update motor outputs (call this regularly in main loop)
     */
    void update();

    /**
     * @brief Set motor command values from DroneCAN ESC command
     * @param raw_commands Array of raw command values (-8192 to 8191)
     * @param num_commands Number of commands in array
     */
    void setMotorCommands(const int16_t* raw_commands, uint8_t num_commands);

    /**
     * @brief Set individual motor PWM value
     * @param motor_index Motor index (0 to NUM_MOTORS-1)
     * @param pwm_value PWM value in microseconds (PWM_MIN to PWM_MAX)
     */
    void setMotorPWM(uint8_t motor_index, uint16_t pwm_value);

    /**
     * @brief Get current motor PWM value
     * @param motor_index Motor index (0 to NUM_MOTORS-1)
     * @return Current PWM value in microseconds
     */
    uint16_t getMotorPWM(uint8_t motor_index) const;

    /**
     * @brief Check if motors are currently armed
     * @return true if armed, false if disarmed
     */
    bool isArmed() const;

    /**
     * @brief Manually arm motors (use with caution)
     */
    void arm();

    /**
     * @brief Manually disarm motors (safe)
     */
    void disarm();

    /**
     * @brief Get time since last command received
     * @return Milliseconds since last command
     */
    uint32_t getTimeSinceLastCommand() const;

    /**
     * @brief Print motor status for debugging
     */
    void printStatus() const;

private:
    /// Servo objects for PWM generation
    Servo motors_[NUM_MOTORS];
    
    /// Current PWM values for each motor
    uint16_t motor_pwm_values_[NUM_MOTORS];
    
    /// Motor armed state
    bool motors_armed_;
    
    /// Timestamp of last ESC command received
    uint32_t last_command_time_;
    
    /// Last debug output time
    mutable uint32_t last_debug_time_;

    /**
     * @brief Convert DroneCAN raw command to PWM value
     * @param raw_command Raw command value (-8192 to 8191)
     * @return PWM value in microseconds (PWM_MIN to PWM_MAX)
     */
    uint16_t rawCommandToPWM(int16_t raw_command) const;

    /**
     * @brief Validate motor index
     * @param motor_index Motor index to validate
     * @return true if valid, false otherwise
     */
    bool isValidMotorIndex(uint8_t motor_index) const;

    /**
     * @brief Check for safety timeout and disarm if necessary
     */
    void checkSafetyTimeout();

    /**
     * @brief Apply PWM values to physical motors
     */
    void updateMotorOutputs();
};

#endif // MOTOR_CONTROLLER_H
