# Orange Cube DroneCAN Konfiguration und Überwachung

Dieses Projekt enthält Tools zur Konfiguration und Überwachung eines Orange Cube Autopiloten über MAVLink und zur Analyse der DroneCAN-Kommunikation.

## Übersicht

Das Projekt wurde erfolgreich verwendet, um DroneCAN-Kommunikation auf einem Orange Cube zu aktivieren und zu überwachen. Die wichtigsten Tools sind:

### Python-Tools für Orange Cube:
1. **monitor_orange_cube.py**: Erweiterte MAVLink-Überwachung mit DroneCAN-Parameter-Anzeige
2. **set_can_parameters.py**: Automatisches Setzen von CAN-Parametern zur Optimierung der DroneCAN-Kommunikation
3. **send_dronecan_actuator_commands.py**: Tool zum Senden von DroneCAN-Befehlen

### Batch-Dateien:
- **run-orange-cube-monitor.bat**: Startet das Orange Cube Monitor-Tool
- **run-set-can-parameters.bat**: Startet das Parameter-Setter-Tool
- **install-pymavlink.bat**: Installiert die erforderliche pymavlink-Bibliothek

## Erfolgreiche Konfiguration

Das Projekt hat erfolgreich die DroneCAN-Kommunikation auf dem Orange Cube aktiviert. Die wichtigsten Parameter-Änderungen waren:

- `CAN_D1_UC_NTF_RT`: Erhöht auf 100 Hz (war 20 Hz)
- `CAN_D1_UC_SRV_BM`: Aktiviert auf 5 (Servos 1 und 3)
- `CAN_D1_UC_SRV_RT`: Erhöht auf 100 Hz (war 50 Hz)
- `CAN_D1_UC_ESC_BM`: Angepasst auf 5 (ESCs 1 und 3)

## Verwendung

### 1. Orange Cube Parameter setzen:
```
run-set-can-parameters.bat
```

### 2. Orange Cube überwachen:
```
run-orange-cube-monitor.bat
```

### 3. CAN-Bus mit externem Tool überwachen:
Nach der Konfiguration sendet der Orange Cube regelmäßig DroneCAN-Nachrichten, die mit Tools wie Cangaroo oder anderen CAN-Sniffern überwacht werden können.

## Beyond Robotics CAN Node Tests

### CAN Listener Test:
Das `beyond_robotics_can_test.cpp` Script testet den Empfang von DroneCAN-Nachrichten vom Orange Cube.

**Hardware Setup:**
- STM-LINK V3 Programmer verbunden mit STLINK-Header
- SW1 auf Position "1" (STLINK aktiviert)
- CAN-Verbindung: CANH/CANL zwischen Dev Board und Orange Cube
- Serielle Ausgabe über COM8

## Archivierte Dateien

Alle nicht mehr benötigten Dateien wurden in den `archive`-Ordner verschoben:
- `archive/esp32_files/`: Alle ESP32-bezogenen Dateien (nicht mehr benötigt)
- `archive/old_tests/`: Alte Test-Dateien
- `archive/old_batch_files/`: Alte Batch-Dateien
- `archive/old_documentation/`: Alte Dokumentation

## Erfolg

Das Projekt hat erfolgreich die DroneCAN-Kommunikation auf dem Orange Cube aktiviert. Mit dem USB-CAN-Sniffer und Cangaroo können nun regelmäßige DroneCAN-Nachrichten vom Orange Cube beobachtet werden.

Die Parameter-Optimierung war der Schlüssel zum Erfolg - ohne die richtigen Einstellungen sendete der Orange Cube keine regelmäßigen DroneCAN-Nachrichten.
