/**
 * ESP32 TWAI Timeout Investigation
 *
 * Dieses Programm untersucht speziell das Timeout-Problem (Fehlercode 259)
 * beim Senden von CAN-Nachrichten im Loopback-Modus.
 */

#include <Arduino.h>
#include <driver/twai.h>
#include <esp_timer.h>

// Pin-Definitionen
#define CAN_TX_PIN GPIO_NUM_5
#define CAN_RX_PIN GPIO_NUM_4
#define LED_PIN    GPIO_NUM_2

// Globale Variablen
bool driverInstalled = false;
uint32_t messagesSent = 0;
uint32_t messagesReceived = 0;
uint32_t errorCount = 0;

// Funktionsdeklarationen
void blinkLED(int times, int delayMs);
bool initTWAI(twai_mode_t mode);
void stopTWAI();
bool sendTestMessage(uint32_t timeoutMs);
bool receiveMessage(uint32_t timeoutMs);
void printStatus();
void testWithDifferentTimeouts();
void testWithDifferentModes();

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
bool initTWAI(twai_mode_t mode) {
  // TWAI-Konfiguration
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, mode);
  
  // Timing-Konfiguration für 500 kbps
  twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
  
  // Filter-Konfiguration (alle Nachrichten akzeptieren)
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

  const char* modeStr;
  switch (mode) {
    case TWAI_MODE_NORMAL:
      modeStr = "Normal";
      break;
    case TWAI_MODE_NO_ACK:
      modeStr = "No-ACK (Loopback)";
      break;
    case TWAI_MODE_LISTEN_ONLY:
      modeStr = "Listen-Only";
      break;
    default:
      modeStr = "Unbekannt";
  }

  Serial.printf("TWAI erfolgreich initialisiert im %s-Modus mit 500 kbps: TX Pin=%d, RX Pin=%d\n",
                modeStr, (int)CAN_TX_PIN, (int)CAN_RX_PIN);
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

// Funktion zum Senden einer Test-Nachricht
bool sendTestMessage(uint32_t timeoutMs) {
  if (!driverInstalled) {
    Serial.println("TWAI-Treiber nicht installiert!");
    return false;
  }

  // Test-Nachricht erstellen
  twai_message_t message;
  message.identifier = 0x123;
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

  // Startzeit für Zeitmessung
  uint64_t startTime = esp_timer_get_time();

  // Nachricht senden mit angegebenem Timeout
  esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(timeoutMs));

  // Endzeit für Zeitmessung
  uint64_t endTime = esp_timer_get_time();
  uint64_t duration = endTime - startTime;

  if (result == ESP_OK) {
    messagesSent++;
    Serial.printf("Test-Nachricht #%lu gesendet: ID=0x%X (Dauer: %llu µs, Timeout: %lu ms)\n", 
                  messagesSent, message.identifier, duration, timeoutMs);
    blinkLED(1, 20);  // Kurzes Blinken bei gesendeter Nachricht
    return true;
  } else {
    errorCount++;
    Serial.printf("Fehler beim Senden der Test-Nachricht! Fehlercode: %d (Dauer: %llu µs, Timeout: %lu ms)\n", 
                  result, duration, timeoutMs);
    
    // Detaillierte Fehlerbeschreibung
    switch (result) {
      case ESP_ERR_TIMEOUT:
        Serial.println("  -> Timeout beim Senden (ESP_ERR_TIMEOUT, Code 259)");
        break;
      case ESP_ERR_INVALID_STATE:
        Serial.println("  -> Ungültiger Zustand (ESP_ERR_INVALID_STATE)");
        break;
      case ESP_ERR_INVALID_ARG:
        Serial.println("  -> Ungültiges Argument (ESP_ERR_INVALID_ARG)");
        break;
      case ESP_FAIL:
        Serial.println("  -> Allgemeiner Fehler (ESP_FAIL)");
        break;
      default:
        Serial.printf("  -> Unbekannter Fehler (%d)\n", result);
    }
    
    return false;
  }
}

// Funktion zum Empfangen einer Nachricht
bool receiveMessage(uint32_t timeoutMs) {
  if (!driverInstalled) {
    Serial.println("TWAI-Treiber nicht installiert!");
    return false;
  }

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
    // Kein Fehler, nur kein Empfang innerhalb des Timeouts
    return false;
  } else {
    Serial.printf("Fehler beim Empfangen einer Nachricht! Fehlercode: %d\n", result);
    return false;
  }
}

