/**
 * ESP32 Blink Test
 *
 * Einfacher Test, der nur die LED blinken lässt, um die grundlegende Funktionalität zu überprüfen.
 */

#include <Arduino.h>

// LED-Pin für visuelles Feedback
const int ledPin = 2;  // Eingebaute LED auf den meisten ESP32-Boards

void setup() {
  // LED initialisieren
  pinMode(ledPin, OUTPUT);

  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(2000);  // Längere Verzögerung für Stabilität

  Serial.println("\n\n\n");
  Serial.println("==============================================");
  Serial.println("ESP32 Blink Test");
  Serial.println("==============================================");
  Serial.println("Dieser Test lässt nur die LED blinken, um die grundlegende Funktionalität zu überprüfen.");
  Serial.println("Wenn die LED blinkt, funktioniert der ESP32 grundsätzlich.");
}

void loop() {
  // LED ein- und ausschalten
  digitalWrite(ledPin, HIGH);
  Serial.println("LED EIN");
  delay(500);
  digitalWrite(ledPin, LOW);
  Serial.println("LED AUS");
  delay(500);
}
