/**
 * ESP32 CAN Reset Test
 *
 * Dieses Programm testet die CAN-Kommunikation mit automatischem Reset
 * nach jeder Nachricht als Workaround für Probleme mit dem TWAI-Treiber.
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
uint8_t sendErrorCount = 0;
uint8_t sendSuccessCount = 0;

// Funktionsdeklarationen
void checkForReceivedMessages();

// Hilfsfunktion zum Blinken der LED
void blinkLED(int times, int duration = 50) {
  for (int i = 0; i < times; i++) {
    digitalWrite(ledPin, HIGH);
    delay(duration);
    digitalWrite(ledPin, LOW);
    delay(duration);
  }
}

// Funktion zum Initialisieren des TWAI-Treibers
bool initTWAI() {
  // TWAI-Konfiguration
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(canTxPin, canRxPin, TWAI_MODE_NORMAL);
  twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
  twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

  // TWAI-Treiber installieren
  esp_err_t result = twai_driver_install(&g_config, &t_config, &f_config);
  if (result != ESP_OK) {
    Serial.printf("Fehler bei der TWAI-Installation! Fehlercode: %d\n", result);
    return false;
  }

  // TWAI-Treiber starten
  result = twai_start();
  if (result != ESP_OK) {
    Serial.printf("Fehler beim Starten des TWAI-Treibers! Fehlercode: %d\n", result);
    return false;
  }

  Serial.printf("TWAI erfolgreich initialisiert mit 500 kbps: TX Pin=%d, RX Pin=%d\n", canTxPin, canRxPin);
  return true;
}

// Funktion zum Zurücksetzen des TWAI-Treibers
bool resetTWAI() {
  // TWAI-Treiber stoppen und deinstallieren
  twai_stop();
  twai_driver_uninstall();
  delay(50);  // Kurze Pause für Stabilität

  // TWAI-Treiber neu initialisieren
  return initTWAI();
}

// Funktion zum Prüfen auf empfangene Nachrichten
void checkForReceivedMessages() {
  // TWAI-Nachrichten empfangen
  twai_message_t rx_message;
  esp_err_t result = twai_receive(&rx_message, pdMS_TO_TICKS(10));

  if (result == ESP_OK) {
    receivedMessages++;

    Serial.printf("Nachricht empfangen: ID=0x%X, Länge=%d, Daten: ",
                  rx_message.identifier, rx_message.data_length_code);

    // Alle Bytes der Nachricht ausgeben
    for (int i = 0; i < rx_message.data_length_code; i++) {
      Serial.printf("%02X ", rx_message.data[i]);
    }
    Serial.println();

    // Schnelles Blinken bei empfangener Nachricht
    blinkLED(3, 30);
  }
}

// Funktion zum Senden einer einfachen CAN-Testnachricht mit automatischem Reset
bool sendMessageWithReset() {
  // TWAI-Treiber zurücksetzen vor dem Senden
  if (!resetTWAI()) {
    Serial.println("Fehler beim Zurücksetzen des TWAI-Treibers!");
    return false;
  }

  // Einfache Test-Nachricht erstellen
  twai_message_t message;
  message.identifier = 0x123;  // Standard Test-ID
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

  // Nachricht senden mit kürzerem Timeout (100ms)
  esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(100));

  if (result == ESP_OK) {
    sendSuccessCount++;
    Serial.printf("Nachricht gesendet: ID=0x%X, Counter=%d, Erfolge=%d, Fehler=%d\n",
                  message.identifier, messageCounter-1, sendSuccessCount, sendErrorCount);
    blinkLED(1, 20);  // Kurzes Blinken bei gesendeter Nachricht

    // Kurz warten und auf Antworten prüfen
    delay(50);
    checkForReceivedMessages();

    return true;
  } else {
    sendErrorCount++;
    Serial.printf("Fehler beim Senden! Fehlercode: %d, Erfolge=%d, Fehler=%d\n",
                  result, sendSuccessCount, sendErrorCount);

    // Detaillierte Fehleranalyse
    if (result == ESP_ERR_TIMEOUT) {
      Serial.println("  - Timeout beim Senden (ESP_ERR_TIMEOUT)");
    } else if (result == ESP_ERR_INVALID_STATE) {
      Serial.println("  - Ungültiger Zustand (ESP_ERR_INVALID_STATE)");
    } else if (result == ESP_ERR_INVALID_ARG) {
      Serial.println("  - Ungültiges Argument (ESP_ERR_INVALID_ARG)");
    }

    return false;
  }
}



// Funktion zum Ausgeben des TWAI-Status
void printTWAIStatus() {
  twai_status_info_t status_info;
  esp_err_t result = twai_get_status_info(&status_info);

  if (result == ESP_OK) {
    Serial.println("\n--- TWAI-STATUS ---");
    Serial.printf("- Nachrichten in TX-Warteschlange: %d\n", status_info.msgs_to_tx);
    Serial.printf("- Nachrichten in RX-Warteschlange: %d\n", status_info.msgs_to_rx);
    Serial.printf("- TX-Fehler-Zähler: %d\n", status_info.tx_error_counter);
    Serial.printf("- RX-Fehler-Zähler: %d\n", status_info.rx_error_counter);
    Serial.printf("- TX-Fehlgeschlagen-Zähler: %d\n", status_info.tx_failed_count);
    Serial.printf("- RX-Verpasst-Zähler: %d\n", status_info.rx_missed_count);
    Serial.printf("- Bus-Fehler-Zähler: %d\n", status_info.bus_error_count);
    Serial.printf("- Arbitrierungs-Verlust-Zähler: %d\n", status_info.arb_lost_count);

    // Bus-Status interpretieren
    Serial.printf("- Bus-Status: ");
    switch (status_info.state) {
      case TWAI_STATE_STOPPED:
        Serial.println("GESTOPPT");
        break;
      case TWAI_STATE_RUNNING:
        Serial.println("AKTIV");
        break;
      case TWAI_STATE_BUS_OFF:
        Serial.println("BUS-OFF (zu viele Fehler, Bus deaktiviert)");
        break;
      case TWAI_STATE_RECOVERING:
        Serial.println("WIEDERHERSTELLUNG (nach Bus-Off)");
        break;
      default:
        Serial.printf("UNBEKANNT (%d)\n", status_info.state);
        break;
    }

    Serial.println("--- ENDE STATUS ---\n");
  } else {
    Serial.printf("Fehler beim Abrufen des TWAI-Status! Fehlercode: %d\n", result);
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
  Serial.println("ESP32 CAN Reset Test");
  Serial.println("==============================================");
  Serial.println("Dieses Programm testet die CAN-Kommunikation mit automatischem Reset");
  Serial.println("nach jeder Nachricht als Workaround für Probleme mit dem TWAI-Treiber.");

  // Benutzeroptionen
  Serial.println("\nBefehle:");
  Serial.println("- 's': Status anzeigen");
  Serial.println("- 't': Testnachricht senden");

  // TWAI initialisieren
  if (!initTWAI()) {
    Serial.println("Kritischer Fehler bei der TWAI-Initialisierung!");
    while (1) {
      blinkLED(10, 100);  // Schnelles Blinken bei Fehler
      delay(1000);
    }
  }

  // Startzeit speichern
  startTime = millis();

  Serial.println("\nCAN Reset Test gestartet. Sende Testnachrichten mit automatischem Reset...");
  Serial.println("Bitte stellen Sie sicher, dass:");
  Serial.println("1. Der CAN-Transceiver korrekt mit dem ESP32 verbunden ist");
  Serial.println("2. Ein 120-Ohm-Widerstand zwischen CANH und CANL angeschlossen ist");
  Serial.println("3. Der Transceiver mit 3.3V versorgt wird");
}

void loop() {
  // Status-LED regelmäßig blinken lassen
  static bool ledState = false;
  if (millis() % 1000 < 50) {
    digitalWrite(ledPin, ledState);
    ledState = !ledState;
  }

  // Serielle Befehle verarbeiten
  if (Serial.available() > 0) {
    char cmd = Serial.read();

    switch (cmd) {
      case 's':  // Status anzeigen
        printTWAIStatus();
        break;

      case 't':  // Testnachricht senden
        sendMessageWithReset();
        break;
    }

    // Restliche Zeichen aus dem Buffer entfernen
    while (Serial.available()) {
      Serial.read();
    }
  }

  // Periodisch Testnachrichten senden (alle 2000ms)
  if (millis() - lastSentTime > 2000) {
    lastSentTime = millis();
    sendMessageWithReset();
  }

  // Regelmäßiger Status-Bericht
  if (millis() - lastStatusTime > 10000) {
    lastStatusTime = millis();

    unsigned long runtime = (millis() - startTime) / 1000;
    Serial.printf("\n--- STATUS NACH %lu SEKUNDEN ---\n", runtime);
    Serial.printf("Gesendete Nachrichten: %d\n", messageCounter);
    Serial.printf("Erfolgreiche Sendungen: %d\n", sendSuccessCount);
    Serial.printf("Fehlgeschlagene Sendungen: %d\n", sendErrorCount);
    Serial.printf("Empfangene Nachrichten: %d\n", receivedMessages);

    // TWAI-Status abrufen
    printTWAIStatus();
  }
}
