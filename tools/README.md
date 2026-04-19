# 🛠️ Quassel UGV - CAN Communication Tools

Essential tools for testing and configuring the new CAN bus architecture.

## 📁 Directory Structure

```
tools/
└── README.md                      # This file
```

## 🚀 Quick Start

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

### View CAN Interface Status
```bash
# On Raspberry Pi
ip link show can0
```

## 📋 Prerequisites

### Python Dependencies
```bash
pip install python-can
```

### Hardware Requirements
- Raspberry Pi with PiCAN FD
- CAN bus connection between Sensor Hub and Controller
- Proper CAN termination (120Ω resistors)

## 🔧 CAN Architecture Overview

### Sensor Hub (Pi Zero 2W)
- **Holybro UM982 RTK-GPS**: Dual-antenna for position and heading
- **WitMotion USB-IMU**: IMU with native orientation output
- **PiCAN FD**: CAN interface (500 kbit/s)
- **Sends**: GPS position, heading, RTK status, IMU orientation

### Controller (Pi 3)
- **Motor Controller**: Receives CAN messages from sensor hub
- **Web Interface**: Real-time Bing Maps display
- **PiCAN FD**: CAN interface (1 Mbps for motor control)
- **Receives**: Sensor data from hub

## 🔗 Integration Workflow

### 1. Test CAN Interface
```bash
# On Raspberry Pi
ip link show can0
candump can0
```

### 2. Monitor Sensor Data
```bash
# On Raspberry Pi - watch CAN messages
candump can0 -c
```

### 3. Verify Communication
- Check CAN messages are received
- Verify message format and content
- Confirm bidirectional communication between hub and controller

## 🐛 Troubleshooting

### Common Issues

#### "No module named 'python-can'"
```bash
pip install python-can
```

#### "CAN interface not found"
```bash
# On Raspberry Pi
ip link show can0

# If not found, check boot config
cat /boot/firmware/config.txt | grep mcp2515
```

#### "No CAN messages received"
- Verify CAN wiring (CANH, CANL, GND)
- Check 120Ω termination resistors
- Confirm CAN bitrate (500 kbit/s for sensor hub, 1 Mbps for motor control)
- Ensure both devices have same bitrate

#### "CAN interface down"
```bash
# On Raspberry Pi - bring interface up
sudo ip link set can0 up type can bitrate 500000
```

## 📊 Expected Output

### Successful CAN Communication
```
Sensor Hub:
📡 GPS Position: 53.8234°N, 10.4567°E
🧭 Heading: 45.2° (Dual-Antenna)
📊 RTK Status: FIXED
📐 Roll: +2.3°, Pitch: -1.8°
🚀 CAN Message sent

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

For issues with CAN communication:

1. **Check hardware connections** - CAN bus, power, USB
2. **Verify software dependencies** - Python packages installed
3. **Review CAN traffic** - Use candump to monitor messages
4. **Test individual components** - Use tools separately to isolate issues

## 🔄 Development

The new CAN architecture is designed for:
- ✅ **Modular design** - Separate sensor hub and controller
- ✅ **Real-time communication** - 50 Hz sensor fusion updates
- ✅ **Scalability** - Easy to add new sensors or controllers
- ✅ **Reliability** - Redundant communication paths

All components maintain compatibility with the Quassel UGV RTK-GPS + IMU system.
