/*
 * Direct DroneCAN ESC Test
 * Sendet manuell ESC-Commands über DroneCAN um Motor-Controller zu testen
 * Läuft auf dem Beyond Robotics Board als Test-Sender
 */

#include <Arduino.h>
#include <dronecan.h>
#include <IWatchdog.h>
#include <app.h>
#include <vector>
#include <Servo.h>

// Motor Controller Configuration
#define NUM_MOTORS 4
#define PWM_MIN 1000
#define PWM_MAX 2000
#define PWM_NEUTRAL 1500

// Test configuration
#define TEST_NODE_ID 50  // Different from normal node ID (25)

DroneCAN dronecan;
uint32_t looptime = 0;

// Motor Controller Variables
const uint8_t MOTOR_PINS[NUM_MOTORS] = {PA8, PA9, PA10, PA11};
Servo motors[NUM_MOTORS];
uint16_t motor_pwm_values[NUM_MOTORS] = {PWM_NEUTRAL, PWM_NEUTRAL, PWM_NEUTRAL, PWM_NEUTRAL};
bool motors_armed = false;
uint32_t last_esc_command_time = 0;
const uint32_t ESC_TIMEOUT_MS = 1000;

// Test variables
uint32_t last_test_send_time = 0;
const uint32_t TEST_SEND_INTERVAL = 2000; // Send test commands every 2 seconds
uint16_t test_pwm_value = PWM_NEUTRAL;
bool test_direction_up = true;

