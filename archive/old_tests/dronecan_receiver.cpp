/**
 * ESP32 DroneCAN Receiver für Orange Cube
 *
 * Dieses Programm ist optimiert für den Empfang von DroneCAN-Nachrichten vom Orange Cube.
 * Es verwendet einen Reset-Workaround nur für das Senden von Nachrichten.
 */

#include <Arduino.h>
#include "driver/twai.h"
#include "driver/gpio.h"

// CAN-Pins (fest verdrahtet im ESP32)
const gpio_num_t canTxPin = GPIO_NUM_5;  // GPIO5
const gpio_num_t canRxPin = GPIO_NUM_4;  // GPIO4

// LED-Pin für visuelles Feedback
const int ledPin = 2;  // Eingebaute LED auf den meisten ESP32-Boards

// PWM Pin-Definitionen
const int motorPins[4] = {25, 26, 27, 33};  // Pins für die 4 Motoren

// PWM Konfiguration
#define PWM_FREQUENCY 50         // Standard RC PWM Frequenz (50Hz)
#define PWM_RESOLUTION 16        // 16-bit Auflösung
#define PWM_MIN_US 1000          // Min. Pulsbreite in Mikrosekunden
#define PWM_MAX_US 2000          // Max. Pulsbreite in Mikrosekunden

// Zeitpunkte für verschiedene Aktionen
unsigned long lastStatusTime = 0;
unsigned long lastHeartbeatTime = 0;
unsigned long lastActivityTime = 0;
unsigned long startTime = 0;

// Zähler
uint32_t receivedMessages = 0;
uint32_t sendErrorCount = 0;
uint32_t sendSuccessCount = 0;

// DroneCAN Konfiguration
#define DRONECAN_NODE_ID 125  // Unsere Node-ID (1-127)
#define DRONECAN_PRIORITY 24  // Standard-Priorität (niedrigere Werte = höhere Priorität)

// DroneCAN Message Type IDs (nach DroneCAN 1.0 Spezifikation)
#define DRONECAN_MSG_TYPE_NODE_STATUS 341      // 0x155
#define DRONECAN_MSG_TYPE_ACTUATOR_COMMAND 1010 // 0x3F2
#define DRONECAN_MSG_TYPE_ESC_STATUS 1034      // 0x40A

// Motorwerte (0.0-1.0)
float motorValues[4] = {0.0, 0.0, 0.0, 0.0};

// Funktionsdeklarationen
void checkForDroneCANMessages();
void updateMotorPWM(uint8_t motorIndex, float value);

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

// Funktion zum Berechnen einer DroneCAN CAN-ID
uint32_t getCANId(uint16_t messageTypeId, uint8_t sourceNodeId, uint8_t priority = DRONECAN_PRIORITY) {
  return ((priority << 24) | (messageTypeId << 8) | sourceNodeId);
}

// Funktion zum Senden einer DroneCAN Node Status-Nachricht mit Reset
bool sendNodeStatus() {
  // TWAI-Treiber zurücksetzen vor dem Senden
  if (!resetTWAI()) {
    Serial.println("Fehler beim Zurücksetzen des TWAI-Treibers!");
    return false;
  }
  
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
  esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(100));
  
  if (result == ESP_OK) {
    sendSuccessCount++;
    Serial.printf("DroneCAN Node Status gesendet: ID=0x%X, Uptime=%u\n",
                  message.identifier, uptimeSeconds);
    blinkLED(1, 20);  // Kurzes Blinken bei gesendeter Nachricht
    
    // Kurz warten und auf Antworten prüfen
    delay(50);
    checkForDroneCANMessages();
    
    return true;
  } else {
    sendErrorCount++;
    Serial.printf("Fehler beim Senden der Node Status-Nachricht! Fehlercode: %d\n", result);
    return false;
  }
}

