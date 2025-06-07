# 🚀 Raspberry Pi DroneCAN with Innomaker RS485 CAN HAT

**Complete setup for DroneCAN communication between Raspberry Pi and Orange Cube flight controller**

## 🎯 Project Overview

**Goal:** Replace Beyond Robotics Dev Board with Raspberry Pi 3 for reliable DroneCAN communication.

**Hardware:**
- Raspberry Pi 3 (headless)
- **Innomaker RS485 CAN HAT** (dual-chip: RS485 + CAN)
- Orange Cube flight controller
- ESP32 DroneBridge for WiFi

**Communication:**
- DroneCAN 1.0 protocol at 1 Mbps
- Bidirectional: ESC commands ← Orange Cube → Battery status
- Skid steering configuration (2 motors)

## 🚀 Quick Setup

### 1. Complete Hardware + Software Setup
```bash
# Run the complete setup script
sudo ./setup_innomaker_can.sh

# This will:
# - Install all required packages (can-utils, python3-can, pymavlink, dronecan)
# - Configure Innomaker CAN HAT hardware in boot config
# - Setup CAN interface at 1 Mbps
# - Reboot if needed for hardware activation
```

### 2. Test CAN Communication
```bash
# Monitor CAN traffic from Orange Cube
candump can0

# Start DroneCAN monitor
sudo python3 can_monitor.py
```

### 3. Hardware Connection
Connect Orange Cube CAN port to Innomaker HAT CAN0:
- **CAN_H** ↔ **CAN_H**
- **CAN_L** ↔ **CAN_L**  
- **GND** ↔ **GND** (optional)

## 🔧 Hardware Configuration

### Innomaker RS485 CAN HAT Details
- **Dual-chip design:** SC16IS752 (RS485) + MCP2515 (CAN)
- **SPI mapping:** RS485 on spi0.0 (CS0), CAN on spi0.1 (CS1)
- **16MHz oscillator** for MCP2515
- **GPIO25** for CAN interrupt
- **No SPI conflicts** due to separate chip-select pins

### Boot Configuration (`/boot/firmware/config.txt`)
```bash
# --- Innomaker RS485 CAN HAT Configuration ---
dtparam=spi=on
dtoverlay=sc16is752-spi0,int_pin=24                    # RS485 on spi0.0
dtoverlay=mcp2515-can1,oscillator=16000000,interrupt=25 # CAN on spi0.1
```

### Orange Cube Settings
```
CAN_P1_BITRATE=1000000    # 1 Mbps
CAN_D1_PROTOCOL=1         # DroneCAN
CAN_D1_UC_NODE=10         # Node ID
CAN_D1_UC_ESC_BM=3        # ESC bitmap (2 motors)
SERVO_BLH_MASK=3          # BLHeli ESC mask
SERVO_BLH_AUTO=1          # Auto ESC detection
```

## 📁 Project Files

```
raspberry_pi/
├── setup_innomaker_can.sh         # 🔧 Complete setup script
├── can_monitor.py                  # 📡 DroneCAN communication
├── dronecan_esc_controller.py      # 🎮 ESC Controller + PWM + Web Interface
├── install_web_dependencies.sh    # 🌐 Web Interface setup
├── templates/index.html            # 📱 Smartphone Web Interface
├── test-can-detailed              # 🧪 CAN testing utility
├── README.md                       # 📚 This documentation
└── README_Web_Interface.md         # 🌐 Web Interface documentation
```

## 🧪 Testing & Validation

### 1. Hardware Validation
```bash
# Check CAN hardware initialization
dmesg | grep -i mcp
# Expected: "mcp251x spi0.1 can0: MCP2515 successfully initialized"

# Check CAN interface status
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

### 3. DroneCAN Communication
```bash
# Start DroneCAN monitor (shows Orange Cube messages)
sudo python3 can_monitor.py

# Expected output:
# ✅ CAN interface can0 configured at 1000000 bps
# 📡 DroneCAN Node 42 started
# 📨 Received ESC command: [motor1, motor2]
# 📤 Sent battery status: 12.6V, 85%
```

### 4. ESC Controller with PWM Output
```bash
# Start ESC controller with PWM output to motors
python3 dronecan_esc_controller.py --pwm

# With Web Interface for smartphone control
python3 dronecan_esc_controller.py --pwm --web

# Access Web Interface: http://raspberrycan:5000
```

### 4. Comprehensive Testing
```bash
# Run detailed CAN tests
sudo ./test-can-detailed

