# CAN Hardware Troubleshooting Guide

Diese Anleitung hilft bei der Diagnose und Behebung von Hardware-Problemen bei der CAN-Kommunikation zwischen dem ESP32 und dem Orange Cube.

## Inhaltsverzeichnis

1. [Grundlegende Überprüfungen](#grundlegende-überprüfungen)
2. [Hardware-Diagnose](#hardware-diagnose)
3. [Verkabelung und Anschlüsse](#verkabelung-und-anschlüsse)
4. [Terminierung](#terminierung)
5. [CAN-Transceiver](#can-transceiver)
6. [Spannungsversorgung](#spannungsversorgung)
7. [Signalqualität](#signalqualität)
8. [Häufige Fehlercodes](#häufige-fehlercodes)
9. [Checkliste für die Fehlerbehebung](#checkliste-für-die-fehlerbehebung)

## Grundlegende Überprüfungen

Bevor Sie mit der detaillierten Diagnose beginnen, führen Sie diese grundlegenden Überprüfungen durch:

1. **Visuelle Inspektion**
   - Überprüfen Sie alle Kabel und Anschlüsse auf sichtbare Schäden
   - Stellen Sie sicher, dass alle Stecker fest sitzen
   - Prüfen Sie auf Kurzschlüsse oder gebrochene Leitungen

2. **Spannungsmessung**
   - Messen Sie die Versorgungsspannung des CAN-Transceivers (sollte 3,3V sein)
   - Überprüfen Sie die Spannung zwischen CAN_H und CAN_L im Ruhezustand (sollte ca. 0V sein)

3. **Kontinuitätsprüfung**
   - Überprüfen Sie die Durchgängigkeit der CAN-Leitungen mit einem Multimeter
   - Stellen Sie sicher, dass keine Verbindung zwischen CAN_H/CAN_L und GND besteht

## Hardware-Diagnose

Verwenden Sie das mitgelieferte Diagnoseprogramm `can_hardware_diagnostic.cpp`, um die CAN-Hardware zu testen:

1. **Loopback-Test**
   - Testet die interne CAN-Hardware des ESP32 ohne externe Verbindungen
   - Sollte immer funktionieren, unabhängig von externen Faktoren
   - Wenn dieser Test fehlschlägt, liegt ein Problem mit dem ESP32 selbst vor

2. **Listen-Only-Modus**
   - Empfängt nur Nachrichten, ohne selbst zu senden
   - Nützlich, um zu überprüfen, ob der Orange Cube Nachrichten sendet
   - Zeigt an, ob die Empfangsseite der Verbindung funktioniert

3. **Signal-Test**
   - Sendet mehrere Nachrichten in schneller Folge
   - Analysiert die Erfolgsrate und Fehler
   - Gibt Hinweise auf Probleme mit der Signalqualität

## Verkabelung und Anschlüsse

Die korrekte Verkabelung ist entscheidend für die CAN-Kommunikation:

1. **ESP32 CAN-Pins**
   - GPIO5 = CAN TX (Pin 5 auf dem Freenove Breakout Board)
   - GPIO4 = CAN RX (Pin 4 auf dem Freenove Breakout Board)
   - Diese Pins sind fest mit dem CAN-Controller verbunden und können nicht geändert werden

2. **CAN-Transceiver Anschlüsse**
   - TX vom ESP32 (GPIO5) → RX am Transceiver
   - RX vom ESP32 (GPIO4) → TX am Transceiver
   - Stellen Sie sicher, dass die Pins nicht vertauscht sind

3. **Orange Cube Anschlüsse**
   - CAN_H vom Transceiver → CAN_H am Orange Cube
   - CAN_L vom Transceiver → CAN_L am Orange Cube
   - GND vom Transceiver → GND am Orange Cube (gemeinsame Masse ist wichtig!)

4. **Überprüfung der Verbindungen**
   - Messen Sie den Widerstand zwischen den Pins mit einem Multimeter
   - Überprüfen Sie die Kontinuität der Verbindungen
   - Stellen Sie sicher, dass keine Kurzschlüsse vorliegen

## Terminierung

Die korrekte Terminierung ist entscheidend für die Signalqualität:

1. **Terminierungswiderstände**
   - An beiden Enden des CAN-Bus muss ein 120-Ohm-Widerstand zwischen CAN_H und CAN_L angeschlossen sein
   - Der Orange Cube hat bereits einen eingebauten Terminierungswiderstand
   - Auf der ESP32-Seite muss ein externer 120-Ohm-Widerstand angeschlossen werden

2. **Überprüfung der Terminierung**
   - Messen Sie den Widerstand zwischen CAN_H und CAN_L mit einem Multimeter
   - Bei korrekter Terminierung sollten Sie etwa 60 Ohm messen (zwei 120-Ohm-Widerstände parallel)
   - Ohne Terminierung sollten Sie einen sehr hohen Widerstand (>1 MOhm) messen

3. **Optimale Platzierung**
   - Die Terminierungswiderstände sollten so nah wie möglich an den Endpunkten des Busses platziert werden
   - Vermeiden Sie lange Stichleitungen (Abzweigungen)

## CAN-Transceiver

Der CAN-Transceiver ist ein kritisches Element in der Kommunikationskette:

1. **Kompatibilität**
   - Stellen Sie sicher, dass der Transceiver für 3,3V-Logik geeignet ist
   - Überprüfen Sie, ob der Transceiver mit der gewählten Baudrate (500 kbps) kompatibel ist

2. **Typische Probleme**
   - Überhitzung (fühlt sich der Transceiver heiß an?)
   - Falsche Versorgungsspannung
   - Beschädigung durch elektrostatische Entladung

3. **Alternativen testen**
   - Wenn möglich, testen Sie mit einem anderen CAN-Transceiver
   - Empfohlene Modelle: SN65HVD230, MCP2551, TJA1050

## Spannungsversorgung

Eine stabile Spannungsversorgung ist wichtig für zuverlässige Kommunikation:

1. **Spannungspegel**
   - Der ESP32 arbeitet mit 3,3V-Logik
   - Stellen Sie sicher, dass der CAN-Transceiver mit 3,3V versorgt wird
   - Überprüfen Sie die Spannungspegel mit einem Multimeter

2. **Stromversorgungsqualität**
   - Verwenden Sie eine stabile Stromquelle
   - Fügen Sie Entkopplungskondensatoren hinzu (100nF zwischen VCC und GND)
   - Vermeiden Sie lange Stromversorgungsleitungen

3. **Gemeinsame Masse**
   - Stellen Sie sicher, dass ESP32, CAN-Transceiver und Orange Cube eine gemeinsame Masseverbindung haben
   - Messen Sie den Spannungsunterschied zwischen den verschiedenen GND-Punkten (sollte nahe 0V sein)

## Signalqualität

Die Signalqualität kann mit einem Oszilloskop überprüft werden:

1. **Ideale Signalform**
   - CAN_H sollte zwischen 2,5V und 3,5V schwanken
   - CAN_L sollte zwischen 2,5V und 1,5V schwanken
   - Die Differenz zwischen CAN_H und CAN_L sollte etwa 2V betragen

2. **Probleme erkennen**
   - Überschwingen oder Unterschwingen der Signale
   - Reflektionen (durch fehlende oder falsche Terminierung)
   - Rauschen oder Störungen auf den Signalen

3. **Verbesserungsmaßnahmen**
   - Verwenden Sie verdrillte Kabelpaare für CAN_H und CAN_L
   - Halten Sie die Kabellänge so kurz wie möglich
   - Vermeiden Sie die Nähe zu Störquellen (Motoren, Schaltnetzteile)

## Häufige Fehlercodes

Hier sind einige häufige ESP32 TWAI-Fehlercodes und ihre Bedeutung:

| Fehlercode | Beschreibung | Mögliche Ursachen |
|------------|--------------|-------------------|
| 259 (ESP_ERR_TIMEOUT) | Timeout beim Senden | Bus-Probleme, keine Bestätigung |
| 512 (ESP_ERR_INVALID_STATE) | Ungültiger Zustand | Bus-Off-Zustand, nicht initialisiert |
| 513 (ESP_ERR_INVALID_ARG) | Ungültiges Argument | Falsche Parameter |
| 516 (ESP_ERR_INVALID_RESPONSE) | Ungültige Antwort | Kommunikationsprobleme |

## Checkliste für die Fehlerbehebung

Verwenden Sie diese Checkliste, um systematisch Probleme zu identifizieren:

- [ ] Sind die CAN-Pins korrekt angeschlossen? (GPIO5=TX, GPIO4=RX)
- [ ] Ist der CAN-Transceiver korrekt mit dem ESP32 verbunden?
- [ ] Sind CAN_H und CAN_L korrekt mit dem Orange Cube verbunden?
- [ ] Ist die Terminierung an beiden Enden des Busses vorhanden?
- [ ] Ist die Spannungsversorgung des CAN-Transceivers stabil?
- [ ] Gibt es eine gemeinsame Masseverbindung zwischen allen Geräten?
- [ ] Ist die Baudrate auf beiden Seiten gleich (500 kbps)?
- [ ] Funktioniert der Loopback-Test auf dem ESP32?
- [ ] Werden im Listen-Only-Modus Nachrichten vom Orange Cube empfangen?
- [ ] Zeigt der Signal-Test eine gute Signalqualität?

## Nächste Schritte

Wenn Sie alle oben genannten Punkte überprüft haben und immer noch Probleme auftreten:

1. Führen Sie den Hardware-Diagnosetest durch und notieren Sie alle Fehlermeldungen
2. Überprüfen Sie die Verkabelung erneut mit einem Multimeter
3. Testen Sie mit einem anderen CAN-Transceiver
4. Reduzieren Sie die Baudrate auf 250 kbps für einen Test
5. Verwenden Sie kürzere Kabel zwischen ESP32 und Orange Cube
6. Überprüfen Sie die Konfiguration des Orange Cube in Mission Planner
