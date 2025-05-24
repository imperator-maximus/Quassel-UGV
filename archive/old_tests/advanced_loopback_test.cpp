/**
 * ESP32 Advanced TWAI Loopback Test
 *
 * Dieses Programm führt einen erweiterten Loopback-Test des TWAI-Controllers durch,
 * mit verschiedenen Konfigurationen und Fehlerbehandlungsstrategien.
 */

#include <Arduino.h>
#include <driver/twai.h>
#include <esp_timer.h>

// Pin-Definitionen
#define CAN_TX_PIN GPIO_NUM_5
#define CAN_RX_PIN GPIO_NUM_4
#define LED_PIN    GPIO_NUM_2

// Timeout-Werte
#define SEND_TIMEOUT_MS 2000  // Sehr langer Timeout für das Senden (2 Sekunden)
#define RECV_TIMEOUT_MS 2000  // Sehr langer Timeout für den Empfang (2 Sekunden)

// Test-Modi
enum TestMode {
  MODE_LOOPBACK_INTERNAL,  // Interner Loopback (TWAI_MODE_NO_ACK)
  MODE_LOOPBACK_EXTERNAL,  // Externer Loopback (TWAI_MODE_NORMAL mit verbundenen Pins)
  MODE_LISTEN_ONLY,        // Nur Empfangen (TWAI_MODE_LISTEN_ONLY)
  MODE_NORMAL              // Normaler Modus (TWAI_MODE_NORMAL)
};

// Globale Variablen
TestMode currentMode = MODE_LOOPBACK_INTERNAL;
uint32_t messagesSent = 0;
uint32_t messagesReceived = 0;
uint32_t errorCount = 0;
bool driverInstalled = false;

