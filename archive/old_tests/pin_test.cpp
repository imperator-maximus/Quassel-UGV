/**
 * ESP32 Pin-Test für Freenove Breakout Board
 *
 * Dieses Programm hilft, die Pins auf dem Freenove Breakout Board zu identifizieren
 * Es blinkt abwechselnd die LEDs an den CAN-Pins und den PWM-Pins
 */

#include <Arduino.h>

// Pin-Definitionen
#define CAN_TX_PIN 5  // GPIO5 - CAN TX (Pin 5 auf dem Freenove Board)
#define CAN_RX_PIN 4  // GPIO4 - CAN RX (Pin 4 auf dem Freenove Board)

// PWM Pin-Definitionen
const int motorPins[4] = {25, 26, 27, 33};  // Pins für die 4 Motoren

// Setup-Funktion
void setup() {
  Serial.begin(115200);
  Serial.println("ESP32 Pin-Test für Freenove Breakout Board");

  // Pins als Ausgänge konfigurieren
  pinMode(CAN_TX_PIN, OUTPUT);
  pinMode(CAN_RX_PIN, OUTPUT);

  for (int i = 0; i < 4; i++) {
    pinMode(motorPins[i], OUTPUT);
  }

  Serial.println("Pins konfiguriert. Test startet...");
}

// Hauptschleife
void loop() {
  // Test 1: CAN-Pins blinken
  Serial.println("Test 1: CAN-Pins blinken (GPIO4 und GPIO5)");
  for (int i = 0; i < 5; i++) {
    digitalWrite(CAN_TX_PIN, HIGH);
    digitalWrite(CAN_RX_PIN, LOW);
    delay(500);
    digitalWrite(CAN_TX_PIN, LOW);
    digitalWrite(CAN_RX_PIN, HIGH);
    delay(500);
  }

  // Alle Pins ausschalten
  digitalWrite(CAN_TX_PIN, LOW);
  digitalWrite(CAN_RX_PIN, LOW);

  // Test 2: PWM-Pins nacheinander blinken
  Serial.println("Test 2: PWM-Pins nacheinander blinken (GPIO25, 26, 27, 33)");
  for (int j = 0; j < 2; j++) {
    for (int i = 0; i < 4; i++) {
      digitalWrite(motorPins[i], HIGH);
      delay(300);
      digitalWrite(motorPins[i], LOW);
      delay(100);
    }
  }

  // Test 3: Alle Pins gleichzeitig blinken
  Serial.println("Test 3: Alle Pins gleichzeitig blinken");
  for (int i = 0; i < 3; i++) {
    // Alle Pins einschalten
    digitalWrite(CAN_TX_PIN, HIGH);
    digitalWrite(CAN_RX_PIN, HIGH);
    for (int j = 0; j < 4; j++) {
      digitalWrite(motorPins[j], HIGH);
    }
    delay(500);

    // Alle Pins ausschalten
    digitalWrite(CAN_TX_PIN, LOW);
    digitalWrite(CAN_RX_PIN, LOW);
    for (int j = 0; j < 4; j++) {
      digitalWrite(motorPins[j], LOW);
    }
    delay(500);
  }

  Serial.println("Test abgeschlossen. Pause vor Neustart...");
  delay(2000);
}
