/**
 * ESP32 CAN Diagnosetest
 *
 * Erweiterter Test für die CAN-Kommunikation mit detaillierter Fehlerdiagnose.
 * Testet verschiedene Baudrates und Nachrichtenformate.
 */

#include <Arduino.h>
#include <ESP32CAN.h>
#include <CAN_config.h>
#include "can_config.h"

// CAN-Instanz
CAN_device_t CAN_cfg;

// LED-Pin für visuelles Feedback
const int ledPin = 2;  // Eingebaute LED auf den meisten ESP32-Boards

// Baudrate-Einstellungen
const CAN_speed_t baudrates[] = {
  CAN_SPEED_500KBPS,   // Mit 500 kbps beginnen
  CAN_SPEED_250KBPS,
  CAN_SPEED_125KBPS,
  CAN_SPEED_1000KBPS
};
const char* baudrateNames[] = {
  "500 kbps",
  "250 kbps",
  "125 kbps",
  "1000 kbps"
};
const int numBaudrates = 4;
int currentBaudrateIndex = 0;

// CAN-IDs für Tests
const uint32_t testIds[] = {
  0x123,    // Standard Test-ID
  0x3F2,    // DroneCAN Actuator Command
  0x155,    // DroneCAN Node Status
  0x001,    // Niedrige ID
  0x7FF     // Höchste Standard-ID
};
const int numIds = 5;

// Zeitpunkte für verschiedene Aktionen
unsigned long lastSentTime = 0;
unsigned long lastBaudrateChangeTime = 0;
unsigned long lastStatusTime = 0;
unsigned long startTime = 0;

// Zähler
uint8_t messageCounter = 0;
uint8_t receivedMessages = 0;

// Hilfsfunktion zum Blinken der LED
void blinkLED(int times, int duration = 50) {
  for (int i = 0; i < times; i++) {
    digitalWrite(ledPin, HIGH);
    delay(duration);
    digitalWrite(ledPin, LOW);
    delay(duration);
  }
}

// Funktion zur Initialisierung des CAN-Controllers mit der aktuellen Baudrate
bool initCAN() {
  // CAN-Konfiguration
  CAN_cfg.speed = baudrates[currentBaudrateIndex];
  CAN_cfg.tx_pin_id = CAN_TX_PIN;  // Aus can_config.h
  CAN_cfg.rx_pin_id = CAN_RX_PIN;  // Aus can_config.h
  CAN_cfg.rx_queue = xQueueCreate(10, sizeof(CAN_frame_t));

  // CAN-Modul initialisieren
  esp_err_t result = ESP32Can.CANInit();

  if (result == ESP_OK) {
    Serial.printf("CAN erfolgreich initialisiert mit %s: TX Pin=%d, RX Pin=%d\n",
                  baudrateNames[currentBaudrateIndex], CAN_cfg.tx_pin_id, CAN_cfg.rx_pin_id);
    return true;
  } else {
    Serial.printf("CAN-Initialisierung fehlgeschlagen mit %s! Fehlercode: %d\n",
                  baudrateNames[currentBaudrateIndex], result);
    return false;
  }
}

// Funktion zum Senden einer CAN-Testnachricht
void sendCANMessage(uint32_t id) {
  // Test-Nachricht erstellen
  CAN_frame_t tx_frame;
  tx_frame.FIR.B.FF = CAN_frame_std;  // Standard-Frame
  tx_frame.MsgID = id;                // Message ID
  tx_frame.FIR.B.DLC = 8;             // Datenlänge (8 Bytes)

  // Testdaten
  tx_frame.data.u8[0] = messageCounter++;
  tx_frame.data.u8[1] = 0xAA;
  tx_frame.data.u8[2] = 0xBB;
  tx_frame.data.u8[3] = 0xCC;
  tx_frame.data.u8[4] = 0xDD;
  tx_frame.data.u8[5] = 0xEE;
  tx_frame.data.u8[6] = 0xFF;
  tx_frame.data.u8[7] = currentBaudrateIndex;  // Aktuelle Baudrate als Marker

  // Nachricht senden
  esp_err_t result = ESP32Can.CANWriteFrame(&tx_frame);

  if (result == ESP_OK) {
    Serial.printf("CAN Nachricht gesendet: ID=0x%X, Counter=%d, Baudrate=%s\n",
                  tx_frame.MsgID, messageCounter-1, baudrateNames[currentBaudrateIndex]);
    blinkLED(1, 20);  // Kurzes Blinken bei gesendeter Nachricht
  } else {
    Serial.printf("Fehler beim Senden der CAN-Nachricht! Fehlercode: %d\n", result);
  }
}

