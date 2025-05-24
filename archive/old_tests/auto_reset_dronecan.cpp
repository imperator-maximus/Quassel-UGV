/**
 * ESP32 DroneCAN mit automatischem TWAI-Reset
 *
 * Dieses Programm implementiert DroneCAN 1.0 Kommunikation zwischen einem ESP32 und
 * einem Orange Cube Autopiloten mit automatischer Überwachung und Zurücksetzung des
 * TWAI-Treibers bei BUS-OFF-Zuständen.
 */

#include <Arduino.h>
#include <driver/twai.h>
#include "can_config.h"  // Verwende die vorhandene Konfigurationsdatei

// Pin-Definitionen
#define LED_PIN    GPIO_NUM_2  // Onboard-LED für Statusanzeige

// DroneCAN Konfiguration
#define DRONECAN_NODE_ID 125  // Unsere Node-ID (1-127)
#define DRONECAN_PRIORITY 24  // Standard-Priorität (niedrigere Werte = höhere Priorität)

// DroneCAN Message Type IDs (nach DroneCAN 1.0 Spezifikation)
#define DRONECAN_MSG_TYPE_NODE_STATUS 341      // 0x155
#define DRONECAN_MSG_TYPE_ACTUATOR_COMMAND 1010 // 0x3F2
#define DRONECAN_MSG_TYPE_ESC_STATUS 1034      // 0x40A

// Zeitintervalle
#define STATUS_CHECK_INTERVAL 2000    // Intervall für Statusprüfung (ms)
#define NODE_STATUS_INTERVAL 3000     // Intervall für Node Status Nachrichten (ms)
#define BUS_RECOVERY_INTERVAL 5000    // Intervall für Bus-Wiederherstellung (ms)

// Zeitpunkte für verschiedene Aktionen
unsigned long lastStatusCheckTime = 0;
unsigned long lastNodeStatusTime = 0;
unsigned long lastBusRecoveryTime = 0;
unsigned long startTime = 0;

// Zähler
uint32_t receivedMessages = 0;
uint32_t sendErrorCount = 0;
uint32_t sendSuccessCount = 0;
uint32_t busResetCount = 0;

// Bus-Status
bool busOffDetected = false;
bool driverInstalled = false;

// Funktionsdeklarationen
void blinkLED(int times, int delayMs);
uint32_t getCANId(uint16_t messageTypeId, uint8_t sourceNodeId, uint8_t priority = DRONECAN_PRIORITY);
bool initTWAI();
bool resetTWAI();
void checkTWAIStatus();
void checkForDroneCANMessages();
bool sendNodeStatus();

// Funktion zum Blinken der LED
void blinkLED(int times, int delayMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(delayMs);
    digitalWrite(LED_PIN, LOW);
    delay(delayMs);
  }
}

// Funktion zum Berechnen einer DroneCAN CAN-ID
uint32_t getCANId(uint16_t messageTypeId, uint8_t sourceNodeId, uint8_t priority) {
  return ((priority << 24) | (messageTypeId << 8) | sourceNodeId);
}

// Funktion zum Initialisieren des TWAI-Treibers
bool initTWAI() {
  // TWAI-Konfiguration
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_NORMAL);
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

  Serial.printf("TWAI erfolgreich initialisiert mit 500 kbps: TX Pin=%d, RX Pin=%d\n",
                (int)CAN_TX_PIN, (int)CAN_RX_PIN);
  return true;
}

// Funktion zum Zurücksetzen des TWAI-Treibers
bool resetTWAI() {
  Serial.println("\n*** TWAI-TREIBER WIRD ZURÜCKGESETZT ***");
  busResetCount++;

  // TWAI-Treiber stoppen und deinstallieren
  if (driverInstalled) {
    twai_stop();
    twai_driver_uninstall();
    driverInstalled = false;
  }

  delay(100);  // Kurze Pause für Stabilität

  // TWAI-Treiber neu initialisieren
  bool result = initTWAI();

  if (result) {
    Serial.println("TWAI-Treiber erfolgreich zurückgesetzt");
    busOffDetected = false;
  } else {
    Serial.println("Fehler beim Zurücksetzen des TWAI-Treibers!");
  }

  return result;
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
      busOffDetected = true;
      break;
    case TWAI_STATE_RECOVERING:
      Serial.println("- Bus-Status: RECOVERING (Wiederherstellung läuft)");
      break;
    default:
      Serial.printf("- Bus-Status: UNBEKANNT (%d)\n", status.state);
  }

  Serial.println("--- ENDE STATUS ---");

  // Automatischer Reset bei BUS-OFF-Zustand
  if (busOffDetected) {
    // Nur alle BUS_RECOVERY_INTERVAL ms zurücksetzen, um ständige Resets zu vermeiden
    if (millis() - lastBusRecoveryTime > BUS_RECOVERY_INTERVAL) {
      lastBusRecoveryTime = millis();
      resetTWAI();
    }
  }
}

