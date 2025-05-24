/**
 * ESP32 Improved DroneCAN Test for Orange Cube
 *
 * Dieses Programm implementiert DroneCAN 1.0 Kommunikation zwischen einem ESP32 und
 * einem Orange Cube Autopiloten. Es sendet korrekt formatierte DroneCAN-Nachrichten
 * und empfängt alle eingehenden Nachrichten mit detaillierter Diagnose.
 */

#include <Arduino.h>
#include <ESP32CAN.h>
#include <CAN_config.h>
#include "can_config.h"

// CAN-Instanz
CAN_device_t CAN_cfg;

// Zeitpunkte für verschiedene Aktionen
unsigned long lastNodeStatusTime = 0;
unsigned long lastServoMsgTime = 0;
unsigned long lastStatusReportTime = 0;
unsigned long lastHeartbeatTime = 0;
unsigned long startTime = 0;

// LED-Pin für visuelles Feedback
const int ledPin = 2;  // Eingebaute LED auf den meisten ESP32-Boards

// DroneCAN Konfiguration
#define DRONECAN_NODE_ID 125  // Unsere Node-ID (1-127)
#define DRONECAN_PRIORITY 24  // Standard-Priorität (niedrigere Werte = höhere Priorität)

// DroneCAN Message IDs (nach DroneCAN 1.0 Spezifikation)
// Format: CAN-ID = ((Priorität << 24) | (Message-Type-ID << 8) | (Source-Node-ID))
// Für Servo/Actuator Commands: Message-Type-ID = 1010 (0x3F2)
// Für Node Status: Message-Type-ID = 341 (0x155)

// Wichtige DroneCAN Message Type IDs
#define DRONECAN_MSG_TYPE_NODE_STATUS 341      // 0x155
#define DRONECAN_MSG_TYPE_ACTUATOR_COMMAND 1010 // 0x3F2
#define DRONECAN_MSG_TYPE_ESC_STATUS 1034      // 0x40A

// Vollständige CAN-IDs berechnen
uint32_t getCANId(uint16_t messageTypeId, uint8_t sourceNodeId, uint8_t priority = DRONECAN_PRIORITY) {
  return ((priority << 24) | (messageTypeId << 8) | sourceNodeId);
}

// Hilfsfunktion zum Blinken der LED
void blinkLED(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(ledPin, HIGH);
    delay(50);
    digitalWrite(ledPin, LOW);
    delay(50);
  }
}

// Funktion zum Senden einer DroneCAN Node Status-Nachricht
void sendNodeStatus() {
  // Berechne Uptime in Sekunden seit Start
  uint32_t uptimeSeconds = (millis() - startTime) / 1000;

  // Nachricht erstellen
  CAN_frame_t tx_frame;
  tx_frame.FIR.B.FF = CAN_frame_std;  // Standard-Frame
  tx_frame.MsgID = getCANId(DRONECAN_MSG_TYPE_NODE_STATUS, DRONECAN_NODE_ID);
  tx_frame.FIR.B.DLC = 8;  // 8 Bytes Datenlänge

  // Daten für Node Status nach DroneCAN 1.0 Spezifikation
  tx_frame.data.u8[0] = uptimeSeconds & 0xFF;          // Uptime LSB
  tx_frame.data.u8[1] = (uptimeSeconds >> 8) & 0xFF;   // Uptime
  tx_frame.data.u8[2] = (uptimeSeconds >> 16) & 0xFF;  // Uptime
  tx_frame.data.u8[3] = (uptimeSeconds >> 24) & 0xFF;  // Uptime MSB
  tx_frame.data.u8[4] = 0;  // Health (0 = OK)
  tx_frame.data.u8[5] = 1;  // Mode (1 = Operational)
  tx_frame.data.u8[6] = 0;  // Sub-Mode
  tx_frame.data.u8[7] = 0;  // Vendor-specific status

  // Nachricht senden
  esp_err_t result = ESP32Can.CANWriteFrame(&tx_frame);

  if (result == ESP_OK) {
    Serial.printf("DroneCAN Node Status gesendet: ID=0x%X, Uptime=%u\n",
                  tx_frame.MsgID, uptimeSeconds);
  } else {
    Serial.printf("Fehler beim Senden der Node Status-Nachricht! Fehlercode: %d\n", result);
  }
}

