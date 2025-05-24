#include <Arduino.h>

// Minimal test variables
uint32_t counter = 0;

void setup() {
    // Initialize LED first
    pinMode(LED_BUILTIN, OUTPUT);

    // Extended startup sequence - 10 blinks to confirm board is running
    for(int i = 0; i < 10; i++) {
        digitalWrite(LED_BUILTIN, HIGH);
        delay(100);
        digitalWrite(LED_BUILTIN, LOW);
        delay(100);
    }

    // Long delay to ensure everything is stable
    delay(3000);

    // Initialize UART2 for ST-LINK communication (Beyond Robotics specific)
    Serial2.begin(115200);
    delay(2000);  // Extra long delay for serial initialization

    // Multiple test messages with delays
    for(int i = 1; i <= 5; i++) {
        Serial2.print("SERIAL2 TEST #");
        Serial2.print(i);
        Serial2.println(" - Beyond Robotics Dev Board");
        Serial2.flush();
        delay(500);
    }

    Serial2.println("=== BOARD STARTUP COMPLETE ===");
    Serial2.println("Hardware: Beyond Robotics Dev Board");
    Serial2.println("MCU: STM32L431 Micro Node");
    Serial2.println("Connection: ST-LINK V3");
    Serial2.println("Serial: UART2 at 115200 baud");
    Serial2.println("===============================");
    Serial2.flush();
}

void loop() {
    // Simple counter and LED blink every second
    counter++;

    // Toggle LED
    static bool led_state = false;
    led_state = !led_state;
    digitalWrite(LED_BUILTIN, led_state);

    // Print detailed status message to UART2 (ST-LINK)
    Serial2.print("Loop #");
    Serial2.print(counter);
    Serial2.print(" | LED: ");
    Serial2.print(led_state ? "ON" : "OFF");
    Serial2.print(" | Uptime: ");
    Serial2.print(millis() / 1000);
    Serial2.println(" sec");
    Serial2.flush();

    // Every 10th loop, print extended status
    if(counter % 10 == 0) {
        Serial2.println("--- STATUS UPDATE ---");
        Serial2.print("Board running for: ");
        Serial2.print(millis() / 1000);
        Serial2.println(" seconds");
        Serial2.println("LED blinking: OK");
        Serial2.println("UART2 Serial output: OK");
        Serial2.println("Ready for CAN implementation");
        Serial2.println("--------------------");
        Serial2.flush();
    }

    // Wait 1 second
    delay(1000);
}


