/**
 * @file TestMode.h
 * @brief Test mode functionality for Beyond Robotics Motor Controller
 * @author Beyond Robotics DroneCAN Implementation
 * @version 1.0
 * @date 2024
 */

#ifndef TEST_MODE_H
#define TEST_MODE_H

#include "project_common.h"
#include "config/config.h"

// Forward declarations
class MotorController;
class DroneCAN_Handler;

/**
 * @class TestMode
 * @brief Provides test functionality for motor controller development and validation
 * 
 * This class handles:
 * - Automatic test ESC command generation
 * - PWM sweep testing
 * - Motor validation sequences
 * - Test pattern generation
 */
class TestMode {
public:
    /**
     * @brief Constructor
     * @param motor_controller Reference to motor controller instance
     * @param dronecan_handler Reference to DroneCAN handler instance
     */
    TestMode(MotorController& motor_controller, DroneCAN_Handler& dronecan_handler);

    /**
     * @brief Destructor
     */
    ~TestMode();

    /**
     * @brief Initialize test mode
     * @return true if initialization successful, false otherwise
     */
    bool initialize();

    /**
     * @brief Update test mode (call this regularly in main loop)
     */
    void update();

    /**
     * @brief Enable/disable test mode
     * @param enabled true to enable, false to disable
     */
    void setEnabled(bool enabled);

    /**
     * @brief Check if test mode is enabled
     * @return true if enabled, false otherwise
     */
    bool isEnabled() const;

    /**
     * @brief Send test ESC command via DroneCAN
     */
    void sendTestESCCommand();

    /**
     * @brief Run motor validation sequence
     */
    void runMotorValidation();

    /**
     * @brief Print test status for debugging
     */
    void printStatus() const;

private:
    /// Reference to motor controller
    MotorController& motor_controller_;
    
    /// Reference to DroneCAN handler
    DroneCAN_Handler& dronecan_handler_;
    
    /// Test mode enabled flag
    bool enabled_;
    
    /// Last test ESC command time
    uint32_t last_test_time_;
    
    /// Current test PWM value
    uint16_t test_pwm_value_;
    
    /// Test direction (true = increasing, false = decreasing)
    bool test_direction_up_;

    /**
     * @brief Update test PWM value for next iteration
     */
    void updateTestPWMValue();

    /**
     * @brief Convert PWM value to DroneCAN raw command
     * @param pwm_value PWM value in microseconds
     * @return Raw command value (-8192 to 8191)
     */
    int16_t pwmToRawCommand(uint16_t pwm_value) const;
};

#endif // TEST_MODE_H