std::vector<DroneCAN::parameter> custom_parameters = {
    { "NODEID", UAVCAN_PROTOCOL_PARAM_VALUE_INTEGER_VALUE, TEST_NODE_ID,  0, 127 },
    { "PARM_1", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
};

void onTransferReceived(CanardRxTransfer* transfer) {
    switch (transfer->data_type_id) {
    case UAVCAN_PROTOCOL_GETNODEINFO_ID:
    {
        Serial.print("GetNodeInfo request from");
        Serial.println(transfer->source_node_id);
        break;
    }
    
    case UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_ID:
    {
        // Handle ESC commands (from other nodes or our own test)
        uavcan_equipment_esc_RawCommand pkt{};
        uavcan_equipment_esc_RawCommand_decode(transfer, &pkt);
        
        Serial.print("🚀 ESC Command received from Node ");
        Serial.print(transfer->source_node_id);
        Serial.print(": [");
        
        for (int i = 0; i < NUM_MOTORS && i < pkt.cmd.len; i++) {
            // Convert from DroneCAN range (-8192 to 8191) to PWM (1000-2000)
            int16_t raw_cmd = pkt.cmd.data[i];
            uint16_t pwm_value = map(raw_cmd, -8192, 8191, PWM_MIN, PWM_MAX);
            pwm_value = constrain(pwm_value, PWM_MIN, PWM_MAX);
            
            motor_pwm_values[i] = pwm_value;
            Serial.print(pwm_value);
            if (i < NUM_MOTORS - 1) Serial.print(", ");
        }
        Serial.println("]");
        
        last_esc_command_time = millis();
        
        // Auto-arm motors when receiving valid commands
        if (!motors_armed) {
            motors_armed = true;
            Serial.println("🔓 Motors ARMED by ESC command");
        }
        break;
    }
    }
}

bool shouldAcceptTransfer(const CanardRxTransfer* transfer,
                          uint64_t* out_data_type_signature) {
    switch (transfer->data_type_id) {
        case UAVCAN_PROTOCOL_GETNODEINFO_ID:
        {
            *out_data_type_signature = UAVCAN_PROTOCOL_GETNODEINFO_SIGNATURE;
            return true;
        }
        
        case UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_ID:
        {
            *out_data_type_signature = UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_SIGNATURE;
            return true;
        }
    }
    return false;
}

void send_test_esc_command() {
    // Send test ESC command to ourselves and other nodes
    uavcan_equipment_esc_RawCommand pkt{};
    
    // Create test PWM values
    for (int i = 0; i < NUM_MOTORS; i++) {
        // Convert PWM (1000-2000) to DroneCAN range (-8192 to 8191)
        int16_t raw_cmd = map(test_pwm_value, PWM_MIN, PWM_MAX, -8192, 8191);
        pkt.cmd.data[i] = raw_cmd;
    }
    pkt.cmd.len = NUM_MOTORS;
    
    // Send the command
    uint8_t buffer[UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_MAX_SIZE];
    uint32_t len = uavcan_equipment_esc_RawCommand_encode(&pkt, buffer);
    static uint8_t transfer_id;
    
    canardBroadcast(&dronecan.canard,
                    UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_SIGNATURE,
                    UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_ID,
                    &transfer_id,
                    CANARD_TRANSFER_PRIORITY_HIGH,
                    buffer,
                    len);
    
    Serial.print("📤 Sent test ESC command: PWM=");
    Serial.print(test_pwm_value);
    Serial.print(" (Raw=");
    Serial.print(pkt.cmd.data[0]);
    Serial.println(")");
    
    // Update test PWM value for next time
    if (test_direction_up) {
        test_pwm_value += 50;
        if (test_pwm_value >= 1700) {
            test_direction_up = false;
        }
    } else {
        test_pwm_value -= 50;
        if (test_pwm_value <= 1300) {
            test_direction_up = true;
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(2000);
    
    Serial.println("=== DroneCAN ESC Direct Test ===");
    Serial.println("This program tests the motor controller by sending");
    Serial.println("DroneCAN ESC commands directly from this board.");
    Serial.println();
    
    // Initialize DroneCAN
    dronecan.init(custom_parameters, onTransferReceived, shouldAcceptTransfer);
    
    Serial.print("Node ID: ");
    Serial.println(dronecan.getParameter("NODEID"));
    Serial.println("CAN Bitrate: 1000000 bps");
    Serial.println();
    
    // Initialize Motor Controller
    Serial.println("=== Motor Controller Initialization ===");
    for (int i = 0; i < NUM_MOTORS; i++) {
        motors[i].attach(MOTOR_PINS[i], PWM_MIN, PWM_MAX);
        motors[i].writeMicroseconds(PWM_NEUTRAL);
        Serial.print("Motor ");
        Serial.print(i + 1);
        Serial.print(" on pin ");
        Serial.println(MOTOR_PINS[i]);
    }
    Serial.println("Motors initialized - starting ESC test...");
    Serial.println();
    
    Serial.println("🧪 TEST SEQUENCE:");
    Serial.println("- Sends ESC commands every 2 seconds");
    Serial.println("- PWM values cycle from 1300 to 1700");
    Serial.println("- Motors should respond to commands");
    Serial.println("- Watch for 🚀 ESC Command received messages");
    Serial.println();
}

void loop() {
    uint32_t now = millis();
    
    // Send test ESC commands periodically
    if (now - last_test_send_time >= TEST_SEND_INTERVAL) {
        last_test_send_time = now;
        send_test_esc_command();
    }
    
    // Motor Controller Updates
    // Safety check - disarm if no commands received for timeout period
    if (motors_armed && (now - last_esc_command_time) > ESC_TIMEOUT_MS) {
        motors_armed = false;
        Serial.println("⚠️ ESC timeout - motors DISARMED for safety");
        for (int i = 0; i < NUM_MOTORS; i++) {
            motor_pwm_values[i] = PWM_NEUTRAL;
        }
    }
    
    // Update motor outputs
    for (int i = 0; i < NUM_MOTORS; i++) {
        if (motors_armed) {
            motors[i].writeMicroseconds(motor_pwm_values[i]);
        } else {
            motors[i].writeMicroseconds(PWM_NEUTRAL);
        }
    }
    
    // Motor status debug output every 5 seconds
    static uint32_t motor_debug_time = 0;
    if (now - motor_debug_time > 5000) {
        motor_debug_time = now;
        Serial.print("Motors: ");
        Serial.print(motors_armed ? "ARMED" : "DISARMED");
        Serial.print(" PWM:[");
        for (int i = 0; i < NUM_MOTORS; i++) {
            Serial.print(motors_armed ? motor_pwm_values[i] : PWM_NEUTRAL);
            if (i < NUM_MOTORS - 1) Serial.print(",");
        }
        Serial.println("]");
    }
    
    dronecan.cycle();
    IWatchdog.reload();
}
