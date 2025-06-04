# Orange Cube Configuration Tools

**CLEAN & ORGANIZED** - Only the essential scripts for Orange Cube DroneCAN setup!

This directory contains the **FINAL, TESTED** scripts for configuring the Orange Cube flight controller for DroneCAN communication with Beyond Robotics Dev Board.

## 🎯 Overview

The Orange Cube acts as DroneCAN master, sending ESC commands to Beyond Robotics Dev Board. These tools provide **COMPLETE** configuration and monitoring.

## 📁 Final Scripts (Ready to Use)

### 🔧 Configuration
- **`master_orange_cube_config.py`** - **COMPLETE Orange Cube setup** (CAN + RC + Servo)
  - All-in-one configuration script
  - Based on Context7 recommendations
  - Tested and verified working
  - Sets all 100+ parameters correctly

### 📊 Monitoring & Testing
- **`monitor_pwm_before_can.py`** - **PWM values before CAN transmission**
  - Shows exact PWM values Orange Cube calculates
  - Displays DroneCAN ESC values (0-8191)
  - Real-time movement interpretation
  - Perfect for debugging

- **`monitor_orange_cube.py`** - **Orange Cube status monitoring**
  - System status and parameters
  - Important for diagnostics

- **`find_throttle_channel.py`** - **RC channel analysis**
  - Identifies RC channel mapping
  - Shows min/max/trim values
  - Essential for RC calibration

### 🔧 Utilities
- **`dump_all_parameters.py`** - **Parameter backup utility**
  - Exports all 963 Orange Cube parameters
  - Creates JSON and Python config files
  - Backup before major changes

## ✅ WORKING Configuration

**Key Parameters (Context7 verified):**
```
SERVO1_FUNCTION = 73    # ThrottleLeft (Skid Steering)
SERVO2_FUNCTION = 74    # ThrottleRight (Skid Steering)
CAN_D1_UC_ESC_BM = 3    # ESC1 + ESC2
SERVO_BLH_MASK = 3      # Servo1 + Servo2
FRAME_TYPE = 1          # Skid Steering
CAN_P1_BITRATE = 1000000 # 1Mbps
```

## 🚀 Quick Start (3 Steps)

### 1. Complete Configuration
```bash
python master_orange_cube_config.py
```
**This sets ALL parameters in one go!**

### 2. Reboot Orange Cube
```bash
python -c "from pymavlink import mavutil; m=mavutil.mavlink_connection('COM4'); m.reboot_autopilot()"
```

### 3. Test PWM Output
```bash
python monitor_pwm_before_can.py
```
**Move RC stick - both ESC1 and ESC2 should show values!**

## 🎮 RC Configuration

**Your RC Setup (Mixed Channels):**
- **RC1**: 995-2115 (Steering component)
- **RC2**: 1166-1995 (Throttle component)
- **One stick controls both channels** (perfect for skid steering!)

**Expected Behavior:**
- **Vorne**: ESC1=high, ESC2=high
- **Links**: ESC1=low, ESC2=high
- **Rechts**: ESC1=high, ESC2=low
- **Zurück**: ESC1=low, ESC2=low

## 🎮 RC Skid Steering Configuration

### `configure_rc_skid_steering.py`
**Configure Orange Cube for RC remote control with skid steering**

**Configured Parameters:**
- **RC Mapping**: Steering on Channel 1, Throttle on Channel 3
- **Skid Steering**: `SKID_STEER_OUT = 1`, `SKID_STEER_IN = 1`
- **Servo Functions**: `SERVO1_FUNCTION = 73` (ThrottleLeft), `SERVO2_FUNCTION = 74` (ThrottleRight)
- **RC Calibration**: Standard 1000-2000μs range with 1500μs neutral
- **Failsafe**: Configured for safe operation

### `monitor_rc_input.py`
**Real-time RC input monitoring and skid steering visualization**

**Features:**
- Live RC channel display (Channels 1-4)
- Skid steering calculation preview
- Servo output monitoring
- DroneCAN ESC status indication

**Usage:**
```bash
python monitor_rc_input.py
# Move RC sticks to see real-time values
```

