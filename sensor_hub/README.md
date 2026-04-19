# 👑 Quassel UGV - Sensor Hub 👑

RTK-GPS + optional IMU + CAN-Telemetrie für den **Orange Pi Zero 2W (DietPi)**.

> Der aktuelle produktive Deploy-Stand steht in **`DEPLOY_ORANGE_PI.md`**.

## 🎯 Features

- **Holybro UM982 RTK-GPS** - Dual-Antenna Positionierung und Heading
- **NTRIP/RTK Client** - Automatische Verbindung zu RTK-Korrekturdaten
- **NMEA-Parser** - Vollständige GPS-Datenverarbeitung
- **RTK-Status Anzeige** - NO GPS / GPS FIX / RTK FLOAT / RTK FIXED
- **Web-Interface** - Einfache HTML5 Oberfläche mit Live-Updates
- **Bing Maps Integration** - Direkter Link zu aktuellen Koordinaten
- **GPS-NTRIP Bridge** - Automatisches Routing von RTK-Daten zum GPS
- **Modular aufgebaut** - Einfach erweiterbar für IMU und CAN

## 📋 Voraussetzungen

### Hardware
- Orange Pi Zero 2W
- CANable2 per USB (`can0` via `slcand`)
- Holybro UM982 RTK-GPS per USB (`/dev/serial/by-id/...`)
- optionale IMU (aktuell deaktiviert)
- stabile 5V-Versorgung

### Software
Siehe **`DEPLOY_ORANGE_PI.md`** für die tatsächlich getesteten Pakete und Deploy-Schritte.

## 🚀 Installation

### 1. Dateien auf Orange Pi kopieren
```bash
scp -r sensor_hub/ nicolay@orangeugv:/home/nicolay/
```

### 2. Dependencies und Service

Die aktuelle, getestete Anleitung steht in **`DEPLOY_ORANGE_PI.md`**.

### 3. ⚠️ WICHTIG: RTK/NTRIP separat aktivieren

**NIEMALS Passwörter in config.py speichern!**

Für den aktuellen Orange-Deploy ist **GPS aktiv**, aber **NTRIP/RTK im Service vorerst deaktiviert**.

Wenn du RTK aktivieren willst, erstelle eine `.env` Datei mit deinen NTRIP-Credentials:

```bash
ssh nicolay@orangeugv
cd /home/nicolay/sensor_hub
cp .env.example .env
nano .env
```

Fülle deine Credentials ein:
```bash
NTRIP_HOST=openrtk-mv.de
NTRIP_PORT=2101
NTRIP_MOUNTPOINT=openrtk_mv_2G
NTRIP_USERNAME=your_username
NTRIP_PASSWORD=your_password
```

**Wichtig:**
- `.env` wird NICHT in Git committed (siehe `.gitignore`)
- Jeder Entwickler hat seine eigene `.env` Datei
- Verwende `.env.example` als Template

### 4. Anwendung starten
```bash
cd /home/nicolay/sensor_hub
python3 sensor_hub_app.py
```

## 🌐 Web-Interface

Öffne im Browser:
```
http://raspberryzero:8080

# oder aktuell
http://orangeugv:8080
```

### Anzeige
- **GPS Status** - RTK Status, Satelliten, Höhe, Heading
- **Verbindung** - GPS Online/Offline, letzte Aktualisierung
- **Koordinaten** - Latitude, Longitude mit Bing Maps Link

## 🔧 Konfiguration

### config.py

```python
# GPS
GPS_PORT = '/dev/serial/by-id/usb-FTDI_FT231X_USB_UART_*'
GPS_BAUDRATE = 230400              # UM982 Baud Rate
GPS_TIMEOUT = 5.0                  # Timeout

# Web
WEB_HOST = '0.0.0.0'               # Listen auf allen Interfaces
WEB_PORT = 8080                    # Web-Port
WEB_UPDATE_RATE = 2                # Updates pro Sekunde

# NTRIP/RTK
NTRIP_ENABLED = True               # NTRIP aktivieren
NTRIP_HOST = 'your-ntrip-server.com'  # NTRIP Server Host
NTRIP_PORT = 2101                  # NTRIP Server Port
NTRIP_MOUNTPOINT = 'MOUNTPOINT'    # NTRIP Mountpoint
NTRIP_USERNAME = 'your_username'   # NTRIP Benutzername (siehe .env)
NTRIP_PASSWORD = 'your_password'   # NTRIP Passwort (siehe .env)
NTRIP_TIMEOUT = 10.0               # Verbindungs-Timeout
NTRIP_RECONNECT_INTERVAL = 30.0    # Reconnect nach X Sekunden
```

