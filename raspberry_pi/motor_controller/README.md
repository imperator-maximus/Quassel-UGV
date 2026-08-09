# Motor Controller v2.0

Modularer Motor Controller für Quassel UGV mit Hardware-PWM, ODrive-USB,
legacy CAN und Web-Interface.

## Aktuelle ODrive- und SensorHub-Anbindung

- Der Haupt-UGV-Rechner nutzt **zwei direkte USB/Fibre-Verbindungen** zu den
  beiden ODrive-Boards. Node 0/1 liegen auf Board A, Node 2 auf Board B.
- Die SensorHub-Pose kommt im Produktionsprofil per HTTP/WiFi.
- Der Client nutzt zwei parallele persistente NDJSON-Streams; der konfigurierte
  Basis-Endpunkt `/api/telemetry` wird intern zu `/api/telemetry/stream` erweitert.
- Der CAN-Dienst des Haupt-UGV ist deaktiviert; der CAN-Code bleibt nur fuer
  Legacy-/Testprofile erhalten und ist kein automatischer Rueckfall.
- Der ehemalige, inzwischen offline geschaltete UGV-Teststand nutzt einen **USB-CAN-Adapter** als `can0`.
- Die ODrive/ODESC-Motorcontroller besitzen jeweils eine **integrierte CAN-Schnittstelle** und sprechen SimpleCAN.
- Alle Teilnehmer verwenden **Classical CAN 2.0** mit maximal 8 Datenbytes pro Frame; CAN FD wird nicht verwendet.
- Legacy-CAN-Profile verwenden einheitlich **250 kbit/s**.
- `odrive_mower.transport` ist in Produktion `usb`; `can` ist nur ein explizites Legacy-/Testprofil.

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
├── communication/           # HTTP/WiFi- und Legacy-CAN-Transporte
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
  bitrate: 250000

sensor_hub:
  transport: wifi
  wifi_url: http://schloss.fdog.de:8081/api/telemetry
  auth_username: ugv          # Passwort: SENSOR_HUB_TELEMETRY_PASSWORD
  poll_interval_s: 0.2
  request_timeout_s: 1.5
  pause_timeout_s: 1.0
  telemetry_timeout_s: 30.0

web:
  enabled: true
  auth_enabled: true          # Passwort: UGV_WEB_PASSWORD
  auth_username: ugv

logging:
  level: INFO
  console: true
```

Die Weboberfläche und der SensorHub sind aus dem Internet erreichbar und
verlangen eine Anmeldung. Passwörter stehen in der Dienst-Umgebung, nicht in
dieser Datei - siehe [WEB_ZUGANGSSCHUTZ.md](../WEB_ZUGANGSSCHUTZ.md).

## 🔌 API

### REST Endpoints

- `GET /` - Web-Interface
- `GET /api/status` - System-Status
- `POST /api/can/toggle` - CAN Ein/Aus
- `POST /api/light/toggle` - Licht Ein/Aus
- `POST /api/mower/toggle` - Maehdeck nur mit explizitem JSON-Zustand
  (`{"state": true, "rpm": 500}` oder `{"state": false}`); fehlendes,
  unlesbares oder nicht-boolesches `state` wird mit HTTP 400 abgelehnt
- `POST /api/mower/speed` - Mäher-Geschwindigkeit
- `POST /api/joystick` - Joystick-Input
- `GET /api/sensor/status` - Sensor-Status anfordern
- `POST /api/sensor/restart` - Sensor Hub neu starten
- `POST /api/mapping/maps/<name>/plan/simulate` - einen Plan ohne Hardware mit
  dem produktiven Navigationscontroller und einem kinematischen Fahrzeugmodell
  simulieren

## Offline-Fahrtsimulation

Die Kartenansicht bietet fuer jeden berechneten oder geladenen Plan
`Fahrt simulieren`. Die Simulation arbeitet auf den tatsaechlich ausfuehrbaren
Segmenten nach Startpunktauswahl, Ringrotation und Uebergangsrouting. Sie nutzt
den produktiven `NavigationController`; nur Motoren und Posequelle werden durch
ein einfaches Skid-Steer-Modell ersetzt.

Das Ergebnis enthaelt und visualisiert:

- simulierte Fahrspur fuer Vorwaerts-, Rueckwaerts- und Uebergangssegmente,
- Fahrzeug-Footprint an der End- oder Stopposition,
- Segmentzustand, Fahrzeit und tatsaechliche Strecke,
- No-Go-Warnungen und denselben Footprint-Stopp wie bei der realen Ausfuehrung.

Das Modell ist keine Gras-/Reifen-Physiksimulation. Es dient als reproduzierbare
Vorpruefung fuer Segmentreihenfolge, Uebergaenge, Startposition, Controller-
Verhalten und Sicherheitsabstaende. Feldtests bleiben fuer Traktion, Schlupf,
Nachlauf und reale Motorreaktion erforderlich.

### Geplante Coverage-Optimierung

Schmale Restkeile, in die keine mindestens 2 m lange reine Restbahn passt,
bleiben derzeit unbefahren. Eine kuenftige Planerstrategie darf solche Bahnen
in bereits durch Konturfahrten gemaehte Innenbereiche verlaengern. Der doppelt
gemaehte Anteil ist dabei ein erlaubter Verbindungskorridor und macht die
eigentliche Restbahn lang genug fuer eine stabile Vor-/Rueckwaertsfahrt. Diese
Strategie soll optional bleiben und im Simulator anhand von Restflaeche,
Doppelmaehstrecke, Wendungen und Sicherheitsabstand verglichen werden.

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
# Nur fuer Legacy/Testprofile mit USB-CAN, Classical CAN 2.0
sudo ip link set can0 up type can bitrate 250000 restart-ms 100
```

