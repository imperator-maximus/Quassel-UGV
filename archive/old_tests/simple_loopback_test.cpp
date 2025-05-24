/**
 * ESP32 Simple TWAI Loopback Test
 *
 * Dieses Programm führt einen einfachen Loopback-Test des TWAI-Controllers durch,
 * um die grundlegende Funktionalität zu überprüfen.
 */

#include <Arduino.h>
#include <driver/twai.h>

// Pin-Definitionen
#define CAN_TX_PIN GPIO_NUM_5
#define CAN_RX_PIN GPIO_NUM_4
#define LED_PIN    GPIO_NUM_2

// Timeout-Werte
#define SEND_TIMEOUT_MS 1000  // Längerer Timeout für das Senden (1 Sekunde)
#define RECV_TIMEOUT_MS 1000  // Längerer Timeout für den Empfang (1 Sekunde)

// Globale Variablen
uint32_t messagesSent = 0;
uint32_t messagesReceived = 0;
uint32_t errorCount = 0;

// Funktionsdeklarationen
void blinkLED(int times, int delayMs);
bool initTWAI();
void stopTWAI();
bool sendTestMessage();
bool receiveMessage(uint32_t timeoutMs);
void printStatus();

// Funktion zum Blinken der LED
void blinkLED(int times, int delayMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(delayMs);
    digitalWrite(LED_PIN, LOW);
    delay(delayMs);
  }
}

// Funktion zum Initialisieren des TWAI-Treibers im Loopback-Modus
bool initTWAI() {
  // TWAI-Konfiguration für Loopback-Modus
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_NO_ACK);
  
  // Timing-Konfiguration für 500 kbps
  twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
  
  // Filter-Konfiguration (alle Nachrichten akzeptieren)
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

  Serial.printf("TWAI erfolgreich initialisiert im Loopback-Modus mit 500 kbps: TX Pin=%d, RX Pin=%d\n",
                (int)CAN_TX_PIN, (int)CAN_RX_PIN);
  return true;
}

// Funktion zum Stoppen des TWAI-Treibers
void stopTWAI() {
  twai_stop();
  twai_driver_uninstall();
  Serial.println("TWAI-Treiber gestoppt und deinstalliert");
}

// Funktion zum Senden einer Test-Nachricht
bool sendTestMessage() {
  // Test-Nachricht erstellen
  twai_message_t message;
  message.identifier = 0x123;  // Test-ID
  message.data_length_code = 8;
  message.flags = TWAI_MSG_FLAG_NONE;

  // Testdaten
  message.data[0] = messagesSent & 0xFF;
  message.data[1] = 0xAA;
  message.data[2] = 0xBB;
  message.data[3] = 0xCC;
  message.data[4] = 0xDD;
  message.data[5] = 0xEE;
  message.data[6] = 0xFF;
  message.data[7] = 0x00;

  // Nachricht senden mit längerem Timeout
  esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(SEND_TIMEOUT_MS));

  if (result == ESP_OK) {
    messagesSent++;
    Serial.printf("Test-Nachricht #%lu gesendet: ID=0x%X\n", messagesSent, message.identifier);
    blinkLED(1, 20);  // Kurzes Blinken bei gesendeter Nachricht
    return true;
  } else {
    errorCount++;
    Serial.printf("Fehler beim Senden der Test-Nachricht! Fehlercode: %d\n", result);
    return false;
  }
}

// Funktion zum Empfangen einer Nachricht
bool receiveMessage(uint32_t timeoutMs) {
  twai_message_t rx_message;
  esp_err_t result = twai_receive(&rx_message, pdMS_TO_TICKS(timeoutMs));

  if (result == ESP_OK) {
    messagesReceived++;
    Serial.printf("\nNachricht #%lu empfangen: ID=0x%X, Länge=%d\n",
                  messagesReceived, rx_message.identifier, rx_message.data_length_code);

    // Daten anzeigen
    Serial.print("  Daten: ");
    for (int i = 0; i < rx_message.data_length_code; i++) {
      Serial.printf("%02X ", rx_message.data[i]);
    }
    Serial.println();

    blinkLED(1, 10);  // Schnelles Blinken bei empfangener Nachricht
    return true;
  } else if (result == ESP_ERR_TIMEOUT) {
    Serial.println("Timeout beim Empfangen einer Nachricht");
    return false;
  } else {
    Serial.printf("Fehler beim Empfangen einer Nachricht! Fehlercode: %d\n", result);
    return false;
  }
}

