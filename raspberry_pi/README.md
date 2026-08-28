# 🚀 Quassel UGV - Sensor Hub & Motor Controller v2.0

**RTK-GPS + USB-IMU telemetry with real-time web interface for autonomous UGV**

> **Produktionsstand 24.07.2026:** SensorHub-Pose ueber zwei parallele
> HTTP/WiFi-Streams; beide ODrive-Boards ueber zwei direkte USB/Fibre-Kabel.
> CAN-Bus und SensorHub sind ausgebaut, ihr Code ist entfernt.

## 🎯 Project Overview

**Goal:** Implement autonomous UGV with RTK-GPS positioning, IMU orientation, and real-time web interface.

**Hardware:**
- **GNSS**: Holybro UM982 per USB seriell am Raspberry
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
- GNSS → Raspberry: USB seriell; RTK-Korrekturen per NTRIP
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
│   ├── pose_cache.py        # Zwischenspeicher der GNSS-Pose
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
pip3 install pyyaml pyserial RPi.GPIO pigpio Flask

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
python3 -m motor_controller.main --pwm --pins 18,19 --web
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

- Der GNSS-Empfaenger haengt per USB am Raspberry; kein Bus, kein zweiter Rechner.
- ODrive Board A und B sind jeweils direkt per USB mit dem Raspberry verbunden.
- CAN-Klemmen, USB-CAN-Adapter und CAN HAT sind ausgebaut.

## 🔧 Hardware Configuration

### Sensor Hub (Orange Pi Zero 2W) Boot Configuration
```bash
# Der separate SensorHub ist ausgebaut. Der GNSS-Empfaenger haengt
# direkt am Raspberry; der Port steht in config.yaml unter pose.gps_port.
```

### Controller (Pi 3) Boot Configuration
```bash
# /boot/firmware/config.txt
# Kein MCP2515-CAN-Overlay noetig.
```

The retired InnoMaker HAT and its `mcp2515-can*` Device Tree overlay are no
longer used. SPI may remain enabled for unrelated peripherals.

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

```

### 2. Sensor Hub Service
```bash
# Start sensor hub service
sudo systemctl start sensor-hub

# Check status
sudo systemctl status sensor-hub

# View logs
journalctl -u sensor-hub -f
```

### 3. Web Interface
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
- **Memory Usage**: Python runtime (~80MB RAM)

### Communication Latency
- **Pose → Web Interface**: <100ms (WebSocket)
- **Web Interface Update**: 20ms (50Hz)

## 🎉 Success Criteria

### Hardware Setup Complete
- ✅ WitMotion USB device detected
- ✅ UART GPS receiving NMEA data

### Sensor Hub Telemetry Working
- ✅ GPS position updates at 50 Hz
- ✅ IMU orientation data available
- ✅ Web interface displays real-time data

## 🚀 Ready for Production

Once setup is complete, the system provides:
- **Precise RTK-GPS positioning** (cm-level accuracy)
- **Dual-antenna heading** without compass
- **6-DoF orientation** from WitMotion IMU
- **Real-time web interface** with Bing Maps
- **Autonomous navigation** capabilities
