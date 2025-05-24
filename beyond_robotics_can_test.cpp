#include <Arduino.h>

// For STM32F1 CAN support
#ifdef STM32F1xx
#include <STM32_CAN.h>
#endif

// CAN instance
#ifdef STM32F1xx
STM32_CAN Can(CAN1, DEF);
#endif

// Statistics
uint32_t total_messages_received = 0;
uint32_t last_stats_time = 0;
uint32_t last_heartbeat_time = 0;

void setup() {
    // Initialize serial communication
    Serial.begin(115200);
    while (!Serial) {
        delay(10);
    }

    Serial.println("=== Beyond Robotics CAN Node Test ===");
    Serial.println("Testing CAN communication with Orange Cube");
    Serial.println("Hardware: Beyond Robotics Dev Board + STM-LINK V3");
    Serial.println("CAN Speed: 500 kbps");
    Serial.println("Serial Output: COM8");
    Serial.println("=====================================");

#ifdef STM32F1xx
    // Initialize CAN
    Serial.println("Initializing CAN...");
    Can.begin();
    Can.setBaudRate(500000);  // 500 kbps

    // Set CAN filters to accept all messages
    Can.setFilter(0, 0, 0x7FF);

    Serial.println("CAN initialized successfully!");
#else
    Serial.println("ERROR: STM32F1 CAN not available on this platform!");
#endif

    Serial.println("Listening for CAN messages from Orange Cube...");
    Serial.println("Expected messages:");
    Serial.println("- DroneCAN NodeStatus (Heartbeat)");
    Serial.println("- DroneCAN ESC Status");
    Serial.println("- DroneCAN Servo Commands");
    Serial.println("- Raw CAN frames");
    Serial.println("=====================================");

    last_stats_time = millis();
    last_heartbeat_time = millis();
}

void loop() {
    const uint32_t now = millis();

#ifdef STM32F1xx
    // Check for received CAN messages
    CAN_message_t rxMsg;
    if (Can.read(rxMsg)) {
        total_messages_received++;

        Serial.print("[RX] ID: 0x");
        Serial.print(rxMsg.id, HEX);
        Serial.print(" | Len: ");
        Serial.print(rxMsg.len);
        Serial.print(" | Data: ");

        for (int i = 0; i < rxMsg.len; i++) {
            if (rxMsg.buf[i] < 0x10) Serial.print("0");
            Serial.print(rxMsg.buf[i], HEX);
            Serial.print(" ");
        }

        // Try to identify DroneCAN message types
        if (rxMsg.id & 0x80) {
            Serial.print("| Type: Service");
        } else {
            uint16_t data_type_id = (rxMsg.id >> 8) & 0xFFFF;
            uint8_t source_node_id = rxMsg.id & 0x7F;

            Serial.print("| Node: ");
            Serial.print(source_node_id);
            Serial.print(" | DataType: ");
            Serial.print(data_type_id);

            // Identify common DroneCAN message types
            switch (data_type_id) {
                case 341:
                    Serial.print(" (NodeStatus/Heartbeat)");
                    break;
                case 1034:
                    Serial.print(" (ESC Status)");
                    break;
                case 1010:
                    Serial.print(" (Actuator Array Command)");
                    break;
                case 1092:
                    Serial.print(" (Battery Info)");
                    break;
                default:
                    Serial.print(" (Unknown)");
                    break;
            }
        }

        Serial.println();
    }
#endif

    // Send periodic test message (every 2 seconds)
    if (now - last_heartbeat_time > 2000) {
        last_heartbeat_time = now;

#ifdef STM32F1xx
        // Send a simple test message
        CAN_message_t txMsg;
        txMsg.id = 0x123;  // Simple test ID
        txMsg.len = 8;
        txMsg.buf[0] = 0xAA;
        txMsg.buf[1] = 0xBB;
        txMsg.buf[2] = (now >> 24) & 0xFF;
        txMsg.buf[3] = (now >> 16) & 0xFF;
        txMsg.buf[4] = (now >> 8) & 0xFF;
        txMsg.buf[5] = now & 0xFF;
        txMsg.buf[6] = 0xCC;
        txMsg.buf[7] = 0xDD;

        if (Can.write(txMsg)) {
            Serial.print("[TX] Test message sent - ID: 0x");
            Serial.println(txMsg.id, HEX);
        } else {
            Serial.println("[TX] Failed to send test message");
        }
#endif
    }

    // Print statistics every 5 seconds
    if (now - last_stats_time > 5000) {
        last_stats_time = now;
        Serial.print("=== STATS === Total messages received: ");
        Serial.print(total_messages_received);
        Serial.print(" | Uptime: ");
        Serial.print(now / 1000);
        Serial.println(" seconds");
    }

    // Small delay to prevent overwhelming the serial output
    delay(10);
}

// Simple CAN test - no DroneCAN library dependencies
// This version uses basic STM32 CAN to receive and decode raw CAN frames