void setup() {
  // LED initialisieren
  pinMode(ledPin, OUTPUT);

  // Schnelles Blinken beim Start
  blinkLED(5);

  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(2000);  // Längere Verzögerung für Stabilität

  Serial.println("\n\n\n");
  Serial.println("==============================================");
  Serial.println("ESP32 CAN Diagnosetest");
  Serial.println("==============================================");
  Serial.println("Dieser Test führt eine detaillierte CAN-Diagnose durch.");
  Serial.println("Er testet verschiedene Baudrates und Nachrichtenformate.");

  // CAN initialisieren mit der ersten Baudrate
  if (!initCAN()) {
    Serial.println("Kritischer Fehler bei der CAN-Initialisierung!");
    while (1) {
      blinkLED(10, 100);  // Schnelles Blinken bei Fehler
      delay(1000);
    }
  }

  // Startzeit speichern
  startTime = millis();
  lastBaudrateChangeTime = startTime;

  Serial.println("\nCAN-Diagnosetest gestartet. Sende Testnachrichten...");
}

void loop() {
  // Status-LED regelmäßig blinken lassen
  static bool ledState = false;
  if (millis() % 1000 < 50) {
    digitalWrite(ledPin, ledState);
    ledState = !ledState;
  }

  // CAN-Nachrichten empfangen
  CAN_frame_t rx_frame;
  if (xQueueReceive(CAN_cfg.rx_queue, &rx_frame, 0) == pdTRUE) {
    receivedMessages++;

    Serial.printf("CAN Nachricht empfangen: ID=0x%X, Länge=%d, Daten: ",
                  rx_frame.MsgID, rx_frame.FIR.B.DLC);

    // Alle Bytes der Nachricht ausgeben
    for (int i = 0; i < rx_frame.FIR.B.DLC; i++) {
      Serial.printf("%02X ", rx_frame.data.u8[i]);
    }
    Serial.println();

    // Schnelles Blinken bei empfangener Nachricht
    blinkLED(3, 30);
  }

  // Periodisch CAN-Nachrichten mit verschiedenen IDs senden (alle 500ms)
  if (millis() - lastSentTime > 500) {
    lastSentTime = millis();

    // Wechselnde IDs verwenden
    static int idIndex = 0;
    sendCANMessage(testIds[idIndex]);
    idIndex = (idIndex + 1) % numIds;
  }

  // Baudrate alle 30 Sekunden wechseln
  if (millis() - lastBaudrateChangeTime > 30000) {
    lastBaudrateChangeTime = millis();

    // Zur nächsten Baudrate wechseln
    currentBaudrateIndex = (currentBaudrateIndex + 1) % numBaudrates;

    Serial.printf("\n--- Wechsle zu Baudrate: %s ---\n", baudrateNames[currentBaudrateIndex]);

    // CAN-Controller neu initialisieren mit der neuen Baudrate
    ESP32Can.CANStop();
    delay(500);  // Kurze Pause

    if (!initCAN()) {
      Serial.println("Fehler beim Wechseln der Baudrate!");
    } else {
      Serial.println("Baudrate erfolgreich gewechselt.");
      blinkLED(2, 200);  // Längeres Blinken bei Baudratenwechsel
    }
  }

  // Regelmäßiger Status-Bericht
  if (millis() - lastStatusTime > 5000) {
    lastStatusTime = millis();

    unsigned long runtime = (millis() - startTime) / 1000;
    Serial.printf("\n--- STATUS NACH %lu SEKUNDEN ---\n", runtime);
    Serial.printf("Aktuelle Baudrate: %s\n", baudrateNames[currentBaudrateIndex]);
    Serial.printf("Gesendete Nachrichten: %d\n", messageCounter);
    Serial.printf("Empfangene Nachrichten: %d\n", receivedMessages);

    if (receivedMessages == 0) {
      Serial.println("\nKeine Nachrichten empfangen! Mögliche Ursachen:");
      Serial.println("1. Falsche Verkabelung:");
      Serial.println("   - ESP32 GPIO5 (TX) → RX am CAN-Transceiver");
      Serial.println("   - ESP32 GPIO4 (RX) → TX am CAN-Transceiver");
      Serial.println("   - CANH vom Transceiver → CANH am Orange Cube");
      Serial.println("   - CANL vom Transceiver → CANL am Orange Cube");
      Serial.println("2. Falsche Baudrate - Der Test wechselt automatisch zwischen Baudraten");
      Serial.println("3. Fehlende oder falsche Terminierung (120 Ohm an beiden Enden)");
      Serial.println("4. Probleme mit der Stromversorgung des CAN-Transceivers");
      Serial.println("5. Orange Cube nicht korrekt konfiguriert");
    }

    Serial.println("--- ENDE STATUS ---\n");
  }
}
