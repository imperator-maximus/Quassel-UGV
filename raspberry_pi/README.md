# 🚀 Quassel UGV - Sensor Hub & Motor Controller v2.0

**RTK-GPS + USB-IMU telemetry with real-time web interface for autonomous UGV**

> **Produktionsstand 24.07.2026:** SensorHub-Pose ueber zwei parallele
> HTTP/WiFi-Streams; beide ODrive-Boards ueber zwei direkte USB/Fibre-Kabel.
> CAN ist auf Haupt-UGV und SensorHub deaktiviert. Weiter unten enthaltene
> CAN-Anweisungen sind ausschliesslich historische Teststand-Dokumentation.

## 🎯 Project Overview

**Goal:** Implement autonomous UGV with RTK-GPS positioning, IMU orientation, and real-time web interface.

**Hardware:**
- **Sensor Hub**: Orange Pi Zero 2W, ohne aktiven CAN-Adapter
  - Holybro UM982 (Dual-antenna RTK-GPS, USB)
  - WitMotion USB-IMU (USB)
- **Motor Controller**: Raspberry Pi 3 + zwei direkte ODrive-USB-Verbindungen
  - Motor control (2-channel Hardware-PWM via pigpio)
  - Mower control (Relay + PWM speed control)
  - Light control (Relay)
  - Safety switch (Emergency stop)
  - Web interface with virtual joystick

**Communication:**
- SensorHub → Raspberry: zwei persistente HTTP/WiFi-NDJSON-Streams
- Raspberry → ODrives: direkte USB/Fibre-Verbindungen nach Seriennummer/Achse
- CAN: nur ehemaliger Offline-Teststand, Classical CAN 2.0 bei 250 kbit/s
- IMU/GPS telemetry updates
- WebSocket: Real-time web interface

## 📁 Architektur

```
motor_controller/
├── __init__.py              # Package-Initialisierung
├── main.py                  # Entry Point
├── config.py                # Konfigurationsverwaltung
├── config.yaml.example      # Beispiel-Konfiguration
├── hardware/
│   ├── __init__.py
│   ├── gpio_controller.py   # GPIO-Verwaltung (Singleton)
│   ├── pwm_controller.py    # PWM-Steuerung (Motoren + Mäher)
│   └── safety_monitor.py    # Sicherheitsüberwachung + Watchdog
├── communication/
│   ├── __init__.py
│   ├── can_handler.py       # CAN-Bus-Kommunikation
│   └── can_protocol.py      # Multi-Frame JSON-Protokoll
├── control/
│   ├── __init__.py
│   ├── motor_control.py     # Motor-Logik (Skid Steering + Ramping)
│   └── joystick_handler.py  # Joystick-Verarbeitung
└── web/
    ├── __init__.py
    └── web_server.py         # Flask Web-Interface
```

## 🚀 Quick Setup

### 1. Sensor Hub Setup (Pi Zero 2W)
```bash
# Follow the current Orange Pi deploy guide
cd ../sensor_hub
less DEPLOY_ORANGE_PI.md
```

### 2. Motor Controller Setup (Pi 3) - v2.0

#### **Installation**
```bash
# Dependencies installieren
pip3 install pyyaml python-can RPi.GPIO pigpio Flask

# pigpiod aktivieren
sudo systemctl enable pigpiod
sudo systemctl start pigpiod

# Verzeichnis erstellen
mkdir -p /home/nicolay/motor_controller

# Dateien kopieren (aus Repository)
cp -r raspberry_pi/motor_controller/* /home/nicolay/motor_controller/
```

#### **Konfiguration**
```bash
# Beispiel-Config kopieren
cp /home/nicolay/motor_controller/config.yaml.example \
   /home/nicolay/motor_controller/config.yaml

# Config anpassen
nano /home/nicolay/motor_controller/config.yaml
```

#### **Manueller Test**
```bash
cd /home/nicolay/motor_controller
python3 -m motor_controller.main --config config.yaml

# Oder mit Legacy CLI-Args
python3 -m motor_controller.main --pwm --pins 18,19 --web --can can0
```

#### **Systemd-Service**
```bash
# Service installieren
sudo cp motor_controller_v2.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable motor-controller-v2.service
sudo systemctl start motor-controller-v2.service

# Status prüfen
sudo systemctl status motor-controller-v2.service

# Logs anzeigen
sudo journalctl -u motor-controller-v2.service -f
```

#### **Web-Interface**
```bash
# Zugriff über Browser
http://raspberrycan/

# API-Status
curl http://raspberrycan/api/status
```

### 3. Produktive Hardware-Verbindungen

