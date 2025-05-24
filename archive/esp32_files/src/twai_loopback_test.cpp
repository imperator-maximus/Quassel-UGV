/**
 * ESP32 TWAI (CAN) Loopback Test
 *
 * Dieser Test verwendet die native TWAI-Bibliothek von Espressif
 * im Loopback-Modus, um die Funktionalität des CAN-Controllers zu testen.
 */

#include <Arduino.h>
#include "driver/twai.h"
#include "driver/gpio.h"

// CAN-Pins (fest verdrahtet im ESP32)
const gpio_num_t canTxPin = GPIO_NUM_5;  // GPIO5
const gpio_num_t canRxPin = GPIO_NUM_4;  // GPIO4

// LED-Pin für visuelles Feedback
const int ledPin = 2;  // Eingebaute LED auf den meisten ESP32-Boards

// Zeitpunkte für verschiedene Aktionen
unsigned long lastSentTime = 0;
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
  Serial.println("ESP32 TWAI (CAN) Loopback Test");
  Serial.println("==============================================");
  Serial.println("Dieser Test verwendet die native TWAI-Bibliothek von Espressif im Loopback-Modus.");
  Serial.println("Er testet die Funktionalität des CAN-Controllers ohne externe Verbindungen.");
  
  // TWAI-Konfiguration im Loopback-Modus
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(canTxPin, canRxPin, TWAI_MODE_NO_ACK);
  twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
  twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();
  
  // TWAI-Treiber installieren
  esp_err_t result = twai_driver_install(&g_config, &t_config, &f_config);
  if (result != ESP_OK) {
    Serial.printf("Fehler bei der TWAI-Installation! Fehlercode: %d\n", result);
    while (1) {
      blinkLED(10, 100);  // Schnelles Blinken bei Fehler
      delay(1000);
    }
  }
  
  // TWAI-Treiber starten
  result = twai_start();
  if (result != ESP_OK) {
    Serial.printf("Fehler beim Starten des TWAI-Treibers! Fehlercode: %d\n", result);
    while (1) {
      blinkLED(10, 100);  // Schnelles Blinken bei Fehler
      delay(1000);
    }
  }
  
  Serial.printf("TWAI erfolgreich im Loopback-Modus initialisiert mit 500 kbps: TX Pin=%d, RX Pin=%d\n", canTxPin, canRxPin);
  
  // Startzeit speichern
  startTime = millis();
  
  Serial.println("\nTWAI-Loopback-Test gestartet. Sende Testnachrichten...");
}

void sendTWAIMessage(uint32_t id) {
  // Test-Nachricht erstellen
  twai_message_t message;
  message.identifier = id;
  message.data_length_code = 8;
  message.flags = TWAI_MSG_FLAG_NONE;
  
  // Testdaten
  message.data[0] = messageCounter++;
  message.data[1] = 0xAA;
  message.data[2] = 0xBB;
  message.data[3] = 0xCC;
  message.data[4] = 0xDD;
  message.data[5] = 0xEE;
  message.data[6] = 0xFF;
  message.data[7] = 0x00;
  
  // Nachricht senden
  esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(1000));
  
  if (result == ESP_OK) {
    Serial.printf("TWAI Nachricht gesendet: ID=0x%X, Counter=%d\n", message.identifier, messageCounter-1);
    blinkLED(1, 20);  // Kurzes Blinken bei gesendeter Nachricht
  } else {
    Serial.printf("Fehler beim Senden der TWAI-Nachricht! Fehlercode: %d\n", result);
  }
}

void loop() {
  // Status-LED regelmäßig blinken lassen
  static bool ledState = false;
  if (millis() % 1000 < 50) {
    digitalWrite(ledPin, ledState);
    ledState = !ledState;
  }
  
  // TWAI-Nachrichten empfangen
  twai_message_t rx_message;
  esp_err_t result = twai_receive(&rx_message, pdMS_TO_TICKS(10));
  
  if (result == ESP_OK) {
    receivedMessages++;
    
    Serial.printf("TWAI Nachricht empfangen: ID=0x%X, Länge=%d, Daten: ",
                  rx_message.identifier, rx_message.data_length_code);
    
    // Alle Bytes der Nachricht ausgeben
    for (int i = 0; i < rx_message.data_length_code; i++) {
      Serial.printf("%02X ", rx_message.data[i]);
    }
    Serial.println();
    
    // Schnelles Blinken bei empfangener Nachricht
    blinkLED(3, 30);
  }
  
  // Periodisch TWAI-Nachrichten mit verschiedenen IDs senden (alle 500ms)
  if (millis() - lastSentTime > 500) {
    lastSentTime = millis();
    
    // Wechselnde IDs verwenden
    static uint32_t testIds[] = {0x123, 0x3F2, 0x155, 0x001, 0x7FF};
    static int idIndex = 0;
    
    sendTWAIMessage(testIds[idIndex]);
    idIndex = (idIndex + 1) % 5;
  }
  
  // Regelmäßiger Status-Bericht
  if (millis() - lastStatusTime > 5000) {
    lastStatusTime = millis();
    
    unsigned long runtime = (millis() - startTime) / 1000;
    Serial.printf("\n--- STATUS NACH %lu SEKUNDEN ---\n", runtime);
    Serial.printf("Baudrate: 500 kbps\n");
    Serial.printf("Gesendete Nachrichten: %d\n", messageCounter);
    Serial.printf("Empfangene Nachrichten: %d\n", receivedMessages);
    
    // TWAI-Fehler überprüfen
    twai_status_info_t status_info;
    twai_get_status_info(&status_info);
    
    Serial.printf("\nTWAI-Status:\n");
    Serial.printf("- Nachrichten in TX-Warteschlange: %d\n", status_info.msgs_to_tx);
    Serial.printf("- Nachrichten in RX-Warteschlange: %d\n", status_info.msgs_to_rx);
    Serial.printf("- TX-Fehler-Zähler: %d\n", status_info.tx_error_counter);
    Serial.printf("- RX-Fehler-Zähler: %d\n", status_info.rx_error_counter);
    Serial.printf("- TX-Fehlgeschlagen-Zähler: %d\n", status_info.tx_failed_count);
    Serial.printf("- RX-Verpasst-Zähler: %d\n", status_info.rx_missed_count);
    Serial.printf("- Bus-Fehler-Zähler: %d\n", status_info.bus_error_count);
    Serial.printf("- Arbitrierungs-Verlust-Zähler: %d\n", status_info.arb_lost_count);
    Serial.printf("- Bus-Status: %d\n", status_info.state);
    
    Serial.println("--- ENDE STATUS ---\n");
  }
}
