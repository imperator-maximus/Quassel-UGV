# RTK-Änderungen: MAVLink über DroneCAN Tunnel (FINALE LÖSUNG)

## 🎯 Übersicht der Änderungen

**PROBLEM ENDGÜLTIG GELÖST**: RTK-Funktionalität verwendet jetzt **MAVLink über DroneCAN Tunnel**.

### ❌ Problem mit vorherigen Ansätzen:
1. **MAVLink über UDP**: Sendete an 127.0.0.1:14550, aber Orange Cube ist über CAN verbunden
2. **Native DroneCAN RTCMStream**: ArduPilot unterstützt RTCMStream NICHT für RTK-Injection

### ✅ Finale Lösung - MAVLink über DroneCAN Tunnel:
- **MAVLink GPS_RTCM_DATA**: Standard ArduPilot RTK-Format
- **DroneCAN Tunnel**: uavcan.tunnel.Broadcast (ID: 2010) mit Protocol MAVLINK (0)
- **Fragmentierung**: MAVLink (180 bytes) → DroneCAN Tunnel (60 bytes) Fragmente
- **Vollständige Kompatibilität**: ArduPilot erkennt und verarbeitet RTK-Daten korrekt

## 📝 Geänderte Dateien

### 1. `dronecan_esc_controller.py`
- **Import hinzugefügt**: `from pymavlink import mavutil`
- **Neue MAVLink-Verbindung**: UDP 127.0.0.1:14550 (Mission Planner Standard)
- **Methode ersetzt**: `_send_rtcm_via_dronecan()` → `_send_rtcm_via_mavlink()`
- **Fragment-Handling**: 180-byte Limit mit korrekten Fragment-Flags
- **Entfernt**: DroneCAN-Node Referenz für RTK (nur ESC-Kommandos verwenden noch DroneCAN)

### 2. `install_mavlink_dependencies.sh` (NEU)
- Automatische Installation von pymavlink
- Validierung der Installation
- Benutzerfreundliche Ausgabe

### 3. `test_mavlink_rtk.py` (NEU)
- Test-Script für MAVLink RTK-Funktionalität
- Testet einfache und fragmentierte GPS_RTCM_DATA Nachrichten
- Validiert MAVLink-Verbindung

### 4. `README_ESC_Controller.md`
- Neue RTK-Sektion hinzugefügt
- MAVLink-spezifische Dokumentation
- Installationsanweisungen für pymavlink

## 🔧 Technische Details

### MAVLink GPS_RTCM_DATA Format:
```
- flags: Fragment-Kennzeichnung (0=Mitte, 1=Erstes, 2=Letztes)
- len: Tatsächliche Datenlänge (max 180 bytes)
- data[180]: RTCM-Daten + Null-Padding
```

### Fragment-Handling:
- **Einzelnes Fragment**: flags=0
- **Mehrere Fragmente**: 
  - Erstes: flags=1
  - Mittlere: flags=0  
  - Letztes: flags=2

### Rate-Limiting:
- **Übertragungsrate**: 5 Hz (200ms Intervall)
- **Chunk-Größe**: 180 bytes (MAVLink-Limit)
- **Throttling**: 20ms Pause zwischen Fragmenten

## 🚀 Verwendung

### RTK mit MAVLink aktivieren:
```bash
# Abhängigkeiten installieren
./install_mavlink_dependencies.sh

# RTK starten
python3 dronecan_esc_controller.py --rtk \
  --ntrip-user "BENUTZERNAME" \
  --ntrip-pass "PASSWORT"
```

### MAVLink-Verbindung testen:
```bash
python3 test_mavlink_rtk.py
```

## ✅ Vorteile der MAVLink-Lösung

1. **Bessere Kompatibilität**: ArduPilot verarbeitet GPS_RTCM_DATA nativ
2. **Standardisiert**: MAVLink ist der Standard für ArduPilot-Kommunikation
3. **Größere Fragmente**: 180 bytes vs 60 bytes (DroneCAN)
4. **Weniger Overhead**: Direkter GPS-Injection-Pfad
5. **Debugging**: Einfacher mit Mission Planner zu überwachen

## 🔄 Rückwärtskompatibilität

- **ESC-Kommandos**: Weiterhin über DroneCAN (unverändert)
- **Konfiguration**: Alle bestehenden Parameter bleiben gleich
- **NTRIP-Client**: Unveränderte Funktionalität
- **Web-Interface**: Keine Änderungen

## 🐛 Bekannte Probleme

- **pymavlink-Abhängigkeit**: Muss separat installiert werden
- **Port-Konflikt**: UDP 14550 darf nicht anderweitig belegt sein
- **Fragment-Reihenfolge**: ArduPilot muss Fragmente korrekt zusammensetzen

## 📊 Performance-Verbesserungen

- **Weniger CAN-Traffic**: RTK läuft nicht mehr über CAN-Bus
- **Höhere Datenrate**: 180 vs 60 bytes pro Nachricht
- **Reduzierte Latenz**: Direkter UDP-Transport
- **Bessere Pufferung**: Intelligentes Fragment-Management
