/**
 * ESP32 TWAI (CAN) Listen-Only Test
 *
 * Dieser Test verwendet die native TWAI-Bibliothek von Espressif
 * im Listen-Only-Modus, um zu überprüfen, ob der CAN-Controller
 * korrekt initialisiert werden kann.
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
unsigned long lastStatusTime = 0;
unsigned long startTime = 0;

// Zähler
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
  Serial.println("ESP32 TWAI (CAN) Listen-Only Test");
  Serial.println("==============================================");
  Serial.println("Dieser Test verwendet die native TWAI-Bibliothek von Espressif im Listen-Only-Modus.");
  Serial.println("Er überprüft, ob der CAN-Controller korrekt initialisiert werden kann.");
  
  // TWAI-Konfiguration im Listen-Only-Modus
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(canTxPin, canRxPin, TWAI_MODE_LISTEN_ONLY);
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
  
  Serial.printf("TWAI erfolgreich im Listen-Only-Modus initialisiert mit 500 kbps: TX Pin=%d, RX Pin=%d\n", canTxPin, canRxPin);
  
  // Startzeit speichern
  startTime = millis();
  
  Serial.println("\nTWAI-Listen-Only-Test gestartet. Warte auf Nachrichten...");
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
  
  // Regelmäßiger Status-Bericht
  if (millis() - lastStatusTime > 5000) {
    lastStatusTime = millis();
    
    unsigned long runtime = (millis() - startTime) / 1000;
    Serial.printf("\n--- STATUS NACH %lu SEKUNDEN ---\n", runtime);
    Serial.printf("Baudrate: 500 kbps\n");
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
