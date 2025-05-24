/**
 * ESP32 Simple CAN Test
 *
 * Einfacher Test für die CAN-Kommunikation mit minimaler Funktionalität.
 */

#include <Arduino.h>
#include <ESP32CAN.h>
#include <CAN_config.h>
#include "can_config.h"

// CAN-Instanz
CAN_device_t CAN_cfg;

// LED-Pin für visuelles Feedback
const int ledPin = 2;  // Eingebaute LED auf den meisten ESP32-Boards

void setup() {
  // LED initialisieren
  pinMode(ledPin, OUTPUT);

  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(2000);  // Längere Verzögerung für Stabilität

  Serial.println("\n\n\n");
  Serial.println("==============================================");
  Serial.println("ESP32 Simple CAN Test");
  Serial.println("==============================================");

  // CAN-Konfiguration
  Serial.println("CAN-Initialisierung...");

  // CAN-Konfiguration mit Pins aus can_config.h
  CAN_cfg.speed = CAN_SPEED_500KBPS;  // Reduzierte Baudrate für bessere Stabilität
  CAN_cfg.tx_pin_id = CAN_TX_PIN;  // Aus can_config.h
  CAN_cfg.rx_pin_id = CAN_RX_PIN;  // Aus can_config.h
  CAN_cfg.rx_queue = xQueueCreate(10, sizeof(CAN_frame_t));

  // CAN-Modul initialisieren
  esp_err_t result = ESP32Can.CANInit();

  if (result == ESP_OK) {
    Serial.printf("CAN erfolgreich initialisiert: TX Pin=%d, RX Pin=%d\n",
                  CAN_cfg.tx_pin_id, CAN_cfg.rx_pin_id);

    // Kurze Verzögerung nach erfolgreicher Initialisierung
    delay(1000);

    Serial.println("CAN-Bus bereit. Beginne mit dem Senden von Testnachrichten...");
    Serial.println("Baudrate: 500 kbps (reduziert für bessere Stabilität)");
    Serial.println("Sende Nachrichten mit verschiedenen IDs: 0x123, 0x3F2, 0x155");
  } else {
    Serial.printf("CAN-Initialisierung fehlgeschlagen! Fehlercode: %d\n", result);
    while (1) {
      digitalWrite(ledPin, HIGH);
      delay(100);
      digitalWrite(ledPin, LOW);
      delay(100);
    }
  }
}

void loop() {
  static unsigned long lastSentTime = 0;
  static unsigned long lastStatusTime = 0;
  static uint8_t counter = 0;

  // LED blinken lassen
  digitalWrite(ledPin, (millis() % 1000) < 500);

  // CAN-Nachrichten empfangen
  CAN_frame_t rx_frame;
  if (xQueueReceive(CAN_cfg.rx_queue, &rx_frame, 0) == pdTRUE) {
    Serial.printf("CAN Nachricht empfangen: ID=0x%X, Länge=%d, Daten: ",
                  rx_frame.MsgID, rx_frame.FIR.B.DLC);

    // Alle Bytes der Nachricht ausgeben
    for (int i = 0; i < rx_frame.FIR.B.DLC; i++) {
      Serial.printf("%02X ", rx_frame.data.u8[i]);
    }
    Serial.println();

    // LED schnell blinken lassen bei empfangener Nachricht
    for (int i = 0; i < 3; i++) {
      digitalWrite(ledPin, HIGH);
      delay(50);
      digitalWrite(ledPin, LOW);
      delay(50);
    }
  }

  // Periodisch CAN-Nachrichten mit verschiedenen IDs senden (alle 500ms)
  if (millis() - lastSentTime > 500) {
    lastSentTime = millis();

    // Verschiedene CAN-IDs testen (wechselt zwischen 3 verschiedenen IDs)
    static uint8_t idIndex = 0;
    uint32_t canIds[3] = {0x123, 0x3F2, 0x155}; // Standard, DroneCAN Actuator Command, DroneCAN Node Status

    // Test-Nachricht erstellen
    CAN_frame_t tx_frame;
    tx_frame.FIR.B.FF = CAN_frame_std;         // Standard-Frame
    tx_frame.MsgID = canIds[idIndex];          // Wechselnde Message ID
    tx_frame.FIR.B.DLC = 8;                    // Datenlänge (8 Bytes)

    // ID-Index für nächste Nachricht aktualisieren
    idIndex = (idIndex + 1) % 3;

    // Einfache Testdaten
    tx_frame.data.u8[0] = counter++;
    tx_frame.data.u8[1] = 0xAA;
    tx_frame.data.u8[2] = 0xBB;
    tx_frame.data.u8[3] = 0xCC;
    tx_frame.data.u8[4] = 0xDD;
    tx_frame.data.u8[5] = 0xEE;
    tx_frame.data.u8[6] = 0xFF;
    tx_frame.data.u8[7] = 0x00;

    // Nachricht senden
    esp_err_t result = ESP32Can.CANWriteFrame(&tx_frame);

    if (result == ESP_OK) {
      Serial.printf("CAN Nachricht gesendet: ID=0x%X, Counter=%d\n", tx_frame.MsgID, counter-1);
    } else {
      Serial.printf("Fehler beim Senden der CAN-Nachricht! Fehlercode: %d\n", result);
    }
  }

  // Regelmäßiger Status-Bericht mit Fehlersuche-Tipps
  if (millis() - lastStatusTime > 3000) {
    lastStatusTime = millis();
    Serial.printf("Status: Laufzeit=%d Sekunden, Counter=%d\n", millis()/1000, counter);
    Serial.println("Wenn keine 'CAN Nachricht empfangen' Meldungen erscheinen, werden keine Nachrichten empfangen.");

    // Zusätzliche Fehlersuche-Tipps
    Serial.println("\n--- FEHLERSUCHE-TIPPS ---");
    Serial.println("1. Überprüfen Sie die Verkabelung:");
    Serial.println("   - ESP32 GPIO5 (TX) → RX am CAN-Transceiver");
    Serial.println("   - ESP32 GPIO4 (RX) → TX am CAN-Transceiver");
    Serial.println("   - CANH vom Transceiver → CANH am Orange Cube");
    Serial.println("   - CANL vom Transceiver → CANL am Orange Cube");
    Serial.println("2. Überprüfen Sie die Terminierung (120 Ohm an beiden Enden)");
    Serial.println("3. Überprüfen Sie die CAN-Parameter im Orange Cube:");
    Serial.println("   - CAN_P1_DRIVER = 1");
    Serial.println("   - CAN_P1_BITRATE = 500000");  // Geändert auf 500 kbps
    Serial.println("   - CAN_D1_PROTOCOL = 1");
    Serial.println("   - CAN_D1_UC_NODE = 1");
    Serial.println("4. Versuchen Sie, die Baudrate auf 500 kbps zu reduzieren");
    Serial.println("5. Überprüfen Sie die Stromversorgung des CAN-Transceivers");
    Serial.println("--- ENDE FEHLERSUCHE-TIPPS ---\n");
  }
}
