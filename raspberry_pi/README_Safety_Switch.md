# 🛡️ Sicherheitsschaltleiste Integration

## Übersicht

Die Sicherheitsschaltleiste ist eine Hardware-Sicherheitseinrichtung, die bei Betätigung den bestehenden Notaus-Modus (CAN deaktiviert) aktiviert. Sie ist an GPIO17 des Raspberry Pi angeschlossen und arbeitet mit einem Betätigungswiderstand von ≤ 500 Ohm.

## Hardware-Spezifikationen

### Sicherheitsschaltleiste
- **Betätigungswiderstand**: ≤ 500 Ohm
- **Betätigungskraft**: 52,9 N bei 100 mm/s
- **Ansprechweg**: 5,2 mm bei 100 mm/s
- **Nachlaufweg**: 7,8 mm (bis 400 N bei 100 mm/s)
- **Schutzart**: IP67
- **Schaltspiele**: 10.000 (mechanisch, typisch)
- **Umgebungstemperatur**: -10°C bis +50°C
- **Normen**: EN ISO 13849-1, EN ISO 13856-2
- **Zulassungen**: UL, CE, TÜV

### Anschluss
- **GPIO-Pin**: GPIO17 (Standard, konfigurierbar)
- **Masse**: GND
- **Konfiguration**: Input mit Pull-Up-Widerstand
- **Auslösung**: Fallende Flanke (GPIO17 → GND)

## Software-Integration

### Funktionsweise
1. **Initialisierung**: GPIO17 wird als Input mit Pull-Up konfiguriert
2. **Überwachung**: Interrupt-Handler für fallende Flanke registriert
3. **Auslösung**: Bei Schaltleisten-Betätigung wird Notaus-Modus aktiviert
4. **Schutz**: Doppelte Aktivierung wird verhindert (bereits im Notaus-Modus)
5. **Entprellung**: 100ms Mindestabstand zwischen Auslösungen

### Integration in bestehenden Notaus-Modus
- Nutzt vorhandene `self.can_enabled` Variable
- Ruft bestehende `_emergency_stop()` Methode auf
- Informiert Web-Interface über Statusänderung
- Verhindert Konflikte mit manueller CAN-Deaktivierung

## Verwendung

### Standard-Betrieb
```bash
# Mit Sicherheitsschaltleiste (Standard)
python3 dronecan_esc_controller.py --pwm

# Mit Web-Interface
python3 dronecan_esc_controller.py --pwm --web
```

### Konfiguration
```bash
# Anderen GPIO-Pin verwenden
python3 dronecan_esc_controller.py --pwm --safety-pin 22

# Sicherheitsschaltleiste deaktivieren
python3 dronecan_esc_controller.py --pwm --no-safety
```

### Service-Integration
```bash
# Service mit Sicherheitsschaltleiste starten
esc-start

# Status prüfen (zeigt Sicherheitsstatus)
esc-status

# Logs überwachen
esc-logs
```

## Testing

### Hardware-Test
```bash
# Sicherheitsschaltleiste testen
python3 test_safety_switch.py
```

**Test-Ablauf:**
1. GPIO17 Status-Monitoring
2. Schaltleiste drücken → "AUSGELÖST" Meldung
3. Schaltleiste loslassen → "losgelassen" Meldung
4. Entprellung-Test durch mehrfaches Drücken

### Integration-Test
```bash
# Controller mit Debug-Output starten
python3 dronecan_esc_controller.py --pwm --web

# Sicherheitsschaltleiste betätigen
# Erwartung: "🚨 SICHERHEITSSCHALTLEISTE AUSGELÖST! → Notaus aktiviert"
```

## Web-Interface Integration

### Status-Anzeige
- Sicherheitsstatus wird in `/api/status` angezeigt
- `safety_enabled`: true/false
- `safety_pin`: GPIO-Pin-Nummer

### Ereignis-Benachrichtigung
- WebSocket-Event bei Sicherheitsauslösung
- Automatische UI-Aktualisierung
- Visueller Hinweis auf Notaus-Aktivierung

## Sicherheitsfeatures

### Fail-Safe Design
- **Graceful Degradation**: Bei GPIO-Initialisierungsfehlern läuft System ohne Hardware-Sicherheitsschaltleiste weiter
- **Thread-Sicherheit**: Interrupt-Handler arbeitet thread-sicher mit Hauptprogramm
- **Cleanup**: Automatisches GPIO-Cleanup bei Programmende
- **Entprellung**: Hardware-Entprellung verhindert Fehlauslösungen

### Redundanz
- **Hardware + Software**: Physische Sicherheitsschaltleiste + Software-Notaus-Button
- **Mehrfach-Schutz**: Signal-Handler, atexit-Handler, Exception-Handler
- **Timeout-Überwachung**: Bestehende DroneCAN-Timeout-Überwachung bleibt aktiv

## Troubleshooting

### Häufige Probleme

#### ❌ "pigpio daemon nicht verbunden"
**Ursache**: pigpiod läuft nicht
**Lösung**:
```bash
sudo systemctl start pigpiod
sudo systemctl enable pigpiod  # Autostart
```

#### ❌ "Sicherheitsschaltleiste-Initialisierung fehlgeschlagen"
**Ursache**: GPIO bereits in Verwendung oder Hardware-Problem
**Lösung**:
1. Anderen GPIO-Pin verwenden: `--safety-pin 22`
2. Hardware-Verbindung prüfen
3. Mit `--no-safety` deaktivieren

#### ❌ "Keine Reaktion auf Schaltleisten-Betätigung"
**Ursache**: Widerstand zu hoch oder schlechte Verbindung
**Lösung**:
1. Widerstand mit Multimeter messen (≤ 500 Ohm)
2. Verbindung GPIO17 ↔ GND prüfen
3. Test-Script ausführen: `python3 test_safety_switch.py`

### Debug-Modus
```bash
# Mit ausführlichem Logging
python3 dronecan_esc_controller.py --pwm --web

# GPIO-Status überwachen
python3 test_safety_switch.py
```

## Wartung

### Regelmäßige Prüfung
- **Wöchentlich**: Funktionstest der Sicherheitsschaltleiste
- **Monatlich**: Widerstandsmessung (≤ 500 Ohm)
- **Jährlich**: Mechanische Prüfung (Ansprechweg, Betätigungskraft)

### Austausch-Kriterien
- Widerstand > 500 Ohm
- Ansprechweg > 6 mm
- Mechanische Beschädigungen
- Nach 10.000 Schaltzyklen (präventiv)

## Integration mit Orange Cube

Die Sicherheitsschaltleiste arbeitet unabhängig vom Orange Cube und aktiviert den lokalen Notaus-Modus auf dem Raspberry Pi. Dies bietet zusätzliche Sicherheit, da:

1. **Lokale Reaktion**: Sofortige Motorabschaltung ohne DroneCAN-Kommunikation
2. **Hardware-Unabhängigkeit**: Funktioniert auch bei Orange Cube-Ausfall
3. **Redundanz**: Zusätzlich zu Orange Cube Failsafe-Systemen
4. **Schnelle Reaktion**: GPIO-Interrupt schneller als DroneCAN-Kommunikation
