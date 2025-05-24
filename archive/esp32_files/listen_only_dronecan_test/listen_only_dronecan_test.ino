/**
 * ESP32 DroneCAN Listen-Only Test
 *
 * Dieses Programm initialisiert den TWAI-Treiber im Listen-Only-Modus,
 * um DroneCAN-Nachrichten vom Orange Cube zu empfangen, ohne selbst zu senden.
 * Dies vermeidet BUS-OFF-Zustände und ist ideal zum Testen der Empfangsfunktion.
 */

#include <Arduino.h>
#include <driver/twai.h>

// Pin-Definitionen
#define LED_PIN    GPIO_NUM_2  // Onboard-LED für Statusanzeige
#define CAN_TX_PIN GPIO_NUM_5  // Pin 5 auf dem Freenove Board
#define CAN_RX_PIN GPIO_NUM_4  // Pin 4 auf dem Freenove Board

// DroneCAN Message Type IDs (nach DroneCAN 1.0 Spezifikation)
#define DRONECAN_MSG_TYPE_NODE_STATUS 341      // 0x155
#define DRONECAN_MSG_TYPE_ACTUATOR_COMMAND 1010 // 0x3F2
#define DRONECAN_MSG_TYPE_ESC_STATUS 1034      // 0x40A

// Zeitintervalle
#define STATUS_CHECK_INTERVAL 5000    // Intervall für Statusprüfung (ms)

// Zeitpunkte für verschiedene Aktionen
unsigned long lastStatusCheckTime = 0;
unsigned long startTime = 0;

// Zähler
uint32_t receivedMessages = 0;

// Bus-Status
bool driverInstalled = false;

// Funktionsdeklarationen
void blinkLED(int times, int delayMs);
bool initTWAI();
void checkTWAIStatus();
void checkForDroneCANMessages();

// Funktion zum Blinken der LED
void blinkLED(int times, int delayMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(delayMs);
    digitalWrite(LED_PIN, LOW);
    delay(delayMs);
  }
}

// Funktion zum Initialisieren des TWAI-Treibers im Listen-Only-Modus
bool initTWAI() {
  // TWAI-Konfiguration mit Listen-Only-Modus
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_LISTEN_ONLY);
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

  Serial.printf("TWAI erfolgreich im LISTEN-ONLY-Modus initialisiert mit 500 kbps: TX Pin=%d, RX Pin=%d\n",
                (int)CAN_TX_PIN, (int)CAN_RX_PIN);
  return true;
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

// Funktion zum Prüfen auf empfangene DroneCAN-Nachrichten
void checkForDroneCANMessages() {
  if (!driverInstalled) {
    return;
  }

  // TWAI-Nachrichten empfangen
  twai_message_t rx_message;
  esp_err_t result = twai_receive(&rx_message, pdMS_TO_TICKS(10));

  if (result == ESP_OK) {
    receivedMessages++;

    // CAN-ID analysieren
    uint32_t canId = rx_message.identifier;
    uint8_t sourceNodeId = canId & 0xFF;
    uint16_t messageTypeId = (canId >> 8) & 0xFFFF;
    uint8_t priority = (canId >> 24) & 0xFF;

    Serial.printf("\nCAN-Nachricht #%lu empfangen: ID=0x%X, Länge=%d\n",
                  receivedMessages, canId, rx_message.data_length_code);
    Serial.printf("  Format: %s, RTR: %s\n", 
                  (rx_message.flags & TWAI_MSG_FLAG_EXTD) ? "Extended" : "Standard",
                  (rx_message.flags & TWAI_MSG_FLAG_RTR) ? "Ja" : "Nein");
    
    // Wenn es eine Extended-ID ist, DroneCAN-Felder extrahieren
    if (rx_message.flags & TWAI_MSG_FLAG_EXTD) {
      Serial.printf("  DroneCAN: Node-ID=%d, Nachrichtentyp=0x%X, Priorität=%d\n",
                    sourceNodeId, messageTypeId, priority);
    }

    // Daten anzeigen
    Serial.print("  Daten: ");
    for (int i = 0; i < rx_message.data_length_code; i++) {
      Serial.printf("%02X ", rx_message.data[i]);
    }
    Serial.println();

    // Bekannte DroneCAN-Nachrichtentypen interpretieren (nur für Extended-IDs)
    if (rx_message.flags & TWAI_MSG_FLAG_EXTD) {
      if (messageTypeId == DRONECAN_MSG_TYPE_NODE_STATUS) {
        Serial.println("  -> DroneCAN Node Status");

        // Node Status interpretieren
        uint32_t uptime = rx_message.data[0] |
                          (rx_message.data[1] << 8) |
                          (rx_message.data[2] << 16) |
                          (rx_message.data[3] << 24);
        uint8_t health = rx_message.data[4];
        uint8_t mode = rx_message.data[5];

        Serial.printf("     Uptime: %u Sekunden\n", uptime);
        Serial.printf("     Health: %u\n", health);
        Serial.printf("     Mode: %u\n", mode);

      } else if (messageTypeId == DRONECAN_MSG_TYPE_ACTUATOR_COMMAND) {
        Serial.println("  -> DroneCAN Actuator Command");

        if (rx_message.data_length_code >= 4) {
          uint8_t actuatorIndex = rx_message.data[0];
          uint16_t rawValue = (rx_message.data[2] << 8) | rx_message.data[1];
          float value = rawValue / 65535.0f;

          Serial.printf("     Actuator %d = %.2f\n", actuatorIndex, value);
        }
      }
    }

    // Schnelles Blinken bei empfangener Nachricht
    blinkLED(1, 10);
  }
}

