/**
 * @file DroneCAN_Handler.cpp
 * @brief Implementation of DroneCAN_Handler class
 * @author Beyond Robotics DroneCAN Implementation
 * @version 1.0
 * @date 2024
 */

#include "dronecan_handler/DroneCAN_Handler.h"
#include "motor_controller/MotorController.h"

// Static instance pointer for callbacks
DroneCAN_Handler* DroneCAN_Handler::instance_ = nullptr;

// DroneCAN parameters definition
const std::vector<DroneCAN::parameter> DRONECAN_PARAMETERS = {
    { "NODEID", UAVCAN_PROTOCOL_PARAM_VALUE_INTEGER_VALUE, DRONECAN_NODE_ID, 0, 127 },
    { "PARM_1", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_2", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_3", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_4", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_5", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_6", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_7", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
};

DroneCAN_Handler::DroneCAN_Handler(MotorController& motor_controller)
    : motor_controller_(motor_controller)
    , last_battery_time_(0)
    , battery_debug_counter_(0)
{
    // Set static instance for callbacks
    instance_ = this;
}

DroneCAN_Handler::~DroneCAN_Handler() {
    instance_ = nullptr;
}

bool DroneCAN_Handler::initialize() {
    DEBUG_PRINTLN("=== DroneCAN Handler Initialization ===");

    // Set DroneCAN version
    dronecan_.version_major = PROJECT_VERSION_MAJOR;
    dronecan_.version_minor = PROJECT_VERSION_MINOR;

    // Initialize DroneCAN with callbacks, parameters, and static Node ID
    dronecan_.init(
        onTransferReceived,
        shouldAcceptTransfer,
        DRONECAN_PARAMETERS,
        DRONECAN_NODE_NAME,
        DRONECAN_NODE_ID
    );

    // Example parameter usage
    dronecan_.setParameter("PARM_1", 69);
    DEBUG_PRINT("PARM_1 value: ");
    DEBUG_PRINTLN(dronecan_.getParameter("PARM_1"));

    // Print configuration
    DEBUG_PRINT("Node ID: ");
    DEBUG_PRINTLN(dronecan_.getParameter("NODEID"));
    DEBUG_PRINT("CAN Bitrate: ");
    DEBUG_PRINT(CAN_BITRATE);
    DEBUG_PRINTLN(" bps");
    DEBUG_PRINTLN("✅ Ready for Orange Cube integration!");
    DEBUG_PRINT("Battery messages every ");
    DEBUG_PRINT(BATTERY_UPDATE_INTERVAL_MS);
    DEBUG_PRINTLN("ms");

    return true;
}

void DroneCAN_Handler::update() {
    // Send battery info at regular intervals
    uint32_t now = millis();
    if (now - last_battery_time_ >= BATTERY_UPDATE_INTERVAL_MS) {
        last_battery_time_ = now;
        sendBatteryInfo();
    }

    // Process DroneCAN communication
    dronecan_.cycle();
}

DroneCAN& DroneCAN_Handler::getDroneCAN() {
    return dronecan_;
}

void DroneCAN_Handler::sendBatteryInfo() {
    // Read MCU temperature
    int32_t cpu_temp = readMCUTemperature();

    // Construct DroneCAN battery packet
    uavcan_equipment_power_BatteryInfo pkt{};
    pkt.voltage = analogRead(BATTERY_VOLTAGE_PIN);
    pkt.current = analogRead(BATTERY_CURRENT_PIN);
    pkt.temperature = cpu_temp;

    // Encode and send message
    uint8_t buffer[UAVCAN_EQUIPMENT_POWER_BATTERYINFO_MAX_SIZE];
    uint32_t len = uavcan_equipment_power_BatteryInfo_encode(&pkt, buffer);
    static uint8_t transfer_id;

    canardBroadcast(&dronecan_.canard,
                    UAVCAN_EQUIPMENT_POWER_BATTERYINFO_SIGNATURE,
                    UAVCAN_EQUIPMENT_POWER_BATTERYINFO_ID,
                    &transfer_id,
                    CANARD_TRANSFER_PRIORITY_LOW,
                    buffer,
                    len);

    // Debug output at regular intervals
    battery_debug_counter_++;
    if (battery_debug_counter_ % BATTERY_DEBUG_INTERVAL == 0) {
        DEBUG_PRINT(ICON_BATTERY " Battery: V=");
        DEBUG_PRINT(pkt.voltage);
        DEBUG_PRINT(", I=");
        DEBUG_PRINT(pkt.current);
        DEBUG_PRINT(", T=");
        DEBUG_PRINT(pkt.temperature);
        DEBUG_PRINT("°C, Transfer ID=");
        DEBUG_PRINTLN(transfer_id);
    }
}

void DroneCAN_Handler::printStatus() const {
    DEBUG_PRINT("DroneCAN Node ID: ");
    DEBUG_PRINT(DRONECAN_NODE_ID);
    DEBUG_PRINT(", Battery messages sent: ");
    DEBUG_PRINTLN(battery_debug_counter_);
}

void DroneCAN_Handler::onTransferReceived(CanardInstance* ins, CanardRxTransfer* transfer) {
    if (instance_) {
        instance_->onTransferReceivedInstance(ins, transfer);
    }
}

bool DroneCAN_Handler::shouldAcceptTransfer(const CanardInstance* ins,
                                          uint64_t* out_data_type_signature,
                                          uint16_t data_type_id,
                                          CanardTransferType transfer_type,
                                          uint8_t source_node_id) {
    if (instance_) {
        return instance_->shouldAcceptTransferInstance(ins, out_data_type_signature,
                                                     data_type_id, transfer_type, source_node_id);
    }
    return false;
}

void DroneCAN_Handler::handleESCCommand(CanardRxTransfer* transfer) {
    uavcan_equipment_esc_RawCommand pkt{};
    uavcan_equipment_esc_RawCommand_decode(transfer, &pkt);

    // DEBUG: Print received ESC command
    DEBUG_PRINT("🎮 ESC Command received! Motors: ");
    for (uint8_t i = 0; i < pkt.cmd.len && i < 4; i++) {
        DEBUG_PRINT(pkt.cmd.data[i]);
        if (i < pkt.cmd.len - 1) DEBUG_PRINT(", ");
    }
    DEBUG_PRINTLN("");

    // Forward command to motor controller
    motor_controller_.setMotorCommands(pkt.cmd.data, pkt.cmd.len);
}

void DroneCAN_Handler::handleMagneticFieldStrength(CanardRxTransfer* transfer) {
    uavcan_equipment_ahrs_MagneticFieldStrength pkt{};
    uavcan_equipment_ahrs_MagneticFieldStrength_decode(transfer, &pkt);

    // Example: could be used for compass data processing
    // Currently just decoded but not used
}

void DroneCAN_Handler::onTransferReceivedInstance(CanardInstance* ins, CanardRxTransfer* transfer) {
    // Handle specific message types
    switch (transfer->data_type_id) {
        case UAVCAN_EQUIPMENT_AHRS_MAGNETICFIELDSTRENGTH_ID:
            handleMagneticFieldStrength(transfer);
            break;

        case UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_ID:
            handleESCCommand(transfer);
            break;
    }

    // Call library's default handler for parameter management, etc.
    DroneCANonTransferReceived(dronecan_, ins, transfer);
}

bool DroneCAN_Handler::shouldAcceptTransferInstance(const CanardInstance* ins,
                                                  uint64_t* out_data_type_signature,
                                                  uint16_t data_type_id,
                                                  CanardTransferType transfer_type,
                                                  uint8_t source_node_id) {
    if (transfer_type == CanardTransferTypeBroadcast) {
        switch (data_type_id) {
            case UAVCAN_EQUIPMENT_AHRS_MAGNETICFIELDSTRENGTH_ID:
                *out_data_type_signature = UAVCAN_EQUIPMENT_AHRS_MAGNETICFIELDSTRENGTH_SIGNATURE;
                return true;

            case UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_ID:
                *out_data_type_signature = UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_SIGNATURE;
                return true;
        }
    }

    // Delegate to library's default handler
    return DroneCANshoudlAcceptTransfer(ins, out_data_type_signature, data_type_id, transfer_type, source_node_id);
}

int32_t DroneCAN_Handler::readMCUTemperature() const {
    // Read MCU core temperature using STM32 specific functions
    int32_t vref = __LL_ADC_CALC_VREFANALOG_VOLTAGE(analogRead(AVREF), LL_ADC_RESOLUTION_12B);
    return __LL_ADC_CALC_TEMPERATURE(vref, analogRead(ATEMP), LL_ADC_RESOLUTION_12B);
}
