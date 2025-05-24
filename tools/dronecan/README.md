# 🔗 DroneCAN Tools

Tools for testing DroneCAN communication and sending actuator commands.

## 📋 Tools Overview

### `send_dronecan_actuator_commands.py`
**Send test actuator commands via DroneCAN**

**Features:**
- Oscillating motor commands (0-100%)
- Configurable CAN interface and bitrate
- Real-time command feedback
- Automatic command cycling

**Usage:**
```bash
python send_dronecan_actuator_commands.py [options]
```

**Options:**
- `--port, -p`: CAN interface (default: COM5)
- `--bitrate, -b`: CAN bitrate (default: 1000000)

**Examples:**
```bash
# Default settings (COM5, 1Mbps)
python send_dronecan_actuator_commands.py

# Custom port and bitrate
python send_dronecan_actuator_commands.py --port COM3 --bitrate 500000

# Short form
python send_dronecan_actuator_commands.py -p COM3 -b 1000000
```

## 🔧 Prerequisites

### Hardware
- CAN interface connected to PC (USB-CAN adapter)
- CAN bus connection to Beyond Robotics board
- Proper CAN termination (120Ω resistors)

### Software
```bash
pip install dronecan
```

## 🚀 Quick Start

### 1. Connect CAN Interface
- Connect USB-CAN adapter to PC
- Note the COM port (e.g., COM5)
- Connect CAN bus to Beyond Robotics board

### 2. Run Test Commands
```bash
python send_dronecan_actuator_commands.py --port COM5
```

### 3. Monitor Output
```
Initializing DroneCAN node on COM5 at 1000000 bps...
Sending actuator commands. Press Ctrl+C to stop.
Sent actuator command: value=0.01
Sent actuator command: value=0.02
Sent actuator command: value=0.03
...
```

## 📊 Expected Output

### Successful Communication
```bash
$ python send_dronecan_actuator_commands.py
Initializing DroneCAN node on COM5 at 1000000 bps...
Sending actuator commands. Press Ctrl+C to stop.
Sent actuator command: value=0.00
Sent actuator command: value=0.01
Sent actuator command: value=0.02
...
Sent actuator command: value=1.00
Sent actuator command: value=0.99
Sent actuator command: value=0.98
...
```

### Beyond Robotics Board Response
```
🚀 ESC Command: [1000, 1000, 1000, 1000]
🔓 Motors ARMED by ESC command
🚀 ESC Command: [1100, 1100, 1100, 1100]
🚀 ESC Command: [1200, 1200, 1200, 1200]
...
⚙️ Motors: ARMED PWM:[1500,1500,1500,1500]
```

## 🔍 Command Details

### Message Type
- **DroneCAN Message**: `uavcan.equipment.actuator.Command`
- **Command Type**: 0 (position command)
- **Actuator ID**: 0 (first actuator)
- **Value Range**: 0.0 to 1.0 (0% to 100%)

### Command Cycling
The tool automatically cycles through values:
1. **Ramp Up**: 0.0 → 1.0 (increment +0.01)
2. **Ramp Down**: 1.0 → 0.0 (increment -0.01)
3. **Repeat**: Continuous cycling

### Update Rate
- **Frequency**: 10 Hz (every 100ms)
- **Smooth Transition**: Small increments for smooth motion

## 🔧 Integration Testing

### Test Workflow
1. **Start Beyond Robotics board**
2. **Run DroneCAN command tool**
3. **Monitor both outputs**
4. **Verify PWM response**

### Verification Points
- ✅ DroneCAN messages transmitted
- ✅ Beyond Robotics board receives commands
- ✅ Motor controller processes commands
- ✅ PWM outputs change accordingly
- ✅ Safety timeout works when stopped

## 🐛 Troubleshooting

### "Could not initialize DroneCAN node"
**Causes:**
- Incorrect COM port
- CAN interface not connected
- Wrong bitrate setting

**Solutions:**
```bash
# Check available COM ports
python -c "import serial.tools.list_ports; print([p.device for p in serial.tools.list_ports.comports()])"

# Try different port
python send_dronecan_actuator_commands.py --port COM3

# Try different bitrate
python send_dronecan_actuator_commands.py --bitrate 500000
```

### "No response from Beyond Robotics board"
**Causes:**
- CAN bus not connected
- Wrong CAN bitrate
- Missing termination resistors
- Beyond Robotics board not powered

**Solutions:**
- Verify CAN wiring (CANH, CANL, GND)
- Check 120Ω termination resistors
- Ensure matching bitrates (1Mbps)
- Verify Beyond Robotics board power and operation

### "Commands sent but no motor movement"
**Causes:**
- Motors not armed
- Safety timeout active
- PWM range issues
- Motor controller configuration

**Solutions:**
- Check Beyond Robotics serial output for arming status
- Verify ESC command timeout (should be < 1 second)
- Check PWM signal range and motor calibration

## 📈 Advanced Usage

### Custom Command Values
Modify the script to send specific values:

```python
# Example: Send fixed 50% command
actuator_cmd.command_value = 0.5
node.broadcast(actuator_cmd)
```

### Multiple Actuators
```python
# Send different values to different actuators
for actuator_id in range(4):
    actuator_cmd.actuator_id = actuator_id
    actuator_cmd.command_value = values[actuator_id]
    node.broadcast(actuator_cmd)
```

### Custom Update Rate
```python
# Change update frequency
time.sleep(0.05)  # 20 Hz instead of 10 Hz
```

## 🔄 Development Integration

### Testing Scenarios
1. **Basic Communication**: Verify DroneCAN message reception
2. **Motor Response**: Test PWM output generation
3. **Safety Systems**: Verify timeout behavior
4. **Performance**: Test update rates and latency

### Integration with Orange Cube
- Orange Cube sends real ESC commands
- This tool sends test commands
- Both should work with Beyond Robotics board
- Use for development when Orange Cube not available

## 📞 Support

For troubleshooting:
1. Check CAN bus hardware connections
2. Verify software dependencies installed
3. Monitor Beyond Robotics board serial output
4. Test with different CAN interfaces/ports

This tool is designed to work seamlessly with the refactored Beyond Robotics DroneCAN Motor Controller.