// Setup-Funktion
void setup() {
  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(1000);  // Kurze Pause für Stabilität

  Serial.println("\n\n=== ESP32 DroneCAN Listen-Only Test ===");
  Serial.println("Version 1.0 - Nur Empfang, kein Senden");

  // LED-Pin konfigurieren
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // Hardware-Informationen ausgeben
  Serial.printf("ESP32 Chip Revision: %d\n", ESP.getChipRevision());
  Serial.printf("ESP32 SDK Version: %s\n", ESP.getSdkVersion());
  Serial.printf("ESP32 CPU Frequenz: %d MHz\n", ESP.getCpuFreqMHz());
  Serial.printf("ESP32 Flash Größe: %d bytes\n", ESP.getFlashChipSize());

  // Konfigurationsparameter anzeigen
  Serial.println("\nKonfiguration:");
  Serial.printf("- CAN TX Pin: %d\n", (int)CAN_TX_PIN);
  Serial.printf("- CAN RX Pin: %d\n", (int)CAN_RX_PIN);
  Serial.printf("- CAN Baudrate: 500 kbps\n");
  Serial.printf("- Modus: LISTEN-ONLY (nur Empfang)\n");

  // Benutzeroptionen
  Serial.println("\nBefehle:");
  Serial.println("- 's': Status anzeigen");

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

  Serial.println("\nDroneCAN Listen-Only Test gestartet. Warte auf Nachrichten...");
  Serial.println("Bitte führen Sie Aktionen in Mission Planner aus, um CAN-Aktivität zu erzeugen.");
  Serial.println("Zum Beispiel: Servo-Werte ändern, Modi wechseln, etc.");
}

// Loop-Funktion
void loop() {
  // Auf serielle Eingabe prüfen
  if (Serial.available()) {
    char cmd = Serial.read();

    switch (cmd) {
      case 's':
        checkTWAIStatus();
        break;
    }
  }

  // Status regelmäßig prüfen
  if (millis() - lastStatusCheckTime > STATUS_CHECK_INTERVAL) {
    lastStatusCheckTime = millis();
    checkTWAIStatus();
    
    // Statistik ausgeben
    Serial.printf("\nStatistik: %lu Nachrichten empfangen in %lu Sekunden\n", 
                  receivedMessages, (millis() - startTime) / 1000);
  }

  // Kontinuierlich auf eingehende Nachrichten prüfen
  checkForDroneCANMessages();

  // Kurze Pause für Stabilität
  delay(5);
}
