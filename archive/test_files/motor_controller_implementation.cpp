/*
 * Motor Controller Implementation for Beyond Robotics Board
 * Receives ESC commands from Orange Cube via DroneCAN
 * Controls PWM outputs for motor control
 */

#include <Arduino.h>
#include <DroneCAN.h>
#include <Servo.h>

// Motor Controller Configuration
#define NUM_MOTORS 4
#define PWM_FREQUENCY 50  // 50Hz for ESCs
#define PWM_MIN 1000      // 1ms pulse width (minimum)
#define PWM_MAX 2000      // 2ms pulse width (maximum)
#define PWM_NEUTRAL 1500  // 1.5ms pulse width (neutral)

// PWM Output Pins (STM32L431 Timer-capable pins)
const uint8_t MOTOR_PINS[NUM_MOTORS] = {
    PA8,   // TIM1_CH1 - Motor 1 (Front Left)
    PA9,   // TIM1_CH2 - Motor 2 (Front Right)  
    PA10,  // TIM1_CH3 - Motor 3 (Rear Left)
    PA11   // TIM1_CH4 - Motor 4 (Rear Right)
};

// Servo objects for PWM control
Servo motors[NUM_MOTORS];

// Motor state variables
uint16_t motor_pwm_values[NUM_MOTORS] = {PWM_NEUTRAL, PWM_NEUTRAL, PWM_NEUTRAL, PWM_NEUTRAL};
bool motors_armed = false;
uint32_t last_command_time = 0;
const uint32_t COMMAND_TIMEOUT_MS = 1000; // 1 second timeout

// DroneCAN ESC Status structure
struct ESCStatus {
    uint16_t pwm_value;
    float current;
    float voltage;
    float temperature;
    uint32_t error_count;
    bool armed;
};

ESCStatus esc_status[NUM_MOTORS];

// Function prototypes
void init_motor_controller();
void handle_esc_command(CanardRxTransfer* transfer);
void update_motor_outputs();
void send_esc_status();
void safety_check();
void arm_motors();
void disarm_motors();

void init_motor_controller() {
    Serial.println("=== Motor Controller Initialization ===");
    
    // Initialize servo objects for PWM control
    for (int i = 0; i < NUM_MOTORS; i++) {
        motors[i].attach(MOTOR_PINS[i], PWM_MIN, PWM_MAX);
        motors[i].writeMicroseconds(PWM_NEUTRAL);
        
        // Initialize ESC status
        esc_status[i].pwm_value = PWM_NEUTRAL;
        esc_status[i].current = 0.0f;
        esc_status[i].voltage = 0.0f;
        esc_status[i].temperature = 25.0f;
        esc_status[i].error_count = 0;
        esc_status[i].armed = false;
        
        Serial.print("Motor ");
        Serial.print(i + 1);
        Serial.print(" initialized on pin ");
        Serial.println(MOTOR_PINS[i]);
    }
    
    Serial.println("Motors initialized in DISARMED state");
    Serial.println("Waiting for ESC commands from Orange Cube...");
}

void handle_esc_command(CanardRxTransfer* transfer) {
    // Decode DroneCAN ESC command message
    // This would be called by the DroneCAN library when ESC commands are received
    
    if (transfer->payload_len >= 8) { // Minimum payload for ESC command
        // Parse ESC command data (simplified example)
        uint16_t* pwm_commands = (uint16_t*)transfer->payload;
        
        Serial.print("ESC Command received: ");
        for (int i = 0; i < NUM_MOTORS && i < transfer->payload_len/2; i++) {
            uint16_t pwm_value = pwm_commands[i];
            
            // Validate PWM range
            if (pwm_value >= PWM_MIN && pwm_value <= PWM_MAX) {
                motor_pwm_values[i] = pwm_value;
                Serial.print("M");
                Serial.print(i + 1);
                Serial.print("=");
                Serial.print(pwm_value);
                Serial.print(" ");
            }
        }
        Serial.println();
        
        last_command_time = millis();
        
        // Auto-arm if valid commands received
        if (!motors_armed && last_command_time > 0) {
            arm_motors();
        }
    }
}

void update_motor_outputs() {
    if (motors_armed) {
        for (int i = 0; i < NUM_MOTORS; i++) {
            motors[i].writeMicroseconds(motor_pwm_values[i]);
            esc_status[i].pwm_value = motor_pwm_values[i];
            esc_status[i].armed = true;
        }
    } else {
        // Output neutral/stop signals when disarmed
        for (int i = 0; i < NUM_MOTORS; i++) {
            motors[i].writeMicroseconds(PWM_NEUTRAL);
            esc_status[i].pwm_value = PWM_NEUTRAL;
            esc_status[i].armed = false;
        }
    }
}

void send_esc_status() {
    // Send ESC status back to Orange Cube via DroneCAN
    // This provides feedback about motor states
    
    static uint32_t last_status_time = 0;
    const uint32_t STATUS_INTERVAL_MS = 100; // 10Hz status updates
    
    if (millis() - last_status_time >= STATUS_INTERVAL_MS) {
        for (int i = 0; i < NUM_MOTORS; i++) {
            // Simulate current/voltage readings (replace with real sensors)
            esc_status[i].current = (motor_pwm_values[i] - PWM_NEUTRAL) * 0.01f; // Simulated current
            esc_status[i].voltage = 12.0f; // Simulated battery voltage
            esc_status[i].temperature = 25.0f + (motor_pwm_values[i] - PWM_NEUTRAL) * 0.005f;
            
            // TODO: Encode and send DroneCAN ESC status message
            // This would use the DroneCAN library to broadcast ESC status
        }
        
        // Debug output every 5 seconds
        static uint32_t debug_counter = 0;
        debug_counter++;
        if (debug_counter % 50 == 0) {
            Serial.print("ESC Status - Armed: ");
            Serial.print(motors_armed ? "YES" : "NO");
            Serial.print(", PWM: [");
            for (int i = 0; i < NUM_MOTORS; i++) {
                Serial.print(motor_pwm_values[i]);
                if (i < NUM_MOTORS - 1) Serial.print(", ");
            }
            Serial.println("]");
        }
        
        last_status_time = millis();
    }
}

void safety_check() {
    // Check for command timeout
    if (motors_armed && (millis() - last_command_time) > COMMAND_TIMEOUT_MS) {
        Serial.println("⚠️ Command timeout - disarming motors for safety");
        disarm_motors();
    }
    
    // Additional safety checks can be added here:
    // - Battery voltage monitoring
    // - Temperature monitoring  
    // - Error condition detection
}

void arm_motors() {
    if (!motors_armed) {
        motors_armed = true;
        Serial.println("🚀 Motors ARMED - ESC control active");
        
        // Send arming confirmation to Orange Cube
        // TODO: Send DroneCAN arming status message
    }
}

void disarm_motors() {
    if (motors_armed) {
        motors_armed = false;
        
        // Set all motors to neutral
        for (int i = 0; i < NUM_MOTORS; i++) {
            motor_pwm_values[i] = PWM_NEUTRAL;
        }
        
        Serial.println("🛑 Motors DISARMED - safety stop");
        
        // Send disarming confirmation to Orange Cube
        // TODO: Send DroneCAN disarming status message
    }
}

// Main motor controller loop functions
void motor_controller_setup() {
    init_motor_controller();
}

void motor_controller_loop() {
    update_motor_outputs();
    send_esc_status();
    safety_check();
}
