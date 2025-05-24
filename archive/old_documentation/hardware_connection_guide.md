# Hardware Connection Guide for ESP32 DroneCAN with Orange Cube

This guide provides detailed instructions for connecting an ESP32 to an Orange Cube autopilot using DroneCAN.

## Components Required

1. ESP32 development board (Freenove)
2. CAN transceiver module (e.g., SN65HVD230, TJA1050, MCP2551)
3. Orange Cube autopilot
4. Jumper wires
5. 120 Ohm resistors (2x) for CAN bus termination

## Wiring Diagram

```
+---------------+          +------------------+          +---------------+
|               |          |                  |          |               |
|    ESP32      |          | CAN Transceiver  |          | Orange Cube   |
|               |          |                  |          |               |
+---------------+          +------------------+          +---------------+
     |   |                      |  |  |  |                    |   |
     |   |                      |  |  |  |                    |   |
     v   v                      v  v  v  v                    v   v
    [5] [4]                    TX RX H  L                   CAN_H CAN_L
     |   |                      |  |  |  |                    |   |
     |   |                      |  |  |  |                    |   |
     |   +--------------------->|  |  |  |                    |   |
     |                          |  |  |  |                    |   |
     +------------------------->|  |  |  |                    |   |
                                   |  |  |                    |   |
                                   |  |  |                    |   |
                                   |  +--+--------------------+   |
                                   |     |                        |
                                   +-----+------------------------+
```

## Connection Steps

### 1. ESP32 to CAN Transceiver

| ESP32 Pin | CAN Transceiver Pin |
|-----------|---------------------|
| GPIO5     | TX                  |
| GPIO4     | RX                  |
| 3.3V      | VCC                 |
| GND       | GND                 |

**IMPORTANT**: The ESP32 CAN controller uses GPIO4 and GPIO5 pins. These pins cannot be changed as they are hardwired to the internal CAN controller.

### 2. CAN Transceiver to Orange Cube

| CAN Transceiver Pin | Orange Cube Pin |
|---------------------|-----------------|
| CANH                | CAN_H           |
| CANL                | CAN_L           |

### 3. CAN Bus Termination

For proper CAN bus operation, you need termination resistors at both ends of the bus:

1. Place a 120 Ohm resistor between CANH and CANL at the CAN transceiver if it's at one end of the bus
2. The Orange Cube typically has built-in termination resistors that can be enabled via solder jumpers or settings

## Common Issues and Troubleshooting

### No Communication

1. **Check Wiring**: Verify all connections, especially TX/RX orientation
2. **Check Termination**: Ensure proper 120 Ohm termination at both ends
3. **Check Power**: Ensure the CAN transceiver is properly powered
4. **Check Baudrate**: Verify both devices are using the same baudrate (1Mbps for DroneCAN)

### Intermittent Communication

1. **Check Cable Quality**: Use twisted pair cables for CANH/CANL
2. **Check Ground**: Ensure proper grounding between devices
3. **Check Interference**: Keep CAN wires away from power lines and motors

## Orange Cube Configuration

To enable DroneCAN on the Orange Cube:

1. Connect to the Orange Cube using Mission Planner
2. Go to **Config/Tuning** > **Full Parameter List**
3. Set the following parameters:
   - `CAN_P1_DRIVER` to `1` (First driver enabled)
   - `CAN_P1_BITRATE` to `1000000` (1Mbps)
   - `CAN_D1_PROTOCOL` to `1` (DroneCAN protocol)
   - `CAN_D1_UC_NODE` to `1` (Enable DroneCAN node)
   - `CAN_D1_UC_ESC_BM` to `15` (Enable ESC outputs 1-4)

4. Restart the Orange Cube

## Testing the Connection

After connecting everything:

1. Power on both the ESP32 and Orange Cube
2. Monitor the serial output from the ESP32 for CAN messages
3. Check if the Orange Cube recognizes the ESP32 as a DroneCAN node
4. Test actuator commands by observing servo outputs on the Orange Cube

## Additional Resources

- [DroneCAN Specification](https://dronecan.github.io/Specification/)
- [Orange Cube Documentation](https://docs.cubepilot.org/user-guides/autopilot/the-cube-user-manual)
- [ESP32 CAN Documentation](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/twai.html)
