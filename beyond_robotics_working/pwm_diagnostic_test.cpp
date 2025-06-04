/**
 * @file pwm_diagnostic_test.cpp
 * @brief PWM Diagnostic Test - Beyond Robotics Motor Controller
 * @author Beyond Robotics DroneCAN Implementation
 * @version 1.0 - PWM DIAGNOSTIC MODE
 * @date 2024
 * 
 * MINIMAL PWM TEST TO DIAGNOSE SERVO.ATTACH() ISSUES
 * Tests PA8/PA9 and alternative pins PA6/PA7
 * 
 * PROBLEM: Motor PWM-Ausgabe funktioniert nicht. 
 * DroneCAN-Kommunikation OK (RC-Werte sichtbar via STLink), 
 * aber Motoren bewegen sich nicht. Multimeter zeigt konstant 
 * 0,62V an PA8/PA9 (sollte sich mit RC-Eingaben ändern).
 * 
 * EXPECTED VOLTAGES (3.3V logic, 20kHz PWM):
 * 1000μs: ~0.17V (5% duty cycle)
 * 1500μs: ~0.25V (7.5% duty cycle) 
 * 2000μs: ~0.33V (10% duty cycle)
 * 
 * CURRENT: Konstant 0,62V (Problem!)
 */

#include <Arduino.h>
#include <Servo.h>

// ============================================================================
// PWM DIAGNOSTIC CONFIGURATION
// ============================================================================

// Test pins - Primary and Alternative
#define TEST_PIN_1_PRIMARY   PA8   // TIM1_CH1 (Primary)
#define TEST_PIN_2_PRIMARY   PA9   // TIM1_CH2 (Primary)
#define TEST_PIN_1_ALT       PA6   // TIM16_CH1 (Alternative)
#define TEST_PIN_2_ALT       PA7   // TIM17_CH1 (Alternative)

// PWM Test Values
#define PWM_MIN     1000
#define PWM_NEUTRAL 1500
#define PWM_MAX     2000

// Test sequence timing
#define TEST_STEP_DELAY 3000  // 3 seconds per step

// ============================================================================
// GLOBAL VARIABLES
// ============================================================================

Servo test_servo_1;
Servo test_servo_2;
uint8_t current_test_pin_1 = TEST_PIN_1_PRIMARY;
uint8_t current_test_pin_2 = TEST_PIN_2_PRIMARY;
bool using_primary_pins = true;

// ============================================================================
// DIAGNOSTIC FUNCTIONS
// ============================================================================

void printPinInfo(uint8_t pin, const char* name) {
    Serial.print("📍 ");
    Serial.print(name);
    Serial.print(" (Pin ");
    Serial.print(pin);
    Serial.print("): ");
    
    // Print pin mapping info
    if (pin == PA8) Serial.println("PA8 - TIM1_CH1");
    else if (pin == PA9) Serial.println("PA9 - TIM1_CH2");
    else if (pin == PA6) Serial.println("PA6 - TIM16_CH1");
    else if (pin == PA7) Serial.println("PA7 - TIM17_CH1");
    else Serial.println("Unknown pin");
}

bool testServoAttach(Servo& servo, uint8_t pin, const char* servo_name) {
    Serial.print("🔧 Testing Servo.attach() for ");
    Serial.print(servo_name);
    Serial.print(" on pin ");
    Serial.print(pin);
    Serial.print("... ");
    
    bool result = servo.attach(pin, PWM_MIN, PWM_MAX);
    
    if (result) {
        Serial.println("✅ SUCCESS");
        return true;
    } else {
        Serial.println("❌ FAILED");
        return false;
    }
}

void testPWMOutput(Servo& servo, const char* servo_name, uint16_t pwm_value) {
    Serial.print("📡 Setting ");
    Serial.print(servo_name);
    Serial.print(" to ");
    Serial.print(pwm_value);
    Serial.println("μs");
    
    servo.writeMicroseconds(pwm_value);
}

void measureVoltage(uint8_t pin) {
    // Note: This is just for documentation - actual measurement with multimeter
    Serial.print("📏 Measure voltage on pin ");
    Serial.print(pin);
    Serial.println(" with multimeter");
    Serial.println("   Expected voltages (3.3V logic):");
    Serial.println("   1000μs: ~0.17V (5% duty cycle)");
    Serial.println("   1500μs: ~0.25V (7.5% duty cycle)");
    Serial.println("   2000μs: ~0.33V (10% duty cycle)");
}

// ============================================================================
// SETUP FUNCTION
// ============================================================================

