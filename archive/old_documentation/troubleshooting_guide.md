# DroneCAN Troubleshooting Guide

This guide provides detailed troubleshooting steps for ESP32 to Orange Cube DroneCAN communication issues.

## Diagnostic Tools

### 1. Serial Monitor

The ESP32 outputs detailed diagnostic information via the serial port. Use PlatformIO's serial monitor or the provided `platformio-monitor.bat` script to view this output.

```
platformio device monitor -b 115200 -p COM7
```

### 2. LED Indicators

The ESP32 uses the onboard LED (GPIO2) to indicate status:
- Regular blinking: Program is running
- Fast blinking: CAN message received
- Rapid blinking: Error condition

### 3. Mission Planner

Use Mission Planner to check the Orange Cube's DroneCAN configuration:
1. Connect to the Orange Cube
2. Go to **Config/Tuning** > **Full Parameter List**
3. Search for parameters starting with "CAN_"

## Common Issues and Solutions

### 1. No CAN Messages Received

**Symptoms:**
- ESP32 reports "No CAN messages received"
- No fast LED blinks indicating message reception

**Possible Causes and Solutions:**

a) **Incorrect Wiring**
   - Verify connections between ESP32 and CAN transceiver
   - Check if TX/RX connections are reversed
   - Ensure CANH/CANL are connected correctly to the Orange Cube

b) **Missing Termination Resistors**
   - Verify 120 Ohm resistors are installed at both ends of the CAN bus
   - Check if Orange Cube's internal termination is enabled

c) **Incorrect Baudrate**
   - Ensure both devices are using 1Mbps (standard for DroneCAN)
   - Check `CAN_P1_BITRATE` parameter on Orange Cube

d) **Power Issues**
   - Ensure CAN transceiver is properly powered (3.3V for most transceivers)
   - Check for stable power supply to both devices

### 2. CAN Initialization Fails

**Symptoms:**
- ESP32 reports "CAN initialization failed"
- Rapid LED blinking during startup

**Possible Causes and Solutions:**

a) **Hardware Issues**
   - Check if CAN transceiver is properly connected
   - Try a different CAN transceiver module
   - Verify ESP32 GPIO4 and GPIO5 are functioning correctly

b) **Software Configuration**
   - Verify CAN_TX_PIN and CAN_RX_PIN are correctly defined in can_config.h
   - Check if the ESP32CAN library is properly installed

### 3. Messages Sent But Not Recognized

**Symptoms:**
- ESP32 reports successful message transmission
- Orange Cube doesn't respond or recognize the messages

**Possible Causes and Solutions:**

a) **Incorrect DroneCAN Configuration**
   - Verify DroneCAN is enabled on the Orange Cube
   - Check if the correct DroneCAN message IDs are being used
   - Ensure the Orange Cube is configured to accept external actuator commands

b) **Node ID Conflicts**
   - Change the ESP32's DroneCAN node ID to avoid conflicts
   - Check if dynamic node allocation is enabled on the Orange Cube

c) **Protocol Mismatch**
   - Ensure the ESP32 is sending properly formatted DroneCAN messages
   - Verify message structure matches DroneCAN 1.0 specification

### 4. Intermittent Communication

**Symptoms:**
- Communication works sometimes but fails randomly
- Messages get corrupted or lost

**Possible Causes and Solutions:**

a) **Signal Integrity Issues**
   - Use twisted pair cables for CANH/CANL
   - Keep CAN wires away from power lines and motors
   - Reduce cable length if possible

b) **Grounding Problems**
   - Ensure proper ground connection between ESP32 and Orange Cube
   - Add additional ground connections if necessary

c) **EMI/RFI Interference**
   - Use shielded cables for CAN bus
   - Add ferrite beads to CAN lines
   - Move CAN wires away from sources of interference

## Step-by-Step Debugging Procedure

1. **Verify Basic Functionality**
   - Run the pin test program to verify ESP32 GPIO functionality
   - Check if the ESP32 can communicate via serial

2. **Test Basic CAN Communication**
   - Run the simple CAN test to verify CAN controller initialization
   - Check if CAN messages can be sent (even if not received)

3. **Analyze CAN Bus with Oscilloscope (if available)**
   - Check for proper signal levels on CANH/CANL
   - Verify timing and baudrate

4. **Isolate the Problem**
   - Test ESP32 with another CAN device if available
   - Try connecting only essential components

5. **Verify Orange Cube Configuration**
   - Check all DroneCAN-related parameters
   - Ensure the Orange Cube is in the correct operating mode

## Advanced Diagnostics

### Using a CAN Analyzer

If available, use a CAN analyzer to monitor the bus:
1. Connect the analyzer to the CAN bus
2. Monitor for messages from both the ESP32 and Orange Cube
3. Check for proper message formatting and timing

### Testing with Another DroneCAN Device

If possible, test with a known working DroneCAN device:
1. Connect the device to the Orange Cube
2. Verify the Orange Cube can communicate with it
3. Compare the message format with your ESP32 implementation

## Getting Help

If you've tried all the above steps and still have issues:
1. Document all your troubleshooting steps
2. Capture serial output from the ESP32
3. Note all parameter settings from the Orange Cube
4. Share this information when seeking help from the community
