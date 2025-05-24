/**
 * @file DroneCAN_Handler.h
 * @brief DroneCAN communication handler for Beyond Robotics Motor Controller
 * @author Beyond Robotics DroneCAN Implementation
 * @version 1.0
 * @date 2024
 */

#ifndef DRONECAN_HANDLER_H
#define DRONECAN_HANDLER_H

#include "project_common.h"
#include "config/config.h"

// Forward declaration
class MotorController;

/**
 * @class DroneCAN_Handler
 * @brief Handles all DroneCAN communication including message reception and transmission
 * 
 * This class manages:
 * - DroneCAN initialization and configuration
 * - Message reception (ESC commands, etc.)
 * - Message transmission (battery info, status, etc.)
 * - Parameter management
 * - Integration with MotorController
 */
class DroneCAN_Handler {
public:
    /**
     * @brief Constructor
     * @param motor_controller Reference to motor controller instance
     */
    explicit DroneCAN_Handler(MotorController& motor_controller);

    /**
     * @brief Destructor
     */
    ~DroneCAN_Handler();

    /**
     * @brief Initialize DroneCAN communication
     * @return true if initialization successful, false otherwise
     */
    bool initialize();

    /**
     * @brief Process DroneCAN communication (call this regularly in main loop)
     */
    void update();

    /**
     * @brief Get the DroneCAN instance
     * @return Reference to DroneCAN instance
     */
    DroneCAN& getDroneCAN();

    /**
     * @brief Send battery information message
     */
    void sendBatteryInfo();

    /**
     * @brief Print DroneCAN status for debugging
     */
    void printStatus() const;

    /**
     * @brief Static callback for transfer reception (required by DroneCAN library)
     * @param ins Canard instance
     * @param transfer Received transfer
     */
    static void onTransferReceived(CanardInstance* ins, CanardRxTransfer* transfer);

    /**
     * @brief Static callback for transfer acceptance (required by DroneCAN library)
     * @param ins Canard instance
     * @param out_data_type_signature Output data type signature
     * @param data_type_id Data type ID
     * @param transfer_type Transfer type
     * @param source_node_id Source node ID
     * @return true if transfer should be accepted
     */
    static bool shouldAcceptTransfer(const CanardInstance* ins,
                                   uint64_t* out_data_type_signature,
                                   uint16_t data_type_id,
                                   CanardTransferType transfer_type,
                                   uint8_t source_node_id);

private:
    /// Reference to motor controller
    MotorController& motor_controller_;
    
    /// DroneCAN instance
    DroneCAN dronecan_;
    
    /// Battery info transmission timing
    uint32_t last_battery_time_;
    
    /// Battery debug counter
    uint32_t battery_debug_counter_;
    
    /// Static instance pointer for callbacks
    static DroneCAN_Handler* instance_;

    /**
     * @brief Handle received ESC command
     * @param transfer Received transfer containing ESC command
     */
    void handleESCCommand(CanardRxTransfer* transfer);

    /**
     * @brief Handle received magnetic field strength (example)
     * @param transfer Received transfer containing magnetic field data
     */
    void handleMagneticFieldStrength(CanardRxTransfer* transfer);

    /**
     * @brief Instance method for transfer reception
     * @param ins Canard instance
     * @param transfer Received transfer
     */
    void onTransferReceivedInstance(CanardInstance* ins, CanardRxTransfer* transfer);

    /**
     * @brief Instance method for transfer acceptance
     * @param ins Canard instance
     * @param out_data_type_signature Output data type signature
     * @param data_type_id Data type ID
     * @param transfer_type Transfer type
     * @param source_node_id Source node ID
     * @return true if transfer should be accepted
     */
    bool shouldAcceptTransferInstance(const CanardInstance* ins,
                                    uint64_t* out_data_type_signature,
                                    uint16_t data_type_id,
                                    CanardTransferType transfer_type,
                                    uint8_t source_node_id);

    /**
     * @brief Read MCU temperature sensor
     * @return Temperature in degrees Celsius
     */
    int32_t readMCUTemperature() const;
};

#endif // DRONECAN_HANDLER_H
