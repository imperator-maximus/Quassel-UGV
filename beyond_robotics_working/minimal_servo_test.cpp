/**
 * @file minimal_servo_test.cpp
 * @brief MINIMAL SERVO TEST - PA8/PA9 ohne Konflikte
 * 
 * Testet nur Servo.h auf PA8/PA9 ohne DroneCAN oder andere Bibliotheken
 * um herauszufinden, ob das Problem bei Pin-Konflikten liegt.
 */

#include <Arduino.h>
#include <Servo.h>

// Test-Servos
Servo motor1;  // PA8
Servo motor2;  // PA9

// Test-Werte
#define PWM_MIN     1000
#define PWM_NEUTRAL 1500
#define PWM_MAX     2000

void setup() {
    Serial.begin(115200);
    delay(2000);
    
    Serial.println("=== MINIMAL SERVO TEST ===");
    Serial.println("Testing PA8/PA9 without any conflicts");
    Serial.println();
    
    // Test PA8 (Pin 8)
    Serial.print("Testing PA8 (pin 8) Servo.attach()... ");
    if (motor1.attach(8, PWM_MIN, PWM_MAX)) {
        Serial.println("✅ SUCCESS");
        motor1.writeMicroseconds(PWM_NEUTRAL);
    } else {
        Serial.println("❌ FAILED");
    }
    
    // Test PA9 (Pin 9) - MIGHT CONFLICT WITH I2C!
    Serial.print("Testing PA9 (pin 9) Servo.attach()... ");
    if (motor2.attach(9, PWM_MIN, PWM_MAX)) {
        Serial.println("✅ SUCCESS");
        motor2.writeMicroseconds(PWM_NEUTRAL);
    } else {
        Serial.println("❌ FAILED - MIGHT BE I2C CONFLICT!");
    }
    
    Serial.println();
    Serial.println("📏 Measure PA8 and PA9 with multimeter");
    Serial.println("Expected: ~0.25V for 1500μs PWM");
    Serial.println();
}

void loop() {
    static uint32_t last_change = 0;
    static uint8_t phase = 0;
    
    if (millis() - last_change > 3000) {
        last_change = millis();
        
        switch (phase) {
            case 0:
                Serial.println("Setting 1000μs (expect ~0.17V)");
                if (motor1.attached()) motor1.writeMicroseconds(PWM_MIN);
                if (motor2.attached()) motor2.writeMicroseconds(PWM_MIN);
                break;
                
            case 1:
                Serial.println("Setting 1500μs (expect ~0.25V)");
                if (motor1.attached()) motor1.writeMicroseconds(PWM_NEUTRAL);
                if (motor2.attached()) motor2.writeMicroseconds(PWM_NEUTRAL);
                break;
                
            case 2:
                Serial.println("Setting 2000μs (expect ~0.33V)");
                if (motor1.attached()) motor1.writeMicroseconds(PWM_MAX);
                if (motor2.attached()) motor2.writeMicroseconds(PWM_MAX);
                break;
        }
        
        phase = (phase + 1) % 3;
    }
}
