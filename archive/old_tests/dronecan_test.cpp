/**
 * ESP32 DroneCAN Test
 * 
 * Dieses Programm sendet spezifische DroneCAN-Nachrichten, die von einem Orange Cube
 * verstanden werden sollten, und empfängt alle eingehenden Nachrichten.
 */

#include <Arduino.h>
#include <ESP32CAN.h>
#include <CAN_config.h>
#include "can_config.h"

// CAN-Instanz
CAN_device_t CAN_cfg;

// Zeitpunkt der letzten gesendeten Nachricht
unsigned long lastSentTime = 0;
unsigned long lastStatusTime = 0;

// LED-Pin für visuelles Feedback
const int ledPin = 2;  // Eingebaute LED auf den meisten ESP32-Boards

// DroneCAN Message IDs
// Diese IDs sind typisch für DroneCAN/UAVCAN, aber möglicherweise nicht exakt
// die, die der Orange Cube erwartet. Wir testen verschiedene IDs.
const uint32_t DRONECAN_SERVO_ID = 0x1E0;        // Servo/Actuator Befehl
const uint32_t DRONECAN_ESC_RAW_ID = 0x2F0;      // ESC Raw Command
const uint32_t DRONECAN_NODE_STATUS_ID = 0x100;  // Node Status

void blinkLED(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(ledPin, HIGH);
    delay(100);
    digitalWrite(ledPin, LOW);
    delay(100);
  }
}

// Funktion zum Senden einer DroneCAN Servo-Nachricht
void sendDroneCANServoMessage(uint8_t servoIndex, float position) {
  // Position auf 0.0-1.0 begrenzen
  position = constrain(position, 0.0, 1.0);
  
  // 16-bit Wert berechnen (0-65535)
  uint16_t rawValue = (uint16_t)(position * 65535.0f);
  
  // Nachricht erstellen
  CAN_frame_t tx_frame;
  tx_frame.FIR.B.FF = CAN_frame_std;      // Standard-Frame
  tx_frame.MsgID = DRONECAN_SERVO_ID;     // Servo Message ID
  tx_frame.FIR.B.DLC = 4;                 // 4 Bytes Datenlänge
  
  // Daten: [Servo-Index, Wert-LSB, Wert-MSB, 0]
  tx_frame.data.u8[0] = servoIndex;       // Servo-Index (0-15)
  tx_frame.data.u8[1] = rawValue & 0xFF;  // LSB des Werts
  tx_frame.data.u8[2] = (rawValue >> 8) & 0xFF; // MSB des Werts
  tx_frame.data.u8[3] = 0;                // Reserviert/Flags
  
  // Nachricht senden
  esp_err_t result = ESP32Can.CANWriteFrame(&tx_frame);
  
  if (result == ESP_OK) {
    Serial.printf("DroneCAN Servo Nachricht gesendet: Index=%d, Position=%.2f, Raw=%u\n",
                  servoIndex, position, rawValue);
  } else {
    Serial.printf("Fehler beim Senden der DroneCAN Servo-Nachricht! Fehlercode: %d\n", result);
  }
}

// Funktion zum Senden einer DroneCAN ESC Raw-Nachricht
void sendDroneCANESCMessage(uint8_t escIndex, float throttle) {
  // Throttle auf 0.0-1.0 begrenzen
  throttle = constrain(throttle, 0.0, 1.0);
  
  // 16-bit Wert berechnen (0-65535)
  uint16_t rawValue = (uint16_t)(throttle * 65535.0f);
  
  // Nachricht erstellen
  CAN_frame_t tx_frame;
  tx_frame.FIR.B.FF = CAN_frame_std;      // Standard-Frame
  tx_frame.MsgID = DRONECAN_ESC_RAW_ID;   // ESC Raw Message ID
  tx_frame.FIR.B.DLC = 4;                 // 4 Bytes Datenlänge
  
  // Daten: [ESC-Index, Wert-LSB, Wert-MSB, 0]
  tx_frame.data.u8[0] = escIndex;         // ESC-Index (0-15)
  tx_frame.data.u8[1] = rawValue & 0xFF;  // LSB des Werts
  tx_frame.data.u8[2] = (rawValue >> 8) & 0xFF; // MSB des Werts
  tx_frame.data.u8[3] = 0;                // Reserviert/Flags
  
  // Nachricht senden
  esp_err_t result = ESP32Can.CANWriteFrame(&tx_frame);
  
  if (result == ESP_OK) {
    Serial.printf("DroneCAN ESC Nachricht gesendet: Index=%d, Throttle=%.2f, Raw=%u\n",
                  escIndex, throttle, rawValue);
  } else {
    Serial.printf("Fehler beim Senden der DroneCAN ESC-Nachricht! Fehlercode: %d\n", result);
  }
}

