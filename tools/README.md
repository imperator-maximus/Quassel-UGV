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
- Orange Pi Zero 2W with USB-CAN adapter for the sensor hub
- Main Raspberry Pi 3 with USB-CAN adapter (`gs_usb`)
- Former UGV test Raspberry Pi with USB-CAN adapter (offline)
- ODrive/ODESC controllers with integrated CAN interfaces
- CAN bus connection between Sensor Hub and Controller
- Proper CAN termination (120Ω resistors)
- Classical CAN 2.0 on every node; CAN FD is not used

## 🔧 CAN Architecture Overview

### Sensor Hub (Orange Pi Zero 2W)
- **Holybro UM982 RTK-GPS**: Dual-antenna for position and heading
- **WitMotion USB-IMU**: IMU with native orientation output
- **USB-CAN adapter (currently CANable2)**: SocketCAN `can0`, Classical CAN 2.0 at 250 kbit/s
- **Sends**: GPS position, heading, RTK status, IMU orientation

### Controller (Pi 3)
- **Motor Controller**: Receives CAN messages from sensor hub
- **Web Interface**: Real-time Bing Maps display
- **USB-CAN adapter (`gs_usb`)**: SocketCAN `can0`, Classical CAN 2.0 at 250 kbit/s
- **Receives**: Sensor data from hub

### Former UGV Test Stand (Offline)
- **USB-CAN adapter**: SocketCAN `can0`, Classical CAN 2.0 at 250 kbit/s
- **ODrive/ODESC units**: Integrated CAN interfaces using SimpleCAN
- **Requirement**: Every test-bus node must be configured for 250 kbit/s

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

# Main UGV: verify USB-CAN driver and interface
lsusb
ip -details link show can0
```

All host computers use USB-CAN adapters. The main UGV uses `gs_usb`; the
Orange Pi CANable2 currently uses `slcand`.

#### "No CAN messages received"
- Verify CAN wiring (CANH, CANL, GND)
- Check 120Ω termination resistors
- Confirm the unified CAN bitrate of 250 kbit/s
- Ensure both devices have same bitrate

#### "CAN interface down"
```bash
# Main UGV production bus
sudo ip link set can0 up type can bitrate 250000 restart-ms 100

# UGV test stand (USB-CAN)
sudo ip link set can0 up type can bitrate 250000
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
- ✅ **Real-time communication** - Continuous GPS/IMU CAN telemetry updates
- ✅ **Scalability** - Easy to add new sensors or controllers
- ✅ **Reliability** - Redundant communication paths

All components maintain compatibility with the Quassel UGV RTK-GPS + IMU system.
