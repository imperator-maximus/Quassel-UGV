/**
 * ESP32 CAN Test - Verbesserte Version
 *
 * Dieses Programm sendet periodisch CAN-Nachrichten und empfängt alle eingehenden Nachrichten.
 * Es hilft, die CAN-Hardware und -Verbindung zu testen.
 *
 * Diese Version enthält zusätzliche Debug-Ausgaben und Statusmeldungen.
 */

#include <Arduino.h>
#include <ESP32CAN.h>
#include <CAN_config.h>
#include "can_config.h"  // Verwende die vorhandene Konfigurationsdatei

// CAN-Instanz
CAN_device_t CAN_cfg;

// Zeitpunkt der letzten gesendeten Nachricht
unsigned long lastSentTime = 0;
unsigned long lastStatusTime = 0;

// LED-Pin für visuelles Feedback
const int ledPin = 2;  // Eingebaute LED auf den meisten ESP32-Boards

void blinkLED(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(ledPin, HIGH);
    delay(100);
    digitalWrite(ledPin, LOW);
    delay(100);
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
  Serial.println("ESP32 CAN Test - Verbesserte Version");
  Serial.println("==============================================");
  Serial.println("Dieser Test sendet und empfängt CAN-Nachrichten.");
  Serial.println("Wenn Sie diese Nachricht sehen, funktioniert die serielle Kommunikation!");

  // Hardware-Informationen ausgeben
  Serial.printf("ESP32 Chip Revision: %d\n", ESP.getChipRevision());
  Serial.printf("ESP32 SDK Version: %s\n", ESP.getSdkVersion());
  Serial.printf("ESP32 CPU Frequenz: %d MHz\n", ESP.getCpuFreqMHz());
  Serial.printf("ESP32 Flash Größe: %d bytes\n", ESP.getFlashChipSize());

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

  Serial.println("\nSystem bereit - Sende und empfange CAN-Nachrichten...");
  Serial.println("Wenn keine Ausgabe erscheint, werden keine CAN-Nachrichten empfangen.");
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

  // Periodisch CAN-Nachrichten senden (alle 1000ms)
  if (millis() - lastSentTime > 1000) {
    lastSentTime = millis();

    // Test-Nachricht erstellen
    CAN_frame_t tx_frame;
    tx_frame.FIR.B.FF = CAN_frame_std;  // Standard-Frame (nicht Extended)
    tx_frame.MsgID = 0x123;             // Message ID
    tx_frame.FIR.B.DLC = 8;             // Datenlänge (8 Bytes)

    // Testdaten: Zähler und zufällige Werte
    static uint8_t counter = 0;
    tx_frame.data.u8[0] = counter++;    // Zähler
    tx_frame.data.u8[1] = random(0, 255); // Zufälliger Wert
    tx_frame.data.u8[2] = random(0, 255); // Zufälliger Wert
    tx_frame.data.u8[3] = random(0, 255); // Zufälliger Wert
    tx_frame.data.u8[4] = 0xAA;         // Fester Wert
    tx_frame.data.u8[5] = 0xBB;         // Fester Wert
    tx_frame.data.u8[6] = 0xCC;         // Fester Wert
    tx_frame.data.u8[7] = 0xDD;         // Fester Wert

    // Nachricht senden
    esp_err_t result = ESP32Can.CANWriteFrame(&tx_frame);

    if (result == ESP_OK) {
      // Debug-Ausgabe
      Serial.printf("CAN Nachricht gesendet: ID=0x%X, Daten: %02X %02X %02X %02X %02X %02X %02X %02X\n",
                    tx_frame.MsgID,
                    tx_frame.data.u8[0], tx_frame.data.u8[1], tx_frame.data.u8[2], tx_frame.data.u8[3],
                    tx_frame.data.u8[4], tx_frame.data.u8[5], tx_frame.data.u8[6], tx_frame.data.u8[7]);
    } else {
      Serial.printf("Fehler beim Senden der CAN-Nachricht! Fehlercode: %d\n", result);
    }
  }

  // Regelmäßiger Status-Bericht
  if (millis() - lastStatusTime > 5000) {
    lastStatusTime = millis();
    Serial.printf("Status: Laufzeit=%d Sekunden, Zähler=%d\n", millis()/1000, counter);
    Serial.println("Wenn keine 'CAN Nachricht empfangen' Meldungen erscheinen, werden keine Nachrichten empfangen.");
  }
}