void setup() {
    Serial.begin(115200);
    delay(2000);  // Allow serial to stabilize
    
    Serial.println("=== PWM DIAGNOSTIC TEST ===");
    Serial.println("Beyond Robotics STM32L431 Motor Controller");
    Serial.println("Testing Servo.attach() and PWM output");
    Serial.println();
    
    // Print system info
    Serial.println("🔍 SYSTEM INFORMATION:");
    Serial.println("Board: STM32L431 Beyond Robotics Dev Board");
    Serial.println("Framework: Arduino");
    Serial.println("PWM Library: Servo.h");
    Serial.println();
    
    // Print pin information
    Serial.println("📍 PIN MAPPING:");
    printPinInfo(TEST_PIN_1_PRIMARY, "Motor 1 Primary");
    printPinInfo(TEST_PIN_2_PRIMARY, "Motor 2 Primary");
    printPinInfo(TEST_PIN_1_ALT, "Motor 1 Alternative");
    printPinInfo(TEST_PIN_2_ALT, "Motor 2 Alternative");
    Serial.println();
    
    Serial.println("🚀 STARTING PWM DIAGNOSTIC TEST...");
    Serial.println();
}

// ============================================================================
// MAIN LOOP
// ============================================================================

void loop() {
    static uint8_t test_phase = 0;
    static uint32_t last_test_time = 0;
    static bool test_completed = false;
    
    uint32_t current_time = millis();
    
    // Skip if test already completed
    if (test_completed) {
        delay(5000);
        Serial.println("🔄 Restarting diagnostic test...");
        test_completed = false;
        test_phase = 0;
        return;
    }
    
    // Run test phases with timing
    if (current_time - last_test_time >= TEST_STEP_DELAY || test_phase == 0) {
        
        switch (test_phase) {
            case 0:
                Serial.println("=== PHASE 1: TESTING PRIMARY PINS (PA8/PA9) ===");
                Serial.println();
                
                // Test primary pins
                if (testServoAttach(test_servo_1, TEST_PIN_1_PRIMARY, "Servo1")) {
                    measureVoltage(TEST_PIN_1_PRIMARY);
                }
                Serial.println();
                
                if (testServoAttach(test_servo_2, TEST_PIN_2_PRIMARY, "Servo2")) {
                    measureVoltage(TEST_PIN_2_PRIMARY);
                }
                Serial.println();
                break;
                
            case 1:
                Serial.println("🔧 Testing PWM_MIN (1000μs)...");
                if (test_servo_1.attached()) testPWMOutput(test_servo_1, "Servo1", PWM_MIN);
                if (test_servo_2.attached()) testPWMOutput(test_servo_2, "Servo2", PWM_MIN);
                Serial.println("📏 Measure voltages now!");
                Serial.println();
                break;
                
            case 2:
                Serial.println("🔧 Testing PWM_NEUTRAL (1500μs)...");
                if (test_servo_1.attached()) testPWMOutput(test_servo_1, "Servo1", PWM_NEUTRAL);
                if (test_servo_2.attached()) testPWMOutput(test_servo_2, "Servo2", PWM_NEUTRAL);
                Serial.println("📏 Measure voltages now!");
                Serial.println();
                break;
                
            case 3:
                Serial.println("🔧 Testing PWM_MAX (2000μs)...");
                if (test_servo_1.attached()) testPWMOutput(test_servo_1, "Servo1", PWM_MAX);
                if (test_servo_2.attached()) testPWMOutput(test_servo_2, "Servo2", PWM_MAX);
                Serial.println("📏 Measure voltages now!");
                Serial.println();
                break;
                
            case 4:
                Serial.println("=== PHASE 2: TESTING ALTERNATIVE PINS (PA6/PA7) ===");
                Serial.println();
                
                // Detach primary pins
                test_servo_1.detach();
                test_servo_2.detach();
                delay(100);
                
                // Test alternative pins
                if (testServoAttach(test_servo_1, TEST_PIN_1_ALT, "Servo1_Alt")) {
                    measureVoltage(TEST_PIN_1_ALT);
                }
                Serial.println();
                
                if (testServoAttach(test_servo_2, TEST_PIN_2_ALT, "Servo2_Alt")) {
                    measureVoltage(TEST_PIN_2_ALT);
                }
                Serial.println();
                break;
                
            case 5:
                Serial.println("🔧 Testing ALT PWM_NEUTRAL (1500μs)...");
                if (test_servo_1.attached()) testPWMOutput(test_servo_1, "Servo1_Alt", PWM_NEUTRAL);
                if (test_servo_2.attached()) testPWMOutput(test_servo_2, "Servo2_Alt", PWM_NEUTRAL);
                Serial.println("📏 Measure voltages now!");
                Serial.println();
                break;
                
            case 6:
                Serial.println("=== DIAGNOSTIC TEST COMPLETED ===");
                Serial.println();
                Serial.println("📊 RESULTS SUMMARY:");
                Serial.println("1. Check if Servo.attach() succeeded for each pin");
                Serial.println("2. Verify voltage measurements match expected values");
                Serial.println("3. If PA8/PA9 failed, try PA6/PA7 alternatives");
                Serial.println();
                Serial.println("🔍 TROUBLESHOOTING:");
                Serial.println("- Constant 0.62V = PWM not working (attach failed)");
                Serial.println("- Changing voltages = PWM working correctly");
                Serial.println("- Check timer conflicts in variant files");
                Serial.println();
                test_completed = true;
                break;
        }
        
        test_phase++;
        last_test_time = current_time;
    }
    
    delay(100);
}