// Funktion zum Anzeigen des TWAI-Status
void printStatus() {
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

// Funktion zum Testen mit verschiedenen Timeout-Werten
void testWithDifferentTimeouts() {
  Serial.println("\n=== Test mit verschiedenen Timeout-Werten ===");
  
  // Verschiedene Timeout-Werte testen
  uint32_t timeouts[] = {10, 50, 100, 500, 1000, 2000, 5000};
  int numTimeouts = sizeof(timeouts) / sizeof(timeouts[0]);
  
  for (int i = 0; i < numTimeouts; i++) {
    Serial.printf("\nTest mit Timeout = %lu ms\n", timeouts[i]);
    
    // Status vor dem Senden anzeigen
    printStatus();
    
    // Nachricht senden
    bool success = sendTestMessage(timeouts[i]);
    
    // Kurze Pause
    delay(100);
    
    // Auf Empfang prüfen
    if (success) {
      Serial.println("Prüfe auf Empfang...");
      receiveMessage(100);
    }
    
    // Status nach dem Senden anzeigen
    printStatus();
    
    // Pause zwischen den Tests
    delay(500);
  }
  
  Serial.println("\n=== Test mit verschiedenen Timeout-Werten abgeschlossen ===");
}

// Funktion zum Testen mit verschiedenen TWAI-Modi
void testWithDifferentModes() {
  Serial.println("\n=== Test mit verschiedenen TWAI-Modi ===");
  
  // Verschiedene Modi testen
  twai_mode_t modes[] = {TWAI_MODE_NORMAL, TWAI_MODE_NO_ACK, TWAI_MODE_LISTEN_ONLY};
  const char* modeNames[] = {"Normal", "No-ACK (Loopback)", "Listen-Only"};
  int numModes = sizeof(modes) / sizeof(modes[0]);
  
  for (int i = 0; i < numModes; i++) {
    Serial.printf("\nTest im %s-Modus\n", modeNames[i]);
    
    // TWAI-Treiber neu initialisieren
    stopTWAI();
    delay(500);
    
    if (!initTWAI(modes[i])) {
      Serial.printf("Fehler bei der Initialisierung im %s-Modus!\n", modeNames[i]);
      continue;
    }
    
    // Kurze Pause
    delay(500);
    
    // Status anzeigen
    printStatus();
    
    // Im Listen-Only-Modus können wir nicht senden
    if (modes[i] != TWAI_MODE_LISTEN_ONLY) {
      // Nachricht senden
      Serial.println("Sende Test-Nachricht...");
      bool success = sendTestMessage(1000);
      
      // Kurze Pause
      delay(100);
      
      // Auf Empfang prüfen
      if (success) {
        Serial.println("Prüfe auf Empfang...");
        receiveMessage(100);
      }
    } else {
      Serial.println("Senden im Listen-Only-Modus nicht möglich.");
    }
    
    // Status anzeigen
    printStatus();
    
    // Pause zwischen den Tests
    delay(1000);
  }
  
  Serial.println("\n=== Test mit verschiedenen TWAI-Modi abgeschlossen ===");
  
  // Zurück zum No-ACK-Modus
  stopTWAI();
  delay(500);
  initTWAI(TWAI_MODE_NO_ACK);
}

// Setup-Funktion
void setup() {
  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(1000);  // Kurze Pause für Stabilität

  Serial.println("\n\n=== ESP32 TWAI Timeout Investigation ===");
  Serial.println("Untersucht speziell das Timeout-Problem (Fehlercode 259)");

  // LED-Pin konfigurieren
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // Hardware-Informationen ausgeben
  Serial.printf("ESP32 Chip Revision: %d\n", ESP.getChipRevision());
  Serial.printf("ESP32 SDK Version: %s\n", ESP.getSdkVersion());
  Serial.printf("ESP32 CPU Frequenz: %d MHz\n", ESP.getCpuFreqMHz());

  // Benutzeroptionen
  Serial.println("\nBefehle:");
  Serial.println("- 't': Test mit verschiedenen Timeout-Werten");
  Serial.println("- 'm': Test mit verschiedenen TWAI-Modi");
  Serial.println("- 's': Status anzeigen");
  Serial.println("- 'r': TWAI-Treiber neu starten");
  Serial.println("- '1': Einzelne Nachricht mit 100ms Timeout senden");
  Serial.println("- '2': Einzelne Nachricht mit 1000ms Timeout senden");
  Serial.println("- '3': Einzelne Nachricht mit 5000ms Timeout senden");

  // TWAI im No-ACK-Modus (Loopback) initialisieren
  if (!initTWAI(TWAI_MODE_NO_ACK)) {
    Serial.println("Kritischer Fehler bei der TWAI-Initialisierung!");
    while (1) {
      blinkLED(10, 100);  // Schnelles Blinken bei Fehler
      delay(1000);
    }
  }

  // Kurze Pause für Stabilität
  delay(500);
  
  // Status anzeigen
  printStatus();
  
  // Automatisch einen Test mit verschiedenen Timeout-Werten starten
  testWithDifferentTimeouts();
}

// Loop-Funktion
void loop() {
  // Auf serielle Eingabe prüfen
  if (Serial.available()) {
    char cmd = Serial.read();

    switch (cmd) {
      case 't':
        // Test mit verschiedenen Timeout-Werten
        testWithDifferentTimeouts();
        break;

      case 'm':
        // Test mit verschiedenen TWAI-Modi
        testWithDifferentModes();
        break;

      case 's':
        // Status anzeigen
        printStatus();
        break;

      case 'r':
        // TWAI-Treiber neu starten
        Serial.println("\nStarte TWAI-Treiber neu...");
        stopTWAI();
        delay(500);
        initTWAI(TWAI_MODE_NO_ACK);
        break;

      case '1':
        // Einzelne Nachricht mit 100ms Timeout senden
        Serial.println("\nSende Nachricht mit 100ms Timeout...");
        sendTestMessage(100);
        break;

      case '2':
        // Einzelne Nachricht mit 1000ms Timeout senden
        Serial.println("\nSende Nachricht mit 1000ms Timeout...");
        sendTestMessage(1000);
        break;

      case '3':
        // Einzelne Nachricht mit 5000ms Timeout senden
        Serial.println("\nSende Nachricht mit 5000ms Timeout...");
        sendTestMessage(5000);
        break;
    }
  }

  // Regelmäßig auf Nachrichten prüfen (mit kurzem Timeout)
  receiveMessage(10);

  // Kurze Pause für Stabilität
  delay(50);
}
