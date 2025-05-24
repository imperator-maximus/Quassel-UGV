# Beyond Robotics DroneCAN Motor Controller - Refactored

## 🎯 Overview

This is a **clean, modular implementation** of a DroneCAN motor controller for the Beyond Robotics Dev Board (STM32L431). The code has been refactored from a working prototype into a professional, maintainable structure.

## ✅ Features

- **4-Channel PWM Motor Control** - PA8, PA9, PA10, PA11
- **DroneCAN ESC Command Reception** - Compatible with Orange Cube
- **Battery Information Broadcasting** - Real-time telemetry
- **Safety Timeout System** - 1-second ESC command timeout
- **Test Mode** - Automated testing and validation
- **Orange Cube Integration** - Node ID 25, 1Mbps CAN

## 📁 Project Structure

```
beyond_robotics_working/
├── src/
│   ├── main.cpp                    # Clean main application
│   ├── config/
│   │   └── config.h               # All configuration settings
│   ├── motor_controller/
│   │   ├── MotorController.h      # Motor control class
│   │   └── MotorController.cpp
│   ├── dronecan_handler/
│   │   ├── DroneCAN_Handler.h     # DroneCAN communication
│   │   └── DroneCAN_Handler.cpp
│   └── test/
│       ├── TestMode.h             # Test functionality
│       └── TestMode.cpp
├── include/
│   └── project_common.h           # Common includes & definitions
├── platformio.ini                 # PlatformIO configuration
└── README_REFACTORED.md          # This file
```

## 🔧 Configuration

All configuration is centralized in `src/config/config.h`:

### DroneCAN Settings
- **Node ID**: 25 (Orange Cube compatible)
- **CAN Bitrate**: 1,000,000 bps
- **Node Name**: "Beyond Robotix Motor Controller"

### Motor Settings
- **Number of Motors**: 4
- **PWM Range**: 1000-2000 μs (standard ESC)
- **Neutral Position**: 1500 μs
- **Safety Timeout**: 1000 ms

### Test Mode
- **Test Interval**: 3000 ms
- **PWM Test Range**: 1300-1700 μs
- **PWM Step Size**: 100 μs

## 🚀 Quick Start

1. **Build and Upload**:
   ```bash
   pio run -t upload
   ```

2. **Monitor Serial Output**:
   ```bash
   pio device monitor -b 115200
   ```

3. **Expected Output**:
   ```
   =====================================
   Beyond Robotics DroneCAN Motor Controller
   Version: 1.0
   Beyond Robotics Dev Board (STM32L431)
   =====================================
   Node ID: 25
   CAN Bitrate: 1000000 bps
   Number of Motors: 4
   Ready for Orange Cube integration!
   =====================================
   ```

## 🏗️ Architecture

### MotorController Class
- **Purpose**: Manages PWM outputs and safety
- **Features**: 
  - ESC command processing
  - Safety timeout monitoring
  - Motor arming/disarming
  - PWM value validation

### DroneCAN_Handler Class
- **Purpose**: Handles all DroneCAN communication
- **Features**:
  - Message reception (ESC commands)
  - Message transmission (battery info)
  - Parameter management
  - Orange Cube integration

### TestMode Class
- **Purpose**: Development and validation testing
- **Features**:
  - Automated ESC command generation
  - PWM sweep testing
  - Motor validation sequences

## 📡 DroneCAN Integration

### Received Messages
- `UAVCAN_EQUIPMENT_ESC_RAWCOMMAND` - Motor control commands
- `UAVCAN_EQUIPMENT_AHRS_MAGNETICFIELDSTRENGTH` - Compass data (example)

### Transmitted Messages
- `UAVCAN_EQUIPMENT_POWER_BATTERYINFO` - Battery telemetry (100ms interval)

### Orange Cube Configuration
```
CAN_P1_BITRATE = 1000000
CAN_D1_PROTOCOL = 1
CAN_D1_UC_NODE = 10
CAN_D1_UC_ESC_BM = 15
```

## 🔒 Safety Features

1. **ESC Timeout**: Motors automatically disarm after 1s without commands
2. **PWM Validation**: All PWM values constrained to safe range
3. **Watchdog Timer**: System reset if main loop hangs (2s timeout)
4. **Neutral Position**: Motors default to 1500μs (stop) when disarmed

## 🧪 Test Mode

Test mode can be enabled/disabled in `config.h`:

```cpp
#define ENABLE_TEST_MODE  // Comment out to disable
```

When enabled:
- Sends test ESC commands every 3 seconds
- Cycles PWM from 1300-1700μs in 100μs steps
- Provides visual feedback via serial output

## 🔧 Customization

### Adding New Motors
1. Update `NUM_MOTORS` in `config.h`
2. Add new pins to `MOTOR_PINS` array
3. Ensure pins are timer-capable (TIM1/TIM2/TIM15/TIM16)

### Changing PWM Range
```cpp
#define PWM_MIN 1000      // Minimum throttle
#define PWM_MAX 2000      // Maximum throttle  
#define PWM_NEUTRAL 1500  // Stop position
```

### Adjusting Safety Timeout
```cpp
#define ESC_TIMEOUT_MS 1000  // Milliseconds
```

## 🐛 Debugging

### Serial Output Icons
- 🚀 ESC commands received
- 🔓 Motor arming events
- ⚠️ Safety warnings
- 📤 Test commands sent
- 🔋 Battery information
- ⚙️ Motor status

### Debug Intervals
- **Motor Status**: Every 5 seconds
- **Battery Info**: Every 10 seconds (100 messages)
- **Test Commands**: Every 3 seconds (if enabled)

## 📋 Migration from Original Code

The refactored code maintains **100% compatibility** with the original functionality while providing:

1. **Better Organization**: Logical separation of concerns
2. **Easier Maintenance**: Modular, documented code
3. **Improved Testing**: Dedicated test infrastructure
4. **Enhanced Safety**: Centralized safety checks
5. **Flexible Configuration**: Easy parameter adjustment

## 🔄 Build Process

The project uses PlatformIO with the Beyond Robotics board definition:

```ini
[env:stm32L431]
platform = ststm32
board = BRMicroNode
framework = arduino
upload_protocol = stlink
monitor_speed = 115200
```

## 📞 Support

For issues or questions:
1. Check serial output for error messages
2. Verify hardware connections
3. Ensure Orange Cube CAN configuration matches
4. Test with individual motor validation

---

**Status**: ✅ **Production Ready** - Fully tested and validated
