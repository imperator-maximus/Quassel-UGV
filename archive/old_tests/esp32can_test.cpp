/**
 * ESP32 Alternative CAN Library Test
 *
 * Dieses Programm testet die CAN-Kommunikation mit der ESP32CAN-Bibliothek
 * anstelle der nativen TWAI-Bibliothek.
 */

#include <Arduino.h>
#include <ESP32CAN.h>
#include <CAN_config.h>

// CAN-Instanz
CAN_device_t CAN_cfg;

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

// Hilfsfunktion zum Blinken der LED
void blinkLED(int times, int duration = 50) {
  for (int i = 0; i < times; i++) {
    digitalWrite(ledPin, HIGH);
    delay(duration);
    digitalWrite(ledPin, LOW);
    delay(duration);
  }
}

// Funktion zum Initialisieren des CAN-Controllers
bool initCAN() {
  // CAN-Konfiguration
  CAN_cfg.speed = CAN_SPEED_500KBPS;
  CAN_cfg.tx_pin_id = GPIO_NUM_5;  // GPIO5
  CAN_cfg.rx_pin_id = GPIO_NUM_4;  // GPIO4
  CAN_cfg.rx_queue = xQueueCreate(10, sizeof(CAN_frame_t));
  
  // CAN-Modul initialisieren
  esp_err_t result = ESP32Can.CANInit();
  
  if (result == ESP_OK) {
    Serial.printf("CAN erfolgreich initialisiert: TX Pin=%d, RX Pin=%d\n", 
                  CAN_cfg.tx_pin_id, CAN_cfg.rx_pin_id);
    return true;
  } else {
    Serial.printf("Fehler bei der CAN-Initialisierung! Fehlercode: %d\n", result);
    return false;
  }
}

// Funktion zum Zurücksetzen des CAN-Controllers
bool resetCAN() {
  // CAN-Modul stoppen
  ESP32Can.CANStop();
  delay(50);  // Kurze Pause für Stabilität
  
  // CAN-Modul neu initialisieren
  return initCAN();
}

// Funktion zum Senden einer einfachen CAN-Testnachricht
bool sendCANMessage() {
  // Einfache Test-Nachricht erstellen
  CAN_frame_t tx_frame;
  tx_frame.FIR.B.FF = CAN_frame_std;  // Standard-Frame
  tx_frame.MsgID = 0x123;             // Standard Test-ID
  tx_frame.FIR.B.DLC = 8;             // Datenlänge (8 Bytes)
  
  // Testdaten
  tx_frame.data.u8[0] = messageCounter++;
  tx_frame.data.u8[1] = 0xAA;
  tx_frame.data.u8[2] = 0xBB;
  tx_frame.data.u8[3] = 0xCC;
  tx_frame.data.u8[4] = 0xDD;
  tx_frame.data.u8[5] = 0xEE;
  tx_frame.data.u8[6] = 0xFF;
  tx_frame.data.u8[7] = 0x00;
  
  // Nachricht senden
  esp_err_t result = ESP32Can.CANWriteFrame(&tx_frame);
  
  if (result == ESP_OK) {
    sendSuccessCount++;
    Serial.printf("CAN Nachricht gesendet: ID=0x%X, Counter=%d, Erfolge=%d, Fehler=%d\n", 
                  tx_frame.MsgID, messageCounter-1, sendSuccessCount, sendErrorCount);
    blinkLED(1, 20);  // Kurzes Blinken bei gesendeter Nachricht
    return true;
  } else {
    sendErrorCount++;
    Serial.printf("Fehler beim Senden der CAN-Nachricht! Fehlercode: %d, Erfolge=%d, Fehler=%d\n", 
                  result, sendSuccessCount, sendErrorCount);
    return false;
  }
}

// Funktion zum Senden einer CAN-Nachricht mit automatischem Reset
bool sendCANMessageWithReset() {
  // CAN-Controller zurücksetzen vor dem Senden
  if (!resetCAN()) {
    Serial.println("Fehler beim Zurücksetzen des CAN-Controllers!");
    return false;
  }
  
  // Nachricht senden
  return sendCANMessage();
}

// Funktion zum Prüfen auf empfangene Nachrichten
void checkForReceivedMessages() {
  // CAN-Nachrichten empfangen
  CAN_frame_t rx_frame;
  if (xQueueReceive(CAN_cfg.rx_queue, &rx_frame, 0) == pdTRUE) {
    receivedMessages++;
    
    Serial.printf("CAN Nachricht empfangen: ID=0x%X, Länge=%d, Daten: ",
                  rx_frame.MsgID, rx_frame.FIR.B.DLC);
    
    // Alle Bytes der Nachricht ausgeben
    for (int i = 0; i < rx_frame.FIR.B.DLC; i++) {
      Serial.printf("%02X ", rx_frame.data.u8[i]);
    }
    Serial.println();
    
    // Schnelles Blinken bei empfangener Nachricht
    blinkLED(3, 30);
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
  Serial.println("ESP32 Alternative CAN Library Test");
  Serial.println("==============================================");
  Serial.println("Dieses Programm testet die CAN-Kommunikation mit der ESP32CAN-Bibliothek");
  Serial.println("anstelle der nativen TWAI-Bibliothek.");
  
  // Benutzeroptionen
  Serial.println("\nBefehle:");
  Serial.println("- 'r': CAN-Controller zurücksetzen");
  Serial.println("- 't': Testnachricht senden");
  Serial.println("- 'a': Testnachricht mit Reset senden");
  
  // CAN initialisieren
  if (!initCAN()) {
    Serial.println("Kritischer Fehler bei der CAN-Initialisierung!");
    while (1) {
      blinkLED(10, 100);  // Schnelles Blinken bei Fehler
      delay(1000);
    }
  }
  
  // Startzeit speichern
  startTime = millis();
  
  Serial.println("\nAlternative CAN Library Test gestartet. Sende Testnachrichten...");
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
      case 'r':  // CAN-Controller zurücksetzen
        resetCAN();
        break;
        
      case 't':  // Testnachricht senden
        sendCANMessage();
        break;
        
      case 'a':  // Testnachricht mit Reset senden
        sendCANMessageWithReset();
        break;
    }
    
    // Restliche Zeichen aus dem Buffer entfernen
    while (Serial.available()) {
      Serial.read();
    }
  }
  
  // Auf empfangene Nachrichten prüfen
  checkForReceivedMessages();
  
  // Periodisch Testnachrichten senden (alle 2000ms)
  if (millis() - lastSentTime > 2000) {
    lastSentTime = millis();
    
    // Abwechselnd normale Nachrichten und Nachrichten mit Reset senden
    static bool useReset = false;
    useReset = !useReset;
    
    if (useReset) {
      Serial.println("Sende Nachricht mit Reset...");
      sendCANMessageWithReset();
    } else {
      Serial.println("Sende normale Nachricht...");
      sendCANMessage();
    }
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
    Serial.println("--- ENDE STATUS ---\n");
  }
}
