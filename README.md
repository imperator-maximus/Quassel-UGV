# 🚁 Beyond Robotics DroneCAN Motor Controller

A professional DroneCAN 1.0 motor controller implementation for the Beyond Robotics Dev Board (STM32L431) designed to communicate with Orange Cube flight controllers.

## 🎯 Project Overview

This project implements a complete DroneCAN motor controller system that enables seamless communication between an Orange Cube autopilot and a Beyond Robotics Dev Board for 4-channel PWM motor control. The system has been successfully tested and validated with real hardware.

### ✅ Project Status: **PRODUCTION READY**
- ✅ DroneCAN communication established with Orange Cube
- ✅ 4-channel PWM motor control implemented
- ✅ Safety timeout system operational
- ✅ Battery monitoring and reporting functional
- ✅ Professional modular code architecture
- ✅ Comprehensive testing tools provided

## 🏗️ Architecture Overview

### Custom Application Code (`beyond_robotics_working/src/`)
The core application consists of modular C++ components:

- **`main.cpp`** - Main application entry point and system orchestration
- **`config/config.h`** - Centralized configuration management
- **`motor_controller/`** - PWM motor control implementation
  - `MotorController.cpp/h` - 4-channel PWM control with safety features
- **`dronecan_handler/`** - DroneCAN protocol implementation
  - `DroneCAN_Handler.cpp/h` - ESC command reception and battery broadcasting
- **`test/`** - Development and testing utilities
  - `TestMode.cpp/h` - Automated testing and validation

### DroneCAN Library Components
The project integrates official DroneCAN libraries:

- **`lib/ArduinoDroneCANlib/`** - Beyond Robotics Arduino DroneCAN library
- **`lib/libcanard/`** - Core libcanard CAN protocol implementation
- **`dronecan/`** - Complete DroneCAN ecosystem
  - `DSDL/` - Data Structure Description Language definitions
  - `libcanard_repo/` - Official libcanard repository
  - `pydronecan/` - Python DroneCAN tools

### Hardware Support
- **`boards/BRMicroNode.json`** - PlatformIO board definition
- **`variants/BRMicroNode/`** - STM32L431 hardware abstraction layer
- **`AP_Bootloader.bin`** - ArduPilot-compatible bootloader

## 🛠️ Development Tools (`tools/`)

Professional testing and configuration utilities:

### Orange Cube Tools (`tools/orange_cube/`)
- **`monitor_orange_cube.py`** - Complete MAVLink monitoring and control
- **`set_can_parameters.py`** - Automated CAN parameter configuration

### DroneCAN Tools (`tools/dronecan/`)
- **`send_dronecan_actuator_commands.py`** - DroneCAN command testing

## 🚀 Quick Start

### 1. Flash the Bootloader
```bash
# Use STM32CubeProgrammer to flash AP_Bootloader.bin at 0x8000000
```

### 2. Build and Upload Firmware
```bash
cd beyond_robotics_working
pio run -t upload
pio device monitor -b 115200
```

### 3. Configure Orange Cube
```bash
cd tools/orange_cube
python set_can_parameters.py
```

### 4. Monitor System
```bash
python monitor_orange_cube.py
```

## 📋 Hardware Configuration

### Beyond Robotics Dev Board
- **MCU**: STM32L431 (ARM Cortex-M4)
- **CAN**: Built-in CAN controller
- **PWM**: 4 channels (PA8, PA9, PA10, PA11)
- **Programming**: ST-LINK V3 via STLINK header
- **Serial**: USB or UART (115200 baud)

### Orange Cube Setup
- **Firmware**: ArduPilot Rover with Skid Steering
- **CAN Configuration**:
  - `CAN_P1_BITRATE = 1000000` (1 Mbps)
  - `CAN_D1_PROTOCOL = 1` (DroneCAN)
  - `CAN_D1_UC_NODE = 10` (Orange Cube Node ID)
  - `CAN_D1_UC_ESC_BM = 15` (ESC bitmask)
  - `SERVO_BLH_MASK = 5` (BLHeli outputs)

### CAN Bus Wiring
- **CANH/CANL**: Connect between Orange Cube and Beyond Robotics board
- **Termination**: 120Ω resistors at both ends
- **Ground**: Common ground connection required

## 🔧 Key Features

### Motor Control
- **4-channel PWM output** (1000-2000μs pulse width)
- **Safety timeout system** (1-second ESC command timeout)
- **Smooth motor control** with configurable limits
- **Real-time status monitoring**

