# 🚀 Quassel UGV - Sensor Hub & Controller

**RTK-GPS + IMU sensor fusion with real-time web interface for autonomous UGV**

## 🎯 Project Overview

**Goal:** Implement autonomous UGV with RTK-GPS positioning, IMU orientation, and real-time web interface.

**Hardware:**
- **Sensor Hub**: Raspberry Pi Zero 2W + PiCAN FD
  - Holybro UM982 (Dual-antenna RTK-GPS)
  - ICM-42688-P (6-DoF IMU)
- **Controller**: Raspberry Pi 3 + PiCAN FD
  - Motor control (2-channel PWM)
  - Web interface (Bing Maps)

**Communication:**
- CAN Bus: 500 kbit/s (Sensor Hub) / 1 Mbps (Motor Control)
- Sensor Fusion: 50 Hz updates
- WebSocket: Real-time web interface

## 🚀 Quick Setup

### 1. Sensor Hub Setup (Pi Zero 2W)
```bash
# Run the complete setup script
sudo ./setup_sensor_hub.sh

# This will:
# - Install all required packages (python3-can, pyserial, smbus2)
# - Configure PiCAN FD hardware in boot config
# - Setup I2C and UART for sensors
# - Configure CAN interface at 500 kbit/s
# - Reboot if needed for hardware activation
```

### 2. Controller Setup (Pi 3)
```bash
# Install web interface dependencies
./install_web_dependencies.sh

# Start web interface
python3 web_app.py

# Access at http://raspberrycan:80
```

### 3. Hardware Connection
Connect Sensor Hub to Controller via CAN Bus:
- **CAN_H** ↔ **CAN_H**
- **CAN_L** ↔ **CAN_L**
- **GND** ↔ **GND** (common ground)

## 🔧 Hardware Configuration

### PiCAN FD Details
- **CAN Controller:** MCP2515
- **16MHz oscillator** for stable CAN timing
- **GPIO25** for CAN interrupt
- **SPI Interface:** spi0.1 (CS1)

### Sensor Hub (Pi Zero 2W) Boot Configuration
```bash
# /boot/firmware/config.txt
dtparam=spi=on
dtparam=i2c_arm=on
dtparam=uart0=on
dtoverlay=mcp2515-can1,oscillator=16000000,interrupt=25

# UART for GPS (UM982)
enable_uart=1
```

### Controller (Pi 3) Boot Configuration
```bash
# /boot/firmware/config.txt
dtparam=spi=on
dtoverlay=mcp2515-can1,oscillator=16000000,interrupt=25
```

### Sensor Configuration
**GPS (Holybro UM982):**
- UART: /dev/serial0
- Baud Rate: 230400
- Output: NMEA sentences

**IMU (ICM-42688-P):**
- I2C Address: 0x68
- I2C Bus: 1
- Sampling Rate: 200 Hz

## 📁 Project Files

```
raspberry_pi/
├── sensor_hub.py                  # Sensor fusion (Pi Zero 2W)
├── web_app.py                     # Web interface (Pi 3)
├── setup_sensor_hub.sh            # Sensor hub setup script
├── install_web_dependencies.sh    # Web interface setup
├── templates/index.html           # Web interface template
├── README.md                       # This documentation
└── sensor-hub.service             # systemd service file
```

## 🧪 Testing & Validation

### 1. Sensor Hub Validation
```bash
# Check I2C devices
i2cdetect -y 1
# Expected: IMU at 0x68

# Check UART GPS
cat /dev/serial0
# Expected: NMEA sentences from UM982

# Check CAN interface
ip link show can0
# Expected: "can0: <NOARP,UP,LOWER_UP,ECHO> mtu 16 ... state UP"
```

### 2. Basic CAN Communication
```bash
# Monitor raw CAN traffic
candump can0

# Send test message
cansend can0 123#DEADBEEF
```

### 3. Sensor Hub Service
```bash
# Start sensor hub service
sudo systemctl start sensor-hub

# Check status
sudo systemctl status sensor-hub

# View logs
journalctl -u sensor-hub -f
```

### 4. Web Interface
```bash
# Start web interface
python3 web_app.py

# Access at http://raspberrycan:80
```

## 🔍 Troubleshooting

### GPS Not Receiving Data
```bash
# Check UART connection
cat /dev/serial0

# Verify baud rate: 230400 for UM982
python3 -c "import serial; s=serial.Serial('/dev/serial0', 230400); print(s.readline())"
```

### IMU Not Responding
```bash
# Check I2C address
i2cdetect -y 1
# Should show 0x68

# Test I2C communication
python3 -c "import smbus2; bus=smbus2.SMBus(1); print(bus.read_byte_data(0x68, 0x75))"
```

### CAN Messages Not Received
```bash
# Check CAN interface
ip link show can0

# Monitor CAN traffic
candump can0

# Verify bitrate: 500 kbit/s for sensor hub
```

### Web Interface Not Accessible
```bash
# Check Flask is running
ps aux | grep web_app.py

# Verify port 80
sudo netstat -tlnp | grep :80

# Test locally
curl http://localhost:80
```

## 📈 Performance Characteristics

### System Specifications
- **Sensor Update Rate**: 50 Hz (20ms)
- **GPS Accuracy**: RTK Fixed (cm-level)
- **Heading Accuracy**: Dual-antenna (±1°)
- **IMU Sampling**: 200 Hz (5ms)
- **CAN Bitrate**: 500 kbit/s (Sensor Hub)
- **Memory Usage**: Python runtime (~80MB RAM)

### Communication Latency
- **GPS → CAN Bus**: <50ms
- **IMU → CAN Bus**: <10ms
- **CAN Bus → Web Interface**: <100ms (WebSocket)
- **Web Interface Update**: 20ms (50Hz)

## 🎉 Success Criteria

### Hardware Setup Complete
- ✅ PiCAN FD properly configured in boot config
- ✅ MCP2515 successfully initialized on spi0.1
- ✅ CAN interface can0 UP and ready
- ✅ I2C devices detected (IMU at 0x68)
- ✅ UART GPS receiving NMEA data

### Sensor Fusion Working
- ✅ GPS position updates at 50 Hz
- ✅ IMU orientation data available
- ✅ CAN messages broadcast to controller
- ✅ Web interface displays real-time data

## 🚀 Ready for Production

Once setup is complete, the system provides:
- **Precise RTK-GPS positioning** (cm-level accuracy)
- **Dual-antenna heading** without compass
- **6-DoF orientation** from IMU
- **Real-time web interface** with Bing Maps
- **Autonomous navigation** capabilities

