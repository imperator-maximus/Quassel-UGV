# 🛠️ Quassel UGV - CAN Testing Tools

Essential tools for testing and configuring the CAN bus communication system.

## 📁 Directory Structure

```
tools/
├── dronecan/                      # CAN testing tools
│   ├── send_dronecan_actuator_commands.py  # Send test commands
│   └── README.md                  # CAN tools guide
└── README.md                      # This file
```

## 🚀 Quick Start

### CAN Testing
```bash
cd tools/dronecan
python send_dronecan_actuator_commands.py --port COM5
```

### Monitor CAN Traffic
```bash
# On Raspberry Pi
candump can0
```

### Send Test Messages
```bash
# On Raspberry Pi
cansend can0 123#DEADBEEF
```

## 📋 Prerequisites

### Python Dependencies
```bash
pip install dronecan python-can
```

### Hardware Requirements
- Raspberry Pi with PiCAN FD
- CAN bus connection between Sensor Hub and Controller
- Proper CAN termination (120Ω resistors)

## 🔧 Tool Overview

### DroneCAN Tools (`dronecan/`)

#### `send_dronecan_actuator_commands.py`
**Purpose**: Send test actuator commands via CAN bus
**Features**:
- Oscillating motor commands (0-100%)
- Configurable CAN port and bitrate
- Real-time command feedback
- Support for multiple CAN interfaces

**Usage**:
```bash
python send_dronecan_actuator_commands.py --port COM5 --bitrate 1000000
```

**Options**:
- `--port, -p`: CAN interface (default: COM5)
- `--bitrate, -b`: CAN bitrate (default: 1000000)

## 🔗 Integration Workflow

### 1. Test CAN Interface
```bash
# On Raspberry Pi
ip link show can0
candump can0
```

### 2. Send Test Commands
```bash
cd tools/dronecan
python send_dronecan_actuator_commands.py --port COM5
```

### 3. Monitor Responses
```bash
# On Raspberry Pi
candump can0
```

### 4. Verify Communication
- Check CAN messages are received
- Verify message format and content
- Confirm bidirectional communication

## 🐛 Troubleshooting

### Common Issues

#### "No module named 'dronecan'"
```bash
pip install dronecan
```

#### "No module named 'python-can'"
```bash
pip install python-can
```

#### "Could not open port COM5"
- Check USB-CAN adapter connection
- Verify correct COM port in Device Manager
- Try different USB cable/port

#### "No CAN messages received"
- Verify CAN wiring (CANH, CANL, GND)
- Check 120Ω termination resistors
- Confirm CAN bitrate (500 kbit/s for sensor hub, 1 Mbps for motor control)
- Ensure both devices have same bitrate

#### "CAN interface not found"
```bash
# On Raspberry Pi
ip link show can0

# If not found, check boot config
cat /boot/firmware/config.txt | grep mcp2515
```

## 📊 Expected Output

### Successful CAN Communication
```
Sensor Hub:
📡 GPS Position: 53.8234°N, 10.4567°E
🧭 Heading: 45.2° (Dual-Antenna)
📊 RTK Status: FIXED
📐 Roll: +2.3°, Pitch: -1.8°
🚀 CAN Message sent (ID: 0x123)

Controller:
✅ Received sensor data from hub
📍 Position: 53.8234°N, 10.4567°E
🧭 Heading: 45.2°
📊 RTK: FIXED
```

### System Status Indicators
- 📡 GPS data received
- 🧭 Heading calculated
- 📊 RTK status displayed
- 📐 IMU orientation available
- 🚀 CAN messages transmitted

## 📞 Support

For issues with these tools:

1. **Check hardware connections** - CAN bus, power, USB
2. **Verify software dependencies** - Python packages installed
3. **Review CAN traffic** - Use candump to monitor messages
4. **Test individual components** - Use tools separately to isolate issues

## 🔄 Development

These tools are designed for:
- ✅ **System validation** - Verify complete communication chain
- ✅ **Development testing** - Rapid iteration and debugging
- ✅ **Configuration management** - Easy parameter adjustment
- ✅ **Troubleshooting** - Isolate and identify issues

All tools maintain compatibility with the Quassel UGV RTK-GPS + IMU system.
