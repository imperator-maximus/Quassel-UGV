# CAN Transceiver Troubleshooting Guide

Dieses Dokument hilft bei der Fehlersuche, wenn der ESP32 CAN-Controller im Listen-Only-Modus funktioniert, aber beim Senden von Nachrichten Timeout-Fehler auftreten.

## Typische Symptome

- Der ESP32 kann im Listen-Only-Modus initialisiert werden
- Beim Senden von Nachrichten treten Timeout-Fehler auf
- Die LEDs an den CAN-Pins leuchten dauerhaft, ohne zu blinken

## Schritt 1: Überprüfen der Verkabelung

### ESP32 zu CAN-Transceiver

| ESP32 Pin | CAN-Transceiver Pin | Beschreibung |
|-----------|---------------------|--------------|
| GPIO5     | TX                  | Sendepin vom ESP32 zum Transceiver |
| GPIO4     | RX                  | Empfangspin vom Transceiver zum ESP32 |
| 3.3V      | VCC                 | Stromversorgung für den Transceiver |
| GND       | GND                 | Gemeinsame Masse |

**Wichtig**: Die Pins GPIO4 und GPIO5 sind fest mit dem internen CAN-Controller des ESP32 verbunden und können nicht geändert werden.

### CAN-Transceiver zu Orange Cube

| CAN-Transceiver Pin | Orange Cube Pin | Beschreibung |
|---------------------|-----------------|--------------|
| CANH                | CAN_H           | CAN High-Leitung |
| CANL                | CAN_L           | CAN Low-Leitung |

## Schritt 2: Überprüfen der Stromversorgung

1. Stellen Sie sicher, dass der CAN-Transceiver mit 3.3V versorgt wird
2. Überprüfen Sie mit einem Multimeter die Spannung am VCC-Pin des Transceivers
3. Stellen Sie sicher, dass die Masse (GND) zwischen ESP32 und Transceiver verbunden ist

## Schritt 3: Überprüfen der Terminierung

Für einen korrekten CAN-Bus-Betrieb sind Abschlusswiderstände an beiden Enden des Busses erforderlich:

1. Platzieren Sie einen 120-Ohm-Widerstand zwischen CANH und CANL am CAN-Transceiver
2. Stellen Sie sicher, dass die interne Terminierung des Orange Cube aktiviert ist

## Schritt 4: Testen mit verschiedenen Baudraten

Der Orange Cube verwendet möglicherweise eine andere Baudrate als erwartet. Testen Sie mit:

1. 500 kbps (Standard für viele CAN-Anwendungen)
2. 1 Mbps (Standard für DroneCAN)
3. 250 kbps (Alternative für bessere Stabilität)

## Schritt 5: Überprüfen der CAN-Transceiver-Funktionalität

1. Trennen Sie den CAN-Transceiver vom Orange Cube
2. Verbinden Sie CANH und CANL direkt mit einem 120-Ohm-Widerstand
3. Führen Sie den CAN-Transceiver-Test aus und prüfen Sie, ob Nachrichten gesendet werden können
4. Wenn dies funktioniert, liegt das Problem wahrscheinlich in der Verbindung zum Orange Cube

## Schritt 6: Überprüfen der Orange Cube Konfiguration

1. Verbinden Sie den Orange Cube mit Mission Planner
2. Gehen Sie zu **Config/Tuning** > **Full Parameter List**
3. Überprüfen Sie die folgenden Parameter:
   - `CAN_P1_DRIVER` sollte auf `1` gesetzt sein
   - `CAN_P1_BITRATE` sollte auf `500000` oder `1000000` gesetzt sein
   - `CAN_D1_PROTOCOL` sollte auf `1` gesetzt sein (DroneCAN-Protokoll)

## Häufige Fehlerursachen und Lösungen

### 1. Falsche Verkabelung

**Symptom**: Timeout-Fehler beim Senden, keine empfangenen Nachrichten

**Lösung**:
- Überprüfen Sie, ob TX und RX korrekt angeschlossen sind
- Stellen Sie sicher, dass CANH und CANL nicht vertauscht sind
- Überprüfen Sie alle Lötverbindungen auf kalte Lötstellen

### 2. Fehlende Terminierung

**Symptom**: Sporadische Kommunikation, Fehler bei höheren Baudraten

**Lösung**:
- Fügen Sie 120-Ohm-Widerstände an beiden Enden des CAN-Busses hinzu
- Überprüfen Sie, ob die Terminierung des Orange Cube aktiviert ist

### 3. Probleme mit dem CAN-Transceiver

**Symptom**: Keine Kommunikation, Timeout-Fehler

**Lösung**:
- Testen Sie mit einem anderen CAN-Transceiver
- Überprüfen Sie die Datenblätter des Transceivers für spezielle Konfigurationsanforderungen
- Stellen Sie sicher, dass der Transceiver für 3.3V ausgelegt ist

### 4. Baudrate-Mismatch

**Symptom**: Keine Kommunikation, Bus-Off-Zustand nach mehreren Versuchen

**Lösung**:
- Stellen Sie sicher, dass beide Geräte die gleiche Baudrate verwenden
- Beginnen Sie mit einer niedrigeren Baudrate (250 kbps) für bessere Stabilität
- Erhöhen Sie schrittweise die Baudrate, wenn die Kommunikation funktioniert

## Nächste Schritte

Wenn Sie alle oben genannten Schritte durchgeführt haben und immer noch Probleme haben:

1. Führen Sie den `can_transceiver_test.cpp` aus, um detaillierte Diagnoseinformationen zu erhalten
2. Versuchen Sie, die Baudrate auf 250 kbps zu reduzieren für bessere Stabilität
3. Testen Sie mit dem `dronecan_orange_cube_test.cpp`, um speziell die DroneCAN-Kommunikation zu testen
4. Überprüfen Sie die Dokumentation Ihres spezifischen CAN-Transceivers für weitere Konfigurationsoptionen
