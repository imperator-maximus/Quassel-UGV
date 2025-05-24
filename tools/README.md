# 🛠️ Beyond Robotics DroneCAN Tools

Essential tools for testing and configuring the Beyond Robotics DroneCAN Motor Controller system.

## 📁 Directory Structure

```
tools/
├── orange_cube/                    # Orange Cube MAVLink tools
│   ├── monitor_orange_cube.py     # Complete monitoring & control
│   ├── set_can_parameters.py      # CAN configuration
│   └── README.md                  # Orange Cube tools guide
├── dronecan/                      # DroneCAN testing tools  
│   ├── send_dronecan_actuator_commands.py  # Send test commands
│   └── README.md                  # DroneCAN tools guide
└── README.md                      # This file
```

## 🚀 Quick Start

### Orange Cube Monitoring
```bash
cd tools/orange_cube
python monitor_orange_cube.py
```

### DroneCAN Testing
```bash
cd tools/dronecan  
python send_dronecan_actuator_commands.py --port COM5
```

### CAN Configuration
```bash
cd tools/orange_cube
python set_can_parameters.py
```

## 📋 Prerequisites

### Python Dependencies
```bash
pip install pymavlink dronecan
```

### Hardware Requirements
- Orange Cube connected via USB (typically COM4)
- CAN bus connection between Orange Cube and Beyond Robotics board
- Proper CAN termination (120Ω resistors)

## 🔧 Tool Overview

### Orange Cube Tools (`orange_cube/`)

#### `monitor_orange_cube.py`
**Purpose**: Complete MAVLink monitoring and control interface
**Features**:
- Real-time parameter monitoring
- Servo output testing (RC override)
- Vehicle arming/disarming
- DroneCAN parameter display
- System reboot capability

**Usage**:
```bash
python monitor_orange_cube.py
```

#### `set_can_parameters.py`
**Purpose**: Configure Orange Cube CAN settings for DroneCAN
**Features**:
- Set CAN bitrate (1Mbps)
- Configure DroneCAN protocol
- Set node IDs and ESC bitmasks
- Enable BLHeli servo outputs

**Usage**:
```bash
python set_can_parameters.py
```

### DroneCAN Tools (`dronecan/`)

#### `send_dronecan_actuator_commands.py`
**Purpose**: Send test actuator commands via DroneCAN
**Features**:
- Oscillating motor commands (0-100%)
- Configurable CAN port and bitrate
- Real-time command feedback

**Usage**:
```bash
python send_dronecan_actuator_commands.py --port COM5 --bitrate 1000000
```

## 🔗 Integration Workflow

### 1. Configure Orange Cube
```bash
cd tools/orange_cube
python set_can_parameters.py
```

### 2. Monitor System
```bash
python monitor_orange_cube.py
# Select option 2: Monitor messages
```

### 3. Test DroneCAN Communication
```bash
cd ../dronecan
python send_dronecan_actuator_commands.py
```

### 4. Verify Motor Controller
- Check Beyond Robotics board serial output
- Verify PWM signals on motor pins
- Confirm safety timeout behavior

## 🐛 Troubleshooting

### Common Issues

#### "No module named 'pymavlink'"
```bash
pip install pymavlink
```

#### "No module named 'dronecan'"
```bash
pip install dronecan
```

#### "Could not open port COM4"
- Check Orange Cube USB connection
- Verify correct COM port in Device Manager
- Try different USB cable/port

#### "No CAN messages received"
- Verify CAN wiring (CANH, CANL, GND)
- Check 120Ω termination resistors
- Confirm CAN bitrate (1Mbps)
- Ensure both devices have same bitrate

#### "Orange Cube not responding"
- Check power supply (5V, adequate current)
- Verify firmware compatibility
- Try system reboot via monitor tool

## 📊 Expected Output

### Successful CAN Communication
```
Orange Cube Monitor:
Parameter: CAN_D1_PROTOCOL = 1.0
Parameter: CAN_P1_BITRATE = 1000000.0
Parameter: CAN_D1_UC_NODE = 10.0

Beyond Robotics Board:
🚀 ESC Command: [1500, 1500, 1500, 1500]
🔓 Motors ARMED by ESC command
⚙️ Motors: ARMED PWM:[1500,1500,1500,1500]
```

### System Status Indicators
- 🚀 ESC commands received
- 🔓 Motor arming events  
- ⚙️ Motor status updates
- 🔋 Battery information
- ⚠️ Safety warnings

## 📞 Support

For issues with these tools:

1. **Check hardware connections** - CAN bus, power, USB
2. **Verify software dependencies** - Python packages installed
3. **Review serial output** - Both Orange Cube and Beyond Robotics board
4. **Test individual components** - Use tools separately to isolate issues

## 🔄 Development

These tools are designed for:
- ✅ **System validation** - Verify complete communication chain
- ✅ **Development testing** - Rapid iteration and debugging  
- ✅ **Configuration management** - Easy parameter adjustment
- ✅ **Troubleshooting** - Isolate and identify issues

All tools maintain compatibility with the refactored Beyond Robotics DroneCAN Motor Controller.
