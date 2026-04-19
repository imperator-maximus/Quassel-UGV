# 🚁 Quassel UGV - RTK-GPS + WitMotion Sensor Hub + WebApp

A professional autonomous UGV system with an Orange-Pi-based sensor hub, RTK-GPS positioning, WitMotion IMU orientation, CAN telemetry, and a real-time web interface.

## 🎯 Project Overview

This project implements a complete autonomous UGV system featuring:
- **Dual-antenna RTK-GPS** (Holybro UM982) for precise positioning and heading
- **WitMotion USB-IMU** for roll/pitch/yaw orientation
- **CAN Bus Integration** for sensor and motor telemetry
- **Real-time Web Interface** with Bing Maps satellite view
- **Modular Architecture** with Pi Zero 2W sensor hub and Pi 3 controller

### ✅ Project Status: **ACTIVE DEVELOPMENT**
- ✅ Sensor hub architecture (Pi Zero 2W + PiCAN FD)
- ✅ RTK-GPS + IMU integration
- ✅ CAN bus communication
- ✅ Web interface framework
- ✅ WitMotion-based IMU telemetry on the sensor hub

## 🏗️ System Architecture

### Hardware Architecture

```
┌─────────────────────────────────────────┐
│  MAST (Orange Pi Zero 2W)               │
│  ├─ Holybro UM982 (Dual-Antenna RTK)    │
│  │  └─ USB Serial (/dev/serial/by-id)   │
│  ├─ WitMotion USB-IMU                   │
│  │  └─ USB Serial (/dev/serial/by-id)   │
│  └─ CANable2                            │
│     └─ SocketCAN can0                   │
└─────────────────────────────────────────┘
            │
            │ CAN Bus
            ▼
┌─────────────────────────────────────────┐
│  CHASSIS (Pi 3 + Motor Control)         │
│  ├─ WebApp (Python-based)               │
│  ├─ Motor CAN Interface                 │
│  └─ WLAN Access Point                   │
└─────────────────────────────────────────┘
            │
            │ WLAN
            ▼
    [ Browser-Client ]
```

### Software Stack

**Pi Zero 2W (Sensor Hub):**
| Component | Function | Interface |
|-----------|----------|-----------|
| UM982 GPS | RTK Position + Dual-Antenna Heading | USB Serial /dev/serial/by-id |
| WitMotion USB-IMU | 9-DoF IMU incl. orientation frames | USB Serial |
| CANable2 | CAN Bus Gateway | SocketCAN can0 |
| `sensor_hub_app.py` | Web API + CAN telemetry + sensor status | Systemd Service |

**Data Flow:**
- GPS-NMEA reading (pyserial)
- IMU data reading (pyserial / WitMotion binary protocol)
- Sensor telemetry (Position + Heading + Roll/Pitch/Yaw)
- CAN message transmission (python-can)

**Pi 3 (Controller + WebApp):**
| Component | Function |
|-----------|----------|
| Python WebApp | Flask/FastAPI |
| CAN Listener | Receives sensor data |
| WebSocket/SSE | Real-time push to browser |
| Bing Maps API | Map display |

**WebApp Features:**
- 🗺️ Bing Maps Satellite View (Lübtheen-optimized)
- 📍 GPS Position (Live marker)
- 🧭 Heading Display (Dual-antenna)
- 📊 RTK Status (No Fix / Float / Fixed)
- 🛤️ Trail/Path (last N positions)
- 📐 Roll/Pitch/Yaw from IMU

## 🛠️ Development Tools (`tools/`)

Testing and configuration utilities for CAN communication:

### CAN Testing Tools
- **`candump`** - Monitor CAN traffic on Raspberry Pi
- **`cansend`** - Send test CAN messages

## 🚀 Quick Start

### 1. Install Dependencies on Raspberry Pi Zero 2W (Sensor Hub)
```bash
# Install required packages
sudo apt install python3-pip python3-can python3-serial

# Install Python libraries
pip3 install pyserial python-can

# Enable UART / serial devices as needed
sudo raspi-config nonint do_serial 0
```

### 2. Install Dependencies on Raspberry Pi 3 (Controller)
```bash
# Install web framework
pip3 install flask python-socketio

# Install CAN tools
sudo apt install can-utils
pip3 install python-can
```

### 3. Setup Sensor Hub (Pi Zero 2W)
```bash
# Upload current sensor hub
scp -r sensor_hub nicolay@orangeugv:/home/nicolay/

# Follow the tested deploy guide
ssh nicolay@orangeugv
cd /home/nicolay/sensor_hub
sudo systemctl start sensor-hub.service
```

