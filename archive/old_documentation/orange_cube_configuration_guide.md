# Orange Cube DroneCAN Configuration Guide

This guide provides detailed instructions for configuring an Orange Cube autopilot to work with DroneCAN devices, specifically for communication with an ESP32 running DroneCAN.

## Prerequisites

1. Orange Cube autopilot with ArduPilot/PX4 firmware installed
2. Mission Planner or QGroundControl installed on your computer
3. USB connection to the Orange Cube

## Configuration Steps

### 1. Connect to the Orange Cube

1. Connect the Orange Cube to your computer via USB
2. Open Mission Planner or QGroundControl
3. Select the correct COM port and baudrate (typically 115200)
4. Click "Connect"

### 2. Enable DroneCAN on the Orange Cube

#### For ArduPilot Firmware:

1. Go to **Config/Tuning** > **Full Parameter List**
2. Set the following parameters:

   | Parameter | Value | Description |
   |-----------|-------|-------------|
   | `CAN_P1_DRIVER` | `1` | Enable first CAN driver |
   | `CAN_P1_BITRATE` | `1000000` | Set baudrate to 1Mbps |
   | `CAN_D1_PROTOCOL` | `1` | Set protocol to DroneCAN |
   | `CAN_D1_UC_NODE` | `1` | Enable DroneCAN node |
   | `CAN_D1_UC_ESC_BM` | `15` | Enable ESC outputs 1-4 (bitmask) |

3. Click "Write Params" to save the changes
4. Restart the Orange Cube

#### For PX4 Firmware:

1. Go to **Vehicle Setup** > **Parameters**
2. Set the following parameters:

   | Parameter | Value | Description |
   |-----------|-------|-------------|
   | `UAVCAN_ENABLE` | `3` | Enable DroneCAN for sensors and ESCs |
   | `UAVCAN_NODE_ID` | `1` | Set Orange Cube node ID |
   | `UAVCAN_SUB_BAT` | `1` | Enable battery monitoring (if needed) |
   | `UAVCAN_SUB_GPS` | `1` | Enable GPS (if needed) |
   | `UAVCAN_SUB_MAG` | `1` | Enable magnetometer (if needed) |
   | `UAVCAN_PUB_ARM` | `1` | Publish arming status |

3. Click "Save" to store the parameters
4. Restart the Orange Cube

### 3. Configure Servo/Motor Outputs

#### For ArduPilot Firmware:

1. Go to **Config/Tuning** > **Full Parameter List**
2. Configure servo function assignments:

   | Parameter | Value | Description |
   |-----------|-------|-------------|
   | `SERVO1_FUNCTION` | `33` | Motor 1 |
   | `SERVO2_FUNCTION` | `34` | Motor 2 |
   | `SERVO3_FUNCTION` | `35` | Motor 3 |
   | `SERVO4_FUNCTION` | `36` | Motor 4 |

3. Set servo output ranges:

   | Parameter | Value | Description |
   |-----------|-------|-------------|
   | `SERVO1_MIN` | `1000` | Minimum PWM value |
   | `SERVO1_MAX` | `2000` | Maximum PWM value |
   | `SERVO2_MIN` | `1000` | Minimum PWM value |
   | `SERVO2_MAX` | `2000` | Maximum PWM value |
   | `SERVO3_MIN` | `1000` | Minimum PWM value |
   | `SERVO3_MAX` | `2000` | Maximum PWM value |
   | `SERVO4_MIN` | `1000` | Minimum PWM value |
   | `SERVO4_MAX` | `2000` | Maximum PWM value |

4. Click "Write Params" to save the changes

#### For PX4 Firmware:

1. Go to **Vehicle Setup** > **Actuators**
2. Configure the motor/servo outputs according to your vehicle type
3. Ensure the outputs are set to the correct minimum and maximum values
4. Save the configuration

### 4. Verify DroneCAN Device Detection

#### For ArduPilot Firmware:

1. Connect the ESP32 DroneCAN device to the Orange Cube
2. Power on both devices
3. In Mission Planner, go to **Config/Tuning** > **DroneCAN/UAVCAN**
4. You should see your ESP32 device listed with its node ID
5. If not visible, check connections and configuration

#### For PX4 Firmware:

1. Connect the ESP32 DroneCAN device to the Orange Cube
2. Power on both devices
3. In QGroundControl, go to **Analyze Tools** > **MAVLink Console**
4. Type `uavcan status` and press Enter
5. You should see your ESP32 device listed with its node ID
6. If not visible, check connections and configuration

### 5. Test Servo/Motor Control

1. Ensure all motors/servos are properly connected
2. In Mission Planner or QGroundControl, use the motor test function to verify control
3. For ArduPilot: Go to **Setup** > **Optional Hardware** > **Motor Test**
4. For PX4: Go to **Vehicle Setup** > **Actuators** > **Actuator Testing**
5. Test each motor/servo individually to verify proper operation

## Troubleshooting

### DroneCAN Device Not Detected

1. Verify CAN bus connections (CANH/CANL)
2. Check termination resistors (120 Ohm at both ends)
3. Ensure both devices are using the same baudrate (1Mbps)
4. Verify the ESP32 is sending valid DroneCAN messages
5. Check power supply to both devices

### Motors/Servos Not Responding

1. Verify servo function assignments
2. Check ESC calibration
3. Ensure the Orange Cube is recognizing DroneCAN actuator commands
4. Verify the ESP32 is sending commands to the correct actuator indices

### Parameter Changes Not Taking Effect

1. Ensure you've clicked "Write Params" or "Save" after changing parameters
2. Restart the Orange Cube after parameter changes
3. Verify parameters were actually saved by checking them again after restart

## Advanced Configuration

### Dynamic Node Allocation

If you want to use dynamic node allocation:

1. Set `CAN_D1_UC_DNA` to `1` (ArduPilot) or ensure `UAVCAN_ENABLE` is set to `2` or `3` (PX4)
2. Configure your ESP32 to request a node ID dynamically
3. Restart both devices

### Multiple DroneCAN Devices

If using multiple DroneCAN devices:

1. Ensure each device has a unique node ID
2. Verify the CAN bus can handle the message traffic
3. Consider using a CAN hub for complex setups

## Additional Resources

- [ArduPilot DroneCAN Documentation](https://ardupilot.org/copter/docs/common-uavcan-setup-advanced.html)
- [PX4 DroneCAN Documentation](https://docs.px4.io/main/en/dronecan/)
- [Orange Cube Documentation](https://docs.cubepilot.org/user-guides/autopilot/the-cube-user-manual)
- [DroneCAN Specification](https://dronecan.github.io/Specification/)