### DroneCAN Integration
- **Node ID 25** (configurable)
- **ESC command reception** from Orange Cube
- **Battery information broadcasting**
- **Parameter management system**
- **ArduPilot compatibility**

### Safety Features
- **Watchdog timer** (2-second timeout)
- **ESC command timeout** (motors stop if no commands)
- **Initialization validation** (all systems must initialize)
- **Error reporting** via serial output

## 📊 System Communication Flow

```
Orange Cube (Node 10) → CAN Bus → Beyond Robotics Board (Node 25)
     ↓                                        ↓
ESC Commands                           PWM Motor Control
Battery Requests                      Battery Information
Parameter Access                      Status Reporting
```

## 🗂️ Project Structure

```
UGV ESP32CAN/
├── 📄 README.md                    # This documentation
├── 📁 beyond_robotics_working/     # Main project (PRODUCTION)
│   ├── 📁 src/                    # Custom application code
│   │   ├── main.cpp              # Application entry point
│   │   ├── config/               # Configuration management
│   │   ├── motor_controller/     # PWM motor control
│   │   ├── dronecan_handler/     # DroneCAN communication
│   │   └── test/                 # Testing utilities
│   ├── 📁 lib/                   # DroneCAN libraries
│   ├── 📁 dronecan/              # DroneCAN ecosystem
│   ├── 📁 boards/                # Hardware definitions
│   └── 📁 variants/              # STM32 HAL
├── 📁 tools/                      # Testing and configuration
│   ├── 📁 orange_cube/           # Orange Cube tools
│   └── 📁 dronecan/              # DroneCAN testing
└── 📁 archive/                    # Development history
    ├── 📁 esp32_files/           # Legacy ESP32 implementation
    ├── 📁 development_scripts/   # Development utilities
    └── 📁 old_documentation/     # Historical documentation
```

## 🧪 Testing and Validation

### System Integration Test
```bash
# 1. Upload firmware to Beyond Robotics board
cd beyond_robotics_working
pio run -t upload

# 2. Monitor serial output
pio device monitor -b 115200

# 3. Configure Orange Cube
cd ../tools/orange_cube
python set_can_parameters.py

# 4. Monitor Orange Cube
python monitor_orange_cube.py
```

### Expected Output
**Beyond Robotics Board Serial:**
```
=====================================
Beyond Robotix Motor Controller v1.0
Beyond Robotics Dev Board (STM32L431)
=====================================
🚀 System initialization complete!
🚀 ESC Command: [1500, 1500, 1500, 1500]
🔓 Motors ARMED by ESC command
⚙️ Motors: ARMED PWM:[1500,1500,1500,1500]
```

**Orange Cube Monitor:**
```
Parameter: CAN_D1_PROTOCOL = 1.0
Parameter: CAN_P1_BITRATE = 1000000.0
Parameter: CAN_D1_UC_NODE = 10.0
✅ DroneCAN communication active
```

## 🔧 Configuration Options

### Motor Controller Settings (`config/config.h`)
```cpp
#define NUM_MOTORS 4              // Number of motor channels
#define PWM_MIN 1000              // Minimum PWM (1ms)
#define PWM_MAX 2000              // Maximum PWM (2ms)
#define PWM_NEUTRAL 1500          // Neutral PWM (1.5ms)
#define ESC_TIMEOUT_MS 1000       // Safety timeout
```

### DroneCAN Settings
```cpp
#define DRONECAN_NODE_ID 25       // Unique node identifier
#define CAN_BITRATE 1000000       // 1 Mbps (must match Orange Cube)
```

### Test Mode (Development)
```cpp
#define ENABLE_TEST_MODE          // Enable automated testing
#define TEST_ESC_INTERVAL_MS 3000 // Test command interval
```

## 🐛 Troubleshooting

### Common Issues

#### ❌ "System initialization failed"
**Cause**: Hardware or configuration issue
**Solution**:
1. Check ST-LINK connection and SW1 switch position
2. Verify CAN bus wiring (CANH, CANL, GND)
3. Confirm 120Ω termination resistors
4. Check serial output for specific error messages

#### ❌ "No DroneCAN messages received"
**Cause**: CAN communication failure
**Solution**:
1. Verify Orange Cube CAN parameters:
   ```bash
   cd tools/orange_cube
   python set_can_parameters.py
   ```