### 4. Setup Controller (Pi 3)
```bash
# Upload web app
scp web_app.py nicolay@raspberrycan:/home/nicolay/

# Start web interface
python3 web_app.py
# Access at http://raspberrycan:80
```

## 📋 Hardware Configuration

### Sensor Hub (Orange Pi Zero 2W)
- **MCU**: Allwinner H616
- **CAN Interface**: CANable2 via USB (`can0`)
- **GPS**: Holybro UM982 (Dual-antenna RTK)
  - USB serial via `/dev/serial/by-id/...`
- **IMU**: WitMotion USB-IMU
  - USB serial via `/dev/serial/by-id/...`
- **Operating System**: DietPi / Debian-based
- **Network**: CAN Bus to Controller

### Controller (Pi 3)
- **MCU**: Broadcom BCM2837 (ARM Cortex-A53 Quad-Core)
- **CAN Interface**: PiCAN FD (MCP2515 + 16MHz oscillator)
- **Motor Control**: GPIO 18/19 (Hardware-PWM)
- **Operating System**: Raspberry Pi OS (Debian-based)
- **Network**: WiFi + SSH access (nicolay@raspberrycan)

### Sensor Hub Device Usage (Orange Pi Zero 2W)
**USB Devices:**
- **Holybro UM982**: USB serial GNSS (`/dev/serial/by-id/...`)
- **WitMotion IMU**: USB serial IMU (`/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`)
- **CANable2**: USB CAN adapter (`can0` via `slcan-can0.service`)

**Reserved/System Pins:**
- **GPIO 9-11**: SPI (used by HAT)

### GPIO Pin Configuration (Pi 3 - Controller)
**Motor Control:**
- **GPIO 18**: Right Motor PWM Output (Hardware-PWM)
- **GPIO 19**: Left Motor PWM Output (Hardware-PWM)

**Relay Control:**
- **GPIO 22**: Light Control Relay Output (HIGH = On, LOW = Off)
- **GPIO 23**: Mower Control Relay Output (HIGH = On, LOW = Off)

**Safety:**
- **GPIO 17**: Emergency Stop/Safety Switch Input (pulled high, active low)
- **GPIO 12**: Mower Speed PWM Output (24-100% Duty Cycle, 1000Hz, 3.3V GPIO)

### Mower Speed Control (PWM-to-Analog Conversion)

The mower speed control uses PWM-to-analog conversion via RC filter circuit:

**Circuit Configuration:**
```
GPIO12 (PWM) ----[1kΩ]----+-----> Analog Output (to Mower Controller)
                           |
                         [15µF]
                           |
                         GND
```

**PWM Specifications:**
- **Frequency**: 1000Hz
- **Duty Cycle Range**: 24-100% (optimized for 3.3V GPIO)
- **Output Voltage Range**: 0.8V - 3.3V
- **Speed Mapping**: 0% = 0.8V (idle), 100% = 3.3V (full speed)

**RC Filter Analysis:**
- **Time Constant**: τ = 1kΩ × 15µF = 15ms
- **Smoothing Factor**: 15x PWM period (excellent filtering)
- **Ripple**: <1% of output voltage

### CAN Bus Configuration
- **Bitrate**: 500 kbit/s (Sensor Hub) / 1 Mbps (Motor Control)
- **Termination**: 120Ω resistor on both ends
- **Ground**: Common ground connection required
- **Interface**: can0 on both Pi Zero 2W and Pi 3
- **TX Queue**: Configured with txqueuelen=1000 for improved buffer performance

### JSON CAN Protocol
**Sensor Hub → Controller (Continuous, 50Hz):**
```json
{
  "gps": {"lat": 53.8234, "lon": 10.4567, "altitude": 45.2},
  "heading": 45.2,
  "rtk_status": "FIXED",
  "imu": {"roll": 2.3, "pitch": -1.8, "yaw": 45.2, "heading": 45.2, "is_calibrated": true},
  "timestamp": 1234567890.123
}
```

**Controller → Sensor Hub (On-Demand):**
```json
// Status request
{"request": "sensor_status"}

// Restart sensor hub
{"cmd": "restart"}
```

**Sensor Hub Response to Status Request:**
```json
{
  "gps": {"status": "OK", "satellites": 12, "last_update": 0.02},
  "imu": {"status": "OK", "temperature": 28.5},
  "can": {"status": "OK", "messages_sent": 1250}
}
```

## 🔧 Key Features

