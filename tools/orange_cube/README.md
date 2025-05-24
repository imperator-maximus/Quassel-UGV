# 🟠 Orange Cube Tools

Tools for monitoring and configuring the Orange Cube flight controller for DroneCAN integration.

## 📋 Tools Overview

### `monitor_orange_cube.py`
**Complete MAVLink monitoring and control interface**

**Features:**
- Real-time parameter monitoring
- DroneCAN-specific parameter display
- Servo output testing (RC override)
- Vehicle arming/disarming
- System reboot capability
- Message statistics

**Usage:**
```bash
python monitor_orange_cube.py
```

**Interactive Menu:**
1. Request all parameters
2. Monitor messages (60 seconds)
3. Servo test (RC override)
4. Display DroneCAN parameters
5. Arm vehicle
6. Disarm vehicle
7. Reboot Orange Cube
8. Exit

### `set_can_parameters.py`
**Configure Orange Cube for DroneCAN communication**

**Configured Parameters:**
- `CAN_P1_BITRATE = 1000000` (1Mbps)
- `CAN_D1_PROTOCOL = 1` (DroneCAN)
- `CAN_D1_UC_NODE = 10` (Orange Cube node ID)
- `CAN_D1_UC_ESC_BM = 15` (ESC bitmask for 4 motors)
- `SERVO_BLH_AUTO = 1` (Auto BLHeli detection)
- `SERVO_BLH_MASK = 5` (BLHeli on outputs 1&3)

**Usage:**
```bash
python set_can_parameters.py
```

## 🔧 Prerequisites

### Hardware
- Orange Cube connected via USB (typically COM4)
- CAN bus wired to Beyond Robotics board
- Proper CAN termination (120Ω resistors)

### Software
```bash
pip install pymavlink
```

## 🚀 Quick Start

### 1. Configure CAN Parameters
```bash
python set_can_parameters.py
```

### 2. Monitor System
```bash
python monitor_orange_cube.py
# Select option 4: Display DroneCAN parameters
```

### 3. Test Servo Outputs
```bash
# In monitor_orange_cube.py menu:
# Select option 3: Servo test
# Enter channel: 1
# Enter PWM: 1600
```

## 📊 Expected Output

### Parameter Configuration
```
Setting CAN_P1_BITRATE to 1000000...
✓ CAN_P1_BITRATE set successfully
Setting CAN_D1_PROTOCOL to 1...
✓ CAN_D1_PROTOCOL set successfully
...
Orange Cube configured for DroneCAN!
```

### Monitoring Output
```
Parameter: CAN_D1_PROTOCOL = 1.0
Parameter: CAN_D1_UC_NODE = 10.0
Parameter: CAN_P1_BITRATE = 1000000.0
Servo-Ausgänge: 1=1500, 2=1500, 3=1500, 4=1500
```

## 🔍 Troubleshooting

### Connection Issues
```
Error: Could not open port COM4
```
**Solutions:**
- Check USB cable connection
- Verify COM port in Device Manager
- Try different USB port
- Restart Orange Cube

### Parameter Setting Failures
```
Failed to set parameter CAN_P1_BITRATE
```
**Solutions:**
- Ensure Orange Cube is not armed
- Check MAVLink connection stability
- Retry parameter setting
- Reboot Orange Cube and retry

### No DroneCAN Activity
```
No DroneCAN messages received
```
**Solutions:**
- Verify CAN wiring (CANH, CANL, GND)
- Check 120Ω termination resistors
- Confirm Beyond Robotics board is powered
- Verify matching CAN bitrates (1Mbps)

## 📈 Integration with Beyond Robotics

### Expected Communication Flow
1. **Orange Cube** (Node ID 10) sends ESC commands
2. **Beyond Robotics Board** (Node ID 25) receives commands
3. **Motor Controller** converts to PWM outputs
4. **Safety System** monitors command timeout

### Verification Steps
1. Configure Orange Cube parameters
2. Monitor for DroneCAN messages
3. Check Beyond Robotics serial output
4. Verify PWM signals on motor pins

## 🔄 Development Workflow

### Parameter Testing
```bash
# 1. Set parameters
python set_can_parameters.py

# 2. Verify settings
python monitor_orange_cube.py
# Select option 4

# 3. Test communication
# Check Beyond Robotics board output
```

### Servo Testing
```bash
# 1. Start monitoring
python monitor_orange_cube.py

# 2. Send RC override
# Select option 3
# Test each channel individually

# 3. Verify motor response
# Check Beyond Robotics PWM outputs
```

## 📞 Support

Common parameter values for reference:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `CAN_P1_BITRATE` | 1000000 | 1Mbps CAN speed |
| `CAN_D1_PROTOCOL` | 1 | DroneCAN protocol |
| `CAN_D1_UC_NODE` | 10 | Orange Cube node ID |
| `CAN_D1_UC_ESC_BM` | 15 | ESC outputs 1-4 |
| `SERVO_BLH_AUTO` | 1 | Auto BLHeli detection |
| `SERVO_BLH_MASK` | 5 | BLHeli on outputs 1&3 |

For additional support, check the main project documentation.