// Funktion zum Senden einer DroneCAN Emergency Stop-Nachricht mit Reset
bool sendEmergencyStop() {
  // TWAI-Treiber zurücksetzen vor dem Senden
  if (!resetTWAI()) {
    Serial.println("Fehler beim Zurücksetzen des TWAI-Treibers!");
    return false;
  }
  
  // Nachricht erstellen (vereinfachte Not-Aus-Nachricht)
  twai_message_t message;
  message.identifier = getCANId(DRONECAN_MSG_TYPE_ACTUATOR_COMMAND, DRONECAN_NODE_ID);
  message.data_length_code = 4;
  message.flags = TWAI_MSG_FLAG_NONE;
  
  // Alle Motoren auf 0 setzen
  for (int i = 0; i < 4; i++) {
    message.data[0] = i;  // Actuator Index
    message.data[1] = 0;  // Command LSB (0)
    message.data[2] = 0;  // Command MSB (0)
    message.data[3] = 1;  // Emergency Flag
    
    // Nachricht senden
    esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(100));
    
    if (result == ESP_OK) {
      sendSuccessCount++;
      Serial.printf("Not-Aus für Motor %d gesendet\n", i);
    } else {
      sendErrorCount++;
      Serial.printf("Fehler beim Senden des Not-Aus für Motor %d! Fehlercode: %d\n", i, result);
      return false;
    }
    
    delay(10);  // Kurze Pause zwischen den Nachrichten
  }
  
  Serial.println("Not-Aus für alle Motoren gesendet!");
  blinkLED(5, 100);  // Deutliches Blinken bei Not-Aus
  
  // Kurz warten und auf Antworten prüfen
  delay(50);
  checkForDroneCANMessages();
  
  return true;
}

// Funktion zum Prüfen auf empfangene DroneCAN-Nachrichten
void checkForDroneCANMessages() {
  // TWAI-Nachrichten empfangen
  twai_message_t rx_message;
  esp_err_t result = twai_receive(&rx_message, pdMS_TO_TICKS(10));
  
  if (result == ESP_OK) {
    receivedMessages++;
    lastActivityTime = millis();
    
    // Nachrichtentyp und Quell-Node-ID extrahieren
    uint16_t messageTypeId = (rx_message.identifier >> 8) & 0xFFFF;
    uint8_t sourceNodeId = rx_message.identifier & 0xFF;
    
    Serial.printf("DroneCAN Nachricht empfangen: ID=0x%X, Typ=0x%X, Quelle=%d, Länge=%d, Daten: ",
                  rx_message.identifier, messageTypeId, sourceNodeId, rx_message.data_length_code);
    
    // Alle Bytes der Nachricht ausgeben
    for (int i = 0; i < rx_message.data_length_code; i++) {
      Serial.printf("%02X ", rx_message.data[i]);
    }
    Serial.println();
    
    // Bekannte DroneCAN-Nachrichtentypen interpretieren
    if (messageTypeId == DRONECAN_MSG_TYPE_NODE_STATUS) {
      Serial.println("  -> DroneCAN Node Status");
    } else if (messageTypeId == DRONECAN_MSG_TYPE_ACTUATOR_COMMAND) {
      Serial.println("  -> DroneCAN Actuator Command");
      
      if (rx_message.data_length_code >= 4) {
        uint8_t actuatorIndex = rx_message.data[0];
        uint16_t rawValue = (rx_message.data[2] << 8) | rx_message.data[1];
        float value = rawValue / 65535.0f;
        
        Serial.printf("     Actuator %d = %.2f\n", actuatorIndex, value);
        
        // Motorwert aktualisieren, wenn gültiger Index
        if (actuatorIndex < 4) {
          motorValues[actuatorIndex] = value;
          updateMotorPWM(actuatorIndex, value);
        }
      }
    }
    
    // Schnelles Blinken bei empfangener Nachricht
    blinkLED(1, 10);
  }
}

