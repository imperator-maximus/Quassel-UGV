/**
 * ESP32 Serial Test
 *
 * Einfacher Test, um zu überprüfen, ob die serielle Kommunikation funktioniert.
 */

#include <Arduino.h>

// LED-Pin für visuelles Feedback
const int ledPin = 2;  // Eingebaute LED auf den meisten ESP32-Boards

void setup() {
  // LED für visuelles Feedback initialisieren
  pinMode(ledPin, OUTPUT);

  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  delay(1000); // Kurze Verzögerung für die Stabilisierung

  Serial.println("\n\n\n");
  Serial.println("==============================================");
  Serial.println("ESP32 Serial Test - Setup abgeschlossen");
  Serial.println("==============================================");
  Serial.println("Wenn Sie diese Nachricht sehen, funktioniert die serielle Kommunikation!");

  // Hardware-Informationen ausgeben
  Serial.printf("ESP32 Chip Revision: %d\n", ESP.getChipRevision());
  Serial.printf("ESP32 SDK Version: %s\n", ESP.getSdkVersion());

  // Schnelles Blinken zum Start
  for (int i = 0; i < 5; i++) {
    digitalWrite(ledPin, HIGH);
    delay(100);
    digitalWrite(ledPin, LOW);
    delay(100);
  }
}

void loop() {
  // Einfache Zählschleife, um zu zeigen, dass der ESP32 läuft
  static int counter = 0;

  Serial.printf("Laufzeit: %d Sekunden, Counter: %d\n", millis()/1000, counter++);

  // Blinken der eingebauten LED
  digitalWrite(ledPin, HIGH);
  delay(500);
  digitalWrite(ledPin, LOW);
  delay(500);
}