- SensorHub und Hauptrechner kommunizieren ueber WLAN; kein CAN-Kabel.
- ODrive Board A und B sind jeweils direkt per USB mit dem Raspberry verbunden.
- Die alten CAN-Klemmen und der USB-CAN-Adapter gehoeren nicht zum Produktivpfad.

## 🔧 Hardware Configuration

## Historische CAN-Referenz (Offline-Teststand, nicht am UGV anwenden)

### Historische Main-controller USB-CAN Details (nicht produktiv)
- **Driver:** `gs_usb`
- **Protocol:** Classical CAN 2.0 (maximum 8 data bytes per frame)
- **SocketCAN interface:** `can0`
- **Bitrate:** 250 kbit/s
- **Termination:** disabled at the central Raspberry Pi participant

### Sensor Hub (Orange Pi Zero 2W) Boot Configuration
```bash
# Current production sensor hub:
# - Orange Pi Zero 2W
# - kein USB-CAN-Adapter im Produktionsbetrieb
# - HTTP/WiFi-Telemetrie ueber Port 80/extern 8081
# - Holybro UM982 via USB serial
# - WitMotion via USB serial
#
# See ../sensor_hub/DEPLOY_ORANGE_PI.md for the tested setup.
```

### Controller (Pi 3) Boot Configuration
```bash
# /boot/firmware/config.txt
# No MCP2515 CAN overlay. The USB adapter is detected by gs_usb.
```

The retired InnoMaker HAT and its `mcp2515-can*` Device Tree overlay are no
longer used. SPI may remain enabled for unrelated peripherals.

### Former UGV Test Stand and ODrive

- The now-offline UGV test Raspberry Pi also uses a **USB-CAN adapter**.
- `ugvtestpi-usbcan0.service` configures its `can0` for **250 kbit/s**.
- The ODrive/ODESC units provide their own **integrated Classical CAN 2.0**
  interfaces and communicate via SimpleCAN.
- Every participant on one physical CAN bus must use the same bitrate.

### Sensor Configuration
**GPS (Holybro UM982):**
- UART: /dev/serial0
- Baud Rate: 230400
- Output: NMEA sentences

**IMU (WitMotion USB):**
- Port: `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`
- Baudrate: 9600
- Sampling Rate: 200 Hz

## 📁 Project Files

```
raspberry_pi/
├── motor_controller/              # Current Raspberry Pi 3 controller
├── web_app.py                     # Web interface (Pi 3)
├── setup_sensor_hub.sh            # Older Raspberry Pi sensor hub setup script
├── install_web_dependencies.sh    # Web interface setup
├── templates/index.html           # Web interface template
├── README.md                      # This documentation
└── sensor-hub.service             # Historical Raspberry Pi service example
```

## 🧪 Testing & Validation

### 1. Sensor Hub Validation
```bash
# Check WitMotion USB device
ls /dev/serial/by-id/
# Expected: usb-1a86_USB_Serial-if00-port0

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
# Check USB serial devices
ls /dev/serial/by-id/
# Should show usb-1a86_USB_Serial-if00-port0

# Check live IMU status from the sensor hub
curl http://127.0.0.1:8080/api/imu/status
```

### CAN Messages Not Received
```bash
# Check CAN interface
ip link show can0

# Monitor CAN traffic
candump can0

# Verify bitrate: 250 kbit/s on the production bus
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
- **CAN Protocol**: Classical CAN 2.0; CAN FD is not used
- **CAN Bitrate**: unified 250 kbit/s on all bus participants
- **Memory Usage**: Python runtime (~80MB RAM)

### Communication Latency
- **GPS → CAN Bus**: <50ms
- **IMU → CAN Bus**: <10ms
- **CAN Bus → Web Interface**: <100ms (WebSocket)
- **Web Interface Update**: 20ms (50Hz)

## 🎉 Success Criteria

### Hardware Setup Complete
- ✅ USB-CAN adapter detected by `gs_usb`
- ✅ Legacy MCP2515 Device Tree overlay disabled
- ✅ Legacy test stand: CAN interface `can0` UP and ready
- ✅ WitMotion USB device detected
- ✅ UART GPS receiving NMEA data

### Sensor Hub Telemetry Working
- ✅ GPS position updates at 50 Hz
- ✅ IMU orientation data available
- ✅ Legacy test stand: CAN messages visible in `candump`
- ✅ Web interface displays real-time data

## 🚀 Ready for Production

Once setup is complete, the system provides:
- **Precise RTK-GPS positioning** (cm-level accuracy)
- **Dual-antenna heading** without compass
- **6-DoF orientation** from WitMotion IMU
- **Real-time web interface** with Bing Maps
- **Autonomous navigation** capabilities