// Funktion zum Aktualisieren der PWM-Ausgabe für einen Motor
void updateMotorPWM(uint8_t motorIndex, float value) {
  // Wert auf 0.0-1.0 begrenzen
  value = constrain(value, 0.0f, 1.0f);
  
  // PWM-Wert berechnen (1000-2000µs)
  uint32_t pulseWidth = PWM_MIN_US + (uint32_t)(value * (PWM_MAX_US - PWM_MIN_US));
  
  // PWM-Wert in Ticks umrechnen
  uint32_t duty = (uint32_t)((pulseWidth * 65536.0f) / (1000000.0f / PWM_FREQUENCY));
  
  // PWM-Wert setzen
  ledcWrite(motorIndex, duty);
  
  Serial.printf("Motor %d auf %.2f gesetzt (Pulsbreite: %uµs, Duty: %u)\n", 
                motorIndex, value, pulseWidth, duty);
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
  Serial.println("ESP32 DroneCAN Receiver für Orange Cube");
  Serial.println("==============================================");
  Serial.println("Dieses Programm ist optimiert für den Empfang von DroneCAN-Nachrichten");
  Serial.println("vom Orange Cube und verwendet einen Reset-Workaround nur für das Senden.");
  
  // Benutzeroptionen
  Serial.println("\nBefehle:");
  Serial.println("- 's': Status anzeigen");
  Serial.println("- 'n': Node Status senden");
  Serial.println("- 'e': Not-Aus senden (alle Motoren stoppen)");
  
  // PWM Kanäle konfigurieren
  for (int i = 0; i < 4; i++) {
    ledcSetup(i, PWM_FREQUENCY, PWM_RESOLUTION);
    ledcAttachPin(motorPins[i], i);
    
    // Initial alle Motoren auf Minimum setzen
    updateMotorPWM(i, 0.0);
  }
  
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
  lastActivityTime = startTime;
  
  Serial.println("\nDroneCAN Receiver gestartet. Warte auf Nachrichten vom Orange Cube...");
  Serial.println("Bitte stellen Sie sicher, dass:");
  Serial.println("1. Der CAN-Transceiver korrekt mit dem ESP32 verbunden ist");
  Serial.println("2. Der Orange Cube korrekt konfiguriert ist (DroneCAN aktiviert)");
  Serial.println("3. Die Verkabelung zwischen ESP32 und Orange Cube korrekt ist");
  
  // Initial Node Status senden
  sendNodeStatus();
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
        
      case 'n':  // Node Status senden
        sendNodeStatus();
        break;
        
      case 'e':  // Not-Aus senden
        sendEmergencyStop();
        break;
    }
    
    // Restliche Zeichen aus dem Buffer entfernen
    while (Serial.available()) {
      Serial.read();
    }
  }
  
  // Kontinuierlich auf DroneCAN-Nachrichten prüfen
  checkForDroneCANMessages();
  
  // Heartbeat (Node Status) regelmäßig senden (alle 5 Sekunden)
  if (millis() - lastHeartbeatTime > 5000) {
    lastHeartbeatTime = millis();
    sendNodeStatus();
  }
  
  // Regelmäßiger Status-Bericht
  if (millis() - lastStatusTime > 30000) {
    lastStatusTime = millis();
    
    unsigned long runtime = (millis() - startTime) / 1000;
    unsigned long lastActivity = (millis() - lastActivityTime) / 1000;
    
    Serial.printf("\n--- STATUS NACH %lu SEKUNDEN ---\n", runtime);
    Serial.printf("Empfangene Nachrichten: %u\n", receivedMessages);
    Serial.printf("Erfolgreiche Sendungen: %u\n", sendSuccessCount);
    Serial.printf("Fehlgeschlagene Sendungen: %u\n", sendErrorCount);
    Serial.printf("Letzte Aktivität vor: %lu Sekunden\n", lastActivity);
    
    Serial.println("\nAktuelle Motorwerte:");
    for (int i = 0; i < 4; i++) {
      Serial.printf("Motor %d: %.2f\n", i, motorValues[i]);
    }
    
    // TWAI-Status abrufen
    printTWAIStatus();
  }
}