**⚠️ WICHTIG: Credentials in `.env` Datei speichern!**

Erstelle eine `.env` Datei im `sensor_hub/` Verzeichnis:
```bash
# sensor_hub/.env
NTRIP_HOST=openrtk-mv.de
NTRIP_PORT=2101
NTRIP_MOUNTPOINT=openrtk_mv_2G
NTRIP_USERNAME=your_username
NTRIP_PASSWORD=your_password
```

Dann in `config.py` laden:
```python
from dotenv import load_dotenv
import os

load_dotenv()

NTRIP_HOST = os.getenv('NTRIP_HOST', 'your-ntrip-server.com')
NTRIP_USERNAME = os.getenv('NTRIP_USERNAME', 'your_username')
NTRIP_PASSWORD = os.getenv('NTRIP_PASSWORD', 'your_password')
```

## 📡 GPS-Datenformat

### NMEA-Sätze (unterstützt)
- **GGA** - Position, Höhe, Fix-Qualität
- **RMC** - Position, Heading, Datum
- **GSA** - Satelliten-Info
- **HDT** - Heading True

### RTK-Status
- `NO GPS` - Kein GPS-Signal
- `GPS FIX` - Standard GPS (1-2m Genauigkeit)
- `DGPS` - Differential GPS
- `RTK FLOAT` - RTK mit Float-Lösung (10-20cm)
- `RTK FIXED` - RTK mit Fixed-Lösung (2-5cm)

## 🧪 Testen

### GPS-Verbindung testen
```bash
ssh nicolay@orangeugv
curl http://127.0.0.1:8080/api/status
```

Sollte NMEA-Sätze anzeigen:
```
$GPRMC,123519,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A
$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47
```

### Web-Interface testen
```bash
curl http://orangeugv:8080/api/health
curl http://orangeugv:8080/api/status
```

### Logs anschauen
```bash
ssh nicolay@raspberryzero
cd /home/nicolay/sensor_hub
python3 sensor_hub_app.py
```

## 📁 Projektstruktur

```
sensor_hub/
├── config.py                    # Konfiguration
├── gps_handler.py              # GPS-Handler (NMEA-Parser)
├── sensor_hub_app.py           # Hauptanwendung (Flask)
├── templates/
│   └── sensor_hub.html         # Web-Interface
└── README.md                   # Diese Datei
```

## 🌐 REST API Endpoints

### GPS Status
```bash
curl http://raspberryzero:8080/api/status
```
Gibt: Latitude, Longitude, Altitude, Heading, RTK-Status, Satelliten

### Koordinaten
```bash
curl http://raspberryzero:8080/api/coordinates
```
Gibt: Lat/Lon mit Bing Maps URL

### NTRIP Status
```bash
curl http://raspberryzero:8080/api/ntrip/status
```
Gibt: NTRIP Verbindungsstatus, Bytes empfangen, Mountpoint

### Bridge Status
```bash
curl http://raspberryzero:8080/api/bridge/status
```
Gibt: GPS + NTRIP Status, RTK-Uptime, RTK-Fix-Zähler

### Health Check
```bash
curl http://raspberryzero:8080/api/health
```
Gibt: Allgemeiner System-Status

## 🔄 Nächste Schritte

- [x] Orange-Pi-Deploy mit USB-CAN ✅
- [x] GPS via USB/by-id ✅
- [x] CAN JSON-Transport bidirektional ✅
- [ ] RTK/NTRIP wieder aktivieren
- [ ] USB-IMU integrieren

## 🐛 Troubleshooting

### GPS zeigt "NO GPS"
1. Überprüfe GPS-Verbindung: `cat /dev/serial0`
2. Überprüfe Baud Rate: 230400 für UM982
3. Überprüfe GPS-Stromversorgung
4. Warte 30-60 Sekunden für GPS-Lock

### Web-Interface nicht erreichbar
1. Überprüfe Port: `sudo netstat -tlnp | grep 8080`
2. Überprüfe Firewall
3. Teste lokal: `curl http://localhost:8080`

### Koordinaten sind 0.0
1. Warte auf GPS-Lock (RTK FIXED)
2. Überprüfe NMEA-Daten: `cat /dev/serial0`
3. Überprüfe GPS-Antenne und Stromversorgung

## 📞 Support

Bei Fragen oder Problemen:
1. Überprüfe die Logs
2. Teste GPS-Verbindung manuell
3. Überprüfe Konfiguration in config.py