### `test_rc_skid_steering.py`
**Automated testing of RC skid steering configuration**

**Test Modes:**
- `--test patterns`: Test various skid steering movement patterns
- `--test calibration`: Test RC calibration with extreme values
- `--test monitor`: Monitor servo outputs for 15 seconds
- `--test all`: Run all tests (default)

**Usage:**
```bash
python test_rc_skid_steering.py
# or specific test:
python test_rc_skid_steering.py --test patterns
```

### 5. Test Servo Outputs
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

## 🔍 Troubleshooting

### Problem: Only ESC1 works, ESC2 = 0
**Solution**: Wrong SERVO_FUNCTION values!
```bash
python master_orange_cube_config.py  # Sets correct values 73/74
```

### Problem: RC not responding
**Solution**: Check RC calibration
```bash
python find_throttle_channel.py  # Analyze RC channels
```

### Problem: No CAN communication
**Solution**: Check Beyond Robotics board connection and CAN wiring

## 📋 Complete Test Procedure

```bash
# 1. Complete setup
python master_orange_cube_config.py

# 2. Reboot Orange Cube
python -c "from pymavlink import mavutil; m=mavutil.mavlink_connection('COM4'); m.reboot_autopilot()"

# 3. Test PWM (Orange Cube side)
python monitor_pwm_before_can.py
# Move stick - verify ESC1 and ESC2 values

# 4. Test CAN (Beyond Robotics side)
python ../monitor_real_esc_commands.py
# Connect Beyond Robotics board - verify motor commands
```

## 📤 Lua Script Upload (WiFi)

### `upload_lua_via_wifi.py`
**Upload Lua scripts to Orange Cube via WiFi Bridge using MAVLink FTP**

**Features:**
- WiFi Bridge integration (192.168.178.101:14550)
- Automatic Lua parameter configuration
- MAVFTP file upload
- Test script creation
- Robust error handling

**Usage:**
```bash
# Upload hello world test script
python upload_lua_via_wifi.py hello_world.lua

# Upload neutral position fix
python upload_lua_via_wifi.py neutral_fix.lua

# Auto-create and upload test script
python upload_lua_via_wifi.py
```

### `test_lua_upload.py`
**Comprehensive test tool for Lua upload prerequisites**

**Tests:**
- WiFi Bridge connectivity
- MAVFTP client functionality
- Lua parameter availability
- Directory structure access

**Usage:**
```bash
python test_lua_upload.py
```

### `neutral_fix.lua`
**Lua script to fix neutral position problem (1495μs → 1500μs)**

**Features:**
- RC neutral position correction
- Deadband around neutral (±10μs)
- Real-time PWM output correction
- Status reporting to GCS

**Problem solved:** RC stick neutral (1495μs) was output as 1000μs instead of 1500μs

### Lua Upload Workflow
```bash
# 1. Test WiFi connection and MAVFTP
python test_lua_upload.py

# 2. Upload script
python upload_lua_via_wifi.py neutral_fix.lua

# 3. Monitor GCS for Lua messages
# Orange Cube reboots automatically
# Check Mission Planner/MAVProxy for script messages
```

## 🗂️ Archive

Old experimental scripts moved to `archive/` directory:
- 24 legacy scripts from development phase
- Keep for reference but not needed for normal use

## 📞 Support

**Working Configuration Sources:**
- ✅ **Context7** - Provided correct SERVO_FUNCTION values (73/74)
- ✅ **Parameter dump** - All 963 current parameters exported
- ✅ **Tested setup** - Verified working with your RC system
- ✅ **WiFi Bridge** - Lua script upload via MAVLink FTP

**For help:** Consult Context7, ArduPilot forums, or Beyond Robotics documentation.

## 🎉 Success Criteria

**System is working when:**
1. ✅ `master_orange_cube_config.py` runs without errors
2. ✅ `monitor_pwm_before_can.py` shows both ESC1 and ESC2 values
3. ✅ All 4 RC directions work (Vorne/Links/Rechts/Zurück)
4. ✅ Beyond Robotics board receives motor commands via CAN
5. ✅ Lua scripts upload successfully via WiFi Bridge

**You're ready for the next phase!** 🚀