// Funktion zum Anzeigen des TWAI-Status
void printStatus() {
  twai_status_info_t status;
  esp_err_t result = twai_get_status_info(&status);

  if (result != ESP_OK) {
    Serial.printf("Fehler beim Abrufen des TWAI-Status! Fehlercode: %d\n", result);
    return;
  }

  Serial.println("\n--- TWAI-STATUS ---");
  Serial.printf("- Nachrichten in TX-Warteschlange: %d\n", status.msgs_to_tx);
  Serial.printf("- Nachrichten in RX-Warteschlange: %d\n", status.msgs_to_rx);
  Serial.printf("- TX-Fehler-Zähler: %d\n", status.tx_error_counter);
  Serial.printf("- RX-Fehler-Zähler: %d\n", status.rx_error_counter);
  Serial.printf("- TX-Fehlgeschlagen-Zähler: %d\n", status.tx_failed_count);
  Serial.printf("- RX-Verpasst-Zähler: %d\n", status.rx_missed_count);
  Serial.printf("- Bus-Fehler-Zähler: %d\n", status.bus_error_count);
  Serial.printf("- Arbitrierungs-Verlust-Zähler: %d\n", status.arb_lost_count);

  // Bus-Status anzeigen
  switch (status.state) {
    case TWAI_STATE_STOPPED:
      Serial.println("- Bus-Status: STOPPED (angehalten)");
      break;
    case TWAI_STATE_RUNNING:
      Serial.println("- Bus-Status: RUNNING (läuft)");
      break;
    case TWAI_STATE_BUS_OFF:
      Serial.println("- Bus-Status: BUS-OFF (zu viele Fehler, Bus deaktiviert)");
      break;
    case TWAI_STATE_RECOVERING:
      Serial.println("- Bus-Status: RECOVERING (Wiederherstellung läuft)");
      break;
    default:
      Serial.printf("- Bus-Status: UNBEKANNT (%d)\n", status.state);
  }

  Serial.println("--- ENDE STATUS ---");
}

// Setup-Funktion
void setup() {
  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(1000);  // Kurze Pause für Stabilität

  Serial.println("\n\n=== ESP32 Simple TWAI Loopback Test ===");

  // LED-Pin konfigurieren
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // Hardware-Informationen ausgeben
  Serial.printf("ESP32 Chip Revision: %d\n", ESP.getChipRevision());
  Serial.printf("ESP32 SDK Version: %s\n", ESP.getSdkVersion());
  Serial.printf("ESP32 CPU Frequenz: %d MHz\n", ESP.getCpuFreqMHz());

  // Benutzeroptionen
  Serial.println("\nBefehle:");
  Serial.println("- 's': Status anzeigen");
  Serial.println("- 't': Test-Nachricht senden");
  Serial.println("- 'r': TWAI-Treiber neu starten");
  Serial.println("- 'l': Auf Nachrichten lauschen (5 Sekunden)");

  // TWAI initialisieren
  if (!initTWAI()) {
    Serial.println("Kritischer Fehler bei der TWAI-Initialisierung!");
    while (1) {
      blinkLED(10, 100);  // Schnelles Blinken bei Fehler
      delay(1000);
    }
  }

  // Kurze Pause für Stabilität
  delay(500);

  // Erste Test-Nachricht senden
  Serial.println("\nSende erste Test-Nachricht...");
  sendTestMessage();
}

// Loop-Funktion
void loop() {
  // Auf serielle Eingabe prüfen
  if (Serial.available()) {
    char cmd = Serial.read();

    switch (cmd) {
      case 's':
        printStatus();
        break;
      case 't':
        sendTestMessage();
        break;
      case 'r':
        Serial.println("\nStarte TWAI-Treiber neu...");
        stopTWAI();
        delay(500);
        initTWAI();
        break;
      case 'l':
        Serial.println("\nLausche auf Nachrichten für 5 Sekunden...");
        for (int i = 0; i < 5; i++) {
          receiveMessage(1000);  // 1 Sekunde warten
        }
        break;
    }
  }

  // Regelmäßig auf Nachrichten prüfen (mit kurzem Timeout)
  receiveMessage(10);

  // Kurze Pause für Stabilität
  delay(50);
}
