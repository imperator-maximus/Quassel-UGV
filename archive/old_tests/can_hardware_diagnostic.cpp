/**
 * ESP32 CAN Hardware Diagnose
 *
 * Dieses Programm führt umfangreiche Diagnosetests für die CAN-Hardware durch,
 * um Probleme mit dem CAN-Transceiver, der Verkabelung oder der Terminierung zu identifizieren.
 */

#include <Arduino.h>
#include <driver/twai.h>
#include "can_config.h"  // Verwende die vorhandene Konfigurationsdatei

// Pin-Definitionen
#define LED_PIN    GPIO_NUM_2  // Onboard-LED für Statusanzeige

// Testmodi
enum TestMode {
  MODE_LOOPBACK,
  MODE_LISTEN_ONLY,
  MODE_NORMAL,
  MODE_SIGNAL_TEST
};

// Globale Variablen
TestMode currentMode = MODE_LOOPBACK;
bool driverInstalled = false;
unsigned long testStartTime = 0;
unsigned long lastStatusTime = 0;
unsigned long lastMessageTime = 0;
uint32_t messagesSent = 0;
uint32_t messagesReceived = 0;
uint32_t errorCount = 0;

// Funktionsdeklarationen
void blinkLED(int times, int delayMs);
bool initTWAI(TestMode mode);
void stopTWAI();
void checkTWAIStatus();
bool sendTestMessage();
void checkForMessages();
void runSignalTest();
void printDiagnosticInfo();

// Funktion zum Blinken der LED
void blinkLED(int times, int delayMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(delayMs);
    digitalWrite(LED_PIN, LOW);
    delay(delayMs);
  }
}

// Funktion zum Initialisieren des TWAI-Treibers
bool initTWAI(TestMode mode) {
  // TWAI-Modus basierend auf Testmodus wählen
  twai_mode_t twaiMode;
  switch (mode) {
    case MODE_LOOPBACK:
      twaiMode = TWAI_MODE_NO_ACK;
      break;
    case MODE_LISTEN_ONLY:
      twaiMode = TWAI_MODE_LISTEN_ONLY;
      break;
    case MODE_NORMAL:
    case MODE_SIGNAL_TEST:
      twaiMode = TWAI_MODE_NORMAL;
      break;
    default:
      twaiMode = TWAI_MODE_NORMAL;
  }

  // TWAI-Konfiguration
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, twaiMode);
  twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
  twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

  // TWAI-Treiber installieren
  esp_err_t result = twai_driver_install(&g_config, &t_config, &f_config);
  if (result != ESP_OK) {
    Serial.printf("Fehler bei der TWAI-Installation! Fehlercode: %d\n", result);
    driverInstalled = false;
    return false;
  }

  driverInstalled = true;

  // TWAI-Treiber starten
  result = twai_start();
  if (result != ESP_OK) {
    Serial.printf("Fehler beim Starten des TWAI-Treibers! Fehlercode: %d\n", result);
    return false;
  }

  Serial.printf("TWAI erfolgreich initialisiert im %s-Modus mit 500 kbps: TX Pin=%d, RX Pin=%d\n",
                mode == MODE_LOOPBACK ? "Loopback" : 
                (mode == MODE_LISTEN_ONLY ? "Listen-Only" : "Normal"),
                (int)CAN_TX_PIN, (int)CAN_RX_PIN);
  return true;
}

// Funktion zum Stoppen des TWAI-Treibers
void stopTWAI() {
  if (driverInstalled) {
    twai_stop();
    twai_driver_uninstall();
    driverInstalled = false;
    Serial.println("TWAI-Treiber gestoppt und deinstalliert");
  }
}

