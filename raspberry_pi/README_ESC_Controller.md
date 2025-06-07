# DroneCAN ESC Controller

Erweiterte Version des DroneCAN Monitoring-Scripts mit PWM-Ausgabe für sichere ESC-Steuerung.

## 🎯 Features

- **Kalibriertes Monitoring**: Zeigt DroneCAN ESC-Kommandos mit kalibrierten Prozent-Werten
- **PWM-Ausgabe**: Hardware-PWM für sichere ESC-Steuerung (Anti-Freeze)
- **Sicherheitsfeatures**: Signal-Handler, Timeout-Überwachung, Emergency-Stop
- **Flexible Modi**: Monitor-only, PWM-only, oder beides

## 🔧 Hardware-Anforderungen

### GPIO-Pins (Standard):
- **GPIO 18** (Pin 12) - Rechter Motor (Hardware-PWM0)
- **GPIO 19** (Pin 35) - Linker Motor (Hardware-PWM1)

### Software-Abhängigkeiten:
```bash
# pigpio für Hardware-PWM
sudo apt install pigpio python3-pigpio

# pigpio daemon starten
sudo systemctl enable pigpiod
sudo systemctl start pigpiod
```

## 🚀 Verwendung

### 1. Nur Monitoring (wie bisher):
```bash
python3 dronecan_esc_controller.py
```

### 2. Monitoring + PWM-Ausgabe:
```bash
python3 dronecan_esc_controller.py --pwm
```

### 3. Nur PWM (kein Monitor):
```bash
python3 dronecan_esc_controller.py --pwm --quiet
```

### 4. Andere GPIO-Pins verwenden:
```bash
python3 dronecan_esc_controller.py --pwm --pins 12,13
# Format: rechts,links
```

### 5. Andere CAN-Konfiguration:
```bash
python3 dronecan_esc_controller.py --interface can1 --bitrate 500000 --node-id 25
```

## 🛡️ Sicherheitsfeatures

### PWM-Freeze-Schutz:
- **Hardware-PWM**: Läuft unabhängig vom Python-Prozess
- **Signal-Handler**: Sauberes Shutdown bei SIGINT/SIGTERM
- **Timeout-Überwachung**: Automatisch auf Neutral bei fehlendem Kommando (2s)
- **Emergency-Stop**: Sofortiger Neutral-Zustand bei Fehlern

### Kommando-Timeout:
```
Kein ESC-Kommando für 2 Sekunden → Automatisch auf 1500μs (Neutral)
```

## 📊 Ausgabe-Beispiel

```
[15:33:41] 🚗 ESC RawCommand von Node ID 10:
    ⬆️ L/R: Links=+85.2% | Rechts=+85.2% | FORWARD
    🔧 Raw: Links=7000 | Rechts=7000 | Neutral: L=-114 R=0
    📡 PWM: Links=1927μs | Rechts=1927μs | Neutral=1500μs
    ⚡ GPIO: Links=GPIO19 | Rechts=GPIO18
```

## 🔄 Migration vom alten Script

Das neue Script ersetzt `dronecan_calibrated_monitor.py` vollständig:

```bash
# Alt (nur Monitor):
python3 dronecan_calibrated_monitor.py

# Neu (gleiche Funktionalität):
python3 dronecan_esc_controller.py

# Neu (mit PWM):
python3 dronecan_esc_controller.py --pwm
```

## ⚠️ Wichtige Hinweise

1. **Root-Rechte**: Für Hardware-PWM erforderlich: `sudo python3 ...`
2. **pigpiod**: Muss laufen für Hardware-PWM
3. **GPIO-Konflikte**: Andere PWM-Programme beenden vor Start
4. **ESC-Kalibrierung**: Verwendet automatisch `guided_esc_calibration.json` falls vorhanden

## 🐛 Troubleshooting

### "pigpio library nicht installiert":
```bash
sudo apt install pigpio python3-pigpio
```

### "Kann nicht mit pigpio daemon verbinden":
```bash
sudo systemctl start pigpiod
sudo systemctl status pigpiod
```

### "PWM-Initialisierung fehlgeschlagen":
```bash
# Andere PWM-Programme beenden
sudo pkill -f pigpio
sudo systemctl restart pigpiod
```