2. Check CAN bus bitrate (must be 1 Mbps on both devices)
3. Verify node IDs don't conflict
4. Test with CAN sniffer (Cangaroo + USB CAN adapter)

#### ❌ "Motors not responding"
**Cause**: ESC timeout or configuration issue
**Solution**:
1. Check PWM pin connections (PA8, PA9, PA10, PA11)
2. Verify ESC power supply and calibration
3. Monitor serial output for ESC command reception
4. Test with manual PWM values in test mode

#### ❌ "Orange Cube not arming"
**Cause**: PreArm check failures
**Solution**:
1. Disable hardware safety switch: `BRD_SAFETYENABLE = 0`
2. Skip GPS checks: `ARMING_CHECK = 0` (testing only)
3. Check servo output configuration
4. Verify battery voltage and current sensors

### Debug Tools

#### Serial Monitoring
```bash
# Beyond Robotics board
pio device monitor -b 115200

# Orange Cube
python tools/orange_cube/monitor_orange_cube.py
```

#### CAN Bus Analysis
```bash
# Send test commands
python tools/dronecan/send_dronecan_actuator_commands.py

# Monitor with external sniffer
# Use Cangaroo + USB CAN adapter for detailed analysis
```

## 📈 Performance Characteristics

### System Specifications
- **Update Rate**: 50 Hz (20ms cycle time)
- **CAN Bitrate**: 1 Mbps
- **PWM Resolution**: 1μs precision
- **Safety Timeout**: 1 second
- **Memory Usage**: ~32KB Flash, ~8KB RAM

### Communication Latency
- **Orange Cube → Beyond Robotics**: <5ms
- **ESC Command → PWM Output**: <1ms
- **Battery Info Update**: 100ms interval

## 🔄 Development History

This project evolved from an ESP32-based implementation to a professional Beyond Robotics solution:

### Phase 1: ESP32 Prototype (`archive/esp32_files/`)
- Initial DroneCAN implementation
- CAN bus communication challenges
- Multiple timeout and reset issues

### Phase 2: Beyond Robotics Migration
- Switched to STM32L431-based Beyond Robotics Dev Board
- Integrated official Arduino DroneCAN library
- Resolved CAN communication stability issues

### Phase 3: Professional Refactoring (`beyond_robotics_working/`)
- Modular architecture implementation
- Comprehensive safety features
- Production-ready code quality
- Complete testing framework

### Phase 4: Project Cleanup
- Organized development tools
- Archived legacy implementations
- Created comprehensive documentation
- Established professional project structure

## 🤝 Contributing

### Code Standards
- **C++**: Follow Arduino/PlatformIO conventions
- **Python**: PEP 8 compliance for tools
- **Documentation**: Comprehensive inline comments
- **Testing**: Validate all changes with hardware

### Development Workflow
1. **Test on hardware** - Always validate with real Orange Cube
2. **Maintain compatibility** - Preserve Beyond Robotics integration
3. **Document changes** - Update README and inline comments
4. **Archive old code** - Move obsolete files to archive/

## 📞 Support and Resources

### Official Documentation
- **Beyond Robotics**: https://beyond-robotix.gitbook.io/docs/
- **DroneCAN Protocol**: https://dronecan.github.io/
- **ArduPilot**: https://ardupilot.org/rover/

### Hardware Support
- **Beyond Robotics Dev Board**: STM32L431 with integrated CAN
- **Orange Cube**: ArduPilot-compatible autopilot
- **CAN Tools**: USB CAN adapters, Cangaroo software

### Community
- **ArduPilot Forum**: https://discuss.ardupilot.org/
- **DroneCAN Community**: GitHub discussions and issues
- **Beyond Robotics Support**: Official documentation and examples

---

## 🎯 Project Status Summary

**✅ PRODUCTION READY** - This DroneCAN motor controller implementation is fully functional and tested with real hardware. The system successfully enables 4-channel PWM motor control via DroneCAN commands from an Orange Cube autopilot, with comprehensive safety features and professional code architecture.

**Key Achievements:**
- ✅ Stable DroneCAN communication at 1 Mbps
- ✅ 4-channel PWM motor control with safety timeout
- ✅ Battery monitoring and reporting
- ✅ Professional modular code architecture
- ✅ Comprehensive testing and configuration tools
- ✅ Complete documentation and troubleshooting guides

The project is ready for production use and further development.