// Funktion zum Senden einer DroneCAN Actuator Command-Nachricht
void sendActuatorCommand(uint8_t actuatorIndex, float command) {
  // Command auf 0.0-1.0 begrenzen
  command = constrain(command, 0.0, 1.0);

  // Umwandlung in 16-bit Wert (0-65535)
  uint16_t rawValue = (uint16_t)(command * 65535.0f);

  // Nachricht erstellen
  CAN_frame_t tx_frame;
  tx_frame.FIR.B.FF = CAN_frame_std;  // Standard-Frame
  tx_frame.MsgID = getCANId(DRONECAN_MSG_TYPE_ACTUATOR_COMMAND, DRONECAN_NODE_ID);
  tx_frame.FIR.B.DLC = 4;  // 4 Bytes Datenlänge

  // Daten nach DroneCAN 1.0 Spezifikation
  tx_frame.data.u8[0] = actuatorIndex;  // Actuator Index (0-15)
  tx_frame.data.u8[1] = rawValue & 0xFF;  // Command LSB
  tx_frame.data.u8[2] = (rawValue >> 8) & 0xFF;  // Command MSB
  tx_frame.data.u8[3] = 0;  // Reserved/Flags

  // Nachricht senden
  esp_err_t result = ESP32Can.CANWriteFrame(&tx_frame);

  if (result == ESP_OK) {
    Serial.printf("DroneCAN Actuator Command gesendet: ID=0x%X, Index=%d, Wert=%.2f\n",
                  tx_frame.MsgID, actuatorIndex, command);
  } else {
    Serial.printf("Fehler beim Senden der Actuator Command-Nachricht! Fehlercode: %d\n", result);
  }
}

// Funktion zum Analysieren empfangener CAN-Nachrichten
void analyzeCANMessage(CAN_frame_t &frame) {
  // Extrahiere Message Type ID und Source Node ID aus der CAN-ID
  uint16_t messageTypeId = (frame.MsgID >> 8) & 0xFFFF;
  uint8_t sourceNodeId = frame.MsgID & 0xFF;

  Serial.printf("CAN Nachricht empfangen: ID=0x%X, Länge=%d, Daten: ",
                frame.MsgID, frame.FIR.B.DLC);

  // Alle Bytes der Nachricht ausgeben
  for (int i = 0; i < frame.FIR.B.DLC; i++) {
    Serial.printf("%02X ", frame.data.u8[i]);
  }
  Serial.println();

  // Zusätzliche Analyse basierend auf dem Message Type
  Serial.printf("  Analyse: Message Type ID=0x%X, Source Node ID=%d\n",
                messageTypeId, sourceNodeId);

  // Bekannte Message Types analysieren
  switch (messageTypeId) {
    case DRONECAN_MSG_TYPE_NODE_STATUS:
      Serial.println("  -> Node Status Nachricht");
      break;

    case DRONECAN_MSG_TYPE_ACTUATOR_COMMAND:
      Serial.println("  -> Actuator Command Nachricht");
      break;

    case DRONECAN_MSG_TYPE_ESC_STATUS:
      Serial.println("  -> ESC Status Nachricht");
      break;

    default:
      Serial.println("  -> Unbekannter Message Type");
      break;
  }
}

void setup() {
  // LED für visuelles Feedback initialisieren
  pinMode(ledPin, OUTPUT);

  // Schnelles Blinken beim Start
  blinkLED(5);

  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(1000);  // Warte, bis die serielle Verbindung bereit ist

  Serial.println("\n\n\n");
  Serial.println("==============================================");
  Serial.println("ESP32 Improved DroneCAN Test für Orange Cube");
  Serial.println("==============================================");
  Serial.println("Dieser Test implementiert DroneCAN 1.0 Kommunikation.");
  Serial.println("Wenn Sie diese Nachricht sehen, funktioniert die serielle Kommunikation!");

  // Hardware-Informationen ausgeben
  Serial.printf("ESP32 Chip Revision: %d\n", ESP.getChipRevision());
  Serial.printf("ESP32 SDK Version: %s\n", ESP.getSdkVersion());
  Serial.printf("ESP32 CPU Frequenz: %d MHz\n", ESP.getCpuFreqMHz());

  // CAN-Konfiguration
  Serial.println("\nCAN-Initialisierung...");

  // CAN-Konfiguration mit Pins aus can_config.h
  CAN_cfg.speed = CAN_SPEED_1000KBPS;
  CAN_cfg.tx_pin_id = CAN_TX_PIN;  // Aus can_config.h
  CAN_cfg.rx_pin_id = CAN_RX_PIN;  // Aus can_config.h
  CAN_cfg.rx_queue = xQueueCreate(10, sizeof(CAN_frame_t));

  // CAN-Modul initialisieren
  esp_err_t result = ESP32Can.CANInit();

  if (result == ESP_OK) {
    Serial.printf("CAN erfolgreich initialisiert: TX Pin=%d, RX Pin=%d\n",
                  CAN_cfg.tx_pin_id, CAN_cfg.rx_pin_id);
    // Erfolgreiches Blinken
    blinkLED(3);
  } else {
    Serial.printf("CAN-Initialisierung fehlgeschlagen! Fehlercode: %d\n", result);
    // Fehlerblinken
    while (1) {
      blinkLED(10);
      delay(1000);
    }
  }

  // Startzeit speichern für Uptime-Berechnung
  startTime = millis();

  Serial.println("\nSystem bereit - Starte DroneCAN-Kommunikation...");
  Serial.printf("DroneCAN Node ID: %d\n", DRONECAN_NODE_ID);
}

