# Motor Controller v2.0

Modularer Motor Controller für Quassel UGV mit Hardware-PWM, CAN-Bus und Web-Interface.

## 🚀 Quick Start

### Installation
```bash
# Dependencies installieren
pip3 install -r requirements.txt

# pigpiod starten
sudo systemctl start pigpiod

# Config erstellen
cp config.yaml.example config.yaml
nano config.yaml
```

### Ausführen
```bash
# Mit Config-Datei
python3 -m motor_controller.main --config config.yaml

# Mit CLI-Args (Legacy)
python3 -m motor_controller.main --pwm --pins 18,19 --web --can can0
```

### Als Service
```bash
# Service installieren
sudo cp ../motor_controller_v2.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable motor-controller-v2.service
sudo systemctl start motor-controller-v2.service

# Status prüfen
sudo systemctl status motor-controller-v2.service

# Logs anzeigen
sudo journalctl -u motor-controller-v2.service -f
```

## 📁 Struktur

```
motor_controller/
├── main.py                  # Entry Point
├── config.py                # Konfiguration
├── hardware/                # Hardware-Layer
│   ├── gpio_controller.py   # GPIO Singleton
│   ├── pwm_controller.py    # PWM (Motoren + Mäher)
│   └── safety_monitor.py    # Watchdog
├── communication/           # CAN-Layer
│   ├── can_handler.py
│   └── can_protocol.py
├── control/                 # Steuerungs-Layer
│   ├── motor_control.py
│   └── joystick_handler.py
└── web/                     # Web-Layer
    └── web_server.py
```

## ⚙️ Konfiguration

Alle Parameter sind in `config.yaml` konfigurierbar:

```yaml
pwm:
  enabled: true
  pins:
    left: 19
    right: 18

web:
  enabled: true
  port: 80

can:
  interface: can0
  bitrate: 1000000

logging:
  level: INFO
  console: true
```

## 🔌 API

### REST Endpoints

- `GET /` - Web-Interface
- `GET /api/status` - System-Status
- `POST /api/can/toggle` - CAN Ein/Aus
- `POST /api/light/toggle` - Licht Ein/Aus
- `POST /api/mower/toggle` - Mäher Ein/Aus
- `POST /api/mower/speed` - Mäher-Geschwindigkeit
- `POST /api/joystick` - Joystick-Input
- `GET /api/sensor/status` - Sensor-Status anfordern
- `POST /api/sensor/restart` - Sensor Hub neu starten

## 🔧 Features

- ✅ Hardware-PWM (GPIO 18/19) via pigpio
- ✅ Mäher-Steuerung (Relay + PWM)
- ✅ Licht-Steuerung (Relay)
- ✅ Sicherheitsschalter (Emergency Stop)
- ✅ Timeout-Watchdog
- ✅ Ramping-System
- ✅ CAN-Bus JSON-Kommunikation
- ✅ Web-Interface mit Joystick
- ✅ Thread-Safe
- ✅ Strukturiertes Logging

## 📝 Logging

```bash
# Console-Logs (wenn console: true)
2024-11-04 12:00:00 - motor_controller.main - INFO - ✅ Alle Komponenten initialisiert

# Systemd-Journal
sudo journalctl -u motor-controller-v2.service -f

# Log-Level ändern (in config.yaml)
logging:
  level: DEBUG  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## 🛠️ Troubleshooting

### pigpio nicht erreichbar
```bash
sudo systemctl start pigpiod
sudo systemctl enable pigpiod
```

### CAN-Interface nicht verfügbar
```bash
sudo ip link set can0 up type can bitrate 1000000
```

### Port 80 bereits belegt
```yaml
# In config.yaml anderen Port verwenden
web:
  port: 8080
```

### Import-Fehler
```bash
# PYTHONPATH setzen
export PYTHONPATH=/home/nicolay:$PYTHONPATH
```

## 🔒 Sicherheit

- Sicherheitsschalter (GPIO 17) löst Emergency Stop aus
- Command-Timeout (2s) stoppt Motoren bei fehlenden Befehlen
- Joystick-Timeout (1s) stoppt Motoren bei Verbindungsabbruch
- Watchdog-Thread überwacht alle Timeouts

## 📊 GPIO-Belegung

| GPIO | Funktion |
|------|----------|
| 18 | Motor rechts (PWM) |
| 19 | Motor links (PWM) |
| 22 | Licht (Relay) |
| 23 | Mäher (Relay) |
| 12 | Mäher (PWM) |
| 17 | Sicherheitsschalter |

## 🌐 Web-Interface

```bash
# Zugriff über Browser
http://raspberrycan/

# API-Status
curl http://raspberrycan/api/status
```

