# UGV DroneCAN Controller - Web Interface

## Übersicht

Das Web-Interface erweitert den DroneCAN ESC Controller um eine smartphone-optimierte Fernsteuerung. Es läuft parallel zum DroneCAN-System ohne Performance-Beeinträchtigung.

## Features (Phase 1)

### ✅ Implementiert
- **CAN Ein/Aus (Not-Aus)**: Sofortiges Stoppen aller Motoren
- **Status-Monitor**: Echtzeit-Anzeige von PWM-Werten und System-Status
- **Responsive Design**: Optimiert für Smartphone hochkant
- **WebSocket-Kommunikation**: Niedrige Latenz für Echtzeit-Updates
- **Thread-sichere Architektur**: Separater Web-Server-Thread

### 🔄 Geplant (Phase 2+)
- **Virtueller Joystick**: Touch-Steuerung für Fahrbewegungen
- **Lampe Ein/Aus**: Beleuchtungssteuerung
- **Mähen Ein/Aus**: Mähwerk-Steuerung
- **Erweiterte Diagnostik**: Batterie-Status, Fehlerprotokoll

## Installation

### 1. Dependencies installieren
```bash
# Auf dem Raspberry Pi
cd ~/raspberry_pi
chmod +x install_web_dependencies.sh
./install_web_dependencies.sh
```

### 2. Manuelle Installation (falls Skript nicht funktioniert)
```bash
sudo apt install -y python3 python3-pip
pip3 install flask flask-socketio eventlet
```

## Verwendung

### Basis-Start (nur Monitor)
```bash
python3 dronecan_esc_controller.py --web
```

### Vollständiger Start (PWM + Web)
```bash
python3 dronecan_esc_controller.py --pwm --web
```

### Mit angepasstem Port
```bash
python3 dronecan_esc_controller.py --pwm --web --web-port 8080
```

### Stiller Modus (nur Web-Interface, kein Terminal-Output)
```bash
python3 dronecan_esc_controller.py --pwm --web --quiet
```

## Zugriff

### Über Hostname (empfohlen)
```
http://raspberrycan:5000
```

### Über IP-Adresse
```bash
# IP-Adresse herausfinden
hostname -I

# Dann im Browser
http://192.168.1.XXX:5000
```

### Smartphone-Zugriff
1. Smartphone mit gleichem WLAN verbinden
2. Browser öffnen
3. URL eingeben: `http://raspberrycan:5000`
4. Als Lesezeichen speichern für schnellen Zugriff

## Web-Interface Bedienung

### Status-Anzeige
- **CAN Bus**: Grün = aktiv, Rot = gestoppt
- **PWM Output**: Grün = Hardware-PWM aktiv
- **Monitor**: Grün = DroneCAN-Monitoring aktiv

### Not-Aus Funktion
- **CAN STOPPEN**: Deaktiviert sofort alle DroneCAN-Kommandos
- **CAN STARTEN**: Reaktiviert DroneCAN-Verarbeitung
- Bei gestopptem CAN: Motoren bleiben auf Neutral (1500μs)

### System-Informationen
- **Motor PWM**: Aktuelle PWM-Werte (1000-2000μs)
- **Letztes Kommando**: Zeit seit letztem DroneCAN-Kommando
- **Verbindung**: Dauer der Web-Verbindung

## Technische Details

### Architektur
```
┌─────────────────┐    ┌──────────────────┐
│   Main Thread   │    │   Web Thread     │
│                 │    │                  │
│ ┌─────────────┐ │    │ ┌──────────────┐ │
│ │ DroneCAN    │ │    │ │ Flask Server │ │
│ │ Processing  │ │◄──►│ │ + SocketIO   │ │
│ └─────────────┘ │    │ └──────────────┘ │
│                 │    │                  │
│ ┌─────────────┐ │    │ ┌──────────────┐ │
│ │ PWM Output  │ │    │ │ Web Routes   │ │
│ │ (pigpio)    │ │    │ │ + API        │ │
│ └─────────────┘ │    │ └──────────────┘ │
└─────────────────┘    └──────────────────┘
         │                       │
         └───── can_enabled ─────┘
           (Thread-safe Flag)
```

### Performance
- **Keine Beeinträchtigung**: DroneCAN läuft in separatem Thread
- **Niedrige Latenz**: WebSocket für Echtzeit-Updates
- **Ressourcenschonend**: Nur bei Bedarf aktiv