void loop() {
  // Status-LED blinken lassen, um zu zeigen, dass das Programm läuft
  static bool ledState = false;
  if (millis() % 1000 < 50) {
    digitalWrite(ledPin, ledState);
    ledState = !ledState;
  }

  // CAN-Nachrichten empfangen und analysieren
  CAN_frame_t rx_frame;
  if (xQueueReceive(CAN_cfg.rx_queue, &rx_frame, 0) == pdTRUE) {
    analyzeCANMessage(rx_frame);
    blinkLED(1);  // Kurzes Blinken bei empfangener Nachricht
  }

  // Node Status regelmäßig senden (alle 1000ms)
  if (millis() - lastNodeStatusTime > 1000) {
    lastNodeStatusTime = millis();
    sendNodeStatus();
  }

  // Actuator Commands senden (alle 100ms)
  if (millis() - lastServoMsgTime > 100) {
    lastServoMsgTime = millis();

    // Oszillierende Werte für die Tests
    static float value = 0.0;
    static float step = 0.01;

    value += step;
    if (value >= 1.0 || value <= 0.0) {
      step = -step;
    }

    // Actuator Commands für Kanäle 0-3 senden
    for (int i = 0; i < 4; i++) {
      float channelValue = (i % 2 == 0) ? value : 1.0 - value;  // Abwechselnd normal und invertiert
      sendActuatorCommand(i, channelValue);
    }
  }

  // Regelmäßiger Status-Bericht mit erweiterten Debug-Informationen
  if (millis() - lastStatusReportTime > 5000) {
    lastStatusReportTime = millis();
    Serial.printf("Status: Laufzeit=%d Sekunden\n", (millis() - startTime) / 1000);
    Serial.println("Sende DroneCAN-Nachrichten (Node Status und Actuator Commands)...");

    // Erweiterte Debug-Informationen
    Serial.println("\n--- ERWEITERTE DEBUG-INFORMATIONEN ---");
    Serial.printf("ESP32 Chip ID: %llX\n", ESP.getEfuseMac());
    Serial.printf("CAN TX Pin: %d, RX Pin: %d\n", CAN_cfg.tx_pin_id, CAN_cfg.rx_pin_id);
    Serial.printf("CAN Baudrate: %d\n", CAN_SPEED_1000KBPS);
    Serial.printf("DroneCAN Node ID: %d\n", DRONECAN_NODE_ID);

    // Hinweise zur Fehlersuche
    Serial.println("Mögliche Ursachen für Kommunikationsprobleme:");
    Serial.println("- Falsche Verkabelung (CANH/CANL vertauscht oder TX/RX vertauscht)");
    Serial.println("- Fehlende oder falsche Terminierung");
    Serial.println("- Unterschiedliche Baudraten");
    Serial.println("- Probleme mit der Stromversorgung des CAN-Transceivers");
    Serial.println("- Falsche CAN-Parameter im Orange Cube");

    Serial.println("\nWenn keine 'CAN Nachricht empfangen' Meldungen erscheinen, werden keine Nachrichten empfangen.");
    Serial.println("Überprüfen Sie die Verkabelung und die Konfiguration des Orange Cube.");
    Serial.println("--- ENDE DEBUG-INFORMATIONEN ---\n");
  }
}
