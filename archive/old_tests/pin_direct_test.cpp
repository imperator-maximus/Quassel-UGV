/**
 * ESP32 Pin Direct Test
 *
 * Dieser Test steuert die CAN-Pins direkt an, um zu überprüfen,
 * ob sie korrekt funktionieren und ob die LEDs blinken können.
 */

#include <Arduino.h>

// CAN-Pins (fest verdrahtet im ESP32)
const int canTxPin = 5;  // GPIO5
const int canRxPin = 4;  // GPIO4

// LED-Pin für visuelles Feedback
const int ledPin = 2;  // Eingebaute LED auf den meisten ESP32-Boards

void setup() {
  // Pins als Ausgänge konfigurieren
  pinMode(canTxPin, OUTPUT);
  pinMode(canRxPin, OUTPUT);
  pinMode(ledPin, OUTPUT);
  
  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(2000);  // Längere Verzögerung für Stabilität
  
  Serial.println("\n\n\n");
  Serial.println("==============================================");
  Serial.println("ESP32 Pin Direct Test");
  Serial.println("==============================================");
  Serial.println("Dieser Test steuert die CAN-Pins direkt an.");
  Serial.println("Wenn die LEDs an den Pins blinken, funktionieren die Pins grundsätzlich.");
  Serial.println("Wenn die LEDs nicht blinken, könnte es ein Hardware-Problem geben.");
  
  Serial.printf("CAN TX Pin: %d\n", canTxPin);
  Serial.printf("CAN RX Pin: %d\n", canRxPin);
}

void loop() {
  // Alle Pins auf HIGH setzen
  digitalWrite(canTxPin, HIGH);
  digitalWrite(canRxPin, HIGH);
  digitalWrite(ledPin, HIGH);
  
  Serial.println("Pins auf HIGH gesetzt");
  delay(1000);
  
  // Alle Pins auf LOW setzen
  digitalWrite(canTxPin, LOW);
  digitalWrite(canRxPin, LOW);
  digitalWrite(ledPin, LOW);
  
  Serial.println("Pins auf LOW gesetzt");
  delay(1000);
}
