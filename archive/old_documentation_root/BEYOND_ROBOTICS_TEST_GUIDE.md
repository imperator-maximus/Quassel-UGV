# Beyond Robotics CAN Node Test Guide

## Hardware Setup

### 1. STM-LINK V3 Programmer
- ✅ **Erkannt als**: "ST-Link Debug" und "Serielles USB-Gerät (COM8)"
- ✅ **USB-Kabel funktioniert** (Datenübertragung möglich)
- ✅ **Treiber installiert**

### 2. Beyond Robotics Dev Board Konfiguration
- **SW1 auf Position "1"** (STLINK aktiviert, USB-zu-UART deaktiviert)
- **STM-LINK V3 mit STLINK-Header verbinden**
- **CAN-Verbindung**: CANH/CANL zwischen Dev Board und Orange Cube
- **GND-Verbindung** zwischen Dev Board und Orange Cube

### 3. Orange Cube Setup
- ✅ **Orange Cube bereits konfiguriert** mit optimierten DroneCAN-Parametern
- ✅ **Sendet regelmäßig DroneCAN-Nachrichten** (bestätigt mit Cangaroo)

## Test-Dateien

### 1. `beyond_robotics_can_test.cpp`
**Haupttest-Programm** mit folgenden Funktionen:
- **CAN-Nachrichten empfangen** und dekodieren
- **Heartbeat senden** (alle 1 Sekunde)
- **Statistiken anzeigen** (alle 5 Sekunden)
- **Detaillierte Ausgabe** aller empfangenen Nachrichten

### 2. `platformio_beyond_robotics.ini`
**PlatformIO-Konfiguration** für das Beyond Robotics Dev Board:
- STM32F103RB Mikrocontroller
- STM-LINK Upload und Debug
- COM8 für serielle Ausgabe

### 3. `run-beyond-robotics-test.bat`
**Automatisches Upload und Monitor-Script**

## Test durchführen

### Schritt 1: Hardware vorbereiten
```
1. STM-LINK V3 mit PC verbinden (USB)
2. STM-LINK V3 mit Beyond Robotics Dev Board verbinden (STLINK-Header)
3. SW1 auf Position "1" setzen
4. CAN-Verbindung: CANH/CANL zwischen Dev Board und Orange Cube
5. Orange Cube einschalten und mit Mission Planner verbinden
```

### Schritt 2: Test starten
```
run-beyond-robotics-test.bat
```

### Schritt 3: Erwartete Ausgabe
```
=== Beyond Robotics CAN Node Test ===
Testing DroneCAN communication with Orange Cube
Hardware: Beyond Robotics Dev Board + STM-LINK V3
CAN Speed: 500 kbps
Serial Output: COM8
=====================================
Initializing DroneCAN...
DroneCAN initialized successfully!
Listening for CAN messages from Orange Cube...
Expected messages:
- NodeStatus (Heartbeat)
- ESC Status
- Servo Commands
- Battery Info
=====================================
Sent heartbeat #1
[RX] Node ID: 10 | Data Type ID: 341 | Transfer ID: 5 | Payload Length: 7 bytes | Type: NodeStatus (Heartbeat) | Health: 0 | Mode: 0 | Uptime: 123s
    Payload: 7B 00 00 00 00 00 00
[RX] Node ID: 10 | Data Type ID: 1034 | Transfer ID: 3 | Payload Length: 14 bytes | Type: ESC Status
    Payload: 00 00 00 00 FF FF FF FF
=== STATS === Total messages received: 15 | Uptime: 5 seconds
```

## Troubleshooting

### Problem: Upload fehlgeschlagen
**Lösung:**
- STM-LINK V3 Verbindung prüfen
- SW1 auf Position "1" prüfen
- Beyond Robotics Dev Board richtig am STLINK-Header angeschlossen

### Problem: Keine CAN-Nachrichten empfangen
**Lösung:**
- CAN-Verkabelung prüfen (CANH/CANL/GND)
- Orange Cube läuft und sendet Nachrichten (mit Cangaroo testen)
- Termination-Widerstände prüfen

### Problem: COM8 nicht verfügbar
**Lösung:**
- STM-LINK V3 Treiber neu installieren
- Anderen USB-Port versuchen
- Geräte-Manager prüfen

## Erfolg-Kriterien

✅ **Upload erfolgreich**: Programm wird ohne Fehler hochgeladen
✅ **Heartbeat gesendet**: "Sent heartbeat #X" Nachrichten erscheinen
✅ **CAN-Nachrichten empfangen**: "[RX]" Nachrichten vom Orange Cube
✅ **Statistiken**: Regelmäßige Statistik-Updates alle 5 Sekunden

## Nächste Schritte

Nach erfolgreichem Test können Sie:
1. **Spezifische DroneCAN-Nachrichten senden** (Actuator Commands)
2. **Sensor-Daten über DroneCAN übertragen**
3. **Custom DroneCAN-Nodes entwickeln**