### Sensor Integration
- **Dual-Antenna RTK-GPS** (Holybro UM982)
  - Precise positioning (cm-level accuracy)
  - Dual-antenna heading (no compass needed)
  - NMEA output via UART
- **WitMotion USB-IMU**
  - Accelerometer + Gyroscope + orientation frames
  - Roll/Pitch/Yaw orientation
  - USB serial interface

### Sensor Hub Telemetry
- **Real-time position tracking** with RTK-GPS
- **Heading calculation** from dual-antenna GPS
- **Native orientation data** from the WitMotion IMU
- **CAN bus broadcasting** to controller

### Web Interface
- **Bing Maps satellite view** (Lübtheen-optimized)
- **Live GPS marker** with real-time updates
- **Heading indicator** (dual-antenna)
- **RTK status display** (No Fix / Float / Fixed)
- **Trail visualization** (last N positions)
- **Roll/Pitch/Yaw display** from IMU
- **WebSocket real-time updates** (50Hz)

### Motor Control
- **2-channel Hardware-PWM output** (1000-2000μs pulse width)
- **Freeze-resistant PWM generation** using pigpio hardware timers
- **Real-time monitoring** with live percentage and PWM display
- **Intelligent Ramping System** for smooth acceleration and quick braking

### Safety Features
- **Hardware-PWM independence** (continues running if Python crashes)
- **Command timeout monitoring** (2-second timeout → automatic neutral)
- **Emergency stop functionality** with signal handlers
- **Service integration** with automatic restart on failure

## 🎮 System Commands

### Sensor Hub (Pi Zero 2W)
```bash
# Start sensor hub service
sudo systemctl start sensor-hub.service

# View sensor data
sudo systemctl status sensor-hub.service

# Monitor CAN messages
candump can0

# View logs
journalctl -u sensor-hub -f
```

### Controller (Pi 3)
```bash
# Start web interface
python3 web_app.py

# Access web interface
# http://raspberrycan:80

# Monitor CAN messages
candump can0

# View application logs
tail -f /var/log/ugv_app.log
```

## 📊 System Communication Flow

```
Sensor Hub (Pi Zero 2W)          Controller (Pi 3)
├─ GPS (UM982)                   ├─ Web Interface
├─ IMU (WitMotion USB)           ├─ Motor Control
└─ CAN Transceiver               └─ CAN Transceiver
        │                                │
        └────────── CAN Bus ────────────┘
                    (500 kbit/s)
                        │
                        ▼
                  [ Browser Client ]
                  (Bing Maps + RTK)
```

## 🗂️ Project Structure

```
UGV ESP32CAN/
├── 📄 README.md                    # This documentation
├── 📁 sensor_hub/                 # Current sensor hub (Orange Pi Zero 2W)
│   ├── sensor_hub_app.py          # Flask API + CAN telemetry
│   ├── imu_handler.py             # WitMotion USB IMU parser
│   ├── sensor-hub.service         # systemd service file
│   ├── templates/sensor_hub.html  # Sensor hub web interface
│   └── README.md                  # Detailed usage guide
├── 📁 raspberry_pi/               # Controller and legacy Raspberry Pi docs
│   ├── motor_controller/          # Current controller implementation
│   └── README.md                  # Controller / legacy setup notes
├── 📁 tools/                      # Testing and configuration
│   └── 📁 dronecan/               # CAN testing tools
└── 📁 archive/                    # Development history
    ├── 📁 esp32_files/            # Legacy ESP32 implementation
    ├── 📁 beyond_robotics_working/ # Legacy Beyond Robotics code
    ├── 📁 development_scripts/    # Development utilities
    └── 📁 old_documentation/      # Historical documentation
```

## 🧪 Testing and Validation

### System Integration Test
```bash
# 1. Setup Sensor Hub (Pi Zero 2W)
ssh nicolay@raspberrycan
./setup_sensor_hub.sh
source ~/.bashrc

# 2. Check sensor hub status
sudo systemctl status sensor-hub

# 3. Monitor CAN messages
candump can0

# 4. Start web interface (Pi 3)
python3 web_app.py

# 5. Access web interface
# http://raspberrycan:80
```

### Expected Output
**Sensor Hub Service:**
```
[15:33:41] 📡 GPS Position: 53.8234°N, 10.4567°E
[15:33:41] 🧭 Heading: 45.2° (Dual-Antenna)
[15:33:41] 📊 RTK Status: FIXED
[15:33:41] 📐 Roll: +2.3°, Pitch: -1.8°
[15:33:41] 🚀 CAN Message sent (ID: 0x123)
```

