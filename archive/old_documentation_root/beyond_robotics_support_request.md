# Beyond Robotics Dev Board - UART2 Serial Communication Support Request

## Subject: UART2 Serial Communication Issue with STM32L431 Micro Node via ST-LINK V3

Dear Beyond Robotics Support Team,

I am experiencing difficulties with UART2 serial communication on the Beyond Robotics Node Development Board with mounted STM32L431 Micro Node. After consulting your documentation, I understand that UART2 should be the console port for ST-LINK communication, but I cannot receive any serial output via COM8.

## Hardware Setup

- **Board**: Beyond Robotics Node Development Board with STM32L431 Micro Node
- **Programmer**: ST-LINK V3 MINI (blue dongle)
- **Connection**: ST-LINK V3 connected to STLINK header (pins 13/14 for UART2_TX/RX)
- **Switch Position**: SW1 set to position "1" (STLINK enabled, USB disabled)
- **Operating System**: Windows 11
- **Development Environment**: PlatformIO with Arduino framework

## Current Status

### ✅ Working:
- ST-LINK V3 is recognized by Windows (appears as "ST-Link Debug" and "USB Serial Device (COM8)")
- Chip detection successful (STM32L431 confirmed via documentation)
- Firmware upload successful using ST-LINK with nucleo_l432kc board configuration
- LED blinking confirms firmware is running
- Board reset functionality working
- Hardware connections verified with multimeter

### ❌ Not Working:
- No serial output received on COM8 at 115200 baud
- Virtual COM Port appears to be inactive
- Both Serial.begin(115200) and Serial2.begin(115200) produce no output
- UART2 (pins 13/14 on STLINK header) not responding

## Technical Details

### PlatformIO Configuration (Current Working):
```ini
[env:beyond_robotics_dev_board]
platform = ststm32
board = nucleo_l432kc  ; STM32L431 compatible board
framework = arduino
upload_protocol = stlink
debug_tool = stlink
monitor_speed = 115200
monitor_port = COM8
build_flags =
    -D ARDUINO_ARCH_STM32
    -D STM32L4xx
    -D BOARD_NAME="Beyond_Robotics_Dev_Board"
```

### Test Code (Both Serial and Serial2 Attempted):
```cpp
void setup() {
    pinMode(LED_BUILTIN, OUTPUT);

    // Try both Serial (UART1) and Serial2 (UART2)
    Serial.begin(115200);   // Standard Arduino serial
    Serial2.begin(115200);  // UART2 for ST-LINK (per documentation)
    delay(2000);

    Serial.println("Test message via Serial (UART1)");
    Serial2.println("Test message via Serial2 (UART2)");
}

void loop() {
    digitalWrite(LED_BUILTIN, HIGH);
    Serial.println("LED ON");
    Serial2.println("LED ON via UART2");
    delay(500);

    digitalWrite(LED_BUILTIN, LOW);
    Serial.println("LED OFF");
    Serial2.println("LED OFF via UART2");
    delay(500);
}
```

### Upload Configuration:
Upload works successfully with standard STM32L4 configuration (no custom OpenOCD needed).

## Questions

1. **UART2 Configuration**: Your documentation states that UART2 (pins 13/14 on STLINK header) is the console port. However, neither `Serial.begin(115200)` nor `Serial2.begin(115200)` produce output on COM8. Is there a specific configuration required to enable UART2 output via ST-LINK V3?

2. **Virtual COM Port**: Does the ST-LINK V3 connection automatically provide Virtual COM Port functionality for UART2, or does it require additional configuration/drivers?

3. **Board Configuration**: I'm currently using `board = nucleo_l432kc` for the STM32L431. Is this the correct PlatformIO board configuration for your Micro Node, or should I use a different board definition?

4. **Alternative Serial Debugging**: If ST-LINK serial doesn't work, should I use the JST-GH connectors (SERIAL1/SERIAL3) with an external USB-TTL adapter for debugging?

5. **SW1 Switch**: I have SW1 in position "1" (STLINK enabled). Is this correct for both programming AND serial debugging, or should it be changed after upload?

6. **Arduino Framework Compatibility**: Are there any known issues with the Arduino framework and UART2 on the STM32L431 that might prevent serial output?

## Intended Use Case

I am developing DroneCAN communication between the Beyond Robotics Dev Board and an Orange Cube autopilot. Serial debugging would be extremely helpful for monitoring CAN message traffic and troubleshooting the implementation.

## Request

Could you please provide:
- Correct PlatformIO configuration for serial communication
- Pin mapping for UART connections on your dev board
- Any specific setup requirements for ST-LINK V3 serial debugging
- Example code that demonstrates working serial output

I would greatly appreciate your guidance on this matter. The board appears to be functioning correctly otherwise, and I'm eager to proceed with the DroneCAN implementation once serial debugging is working.

Thank you for your time and support.

Best regards,

[Your Name]
[Your Email]
[Date]

---

## Additional Information

### System Information:
- Windows 11 Professional
- PlatformIO Core 6.1.x
- ST-LINK V3 firmware up to date
- All drivers installed via ST-LINK utility

### Troubleshooting Already Attempted:
- Verified COM port availability (COM8 accessible)
- Tested different baud rates (9600, 57600, 115200)
- Tried multiple board configurations (nucleo_f103rb, genericSTM32F103C8, nucleo_l432kc)
- Confirmed hardware reset functionality (LED blinking after reset)
- Verified LED blinking indicates firmware execution
- Tested both Serial.begin() and Serial2.begin() for UART1/UART2
- Confirmed ST-LINK V3 driver installation and recognition
- Verified hardware connections with multimeter
- Tested with minimal serial output code on STM32L431 configuration

### Hardware Verification:
- Multimeter confirmed proper connections
- ST-LINK V3 LED indicators show normal operation
- Board power supply stable
- No physical damage visible
