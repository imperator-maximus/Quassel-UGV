#include <Arduino.h>
#include <Servo.h>

Servo motor1;

void setup() {
    Serial.begin(115200);
    delay(3000);  // Longer delay for serial to stabilize
    
    Serial.println("=== PA8 ONLY TEST ===");
    Serial.println("Testing ONLY PA8 for PWM");
    Serial.println();
    
    // Test PA8 (Pin 8) only
    Serial.print("Testing PA8 (pin 8) Servo.attach()... ");
    if (motor1.attach(8, 1000, 2000)) {
        Serial.println("✅ SUCCESS!");
        motor1.writeMicroseconds(1500);
        Serial.println("✅ PA8 PWM should be working now!");
        Serial.println("📏 Measure voltage on PA8 with multimeter");
        Serial.println("   Expected: ~0.25V for 1500μs PWM");
    } else {
        Serial.println("❌ FAILED - PA8 not available for PWM");
    }
}

void loop() {
    static uint32_t last_time = 0;
    if (millis() - last_time > 2000) {
        last_time = millis();
        Serial.println("System running... PA8 test active");
        
        if (motor1.attached()) {
            // Cycle PWM values
            static uint16_t pwm = 1000;
            motor1.writeMicroseconds(pwm);
            Serial.print("PWM: ");
            Serial.println(pwm);
            
            pwm += 100;
            if (pwm > 2000) pwm = 1000;
        }
    }
}