**Web Interface:**
```
✅ Connected to Sensor Hub
📍 Position: 53.8234°N, 10.4567°E
🧭 Heading: 45.2°
📊 RTK: FIXED
🛤️ Trail: 42 points
```

## 🔧 Configuration Options

### Sensor Hub Settings (`sensor_hub/config.py`)
```python
# GPS Configuration
GPS_PORT = '/dev/serial/by-id/usb-FTDI_FT231X_USB_UART_*'
GPS_BAUDRATE = 230400            # UM982 baud rate

# IMU Configuration
IMU_TYPE = 'witmotion'
IMU_PORT = '/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0'
IMU_BAUDRATE = 9600

# CAN Configuration
CAN_INTERFACE = 'can0'           # CAN interface
CAN_BITRATE = 500000             # 500 kbit/s for sensor hub

# Telemetry
CAN_SEND_RATE = 10               # Hz CAN transmit rate
```

### Web App Settings (`web_app.py`)
```python
# Flask Configuration
FLASK_HOST = '0.0.0.0'           # Listen on all interfaces
FLASK_PORT = 80                  # HTTP port
DEBUG = False                    # Production mode

# CAN Configuration
CAN_INTERFACE = 'can0'           # CAN interface
CAN_BITRATE = 1000000            # 1 Mbps for motor control

# WebSocket Configuration
UPDATE_RATE = 50                 # Hz (20ms updates)
WEBSOCKET_TIMEOUT = 30           # Seconds
```

### Service Configuration (`sensor-hub.service`)
```ini
[Service]
ExecStart=/usr/bin/python3 /home/nicolay/sensor_hub/sensor_hub_app.py
Restart=always
RestartSec=5
User=nicolay
```

### CAN Interface Configuration (`can-interface.service`)
The CAN interface is automatically configured at boot:
```ini
[Service]
ExecStart=/bin/bash -c 'ip link set can0 down; ip link set can0 type can bitrate 500000; ip link set can0 txqueuelen 1000; ip link set can0 up'
```
- **Bitrate**: 500 kbit/s for sensor hub communication
- **TX Queue Length**: 1000 packets for improved buffer performance
- **Auto-start**: Enabled via systemd for reliable boot configuration

## 🐛 Troubleshooting

### Common Issues

#### ❌ "Sensor Hub service not starting"
**Cause**: Dependencies or permissions issue
**Solution**:
1. Check serial devices: `ls /dev/serial/by-id/`
2. Check CAN interface: `ip link show can0`
3. Verify python-can: `python3 -c "import can"`
4. Check service logs: `journalctl -u sensor-hub.service -f`
5. Restart service: `sudo systemctl restart sensor-hub`

#### ❌ "GPS not receiving data"
**Cause**: UART configuration or GPS hardware issue
**Solution**:
1. Check UART connection: `cat /dev/serial0` (should show NMEA data)
2. Verify baud rate: 230400 for UM982
3. Check GPS power supply
4. Test with: `python3 -c "import serial; s=serial.Serial('/dev/serial0', 230400); print(s.readline())"`

#### ❌ "IMU not responding"
**Cause**: USB serial device or IMU communication failure
**Solution**:
1. Check device path: `ls /dev/serial/by-id/`
2. Verify the WitMotion symlink exists
3. Confirm configured baudrate is `9600`
4. Check service logs: `journalctl -u sensor-hub.service -n 50`

#### ❌ "CAN messages not received"
**Cause**: CAN interface or hardware issue
**Solution**:
1. Check CAN interface: `ip link show can0`
2. Monitor CAN traffic: `candump can0`
3. Verify bitrate: 500 kbit/s for sensor hub
4. Check CAN termination (120Ω resistors)
5. Test CAN: `cansend can0 123#DEADBEEF`

#### ❌ "Web interface not accessible"
**Cause**: Flask or network issue
**Solution**:
1. Check Flask is running: `ps aux | grep web_app.py`
2. Verify port 80: `sudo netstat -tlnp | grep :80`
3. Check firewall: `sudo ufw status`
4. Test locally: `curl http://localhost:80`
5. Check logs: `tail -f /var/log/ugv_app.log`

### Debug Tools

#### Service Management
```bash
# Check sensor hub status
sudo systemctl status sensor-hub.service

# View live logs
journalctl -u sensor-hub.service -f

# Stop for manual testing
sudo systemctl stop sensor-hub.service
python3 sensor_hub/sensor_hub_app.py

# Restart service
sudo systemctl restart sensor-hub.service
```