// Funktionsdeklarationen
void blinkLED(int times, int delayMs);
bool initTWAI(TestMode mode);
void stopTWAI();
bool sendTestMessage(uint32_t id, uint8_t* data, uint8_t length, uint32_t timeoutMs);
bool receiveMessage(uint32_t timeoutMs);
void printStatus();
void runLoopbackTest(int numMessages);
void resetController();

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
    case MODE_LOOPBACK_INTERNAL:
      twaiMode = TWAI_MODE_NO_ACK;
      break;
    case MODE_LISTEN_ONLY:
      twaiMode = TWAI_MODE_LISTEN_ONLY;
      break;
    case MODE_LOOPBACK_EXTERNAL:
    case MODE_NORMAL:
      twaiMode = TWAI_MODE_NORMAL;
      break;
    default:
      twaiMode = TWAI_MODE_NORMAL;
  }

  // TWAI-Konfiguration
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, twaiMode);
  
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
    case MODE_LOOPBACK_INTERNAL:
      modeStr = "Interner Loopback";
      break;
    case MODE_LOOPBACK_EXTERNAL:
      modeStr = "Externer Loopback";
      break;
    case MODE_LISTEN_ONLY:
      modeStr = "Listen-Only";
      break;
    case MODE_NORMAL:
      modeStr = "Normal";
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
bool sendTestMessage(uint32_t id, uint8_t* data, uint8_t length, uint32_t timeoutMs) {
  if (!driverInstalled) {
    Serial.println("TWAI-Treiber nicht installiert!");
    return false;
  }

  // Test-Nachricht erstellen
  twai_message_t message;
  message.identifier = id;
  message.data_length_code = length;
  message.flags = TWAI_MSG_FLAG_NONE;

  // Daten kopieren
  for (int i = 0; i < length; i++) {
    message.data[i] = data[i];
  }

  // Nachricht senden mit angegebenem Timeout
  esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(timeoutMs));

  if (result == ESP_OK) {
    messagesSent++;
    Serial.printf("Nachricht #%lu gesendet: ID=0x%X, Länge=%d\n", 
                  messagesSent, message.identifier, message.data_length_code);
    
    // Daten anzeigen
    Serial.print("  Daten: ");
    for (int i = 0; i < message.data_length_code; i++) {
      Serial.printf("%02X ", message.data[i]);
    }
    Serial.println();
    
    blinkLED(1, 20);  // Kurzes Blinken bei gesendeter Nachricht
    return true;
  } else {
    errorCount++;
    Serial.printf("Fehler beim Senden der Nachricht! Fehlercode: %d\n", result);
    
    // Detaillierte Fehlerbeschreibung
    switch (result) {
      case ESP_ERR_TIMEOUT:
        Serial.println("  -> Timeout beim Senden (ESP_ERR_TIMEOUT)");
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

// Funktion zum Zurücksetzen des TWAI-Controllers
void resetController() {
  Serial.println("\nSetze TWAI-Controller zurück...");
  
  // Aktuellen Modus speichern
  TestMode savedMode = currentMode;
  
  // TWAI-Treiber stoppen und deinstallieren
  stopTWAI();
  
  // Kurze Pause
  delay(500);
  
  // TWAI-Treiber neu initialisieren
  if (initTWAI(savedMode)) {
    Serial.println("TWAI-Controller erfolgreich zurückgesetzt");
  } else {
    Serial.println("Fehler beim Zurücksetzen des TWAI-Controllers!");
  }
}

// Funktion zum Durchführen eines Loopback-Tests
void runLoopbackTest(int numMessages) {
  Serial.printf("\n=== Starte Loopback-Test mit %d Nachrichten ===\n", numMessages);
  
  // Zähler zurücksetzen
  messagesSent = 0;
  messagesReceived = 0;
  errorCount = 0;
  
  // Status vor dem Test anzeigen
  printStatus();
  
  // Nachrichten senden und empfangen
  for (int i = 0; i < numMessages; i++) {
    // Testdaten erstellen
    uint8_t testData[8] = {(uint8_t)i, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x00};
    
    // Nachricht senden
    Serial.printf("\nSende Test-Nachricht %d/%d...\n", i+1, numMessages);
    if (sendTestMessage(0x123 + i, testData, 8, SEND_TIMEOUT_MS)) {
      // Kurze Pause
      delay(50);
      
      // Auf Antwort warten
      Serial.println("Warte auf Empfang...");
      bool received = false;
      
      // Mehrere Empfangsversuche
      for (int j = 0; j < 5; j++) {
        if (receiveMessage(200)) {  // 200ms Timeout pro Versuch
          received = true;
          break;
        }
      }
      
      if (!received) {
        Serial.println("Keine Nachricht empfangen!");
      }
    }
    
    // Pause zwischen den Nachrichten
    delay(200);
  }
  
  // Status nach dem Test anzeigen
  printStatus();
  
  // Ergebnis anzeigen
  Serial.println("\n=== Loopback-Test Ergebnis ===");
  Serial.printf("Gesendete Nachrichten: %lu\n", messagesSent);
  Serial.printf("Empfangene Nachrichten: %lu\n", messagesReceived);
  Serial.printf("Fehler: %lu\n", errorCount);
  
  if (messagesReceived == 0) {
    Serial.println("\nKRITISCH: Keine Nachrichten empfangen!");
    Serial.println("Mögliche Ursachen:");
    Serial.println("- TWAI-Controller funktioniert nicht korrekt");
    Serial.println("- Loopback-Modus wird nicht unterstützt");
    Serial.println("- Hardware-Problem mit dem ESP32");
  } else if (messagesReceived < messagesSent) {
    Serial.printf("\nWARNUNG: Nur %lu von %lu Nachrichten empfangen!\n", 
                 messagesReceived, messagesSent);
  } else {
    Serial.println("\nERFOLG: Alle Nachrichten erfolgreich empfangen!");
  }
}

// Setup-Funktion
void setup() {
  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(1000);  // Kurze Pause für Stabilität

  Serial.println("\n\n=== ESP32 Advanced TWAI Loopback Test ===");

  // LED-Pin konfigurieren
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // Hardware-Informationen ausgeben
  Serial.printf("ESP32 Chip Revision: %d\n", ESP.getChipRevision());
  Serial.printf("ESP32 SDK Version: %s\n", ESP.getSdkVersion());
  Serial.printf("ESP32 CPU Frequenz: %d MHz\n", ESP.getCpuFreqMHz());

  // Benutzeroptionen
  Serial.println("\nBefehle:");
  Serial.println("- '1': Interner Loopback-Modus (TWAI_MODE_NO_ACK)");
  Serial.println("- '2': Externer Loopback-Modus (TWAI_MODE_NORMAL)");
  Serial.println("- '3': Listen-Only-Modus");
  Serial.println("- '4': Normaler Modus");
  Serial.println("- 't': Loopback-Test durchführen (5 Nachrichten)");
  Serial.println("- 's': Status anzeigen");
  Serial.println("- 'r': TWAI-Controller zurücksetzen");
  Serial.println("- 'm': Einzelne Nachricht senden");

  // TWAI im internen Loopback-Modus initialisieren
  if (!initTWAI(MODE_LOOPBACK_INTERNAL)) {
    Serial.println("Kritischer Fehler bei der TWAI-Initialisierung!");
    while (1) {
      blinkLED(10, 100);  // Schnelles Blinken bei Fehler
      delay(1000);
    }
  }
  
  currentMode = MODE_LOOPBACK_INTERNAL;

  // Kurze Pause für Stabilität
  delay(500);
  
  // Automatisch einen Loopback-Test starten
  runLoopbackTest(3);
}

// Loop-Funktion
void loop() {
  // Auf serielle Eingabe prüfen
  if (Serial.available()) {
    char cmd = Serial.read();

    switch (cmd) {
      case '1':
        // Interner Loopback-Modus
        Serial.println("\nWechsle in internen Loopback-Modus...");
        stopTWAI();
        if (initTWAI(MODE_LOOPBACK_INTERNAL)) {
          currentMode = MODE_LOOPBACK_INTERNAL;
        }
        break;

      case '2':
        // Externer Loopback-Modus
        Serial.println("\nWechsle in externen Loopback-Modus...");
        stopTWAI();
        if (initTWAI(MODE_LOOPBACK_EXTERNAL)) {
          currentMode = MODE_LOOPBACK_EXTERNAL;
        }
        break;

      case '3':
        // Listen-Only-Modus
        Serial.println("\nWechsle in Listen-Only-Modus...");
        stopTWAI();
        if (initTWAI(MODE_LISTEN_ONLY)) {
          currentMode = MODE_LISTEN_ONLY;
        }
        break;

      case '4':
        // Normaler Modus
        Serial.println("\nWechsle in normalen Modus...");
        stopTWAI();
        if (initTWAI(MODE_NORMAL)) {
          currentMode = MODE_NORMAL;
        }
        break;

      case 't':
        // Loopback-Test durchführen
        runLoopbackTest(5);
        break;

      case 's':
        // Status anzeigen
        printStatus();
        break;

      case 'r':
        // TWAI-Controller zurücksetzen
        resetController();
        break;

      case 'm':
        // Einzelne Nachricht senden
        {
          uint8_t testData[8] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
          sendTestMessage(0x123, testData, 8, SEND_TIMEOUT_MS);
        }
        break;
    }
  }

  // Regelmäßig auf Nachrichten prüfen (mit kurzem Timeout)
  receiveMessage(10);

  // Kurze Pause für Stabilität
  delay(50);
}