// Funktion zum Senden einer DroneCAN Node Status-Nachricht
bool sendNodeStatus() {
  // TWAI-Treiber vor jeder Nachricht zurücksetzen
  if (!resetTWAI()) {
    Serial.println("Fehler beim Zurücksetzen des TWAI-Treibers vor dem Senden!");
    return false;
  }

  // Kurze Pause für Stabilität
  delay(50);

  // Uptime in Sekunden berechnen
  uint32_t uptimeSeconds = (millis() - startTime) / 1000;

  // Nachricht erstellen
  twai_message_t message;
  message.identifier = getCANId(DRONECAN_MSG_TYPE_NODE_STATUS, DRONECAN_NODE_ID);
  message.data_length_code = 8;  // 8 Bytes Datenlänge
  message.flags = TWAI_MSG_FLAG_NONE;

  // Daten für Node Status nach DroneCAN 1.0 Spezifikation
  message.data[0] = uptimeSeconds & 0xFF;          // Uptime LSB
  message.data[1] = (uptimeSeconds >> 8) & 0xFF;   // Uptime
  message.data[2] = (uptimeSeconds >> 16) & 0xFF;  // Uptime
  message.data[3] = (uptimeSeconds >> 24) & 0xFF;  // Uptime MSB
  message.data[4] = 0;  // Health (0 = OK)
  message.data[5] = 1;  // Mode (1 = Operational)
  message.data[6] = 0;  // Sub-Mode
  message.data[7] = 0;  // Vendor-specific status

  // Nachricht senden
  esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(100));

  if (result == ESP_OK) {
    sendSuccessCount++;
    Serial.printf("DroneCAN Node Status gesendet: ID=0x%X, Uptime=%u\n",
                  message.identifier, uptimeSeconds);
    blinkLED(1, 20);  // Kurzes Blinken bei gesendeter Nachricht

    // Kurze Pause nach dem Senden
    delay(20);

    // Auf eingehende Nachrichten prüfen
    checkForDroneCANMessages();

    return true;
  } else {
    sendErrorCount++;
    Serial.printf("Fehler beim Senden der Node Status-Nachricht! Fehlercode: %d\n", result);

    // Bei Sendefehler Status prüfen
    checkTWAIStatus();
    return false;
  }
}

// Funktion zum Prüfen auf empfangene DroneCAN-Nachrichten
void checkForDroneCANMessages() {
  if (!driverInstalled || busOffDetected) {
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

    Serial.printf("\nDroneCAN-Nachricht empfangen: ID=0x%X, Länge=%d\n",
                  canId, rx_message.data_length_code);
    Serial.printf("  Quelle: Node-ID=%d, Nachrichtentyp=0x%X, Priorität=%d\n",
                  sourceNodeId, messageTypeId, priority);

    // Daten anzeigen
    Serial.print("  Daten: ");
    for (int i = 0; i < rx_message.data_length_code; i++) {
      Serial.printf("%02X ", rx_message.data[i]);
    }
    Serial.println();

    // Bekannte DroneCAN-Nachrichtentypen interpretieren
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

    // Schnelles Blinken bei empfangener Nachricht
    blinkLED(1, 10);
  }
}

// Setup-Funktion
void setup() {
  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(1000);  // Kurze Pause für Stabilität

  Serial.println("\n\n=== ESP32 DroneCAN mit Auto-Reset ===");
  Serial.println("Version 1.0 - Reset vor jeder Nachricht");

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
  Serial.printf("- DroneCAN Node ID: %d\n", DRONECAN_NODE_ID);

  // Benutzeroptionen
  Serial.println("\nBefehle:");
  Serial.println("- 's': Status anzeigen");
  Serial.println("- 'n': Node Status senden");
  Serial.println("- 'r': TWAI-Treiber zurücksetzen");

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

  Serial.println("\nDroneCAN-Test mit Auto-Reset gestartet. Überwache Bus-Status...");
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
      case 'n':
        sendNodeStatus();
        break;
      case 'r':
        resetTWAI();
        break;
    }
  }

  // Status regelmäßig prüfen (weniger häufig, da wir vor jeder Nachricht zurücksetzen)
  if (millis() - lastStatusCheckTime > STATUS_CHECK_INTERVAL * 2) {
    lastStatusCheckTime = millis();
    checkTWAIStatus();
  }

  // Node Status regelmäßig senden (weniger häufig, da der Reset Zeit braucht)
  if (millis() - lastNodeStatusTime > NODE_STATUS_INTERVAL * 3) {
    lastNodeStatusTime = millis();
    sendNodeStatus();
  }

  // Auf eingehende Nachrichten prüfen (nach jedem Reset in sendNodeStatus wird dies bereits aufgerufen)
  // Daher hier nicht mehr nötig

  // Kurze Pause für Stabilität
  delay(10);
}
