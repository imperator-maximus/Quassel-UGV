/**
 * ESP32 DroneCAN Orange Cube Test
 *
 * Dieses Programm implementiert eine einfache DroneCAN-Kommunikation
 * speziell für den Orange Cube Autopiloten.
 * Es sendet korrekt formatierte DroneCAN-Nachrichten mit 500 kbps.
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
unsigned long lastNodeStatusTime = 0;
unsigned long lastActuatorCmdTime = 0;
unsigned long lastStatusTime = 0;
unsigned long startTime = 0;

// Zähler
uint8_t messageCounter = 0;
uint8_t receivedMessages = 0;
uint8_t sendErrorCount = 0;

// DroneCAN Konfiguration
#define DRONECAN_NODE_ID 125  // Unsere Node-ID (1-127)
#define DRONECAN_PRIORITY 24  // Standard-Priorität (niedrigere Werte = höhere Priorität)

// DroneCAN Message Type IDs (nach DroneCAN 1.0 Spezifikation)
#define DRONECAN_MSG_TYPE_NODE_STATUS 341      // 0x155
#define DRONECAN_MSG_TYPE_ACTUATOR_COMMAND 1010 // 0x3F2

// Hilfsfunktion zum Blinken der LED
void blinkLED(int times, int duration = 50) {
  for (int i = 0; i < times; i++) {
    digitalWrite(ledPin, HIGH);
    delay(duration);
    digitalWrite(ledPin, LOW);
    delay(duration);
  }
}

// Funktion zum Berechnen einer DroneCAN CAN-ID
uint32_t getCANId(uint16_t messageTypeId, uint8_t sourceNodeId, uint8_t priority = DRONECAN_PRIORITY) {
  return ((priority << 24) | (messageTypeId << 8) | sourceNodeId);
}

// Funktion zum Senden einer DroneCAN Node Status-Nachricht
bool sendNodeStatus() {
  // Uptime in Sekunden berechnen
  uint32_t uptimeSeconds = (millis() - startTime) / 1000;
  
  // Nachricht erstellen
  twai_message_t message;
  message.identifier = getCANId(DRONECAN_MSG_TYPE_NODE_STATUS, DRONECAN_NODE_ID);
  message.data_length_code = 8;
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
  esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(250));
  
  if (result == ESP_OK) {
    Serial.printf("DroneCAN Node Status gesendet: ID=0x%X, Uptime=%u\n",
                  message.identifier, uptimeSeconds);
    blinkLED(1, 20);  // Kurzes Blinken bei gesendeter Nachricht
    return true;
  } else {
    sendErrorCount++;
    Serial.printf("Fehler beim Senden der Node Status-Nachricht! Fehlercode: %d\n", result);
    return false;
  }
}

// Funktion zum Senden einer DroneCAN Actuator Command-Nachricht
bool sendActuatorCommand(uint8_t actuatorIndex, float command) {
  // Command auf 0.0-1.0 begrenzen
  command = constrain(command, 0.0, 1.0);
  
  // Umwandlung in 16-bit Wert (0-65535)
  uint16_t rawValue = (uint16_t)(command * 65535.0f);
  
  // Nachricht erstellen
  twai_message_t message;
  message.identifier = getCANId(DRONECAN_MSG_TYPE_ACTUATOR_COMMAND, DRONECAN_NODE_ID);
  message.data_length_code = 4;  // 4 Bytes Datenlänge
  message.flags = TWAI_MSG_FLAG_NONE;
  
  // Daten nach DroneCAN 1.0 Spezifikation
  message.data[0] = actuatorIndex;  // Actuator Index (0-15)
  message.data[1] = rawValue & 0xFF;  // Command LSB
  message.data[2] = (rawValue >> 8) & 0xFF;  // Command MSB
  message.data[3] = 0;  // Reserved/Flags
  
  // Nachricht senden
  esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(250));
  
  if (result == ESP_OK) {
    Serial.printf("DroneCAN Actuator Command gesendet: ID=0x%X, Index=%d, Wert=%.2f\n",
                  message.identifier, actuatorIndex, command);
    return true;
  } else {
    sendErrorCount++;
    Serial.printf("Fehler beim Senden der Actuator Command-Nachricht! Fehlercode: %d\n", result);
    return false;
  }
}

// Funktion zum Analysieren einer empfangenen CAN-Nachricht
void analyzeCANMessage(const twai_message_t& message) {
  // Nachrichtentyp und Quell-Node-ID extrahieren
  uint16_t messageTypeId = (message.identifier >> 8) & 0xFFFF;
  uint8_t sourceNodeId = message.identifier & 0xFF;
  
  Serial.printf("CAN Nachricht empfangen: ID=0x%X, Typ=0x%X, Quelle=%d, Länge=%d, Daten: ",
                message.identifier, messageTypeId, sourceNodeId, message.data_length_code);
  
  // Alle Bytes der Nachricht ausgeben
  for (int i = 0; i < message.data_length_code; i++) {
    Serial.printf("%02X ", message.data[i]);
  }
  Serial.println();
  
  // Bekannte DroneCAN-Nachrichtentypen interpretieren
  if (messageTypeId == DRONECAN_MSG_TYPE_NODE_STATUS) {
    Serial.println("  -> DroneCAN Node Status");
  } else if (messageTypeId == DRONECAN_MSG_TYPE_ACTUATOR_COMMAND) {
    Serial.println("  -> DroneCAN Actuator Command");
    
    if (message.data_length_code >= 4) {
      uint8_t actuatorIndex = message.data[0];
      uint16_t rawValue = (message.data[2] << 8) | message.data[1];
      float value = rawValue / 65535.0f;
      
      Serial.printf("     Actuator %d = %.2f\n", actuatorIndex, value);
    }
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
    
    // Wenn der Bus im Bus-Off-Zustand ist, versuchen wir, ihn wiederherzustellen
    if (status_info.state == TWAI_STATE_BUS_OFF) {
      Serial.println("Bus ist im Bus-Off-Zustand. Versuche Wiederherstellung...");
      twai_initiate_recovery();
      delay(100);
    }
  } else {
    Serial.printf("Fehler beim Abrufen des TWAI-Status! Fehlercode: %d\n", result);
  }
}

// Funktion zum Ausgeben von Diagnose-Informationen
void printDiagnostics() {
  unsigned long runtime = (millis() - startTime) / 1000;
  Serial.printf("\n--- DIAGNOSE NACH %lu SEKUNDEN ---\n", runtime);
  Serial.printf("Baudrate: 500 kbps\n");
  Serial.printf("DroneCAN Node ID: %d\n", DRONECAN_NODE_ID);
  Serial.printf("Empfangene Nachrichten: %d\n", receivedMessages);
  Serial.printf("Sendefehler: %d\n", sendErrorCount);
  
  // TWAI-Status abrufen
  printTWAIStatus();
  
  // Orange Cube Konfigurationstipps
  Serial.println("Orange Cube Konfigurationstipps:");
  Serial.println("1. Stelle sicher, dass DroneCAN auf dem Orange Cube aktiviert ist:");
  Serial.println("   - CAN_P1_DRIVER = 1");
  Serial.println("   - CAN_P1_BITRATE = 500000");
  Serial.println("   - CAN_D1_PROTOCOL = 1 (DroneCAN)");
  Serial.println("   - CAN_D1_UC_NODE = 1");
  Serial.println("2. Überprüfe die Verkabelung:");
  Serial.println("   - ESP32 GPIO5 -> TX-Eingang des Transceivers");
  Serial.println("   - ESP32 GPIO4 -> RX-Ausgang des Transceivers");
  Serial.println("   - CANH -> CANH des Orange Cube");
  Serial.println("   - CANL -> CANL des Orange Cube");
  Serial.println("3. Überprüfe die Terminierung (120 Ohm an beiden Enden)");
  
  Serial.println("--- ENDE DIAGNOSE ---\n");
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
  Serial.println("ESP32 DroneCAN Orange Cube Test");
  Serial.println("==============================================");
  Serial.println("Dieses Programm implementiert eine einfache DroneCAN-Kommunikation");
  Serial.println("speziell für den Orange Cube Autopiloten mit 500 kbps.");
  
  // Benutzeroptionen
  Serial.println("\nBefehle:");
  Serial.println("- 's': Status anzeigen");
  Serial.println("- 'd': Diagnose anzeigen");
  Serial.println("- 'n': Node Status senden");
  Serial.println("- '0'-'9': Actuator Command für den entsprechenden Kanal senden");
  
  // TWAI-Konfiguration
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(canTxPin, canRxPin, TWAI_MODE_NORMAL);
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
  
  Serial.printf("TWAI erfolgreich initialisiert mit 500 kbps: TX Pin=%d, RX Pin=%d\n", canTxPin, canRxPin);
  
  // Startzeit speichern
  startTime = millis();
  
  Serial.println("\nDroneCAN-Test gestartet. Sende Node Status und Actuator Commands...");
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
        
      case 'd':  // Diagnose anzeigen
        printDiagnostics();
        break;
        
      case 'n':  // Node Status senden
        sendNodeStatus();
        break;
        
      default:
        // Prüfen, ob es eine Zahl ist (0-9)
        if (cmd >= '0' && cmd <= '9') {
          uint8_t channel = cmd - '0';
          float value = 0.5;  // Mittlere Position
          
          Serial.printf("\nSende Actuator Command für Kanal %d = %.2f\n", channel, value);
          sendActuatorCommand(channel, value);
        }
        break;
    }
    
    // Restliche Zeichen aus dem Buffer entfernen
    while (Serial.available()) {
      Serial.read();
    }
  }
  
  // TWAI-Nachrichten empfangen
  twai_message_t rx_message;
  esp_err_t result = twai_receive(&rx_message, pdMS_TO_TICKS(10));
  
  if (result == ESP_OK) {
    receivedMessages++;
    analyzeCANMessage(rx_message);
    blinkLED(3, 30);  // Schnelles Blinken bei empfangener Nachricht
  }
  
  // Node Status regelmäßig senden (alle 1000ms)
  if (millis() - lastNodeStatusTime > 1000) {
    lastNodeStatusTime = millis();
    sendNodeStatus();
  }
  
  // Actuator Commands regelmäßig senden (alle 100ms)
  if (millis() - lastActuatorCmdTime > 100) {
    lastActuatorCmdTime = millis();
    
    // Oszillierende Werte für die Tests
    static float value = 0.0;
    static float step = 0.01;
    
    value += step;
    if (value >= 1.0 || value <= 0.0) {
      step = -step;
    }
    
    // Actuator Commands für Kanäle 0-3 senden
    for (int i = 0; i < 4; i++) {
      float channelValue = (i % 2 == 0) ? value : 1.0 - value;  // Abwechselnd normal und invertiert
      sendActuatorCommand(i, channelValue);
    }
  }
  
  // Regelmäßiger Status-Bericht
  if (millis() - lastStatusTime > 10000) {
    lastStatusTime = millis();
    printDiagnostics();
  }
}
