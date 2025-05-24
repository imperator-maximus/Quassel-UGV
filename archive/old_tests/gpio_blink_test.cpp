/**
 * ESP32 GPIO Blink Test
 *
 * Dieser Test steuert die GPIO-Pins 4 und 5 direkt an, um zu überprüfen,
 * ob die LEDs an diesen Pins blinken können.
 */

#include <Arduino.h>

// GPIO-Pins für den Test
const int gpio4 = 4;  // GPIO4
const int gpio5 = 5;  // GPIO5

// LED-Pin für visuelles Feedback
const int ledPin = 2;  // Eingebaute LED auf den meisten ESP32-Boards

void setup() {
  // Pins als Ausgänge konfigurieren
  pinMode(gpio4, OUTPUT);
  pinMode(gpio5, OUTPUT);
  pinMode(ledPin, OUTPUT);
  
  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(2000);  // Längere Verzögerung für Stabilität
  
  Serial.println("\n\n\n");
  Serial.println("==============================================");
  Serial.println("ESP32 GPIO Blink Test");
  Serial.println("==============================================");
  Serial.println("Dieser Test steuert die GPIO-Pins 4 und 5 direkt an.");
  Serial.println("Wenn die LEDs an diesen Pins blinken, funktionieren die Pins grundsätzlich.");
  Serial.println("Wenn die LEDs nicht blinken, könnte es ein Hardware-Problem geben.");
  
  Serial.printf("GPIO4 Pin: %d\n", gpio4);
  Serial.printf("GPIO5 Pin: %d\n", gpio5);
}

void loop() {
  // Alle Pins auf HIGH setzen
  digitalWrite(gpio4, HIGH);
  digitalWrite(gpio5, HIGH);
  digitalWrite(ledPin, HIGH);
  
  Serial.println("Pins auf HIGH gesetzt");
  delay(1000);
  
  // Alle Pins auf LOW setzen
  digitalWrite(gpio4, LOW);
  digitalWrite(gpio5, LOW);
  digitalWrite(ledPin, LOW);
  
  Serial.println("Pins auf LOW gesetzt");
  delay(1000);
}