// Funktion zum Senden einer DroneCAN Node Status-Nachricht
void sendDroneCANNodeStatus() {
  // Nachricht erstellen
  CAN_frame_t tx_frame;
  tx_frame.FIR.B.FF = CAN_frame_std;        // Standard-Frame
  tx_frame.MsgID = DRONECAN_NODE_STATUS_ID; // Node Status Message ID
  tx_frame.FIR.B.DLC = 8;                   // 8 Bytes Datenlänge
  
  // Daten für Node Status (vereinfacht)
  tx_frame.data.u8[0] = 0x00;  // Uptime LSB
  tx_frame.data.u8[1] = 0x00;  // Uptime
  tx_frame.data.u8[2] = 0x00;  // Uptime
  tx_frame.data.u8[3] = 0x00;  // Uptime MSB
  tx_frame.data.u8[4] = 0x00;  // Health (0 = OK)
  tx_frame.data.u8[5] = 0x01;  // Mode (1 = Operational)
  tx_frame.data.u8[6] = 0x00;  // Sub-Mode
  tx_frame.data.u8[7] = 0x00;  // Vendor-specific status
  
  // Nachricht senden
  esp_err_t result = ESP32Can.CANWriteFrame(&tx_frame);
  
  if (result == ESP_OK) {
    Serial.println("DroneCAN Node Status Nachricht gesendet");
  } else {
    Serial.printf("Fehler beim Senden der Node Status-Nachricht! Fehlercode: %d\n", result);
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
  Serial.println("ESP32 DroneCAN Test");
  Serial.println("==============================================");
  Serial.println("Dieser Test sendet spezifische DroneCAN-Nachrichten.");
  Serial.println("Wenn Sie diese Nachricht sehen, funktioniert die serielle Kommunikation!");
  
  // Hardware-Informationen ausgeben
  Serial.printf("ESP32 Chip Revision: %d\n", ESP.getChipRevision());
  Serial.printf("ESP32 SDK Version: %s\n", ESP.getSdkVersion());
  
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
  
  Serial.println("\nSystem bereit - Sende DroneCAN-Nachrichten...");
}

void loop() {
  // Status-LED blinken lassen, um zu zeigen, dass das Programm läuft
  static bool ledState = false;
  if (millis() % 500 < 50) {
    digitalWrite(ledPin, ledState);
    ledState = !ledState;
  }
  
  // CAN-Nachrichten empfangen
  CAN_frame_t rx_frame;
  if (xQueueReceive(CAN_cfg.rx_queue, &rx_frame, 0) == pdTRUE) {
    // Debug-Ausgabe für empfangene Nachrichten
    Serial.printf("CAN Nachricht empfangen: ID=0x%X, Länge=%d, Daten: ", 
                  rx_frame.MsgID, rx_frame.FIR.B.DLC);
    
    // Alle Bytes der Nachricht ausgeben
    for (int i = 0; i < rx_frame.FIR.B.DLC; i++) {
      Serial.printf("%02X ", rx_frame.data.u8[i]);
    }
    Serial.println();
    
    // Schnelles Blinken bei empfangener Nachricht
    blinkLED(1);
  }
  
  // Periodisch DroneCAN-Nachrichten senden (alle 100ms)
  if (millis() - lastSentTime > 100) {
    lastSentTime = millis();
    
    // Oszillierende Werte für die Tests
    static float value = 0.0;
    static float step = 0.01;
    
    value += step;
    if (value >= 1.0 || value <= 0.0) {
      step = -step;
    }
    
    // Verschiedene DroneCAN-Nachrichten senden
    
    // 1. Servo-Nachrichten für Kanäle 0-3
    for (int i = 0; i < 4; i++) {
      float channelValue = (i % 2 == 0) ? value : 1.0 - value;  // Abwechselnd normal und invertiert
      sendDroneCANServoMessage(i, channelValue);
    }
    
    // 2. ESC-Nachrichten für Kanäle 0-3
    for (int i = 0; i < 4; i++) {
      float channelValue = (i % 2 == 0) ? value : 1.0 - value;  // Abwechselnd normal und invertiert
      sendDroneCANESCMessage(i, channelValue);
    }
    
    // 3. Node Status-Nachricht (seltener senden)
    static int counter = 0;
    if (counter++ % 10 == 0) {  // Nur jede 10. Iteration
      sendDroneCANNodeStatus();
    }
  }
  
  // Regelmäßiger Status-Bericht
  if (millis() - lastStatusTime > 5000) {
    lastStatusTime = millis();
    Serial.printf("Status: Laufzeit=%d Sekunden\n", millis()/1000);
    Serial.println("Sende DroneCAN-Nachrichten für Servos und ESCs...");
    Serial.println("Wenn keine 'CAN Nachricht empfangen' Meldungen erscheinen, werden keine Nachrichten empfangen.");
  }
}