Am UGV-Teststand wird stattdessen der USB-CAN-Adapter über
`ugvtestpi-usbcan0.service` mit 250 kbit/s aktiviert.

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

- Optionaler Sicherheitsschalter (GPIO 17, `safety.enabled` in config.yaml) stoppt und
  verriegelt Fahrantrieb und Mähdeck, sofern verbaut. Am UGV auf raspberrycan ist
  kein Schalter vorhanden; dort ist `safety.enabled: false` gesetzt.
- Command-Timeout (2s) stoppt Motoren bei fehlenden Befehlen
- Joystick-Timeout (1s) stoppt Motoren bei Verbindungsabbruch
- Nach 1 s ohne SensorHub-Pose pausiert der Watchdog nur Fahrantrieb und Route;
  das Maehdeck darf weiterlaufen. Nach Rueckkehr einer frischen Pose wird eine
  zuvor aktive autonome Route automatisch am Resume-Punkt fortgesetzt.
- Erst nach 10 s ohne SensorHub-Pose oder sofort bei fehlender ODrive-USB-Achse
  verriegelt der Watchdog den Gesamtsystem-Stopp inklusive Maehdeck.
- Native USB-Telemetrie überwacht alle drei Mähmotorströme mit konfigurierbaren Zeitgrenzen.
- Der USB-Monitor liest im IDLE alle 100 ms und fuettert den lokalen Watchdog. Dadurch
  bleibt der lokale 1,0-s-ODrive-Watchdog gefüttert; bei Pi-/Kabelausfall läuft
  er ab und disarmt die Achse lokal.
- Der verriegelte Stopp wird in der Web-Oberfläche angezeigt und kann dort erst
  nach wiederhergestellten USB-Verbindungen manuell zurückgesetzt werden.

Die ODrive-Watchdogs sind auf den drei genutzten Achsen mit 1,0 s gespeichert.
Fuer eine erneute Einrichtung muss der Motor-Controller-Dienst gestoppt sein:

```bash
# Board A (Nodes 0 und 1)
python3 scripts/configure_odrive_watchdog.py apply --serial 0x386132523135 --nodes 0,1 --timeout 1.0

# Board B (nur verwendeter Node 2; Node 3 bleibt unverändert)
python3 scripts/configure_odrive_watchdog.py apply --serial 0x387132523135 --nodes 2 --timeout 1.0
```

## 📊 GPIO-Belegung

| GPIO | Funktion |
|------|----------|
| 18 | Motor rechts (PWM) |
| 19 | Motor links (PWM) |
| 22 | Licht (Relay) |
| 23 | Mäher (Relay) |
| 12 | Mäher (PWM) |
| 17 | Sicherheitsschalter (optional, an raspberrycan nicht verbaut) |

## 🌐 Web-Interface

```bash
# Zugriff über Browser
http://raspberrycan/

# API-Status
curl http://raspberrycan/api/status
```
