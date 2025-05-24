/**
 * ESP32 CAN Transceiver Test
 *
 * Dieses Programm testet die Verbindung zwischen dem ESP32 und dem CAN-Transceiver.
 * Es versucht, Nachrichten zu senden und gibt detaillierte Fehlerinformationen aus.
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

// Baudrate-Einstellungen
const int baudrates[] = {500000, 250000, 1000000, 125000};
const char* baudrateNames[] = {"500 kbps", "250 kbps", "1 Mbps", "125 kbps"};
int currentBaudrateIndex = 0;
unsigned long lastBaudrateChangeTime = 0;
bool baudrateTestMode = false;

// Hilfsfunktion zum Blinken der LED
void blinkLED(int times, int duration = 50) {
  for (int i = 0; i < times; i++) {
    digitalWrite(ledPin, HIGH);
    delay(duration);
    digitalWrite(ledPin, LOW);
    delay(duration);
  }
}

// Funktion zum Initialisieren des TWAI-Treibers mit einer bestimmten Baudrate
bool initTWAI(int baudrate) {
  // TWAI-Treiber stoppen und deinstallieren, falls er bereits läuft
  twai_stop();
  twai_driver_uninstall();
  delay(100);  // Kurze Pause für Stabilität
  
  // TWAI-Konfiguration
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(canTxPin, canRxPin, TWAI_MODE_NORMAL);
  
  // Timing-Konfiguration basierend auf der Baudrate
  twai_timing_config_t t_config;
  switch (baudrate) {
    case 1000000:
      t_config = TWAI_TIMING_CONFIG_1MBITS();
      break;
    case 500000:
      t_config = TWAI_TIMING_CONFIG_500KBITS();
      break;
    case 250000:
      t_config = TWAI_TIMING_CONFIG_250KBITS();
      break;
    case 125000:
      t_config = TWAI_TIMING_CONFIG_125KBITS();
      break;
    default:
      t_config = TWAI_TIMING_CONFIG_500KBITS();
      break;
  }
  
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
  
  Serial.printf("TWAI erfolgreich initialisiert mit %s: TX Pin=%d, RX Pin=%d\n", 
                baudrateNames[currentBaudrateIndex], canTxPin, canRxPin);
  return true;
}

// Funktion zum Senden einer TWAI-Testnachricht
bool sendTWAIMessage(uint32_t id) {
  // Test-Nachricht erstellen
  twai_message_t message;
  message.identifier = id;
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
  message.data[7] = currentBaudrateIndex;  // Aktuelle Baudrate als Marker
  
  // Nachricht senden mit kürzerem Timeout (250ms)
  esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(250));
  
  if (result == ESP_OK) {
    Serial.printf("TWAI Nachricht gesendet: ID=0x%X, Counter=%d, Baudrate=%s\n", 
                  message.identifier, messageCounter-1, baudrateNames[currentBaudrateIndex]);
    blinkLED(1, 20);  // Kurzes Blinken bei gesendeter Nachricht
    return true;
  } else {
    sendErrorCount++;
    Serial.printf("Fehler beim Senden der TWAI-Nachricht! Fehlercode: %d\n", result);
    
    // Detaillierte Fehleranalyse
    if (result == ESP_ERR_TIMEOUT) {
      Serial.println("  - Timeout beim Senden. Mögliche Ursachen:");
      Serial.println("    * Kein CAN-Transceiver angeschlossen");
      Serial.println("    * CAN-Transceiver nicht korrekt verkabelt");
      Serial.println("    * CAN-Bus nicht korrekt terminiert");
      Serial.println("    * Falsche Baudrate");
    } else if (result == ESP_ERR_INVALID_STATE) {
      Serial.println("  - Ungültiger Zustand. TWAI-Treiber nicht initialisiert oder im falschen Modus.");
    } else if (result == ESP_ERR_INVALID_ARG) {
      Serial.println("  - Ungültiges Argument. Nachrichtenformat nicht korrekt.");
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
  Serial.printf("Aktuelle Baudrate: %s\n", baudrateNames[currentBaudrateIndex]);
  Serial.printf("Gesendete Nachrichten: %d\n", messageCounter);
  Serial.printf("Empfangene Nachrichten: %d\n", receivedMessages);
  Serial.printf("Sendefehler: %d\n", sendErrorCount);
  
  // Hardware-Informationen
  Serial.println("\nHardware-Informationen:");
  Serial.printf("- ESP32 Chip Revision: %d\n", ESP.getChipRevision());
  Serial.printf("- ESP32 CPU Frequenz: %d MHz\n", ESP.getCpuFreqMHz());
  Serial.printf("- ESP32 Flash Größe: %d bytes\n", ESP.getFlashChipSize());
  
  // TWAI-Status abrufen
  printTWAIStatus();
  
  // Verkabelungs-Tipps
  Serial.println("Verkabelungs-Tipps:");
  Serial.println("1. Überprüfe, ob der CAN-Transceiver korrekt mit dem ESP32 verbunden ist:");
  Serial.println("   - ESP32 GPIO5 -> TX-Eingang des Transceivers");
  Serial.println("   - ESP32 GPIO4 -> RX-Ausgang des Transceivers");
  Serial.println("   - 3.3V -> VCC des Transceivers");
  Serial.println("   - GND -> GND des Transceivers");
  Serial.println("2. Überprüfe, ob der CAN-Transceiver korrekt mit dem CAN-Bus verbunden ist:");
  Serial.println("   - CANH -> CANH des Orange Cube");
  Serial.println("   - CANL -> CANL des Orange Cube");
  Serial.println("3. Überprüfe, ob der CAN-Bus korrekt terminiert ist (120 Ohm an beiden Enden)");
  Serial.println("4. Überprüfe, ob der Orange Cube für DroneCAN konfiguriert ist");
  
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
  Serial.println("ESP32 CAN Transceiver Test");
  Serial.println("==============================================");
  Serial.println("Dieses Programm testet die Verbindung zwischen dem ESP32 und dem CAN-Transceiver.");
  Serial.println("Es versucht, Nachrichten zu senden und gibt detaillierte Fehlerinformationen aus.");
  
  // Benutzeroptionen
  Serial.println("\nBefehle:");
  Serial.println("- 'b': Baudrate wechseln");
  Serial.println("- 't': Baudrate-Test-Modus ein/aus");
  Serial.println("- 's': Status anzeigen");
  Serial.println("- 'd': Diagnose anzeigen");
  Serial.println("- 'r': TWAI-Treiber neu initialisieren");
  
  // TWAI initialisieren mit der ersten Baudrate
  if (!initTWAI(baudrates[currentBaudrateIndex])) {
    Serial.println("Kritischer Fehler bei der TWAI-Initialisierung!");
    while (1) {
      blinkLED(10, 100);  // Schnelles Blinken bei Fehler
      delay(1000);
    }
  }
  
  // Startzeit speichern
  startTime = millis();
  lastBaudrateChangeTime = startTime;
  
  Serial.println("\nCAN-Transceiver-Test gestartet. Sende Testnachrichten...");
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
      case 'b':  // Baudrate wechseln
        currentBaudrateIndex = (currentBaudrateIndex + 1) % 4;
        Serial.printf("\nWechsle zu Baudrate: %s\n", baudrateNames[currentBaudrateIndex]);
        if (!initTWAI(baudrates[currentBaudrateIndex])) {
          Serial.println("Fehler beim Wechseln der Baudrate!");
        }
        break;
        
      case 't':  // Baudrate-Test-Modus ein/aus
        baudrateTestMode = !baudrateTestMode;
        Serial.printf("\nBaudrate-Test-Modus: %s\n", baudrateTestMode ? "EIN" : "AUS");
        break;
        
      case 's':  // Status anzeigen
        printTWAIStatus();
        break;
        
      case 'd':  // Diagnose anzeigen
        printDiagnostics();
        break;
        
      case 'r':  // TWAI-Treiber neu initialisieren
        Serial.println("\nInitialisiere TWAI-Treiber neu...");
        if (!initTWAI(baudrates[currentBaudrateIndex])) {
          Serial.println("Fehler bei der Neuinitialisierung!");
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
  
  // Periodisch TWAI-Nachrichten mit verschiedenen IDs senden (alle 500ms)
  if (millis() - lastSentTime > 500) {
    lastSentTime = millis();
    
    // Wechselnde IDs verwenden
    static uint32_t testIds[] = {0x123, 0x3F2, 0x155, 0x001, 0x7FF};
    static int idIndex = 0;
    
    sendTWAIMessage(testIds[idIndex]);
    idIndex = (idIndex + 1) % 5;
  }
  
  // Im Baudrate-Test-Modus alle 10 Sekunden die Baudrate wechseln
  if (baudrateTestMode && millis() - lastBaudrateChangeTime > 10000) {
    lastBaudrateChangeTime = millis();
    currentBaudrateIndex = (currentBaudrateIndex + 1) % 4;
    
    Serial.printf("\nBaudrate-Test: Wechsle zu %s\n", baudrateNames[currentBaudrateIndex]);
    if (!initTWAI(baudrates[currentBaudrateIndex])) {
      Serial.println("Fehler beim Wechseln der Baudrate!");
    }
  }
  
  // Regelmäßiger Status-Bericht
  if (millis() - lastStatusTime > 10000) {
    lastStatusTime = millis();
    printDiagnostics();
  }
}
