
#include <Arduino.h>
#include <dronecan.h>
#include <IWatchdog.h>
#include <app.h>
#include <vector>
#include <Servo.h>

// Motor Controller Configuration
#define NUM_MOTORS 4
#define PWM_MIN 1000      // 1ms pulse width (minimum)
#define PWM_MAX 2000      // 2ms pulse width (maximum)
#define PWM_NEUTRAL 1500  // 1.5ms pulse width (neutral)

std::vector<DroneCAN::parameter> custom_parameters = {
    { "NODEID", UAVCAN_PROTOCOL_PARAM_VALUE_INTEGER_VALUE, 25,  0, 127 },  // Changed from 127 to 25 for Orange Cube integration
    { "PARM_1", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_2", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_3", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_4", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_5", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_6", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_7", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
};

DroneCAN dronecan;

uint32_t looptime = 0;

// Test ESC Command Sending
uint32_t last_test_esc_time = 0;
const uint32_t TEST_ESC_INTERVAL = 3000; // Send test ESC every 3 seconds
uint16_t test_pwm_value = PWM_NEUTRAL;
bool test_direction_up = true;

// Motor Controller Variables
const uint8_t MOTOR_PINS[NUM_MOTORS] = {PA8, PA9, PA10, PA11}; // Timer-capable pins
Servo motors[NUM_MOTORS];
uint16_t motor_pwm_values[NUM_MOTORS] = {PWM_NEUTRAL, PWM_NEUTRAL, PWM_NEUTRAL, PWM_NEUTRAL};
bool motors_armed = false;
uint32_t last_esc_command_time = 0;
const uint32_t ESC_TIMEOUT_MS = 1000; // 1 second timeout

/*
This function is called when we receive a CAN message, and it's accepted by the shouldAcceptTransfer function.
We need to do boiler plate code in here to handle parameter updates and so on, but you can also write code to interact with sent messages here.
*/
static void onTransferReceived(CanardInstance *ins, CanardRxTransfer *transfer)
{

    // switch on data type ID to pass to the right handler function
    // if (transfer->transfer_type == CanardTransferTypeRequest)
    // check if we want to handle a specific service request
    switch (transfer->data_type_id)
    {

    case UAVCAN_EQUIPMENT_AHRS_MAGNETICFIELDSTRENGTH_ID:
    {
        uavcan_equipment_ahrs_MagneticFieldStrength pkt{};
        uavcan_equipment_ahrs_MagneticFieldStrength_decode(transfer, &pkt);
        // Serial.print(pkt.magnetic_field_ga[0], 4);
        // Serial.print(" ");
        // Serial.print(pkt.magnetic_field_ga[1], 4);
        // Serial.print(" ");
        // Serial.print(pkt.magnetic_field_ga[2], 4);
        // Serial.print(" ");
        // Serial.println();
        break;
    }

    case UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_ID:
    {
        // Handle ESC commands from Orange Cube
        uavcan_equipment_esc_RawCommand pkt{};
        uavcan_equipment_esc_RawCommand_decode(transfer, &pkt);

        Serial.print("🚀 ESC Command: [");
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

    DroneCANonTransferReceived(dronecan, ins, transfer);
}

/*
For this function, we need to make sure any messages we want to receive follow the following format with
UAVCAN_EQUIPMENT_AHRS_MAGNETICFIELDSTRENGTH_ID as an example
 */
static bool shouldAcceptTransfer(const CanardInstance *ins,
                                 uint64_t *out_data_type_signature,
                                 uint16_t data_type_id,
                                 CanardTransferType transfer_type,
                                 uint8_t source_node_id)

{
    if (transfer_type == CanardTransferTypeBroadcast)
    {
        // Check if we want to handle a specific broadcast packet
        switch (data_type_id)
        {
        case UAVCAN_EQUIPMENT_AHRS_MAGNETICFIELDSTRENGTH_ID:
        {
            *out_data_type_signature = UAVCAN_EQUIPMENT_AHRS_MAGNETICFIELDSTRENGTH_SIGNATURE;
            return true;
        }

        case UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_ID:
        {
            *out_data_type_signature = UAVCAN_EQUIPMENT_ESC_RAWCOMMAND_SIGNATURE;
            return true;
        }
        }
    }

    return false || DroneCANshoudlAcceptTransfer(ins, out_data_type_signature, data_type_id, transfer_type, source_node_id);
}

void send_test_esc_command() {
    // Send test ESC command to test motor controller
    uavcan_equipment_esc_RawCommand pkt{};

    // Create test PWM values for all motors
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

    Serial.print("📤 Test ESC: PWM=");
    Serial.print(test_pwm_value);
    Serial.print(" Raw=");
    Serial.println(pkt.cmd.data[0]);

    // Also directly apply the command to test motor controller
    for (int i = 0; i < NUM_MOTORS; i++) {
        motor_pwm_values[i] = test_pwm_value;
    }
    last_esc_command_time = millis();

    if (!motors_armed) {
        motors_armed = true;
        Serial.println("🔓 Motors ARMED by test ESC command");
    }

    // Update test PWM value for next time (cycle between 1300-1700)
    if (test_direction_up) {
        test_pwm_value += 100;
        if (test_pwm_value >= 1700) {
            test_direction_up = false;
        }
    } else {
        test_pwm_value -= 100;
        if (test_pwm_value <= 1300) {
            test_direction_up = true;
        }
    }
}

void setup()
{
    // to use debugging tools, remove app_setup and set FLASH start from 0x800A000 to 0x8000000 in ldscript.ld
    // this will over-write the bootloader. To use the bootloader again, reflash it and change above back.
    app_setup(); // needed for coming from a bootloader, needs to be first in setup
    Serial.begin(115200);
    dronecan.version_major = 1;
    dronecan.version_minor = 0;
    dronecan.init(
        onTransferReceived,
        shouldAcceptTransfer,
        custom_parameters,
        "Beyond Robotix Node"
    );
    IWatchdog.begin(2000000); // if the loop takes longer than 2 seconds, reset the system

    // an example of getting and setting parameters within the code
    dronecan.setParameter("PARM_1", 69);
    Serial.print("PARM_1 value: ");
    Serial.println(dronecan.getParameter("PARM_1"));

    // Print node configuration for Orange Cube integration
    Serial.println("=== Beyond Robotics DroneCAN Node ===");
    Serial.print("Node ID: ");
    Serial.println(dronecan.getParameter("NODEID"));
    Serial.println("CAN Bitrate: 1000000 bps");
    Serial.println("Ready for Orange Cube integration!");
    Serial.println("Sending battery messages every 100ms...");

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
    Serial.println("Motors initialized - waiting for ESC commands...");

    while (true)
    {
        const uint32_t now = millis();

        // Send test ESC commands periodically
        if (now - last_test_esc_time >= TEST_ESC_INTERVAL) {
            last_test_esc_time = now;
            send_test_esc_command();
        }

        // send our battery message at 10Hz
        if (now - looptime > 100)
        {
            looptime = millis();

            // collect MCU core temperature data
            int32_t vref = __LL_ADC_CALC_VREFANALOG_VOLTAGE(analogRead(AVREF), LL_ADC_RESOLUTION_12B);
            int32_t cpu_temp = __LL_ADC_CALC_TEMPERATURE(vref, analogRead(ATEMP), LL_ADC_RESOLUTION_12B);

            // construct dronecan packet
            uavcan_equipment_power_BatteryInfo pkt{};
            pkt.voltage = analogRead(PA1);
            pkt.current = analogRead(PA0);
            pkt.temperature = cpu_temp;

            // boilerplate to send a message
            uint8_t buffer[UAVCAN_EQUIPMENT_POWER_BATTERYINFO_MAX_SIZE];
            uint32_t len = uavcan_equipment_power_BatteryInfo_encode(&pkt, buffer);
            static uint8_t transfer_id;
            canardBroadcast(&dronecan.canard,
                            UAVCAN_EQUIPMENT_POWER_BATTERYINFO_SIGNATURE,
                            UAVCAN_EQUIPMENT_POWER_BATTERYINFO_ID,
                            &transfer_id,
                            CANARD_TRANSFER_PRIORITY_LOW,
                            buffer,
                            len);

            // Debug output every 10 seconds (every 100th message)
            static uint32_t debug_counter = 0;
            debug_counter++;
            if (debug_counter % 100 == 0) {
                Serial.print("Battery: V=");
                Serial.print(pkt.voltage);
                Serial.print(", I=");
                Serial.print(pkt.current);
                Serial.print(", T=");
                Serial.print(pkt.temperature);
                Serial.print("°C, Transfer ID=");
                Serial.println(transfer_id);
            }
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
}

void loop()
{
    // Doesn't work coming from bootloader ? use while loop in setup
}
