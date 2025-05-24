/**
 * ESP32 PWM Test für DroneCAN zu PWM Konverter
 * 
 * Dieses Skript simuliert die PWM-Ausgabe ohne CAN-Eingabe
 * Es erzeugt PWM-Signale auf den definierten Pins und variiert die Werte
 */

#include <Arduino.h>

// PWM Konfiguration
#define PWM_FREQUENCY 50         // Standard RC PWM Frequenz (50Hz)
#define PWM_RESOLUTION 16        // 16-bit Auflösung
#define PWM_MIN_US 1000          // Min. Pulsbreite in Mikrosekunden
#define PWM_MAX_US 2000          // Max. Pulsbreite in Mikrosekunden

// PWM Pin-Definitionen
const int motorPins[4] = {25, 26, 27, 33};  // Pins für die 4 Motoren

// Letzte empfangene Motorwerte (0.0-1.0)
float motorValues[4] = {0.0, 0.0, 0.0, 0.0};

// PWM für einen Motor aktualisieren mit verbesserten Berechnungen
void updateMotorPWM(int motorIndex, float value) {
  value = constrain(value, 0.0, 1.0); // Wert auf 0-1 begrenzen
  
  // Lineare Umrechnung von 0-1 auf den Mikrosekundenbereich
  float pulseWidth_us = PWM_MIN_US + value * (PWM_MAX_US - PWM_MIN_US);
  
  // Umrechnung von Mikrosekunden in LEDC Duty Cycle Wert
  float period_us = 1000000.0 / PWM_FREQUENCY;
  float duty_cycle_fraction = pulseWidth_us / period_us; // Duty cycle als 0.0-1.0 Fraktion
  
  uint32_t duty = (uint32_t)(duty_cycle_fraction * ((1 << PWM_RESOLUTION) - 1)); // Skalieren auf LEDC Auflösung
  
  ledcWrite(motorIndex, duty);
  
  Serial.printf("Motor %d: Wert=%.2f, Pulsbreite=%.2f µs, Duty=%u\n", 
                motorIndex, value, pulseWidth_us, duty);
}

// Setup-Funktion
void setup() {
  Serial.begin(115200);
  Serial.println("ESP32 PWM Test");
  
  // PWM Kanäle konfigurieren
  for (int i = 0; i < 4; i++) {
    ledcSetup(i, PWM_FREQUENCY, PWM_RESOLUTION);
    ledcAttachPin(motorPins[i], i);
    
    // Initial alle Motoren auf Minimum setzen
    updateMotorPWM(i, 0.0);
  }
  
  Serial.println("System bereit - PWM-Test startet");
}

// Hauptschleife
void loop() {
  static unsigned long lastUpdateTime = 0;
  static float motorValue = 0.0;
  static float direction = 0.01;  // Inkrement-Wert
  
  // Alle 50ms aktualisieren
  if (millis() - lastUpdateTime > 50) {
    lastUpdateTime = millis();
    
    // Motorwert aktualisieren (zwischen 0.0 und 1.0 oszillieren)
    motorValue += direction;
    if (motorValue >= 1.0 || motorValue <= 0.0) {
      direction = -direction;
    }
    
    // Verschiedene Muster für die 4 Motoren
    motorValues[0] = motorValue;                    // Normal
    motorValues[1] = 1.0 - motorValue;              // Invertiert
    motorValues[2] = motorValue < 0.5 ? 0.0 : 1.0;  // Digital (0 oder 1)
    motorValues[3] = motorValue * motorValue;       // Quadratisch
    
    // PWM aktualisieren
    for (int i = 0; i < 4; i++) {
      updateMotorPWM(i, motorValues[i]);
    }
    
    // Status ausgeben
    Serial.printf("Motorwerte: %.2f, %.2f, %.2f, %.2f\n", 
                  motorValues[0], motorValues[1], motorValues[2], motorValues[3]);
  }
}
