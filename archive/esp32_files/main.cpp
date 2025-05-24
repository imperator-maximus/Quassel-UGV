/**
 * ESP32 PWM Test für DroneCAN zu PWM Konverter
 *
 * Dieses Skript implementiert DroneCAN 1.0 Kommunikation und PWM-Ausgabe
 * Es empfängt CAN-Nachrichten und steuert PWM-Signale auf den definierten Pins
 */

#include <Arduino.h>
#include <ESP32CAN.h>
#include <CAN_config.h>
#include "can_config.h"

// CAN-Instanz
CAN_device_t CAN_cfg;

// PWM Konfiguration
#define PWM_FREQUENCY 50         // Standard RC PWM Frequenz (50Hz)
#define PWM_RESOLUTION 16        // 16-bit Auflösung
#define PWM_MIN_US 1000          // Min. Pulsbreite in Mikrosekunden
#define PWM_MAX_US 2000          // Max. Pulsbreite in Mikrosekunden

// PWM Pin-Definitionen
const int motorPins[4] = {25, 26, 27, 33};  // Pins für die 4 Motoren

// CAN Konfiguration
unsigned long lastCANMsgTime = 0; // Zeitpunkt der letzten CAN-Nachricht

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

// Funktion zum Verarbeiten von CAN-Nachrichten
void processCANMessage(CAN_frame_t &frame) {
  // Debug-Ausgabe für alle CAN-Nachrichten
  Serial.printf("CAN Nachricht empfangen: ID=0x%X, Länge=%d, Daten: ",
                frame.MsgID, frame.FIR.B.DLC);

  // Alle Bytes der Nachricht ausgeben
  for (int i = 0; i < frame.FIR.B.DLC; i++) {
    Serial.printf("%02X ", frame.data.u8[i]);
  }
  Serial.println();

  // Zeitpunkt der letzten Nachricht aktualisieren
  lastCANMsgTime = millis();

  // Prüfen, ob es sich um eine DroneCAN Actuator Command Nachricht handelt
  // DroneCAN verwendet verschiedene Message IDs, wir müssen die richtige finden

  // Beispiel: Versuche verschiedene bekannte DroneCAN Message IDs
  // Typische IDs für Servo/ESC Befehle: 0x123, 0x1E0, 0x2F0, etc.
  if (frame.FIR.B.FF == CAN_frame_std &&
      (frame.MsgID == 0x123 || frame.MsgID == 0x1E0 || frame.MsgID == 0x2F0)) {

    // Versuche, die Daten als Motorbefehl zu interpretieren
    if (frame.FIR.B.DLC >= 3) { // Mindestens 3 Bytes (Index + Wert)
      uint8_t motorIndex = frame.data.u8[0]; // Erster Byte: Motor-Index

      if (motorIndex < 4) { // Prüfen, ob ein gültiger Motor-Index
        // Wert aus den Bytes 1-2 extrahieren (16-bit Wert zwischen 0-65535)
        uint16_t rawValue = (frame.data.u8[2] << 8) | frame.data.u8[1];

        // Auf 0.0-1.0 skalieren
        float value = constrain(rawValue / 65535.0f, 0.0f, 1.0f);

        // Motorwert aktualisieren
        motorValues[motorIndex] = value;
        updateMotorPWM(motorIndex, value);

        // Debug-Ausgabe
        Serial.printf("Motor %d Wert gesetzt: %.2f\n", motorIndex, value);
      }
    }
  }
}

// Setup-Funktion
void setup() {
  // Serielle Kommunikation initialisieren
  Serial.begin(115200);
  Serial.println("ESP32 DroneCAN PWM Konverter");

  // CAN-Konfiguration und Initialisierung
  Serial.println("CAN-Initialisierung...");

  // CAN-Konfiguration
  CAN_cfg.speed = CAN_SPEED_1000KBPS;
  CAN_cfg.tx_pin_id = CAN_TX_PIN;
  CAN_cfg.rx_pin_id = CAN_RX_PIN;
  CAN_cfg.rx_queue = xQueueCreate(10, sizeof(CAN_frame_t));

  // CAN-Modul initialisieren
  ESP32Can.CANInit();

  Serial.printf("CAN initialisiert: TX Pin=%d, RX Pin=%d\n", CAN_TX_PIN, CAN_RX_PIN);

  // PWM Kanäle konfigurieren
  for (int i = 0; i < 4; i++) {
    ledcSetup(i, PWM_FREQUENCY, PWM_RESOLUTION);
    ledcAttachPin(motorPins[i], i);

    // Initial alle Motoren auf Minimum setzen
    updateMotorPWM(i, 0.0);
  }

  Serial.println("System bereit - Warte auf CAN-Nachrichten");
}

// Hauptschleife
void loop() {
  static unsigned long lastStatusTime = 0;
  static unsigned long lastFallbackTime = 0;
  static bool fallbackMode = false;
  static float motorValue = 0.0;
  static float direction = 0.01;  // Inkrement-Wert

  // CAN-Nachrichten empfangen und verarbeiten
  CAN_frame_t rx_frame;
  if (xQueueReceive(CAN_cfg.rx_queue, &rx_frame, 0) == pdTRUE) {
    // CAN-Nachricht verarbeiten
    processCANMessage(rx_frame);
    fallbackMode = false; // Zurück zum normalen Modus, wenn CAN-Nachrichten empfangen werden
  }

  // Prüfen, ob seit 1 Sekunde keine CAN-Nachricht empfangen wurde
  if (!fallbackMode && millis() - lastCANMsgTime > 1000) {
    Serial.println("Keine CAN-Nachrichten empfangen - Wechsel zu Fallback-Modus");
    fallbackMode = true;
    lastFallbackTime = millis();
  }

  // Fallback-Modus: Wenn keine CAN-Nachrichten empfangen werden, generiere Test-Muster
  if (fallbackMode && millis() - lastFallbackTime > 50) {
    lastFallbackTime = millis();

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
  }

  // Status alle 500ms ausgeben
  if (millis() - lastStatusTime > 500) {
    lastStatusTime = millis();

    // Status ausgeben
    Serial.printf("Modus: %s, Motorwerte: %.2f, %.2f, %.2f, %.2f\n",
                  fallbackMode ? "Fallback" : "CAN",
                  motorValues[0], motorValues[1], motorValues[2], motorValues[3]);
  }
}