# Tests interface, hardware, and communication
```

## 🔍 Troubleshooting

### Common Success Indicators
- ✅ `dmesg | grep mcp` shows "successfully initialized"
- ✅ `ip link show can0` shows interface UP
- ✅ `candump can0` shows Orange Cube messages
- ✅ No "chipselect already in use" errors

### Hardware Issues
```bash
# Check MCP2515 initialization
dmesg | grep -i mcp

# Common error messages and solutions:
# "MCP251x didn't enter in conf mode" → Wrong oscillator (try 8MHz, 12MHz)
# "chipselect already in use" → SPI conflict (fixed by using separate CS pins)
# "Probe failed, err=110" → Hardware communication issue
```

### No CAN Messages from Orange Cube
1. **Check Orange Cube CAN configuration** (bitrate, protocol, node ID)
2. **Verify physical connections** (CAN_H, CAN_L, GND)
3. **Ensure matching bitrates** (1 Mbps both sides)
4. **Check termination** (Orange Cube has built-in 120Ω)

### Permission Issues
```bash
# Add user to dialout group
sudo usermod -a -G dialout $USER
logout  # Re-login required

# Or run with sudo
sudo python3 can_monitor.py
```

## 🌐 Web Interface (Smartphone Control)

### Features
- **CAN Ein/Aus (Not-Aus)**: Sofortiges Stoppen aller Motoren via Smartphone
- **Status-Monitor**: Echtzeit PWM-Werte und System-Status
- **Responsive Design**: Optimiert für Smartphone hochkant
- **Thread-sichere Architektur**: Keine Performance-Beeinträchtigung

### Installation & Start
```bash
# Dependencies installieren
./install_web_dependencies.sh

# ESC Controller mit Web-Interface starten
python3 dronecan_esc_controller.py --pwm --web

# Zugriff via Smartphone Browser
# http://raspberrycan:5000
```

### Geplante Features (Phase 2+)
- **Virtueller Joystick**: Touch-Steuerung für Fahrbewegungen
- **Lampe Ein/Aus**: Beleuchtungssteuerung
- **Mähen Ein/Aus**: Mähwerk-Steuerung

📚 **Detaillierte Dokumentation**: [README_Web_Interface.md](README_Web_Interface.md)

## 🌐 WiFi Integration

### ESP32 DroneBridge Configuration
- **IP Address:** 192.168.178.134
- **MAVLink Ports:** 14550 (Host), 14555 (Client)
- **Baudrate:** 57600

### File Upload to Orange Cube
```bash
# Using MAVProxy FTP (recommended - reliable)
mavproxy.py --master=udp:192.168.178.134:14550
ftp put script.lua /APM/scripts/

# Using pymavlink MAVFTP (faster but less reliable)
python3 upload_script.py script.lua
```

## 🎉 Success Criteria

### Hardware Setup Complete
- ✅ Innomaker CAN HAT properly configured in boot config
- ✅ MCP2515 successfully initialized on spi0.1
- ✅ CAN interface can0 UP and ready at 1 Mbps
- ✅ No SPI conflicts between RS485 and CAN chips

### DroneCAN Communication Working
- ✅ Orange Cube sends ESC commands via DroneCAN
- ✅ Raspberry Pi receives and processes commands
- ✅ Raspberry Pi sends battery status back to Orange Cube
- ✅ Bidirectional communication established

## 📚 Technical Notes

### Why Innomaker HAT Works
The Innomaker RS485 CAN HAT solves the SPI conflict issue that plagued other CAN HATs:

- **Dual-chip design** with separate functions
- **Separate CS pins:** RS485 on CS0 (spi0.0), CAN on CS1 (spi0.1)
- **16MHz oscillator** matches MCP2515 requirements
- **Proper interrupt handling** on GPIO25
- **No hardware conflicts** between RS485 and CAN

### Migration Benefits from Beyond Robotics
- **Hardware reliability:** No 3.3V access or pin conflict issues
- **Software stability:** No watchdog/timer configuration problems
- **Better debugging:** Full Linux environment with standard tools
- **Cost effective:** Uses standard Raspberry Pi ecosystem
- **Community support:** Well-documented hardware and software

## 🚀 Ready for Production

Once setup is complete, the system provides:
- **Reliable DroneCAN communication** with Orange Cube
- **Bidirectional data exchange** (commands ↔ telemetry)
- **Robust hardware platform** for autonomous vehicle control
- **Easy maintenance and updates** via SSH and WiFi
