# ESP32 Pin-Layout auf dem Freenove Breakout Board

## CAN-Pins (fest verdrahtet)

```
+---------------+
|               |
|    ESP32      |
|               |
+---------------+
     |   |
     |   |
     v   v
    [4] [5]  <-- Diese Pins (GPIO4 und GPIO5) sind für CAN fest verdrahtet
     |   |
     |   |
     v   v
  CAN-RX CAN-TX  <-- Verbinde diese mit dem CAN-Transceiver
```

## Serielle Pins für Programmierung

```
+---------------+
|               |
|    ESP32      |
|               |
+---------------+
     |   |
     |   |
     v   v
   [42] [2]  <-- Diese Pins (RX=42/GPIO3, TX=2/GPIO1) werden für die serielle Programmierung verwendet
     |   |
     |   |
     v   v
  USB-RX USB-TX  <-- Verbunden mit dem USB-Seriell-Wandler auf dem Board
```

## PWM-Ausgänge

```
+---------------+
|               |
|    ESP32      |
|               |
+---------------+
  |  |  |  |
  v  v  v  v
 [25][26][27][33]  <-- Diese Pins werden für PWM-Ausgänge verwendet
  |  |  |  |
  v  v  v  v
 PWM-Ausgänge für Motoren/Servos
```

## Wichtiger Hinweis

Die Pins auf dem Freenove Board sind mit ihrer GPIO-Nummer beschriftet. Die CAN-Pins (GPIO4 und GPIO5) sind fest mit dem CAN-Controller des ESP32 verbunden und können nicht geändert werden.

Achte darauf, dass du den CAN-Transceiver korrekt anschließt:
- ESP32 Pin 5 (GPIO5) → CAN-TX am Transceiver
- ESP32 Pin 4 (GPIO4) → CAN-RX am Transceiver