#### Hardware Testing
```bash
# Test CAN interface
candump can0

# Test GPS
ls /dev/serial/by-id/

# Test IMU
curl http://127.0.0.1:8080/api/imu/status

# Monitor web app
tail -f /var/log/ugv_app.log
```

## 📈 Performance Characteristics

### System Specifications
- **Sensor Update Rate**: 50 Hz (20ms)
- **GPS Accuracy**: RTK Fixed (cm-level)
- **Heading Accuracy**: Dual-antenna (±1°)
- **IMU Sampling**: 200 Hz (5ms)
- **CAN Bitrate**: 500 kbit/s (Sensor Hub) / 1 Mbps (Motor Control)
- **Memory Usage**: Python runtime (~80MB RAM)

### Communication Latency
- **GPS → CAN Bus**: <50ms
- **IMU → CAN Bus**: <10ms
- **CAN Bus → Web Interface**: <100ms (WebSocket)
- **Web Interface Update**: 20ms (50Hz)

## 🔄 Development History

This project evolved from an Orange Cube-based implementation to the current RTK-GPS + WitMotion sensor hub system:

### Phase 1: ESP32 Prototype (`archive/esp32_files/`)
- Initial CAN implementation attempts
- CAN bus communication challenges
- Multiple timeout and reset issues

### Phase 2: RTK-GPS + WitMotion Sensor Hub (Current)
- Switched to Holybro UM982 dual-antenna RTK-GPS
- Added WitMotion USB-IMU
- Replaced legacy I2C fusion path with native WitMotion orientation frames
- Created web interface with Bing Maps
- Implemented JSON-based CAN protocol for robust communication
- Achieved superior positioning and orientation capabilities

## 🤝 Contributing

### Code Standards
- **Python**: PEP 8 compliance
- **Documentation**: Comprehensive inline comments
- **Testing**: Validate all changes with hardware
- **Git**: Clear commit messages with feature descriptions

### Development Workflow
1. **Test on hardware** - Always validate with real Raspberry Pi and sensors
2. **Use service management** - Stop service before testing new versions
3. **Document changes** - Update README and inline comments
4. **Archive old code** - Remove obsolete files or move them to archive/

## 📞 Support and Resources

### Official Documentation
- **Raspberry Pi Foundation**: https://www.raspberrypi.org/documentation/
- **Holybro UM982**: https://holybro.com/products/um982-rtk-gnss-receiver
- **WitMotion Protocol**: https://wit-motion.gitbook.io/witmotion-sdk/wit-standard-protocol/wit-standard-communication-protocol
- **PiCAN FD**: https://www.skpang.co.uk/products/pican-fd-can-bus-board-for-raspberry-pi
- **pigpio Library**: http://abyz.me.uk/rpi/pigpio/

### Hardware Support
- **Raspberry Pi Zero 2W**: ARM Cortex-A53 Dual-Core
- **Raspberry Pi 3**: ARM Cortex-A53 Quad-Core
- **PiCAN FD**: MCP2515-based CAN interface
- **Holybro UM982**: Dual-antenna RTK-GPS receiver
- **WitMotion USB-IMU**: IMU sensor with native orientation output

### Community
- **Raspberry Pi Community**: https://www.raspberrypi.org/forums/
- **CAN Bus Community**: GitHub discussions and issues
- **RTK-GPS Community**: Holybro and u-blox forums

---

## 🎯 Project Status Summary

**🔄 ACTIVE DEVELOPMENT** - This RTK-GPS + WitMotion autonomous UGV system is under active development with a modular architecture featuring dual-antenna positioning, USB-based sensor ingestion, and real-time web interfaces.

**Key Achievements:**
- ✅ Sensor hub architecture (Pi Zero 2W + PiCAN FD)
- ✅ RTK-GPS + IMU integration
- ✅ JSON-based CAN communication (robust, human-readable)
- ✅ Web interface framework with motor control
- ✅ WitMotion-based IMU telemetry on the sensor hub

**Communication Architecture:**
- **Sensor Hub → Controller**: JSON CAN messages (50Hz sensor data)
- **Controller → Sensor Hub**: JSON CAN commands (status requests, restart)
- **Web Interface**: WebSocket for real-time updates and joystick control
- **Fallback**: CAN bus remains operational even if WiFi fails

**Current Focus:**
- 🗺️ Bing Maps satellite view integration
- 📍 Real-time GPS position tracking
- 🧭 Dual-antenna heading calculation
- 📊 RTK status monitoring
- 🛤️ Trail visualization
- 📐 IMU-based orientation display
- 🎮 Web-based joystick control with CAN enable/disable

The project is actively being developed with focus on autonomous navigation capabilities and robust communication.