// Funktion zum Überprüfen des TWAI-Status
void checkTWAIStatus() {
  if (!driverInstalled) {
    Serial.println("TWAI-Treiber nicht installiert!");
    return;
  }

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

// Funktion zum Senden einer Test-Nachricht
bool sendTestMessage() {
  if (!driverInstalled) {
    return false;
  }

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

  // Nachricht senden
  esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(100));

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

// Funktion zum Prüfen auf empfangene Nachrichten
void checkForMessages() {
  if (!driverInstalled) {
    return;
  }

  // TWAI-Nachrichten empfangen
  twai_message_t rx_message;
  esp_err_t result = twai_receive(&rx_message, pdMS_TO_TICKS(10));

  if (result == ESP_OK) {
    messagesReceived++;
    lastMessageTime = millis();

    Serial.printf("\nNachricht #%lu empfangen: ID=0x%X, Länge=%d\n",
                  messagesReceived, rx_message.identifier, rx_message.data_length_code);

    // Daten anzeigen
    Serial.print("  Daten: ");
    for (int i = 0; i < rx_message.data_length_code; i++) {
      Serial.printf("%02X ", rx_message.data[i]);
    }
    Serial.println();

    // Schnelles Blinken bei empfangener Nachricht
    blinkLED(1, 10);
  }
}

// Funktion zum Durchführen eines Signaltests
void runSignalTest() {
  Serial.println("\n=== CAN-SIGNAL-TEST ===");
  Serial.println("Teste die Signalqualität der CAN-Verbindung...");

  // Signaltest-Modus initialisieren
  if (!initTWAI(MODE_NORMAL)) {
    Serial.println("Fehler beim Initialisieren des TWAI-Treibers für den Signaltest!");
    return;
  }

  // Mehrere Nachrichten in schneller Folge senden
  Serial.println("Sende 20 Nachrichten in schneller Folge...");
  int successCount = 0;
  for (int i = 0; i < 20; i++) {
    if (sendTestMessage()) {
      successCount++;
    }
    delay(10);
  }

  // Status prüfen
  checkTWAIStatus();

  // Ergebnis anzeigen
  Serial.printf("\nSignaltest abgeschlossen: %d von 20 Nachrichten erfolgreich gesendet (%.1f%%)\n",
                successCount, (successCount / 20.0) * 100);

  if (successCount == 0) {
    Serial.println("KRITISCH: Keine Nachricht konnte gesendet werden!");
    Serial.println("Mögliche Ursachen:");
    Serial.println("- CAN-Transceiver defekt");
    Serial.println("- Falsche Verkabelung");
    Serial.println("- Kurzschluss auf dem Bus");
  } else if (successCount < 10) {
    Serial.println("WARNUNG: Signalqualität sehr schlecht!");
    Serial.println("Mögliche Ursachen:");
    Serial.println("- Instabile Verbindung");
    Serial.println("- Fehlerhafte Terminierung");
    Serial.println("- Störungen auf dem Bus");
  } else if (successCount < 18) {
    Serial.println("HINWEIS: Signalqualität mäßig.");
    Serial.println("Mögliche Ursachen:");
    Serial.println("- Leichte Störungen");
    Serial.println("- Suboptimale Terminierung");
  } else {
    Serial.println("OK: Signalqualität gut.");
  }

  // TWAI-Treiber stoppen
  stopTWAI();
}

// Funktion zum Anzeigen von Diagnoseinformationen
void printDiagnosticInfo() {
  Serial.println("\n=== DIAGNOSE-INFORMATIONEN ===");
  Serial.printf("Aktueller Modus: %s\n",
                currentMode == MODE_LOOPBACK ? "Loopback" :
                (currentMode == MODE_LISTEN_ONLY ? "Listen-Only" :
                 (currentMode == MODE_SIGNAL_TEST ? "Signal-Test" : "Normal")));
  Serial.printf("Laufzeit: %lu Sekunden\n", (millis() - testStartTime) / 1000);
  Serial.printf("Gesendete Nachrichten: %lu\n", messagesSent);
  Serial.printf("Empfangene Nachrichten: %lu\n", messagesReceived);
  Serial.printf("Fehler: %lu\n", errorCount);

  if (messagesReceived > 0) {
    Serial.printf("Letzte Nachricht vor: %lu ms\n", millis() - lastMessageTime);
  }

  // TWAI-Status anzeigen
  checkTWAIStatus();

  // Hardware-Empfehlungen
  Serial.println("\nHardware-Empfehlungen:");
  Serial.println("- Stellen Sie sicher, dass beide Enden des CAN-Bus mit 120 Ohm terminiert sind");
  Serial.println("- Verwenden Sie verdrillte Kabelpaare für CAN_H und CAN_L");
  Serial.println("- Halten Sie die Kabellänge so kurz wie möglich");
  Serial.println("- Stellen Sie sicher, dass der CAN-Transceiver mit 3,3V versorgt wird");
  Serial.println("- Überprüfen Sie die Verbindungen mit einem Multimeter");
}

// Setup-Funktion
void setup() {
  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(1000);  // Kurze Pause für Stabilität

  Serial.println("\n\n=== ESP32 CAN Hardware Diagnose ===");

  // LED-Pin konfigurieren
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // Hardware-Informationen ausgeben
  Serial.printf("ESP32 Chip Revision: %d\n", ESP.getChipRevision());
  Serial.printf("ESP32 SDK Version: %s\n", ESP.getSdkVersion());
  Serial.printf("ESP32 CPU Frequenz: %d MHz\n", ESP.getCpuFreqMHz());

  // Benutzeroptionen
  Serial.println("\nBefehle:");
  Serial.println("- '1': Loopback-Test (interne Schleife)");
  Serial.println("- '2': Listen-Only-Modus (nur empfangen)");
  Serial.println("- '3': Normaler Modus (senden und empfangen)");
  Serial.println("- '4': Signal-Test durchführen");
  Serial.println("- 's': Status anzeigen");
  Serial.println("- 'd': Diagnose-Informationen anzeigen");
  Serial.println("- 't': Test-Nachricht senden");

  // Startzeit speichern
  testStartTime = millis();
  lastStatusTime = millis();

  // Standardmäßig im Loopback-Modus starten
  Serial.println("\nStarte im Loopback-Modus (interne Schleife)...");
  if (!initTWAI(MODE_LOOPBACK)) {
    Serial.println("Kritischer Fehler bei der TWAI-Initialisierung!");
    while (1) {
      blinkLED(10, 100);  // Schnelles Blinken bei Fehler
      delay(1000);
    }
  }
  currentMode = MODE_LOOPBACK;
}

// Loop-Funktion
void loop() {
  // Auf serielle Eingabe prüfen
  if (Serial.available()) {
    char cmd = Serial.read();

    switch (cmd) {
      case '1':
        // Loopback-Modus
        Serial.println("\nWechsle in Loopback-Modus...");
        stopTWAI();
        if (initTWAI(MODE_LOOPBACK)) {
          currentMode = MODE_LOOPBACK;
          messagesSent = 0;
          messagesReceived = 0;
          errorCount = 0;
        }
        break;

      case '2':
        // Listen-Only-Modus
        Serial.println("\nWechsle in Listen-Only-Modus...");
        stopTWAI();
        if (initTWAI(MODE_LISTEN_ONLY)) {
          currentMode = MODE_LISTEN_ONLY;
          messagesSent = 0;
          messagesReceived = 0;
          errorCount = 0;
        }
        break;

      case '3':
        // Normaler Modus
        Serial.println("\nWechsle in normalen Modus...");
        stopTWAI();
        if (initTWAI(MODE_NORMAL)) {
          currentMode = MODE_NORMAL;
          messagesSent = 0;
          messagesReceived = 0;
          errorCount = 0;
        }
        break;

      case '4':
        // Signal-Test
        currentMode = MODE_SIGNAL_TEST;
        runSignalTest();
        // Nach dem Test zurück zum Loopback-Modus
        if (initTWAI(MODE_LOOPBACK)) {
          currentMode = MODE_LOOPBACK;
          messagesSent = 0;
          messagesReceived = 0;
          errorCount = 0;
        }
        break;

      case 's':
        checkTWAIStatus();
        break;

      case 'd':
        printDiagnosticInfo();
        break;

      case 't':
        sendTestMessage();
        break;
    }
  }

  // Regelmäßig auf Nachrichten prüfen
  checkForMessages();

  // Im Loopback-Modus regelmäßig Testnachrichten senden
  if (currentMode == MODE_LOOPBACK && millis() - lastMessageTime > 1000) {
    sendTestMessage();
    lastMessageTime = millis();
  }

  // Status regelmäßig prüfen
  if (millis() - lastStatusTime > 5000) {
    lastStatusTime = millis();
    
    // Kurze Statusmeldung
    Serial.printf("\nStatus: Modus=%s, Gesendet=%lu, Empfangen=%lu, Fehler=%lu\n",
                  currentMode == MODE_LOOPBACK ? "Loopback" :
                  (currentMode == MODE_LISTEN_ONLY ? "Listen-Only" :
                   (currentMode == MODE_SIGNAL_TEST ? "Signal-Test" : "Normal")),
                  messagesSent, messagesReceived, errorCount);
  }

  // Kurze Pause für Stabilität
  delay(10);
}
