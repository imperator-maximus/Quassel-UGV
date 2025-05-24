# ESP32 DroneCAN mit Auto-Reset

Dieses Projekt implementiert eine DroneCAN-Kommunikation zwischen einem ESP32 und einem Orange Cube Autopiloten mit automatischer Zurücksetzung des TWAI-Treibers vor jeder Nachricht.

## Funktionsweise

1. **Auto-Reset vor jeder Nachricht**
   - Der TWAI-Treiber wird vor jeder Nachricht zurückgesetzt
   - Dies verhindert BUS-OFF-Zustände und ermöglicht zuverlässige Kommunikation
   - Bewährte Lösung für Hardware-Probleme mit dem ESP32 CAN-Controller

2. **Fehlerbehandlung**
   - Automatische Erkennung und Behebung von BUS-OFF-Zuständen
   - Regelmäßige Statusprüfung des CAN-Controllers
   - Zuverlässige Wiederherstellung nach Fehlern

3. **Diagnosefunktionen**
   - Detaillierte Statusanzeige mit allen relevanten Fehlerzählern
   - Separate Hardware-Diagnoseanwendung für Hardwaretests
   - Umfassende Fehlerbehebungsanleitung für Hardware-Probleme

4. **Zusätzliche Diagnosetools**
   - Simple Loopback Test für grundlegende Funktionsprüfung
   - Advanced Loopback Test für detaillierte Analyse
   - Timeout Investigation für spezifische Fehleranalyse

## Verwendung

### Adaptiver Auto-Reset-Code

Der adaptive Auto-Reset-Code ist die Hauptanwendung für die DroneCAN-Kommunikation mit dem Orange Cube. Er bietet folgende Funktionen:

1. **Serielle Befehle**
   - `s`: Status anzeigen
   - `n`: Node Status senden
   - `r`: TWAI-Treiber zurücksetzen
   - `d`: Detaillierte Diagnose anzeigen
   - `l`: In Listen-Only-Modus wechseln (nur empfangen)
   - `n`: In normalen Modus zurückkehren

2. **Automatische Funktionen**
   - Regelmäßige Statusprüfung
   - Automatisches Senden von Node Status-Nachrichten
   - Adaptive Überwachung und Zurücksetzung des TWAI-Treibers

### Hardware-Diagnose-Tool

Das Hardware-Diagnose-Tool ist eine separate Anwendung, die speziell für die Diagnose von Hardware-Problemen entwickelt wurde:

1. **Testmodi**
   - `1`: Loopback-Test (interne Schleife)
   - `2`: Listen-Only-Modus (nur empfangen)
   - `3`: Normaler Modus (senden und empfangen)
   - `4`: Signal-Test durchführen

2. **Diagnosefunktionen**
   - `s`: Status anzeigen
   - `d`: Diagnose-Informationen anzeigen
   - `t`: Test-Nachricht senden

## Installation

### PlatformIO Helper verwenden

Für die einfachste Installation verwenden Sie den mitgelieferten PlatformIO Helper:

```
platformio-helper.bat
```

Dieser bietet ein Menü mit folgenden Optionen:
1. Projekt kompilieren
2. Projekt hochladen
3. Seriellen Monitor öffnen
4. Adaptiven Auto-Reset-Code hochladen
5. Hardware-Diagnose-Tool hochladen

### Originalen Auto-Reset-Code installieren

Alternativ können Sie das mitgelieferte Skript verwenden, um den originalen Auto-Reset-Code direkt zu installieren:

```
run-fixed-original-auto-reset.bat
```

Diese Version setzt den TWAI-Treiber vor jeder Nachricht zurück, was die zuverlässigste Methode für die Kommunikation mit dem Orange Cube ist.

### Hardware-Diagnose-Tool installieren

Oder verwenden Sie das mitgelieferte Skript, um das Hardware-Diagnose-Tool direkt zu installieren:

```
run-diagnostic.bat
```

### Hinweis zu PlatformIO

Falls Sie Probleme mit den PlatformIO-Befehlen in der Kommandozeile haben, verwenden Sie die mitgelieferten Batch-Skripte oder den PlatformIO Helper. Diese verwenden den vollständigen Pfad zum PlatformIO-Executable.

## Hardware-Fehlerbehebung

Bei Hardware-Problemen folgen Sie der umfassenden Anleitung zur Fehlerbehebung:

```
can_hardware_troubleshooting.md
```

Diese Anleitung enthält detaillierte Informationen zu:
- Grundlegenden Überprüfungen
- Verkabelung und Anschlüssen
- Terminierung
- CAN-Transceiver
- Spannungsversorgung
- Signalqualität
- Häufigen Fehlercodes

## Konfiguration

Die wichtigsten Konfigurationsparameter befinden sich am Anfang der Dateien:

### Adaptiver Auto-Reset-Code (auto_reset_dronecan.cpp)

```cpp
// DroneCAN Konfiguration
#define DRONECAN_NODE_ID 125  // Unsere Node-ID (1-127)
#define DRONECAN_PRIORITY 24  // Standard-Priorität (niedrigere Werte = höhere Priorität)

// Schwellenwerte für adaptive Reset-Strategie
#define TX_ERROR_THRESHOLD 64         // TX-Fehler-Schwellenwert für Reset
#define BUS_ERROR_THRESHOLD 20        // Bus-Fehler-Schwellenwert für Reset
#define CONSECUTIVE_ERRORS_THRESHOLD 3 // Anzahl aufeinanderfolgender Fehler für Reset
```

### Hardware-Diagnose-Tool (can_hardware_diagnostic.cpp)

```cpp
// Pin-Definitionen
#define LED_PIN    GPIO_NUM_2  // Onboard-LED für Statusanzeige
```

## Fehlerbehebung

### Häufige Probleme und Lösungen

1. **BUS-OFF-Zustand**
   - Problem: Der CAN-Controller geht in den BUS-OFF-Zustand
   - Lösung: Überprüfen Sie die Hardware-Verbindungen und Terminierung

2. **Keine Nachrichten vom Orange Cube**
   - Problem: Es werden keine Nachrichten vom Orange Cube empfangen
   - Lösung: Verwenden Sie den Listen-Only-Modus, um zu prüfen, ob der Orange Cube sendet

3. **Hohe Fehlerraten**
   - Problem: Viele Sendefehler oder Bus-Fehler
   - Lösung: Führen Sie den Signal-Test durch und überprüfen Sie die Verkabelung

4. **Instabile Kommunikation**
   - Problem: Kommunikation funktioniert zeitweise, bricht aber immer wieder ab
   - Lösung: Passen Sie die Schwellenwerte für die adaptive Reset-Strategie an

## Technische Details

### DroneCAN-Protokoll

Das Projekt implementiert das DroneCAN 1.0-Protokoll mit folgenden Nachrichtentypen:

- Node Status (ID: 341)
- Actuator Command (ID: 1010)
- ESC Status (ID: 1034)

### ESP32 TWAI-Treiber

Der ESP32 verwendet den TWAI-Treiber (Two-Wire Automotive Interface) für die CAN-Kommunikation:

- Baudrate: 500 kbps
- Pins: GPIO5 (TX) und GPIO4 (RX)
- Modi: Normal, Listen-Only, No-ACK (Loopback)

## Weiterentwicklung

Mögliche zukünftige Verbesserungen:

1. Implementierung weiterer DroneCAN-Nachrichtentypen
2. Unterstützung für dynamische Node-ID-Zuweisung
3. Verbesserte Fehlerprotokollierung und -analyse
4. Integration mit anderen Sensoren und Aktoren