### Sicherheit
- **Not-Aus Priorität**: CAN-Deaktivierung hat sofortige Wirkung
- **Thread-sichere Kommunikation**: Keine Race-Conditions
- **Timeout-Schutz**: Bestehende PWM-Timeout-Mechanismen bleiben aktiv

## Fehlerbehebung

### Web-Interface startet nicht
```bash
# Dependencies prüfen
pip3 list | grep -E "(Flask|flask-socketio)"

# Port bereits belegt?
sudo netstat -tulpn | grep :5000

# Anderen Port verwenden
python3 dronecan_esc_controller.py --pwm --web --web-port 8080
```

### Smartphone kann nicht zugreifen
```bash
# Firewall prüfen (falls aktiviert)
sudo ufw status

# Port freigeben (falls nötig)
sudo ufw allow 5000

# IP-Adresse prüfen
ip addr show wlan0
```

### CAN-Toggle funktioniert nicht
- Prüfen ob `--pwm` Parameter gesetzt ist
- Terminal-Output auf Fehlermeldungen prüfen
- Browser-Konsole (F12) auf JavaScript-Fehler prüfen

## Service-Integration

### Systemd-Service erweitern
```bash
# Service-Datei bearbeiten
sudo nano /etc/systemd/system/dronecan-esc.service

# ExecStart-Zeile erweitern um --web
ExecStart=/usr/bin/python3 /home/pi/raspberry_pi/dronecan_esc_controller.py --pwm --web --quiet

# Service neu laden
sudo systemctl daemon-reload
sudo systemctl restart dronecan-esc
```

### Status prüfen
```bash
# Service-Status
sudo systemctl status dronecan-esc

# Web-Interface erreichbar?
curl http://localhost:5000/api/status
```

## Entwicklung

### Logs aktivieren
```bash
# Mit Debug-Output
python3 dronecan_esc_controller.py --pwm --web

# Nur Web-Server-Logs
python3 dronecan_esc_controller.py --pwm --web --no-monitor
```

### API-Endpunkte testen
```bash
# Status abrufen
curl http://raspberrycan:5000/api/status

# CAN togglen
curl -X POST http://raspberrycan:5000/api/can/toggle
```

## ✅ Phase 2: Virtueller Joystick (IMPLEMENTIERT)

### Features
- **HTML5 Canvas Joystick**: Touch-optimierte Steuerung für Smartphones
- **Skid Steering Logic**: X/Y-Koordinaten → Links/Rechts Motor-PWM
- **WebSocket-Kommunikation**: Niedrige Latenz für Echtzeit-Steuerung
- **Geschwindigkeitsregelung**: Einstellbarer Max-Speed-Slider (10-100%)
- **Sicherheitsfeatures**: Joystick nur aktiv wenn CAN **DEAKTIVIERT** (Not-Aus-Modus)
- **Autonomie-Schutz**: Verhindert Störung des autonomen Fahrens (GPS/RTK)
- **Smooth Release**: Automatische Rückkehr zu Neutral-Position

### Bedienung
1. **CAN deaktivieren**: "CAN STOPPEN" drücken (Not-Aus-Modus aktivieren)
2. **Joystick verwenden**: Touch/Drag auf dem grünen Kreis (nur bei CAN AUS)
3. **Geschwindigkeit einstellen**: Slider für Max-Speed anpassen
4. **Loslassen**: Joystick kehrt automatisch zu Neutral zurück
5. **Autonomie aktivieren**: "CAN STARTEN" für GPS/RTK-Navigation

### Technische Details
- **Joystick-Priorität**: Joystick überschreibt DroneCAN-Kommandos
- **Timeout-Überwachung**: 1 Sekunde Joystick-Timeout
- **PWM-Konvertierung**: -1.0→1000μs, 0→1500μs, +1.0→2000μs
- **Ramping**: Bestehende Beschleunigungs-/Verzögerungslogik wird verwendet

## Nächste Schritte (Phase 3)

1. **Erweiterte Features**: Lampe, Mähen, Geschwindigkeitsregelung
2. **Konfiguration**: Web-basierte Parameter-Einstellung
3. **Logging**: Fahrt-Aufzeichnung und Replay
4. **Autonomie**: Wegpunkt-Navigation

---

**Status**: Phase 1 implementiert ✅  
**Nächste Phase**: Virtueller Joystick 🎮  
**Hardware**: Raspberry Pi 3 + Innomaker CAN HAT  
**Kompatibilität**: Orange Cube + DroneCAN 1.0  
