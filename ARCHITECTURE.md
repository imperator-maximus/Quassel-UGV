# Quassel UGV - Skalierbare Architektur

## 🎯 Vision
Modulare, erweiterbare Plattform für autonome Rasenmäher mit:
- Waypoint-Navigation & Pfadplanung
- Flächenberechnung & Mähbereichsverwaltung
- Echtzeit-Telemetrie & Monitoring
- Sicherheitssysteme & Notfallbehandlung
- Web-Interface & Remote-Steuerung

## Aktuelle Produktionstopologie und CAN-Rueckfall

Der Haupt-UGV nutzt keinen aktiven CAN-Bus mehr: Der SensorHub liefert seine
Pose per HTTP/WiFi, und die beiden ODrive-v3.x-Boards sind ueber zwei direkte
USB/Fibre-Verbindungen mit dem Raspberry Pi verbunden. Die drei verwendeten
Achsen werden ueber USB-Seriennummer und Achsindex eindeutig zugeordnet.

Der vorhandene Classical-CAN-2.0-Code bleibt als Rueckfall und fuer den
ehemaligen Teststand erhalten. CAN FD wird nicht verwendet; ein eingesetzter
CAN-Bus arbeitet einheitlich mit 250 kbit/s.

| Einsatz | Aktiver Transport | Profil |
|---------|-------------------|--------|
| Orange Pi Zero 2W Sensor Hub → Haupt-UGV | HTTP/WiFi | `GET /api/telemetry` |
| Haupt-UGV → ODrive Board A/B | zwei direkte USB/Fibre-Leitungen | Seriennummer + Axis 0/1 |
| Ehemaliger UGV-Testrechner (offline) | USB-CAN, SocketCAN `can0` | Classical CAN 2.0, 250 kbit/s |
| Legacy/Rueckfall | ODrive SimpleCAN | Classical CAN 2.0, 250 kbit/s |

Die SensorHub-Telemetrie ist transportabhaengig konfigurierbar: `can` nutzt
den bisherigen Multi-Frame-Stream, `shadow` vergleicht parallel HTTP/WiFi und
`wifi` verwendet `GET /api/telemetry` als aktive Posequelle. Die aktuelle
ODrive-Steuerung und -Safety laufen direkt ueber USB; `transport: can` bleibt
konfigurierbar. Bei ausbleibender aktiver
SensorHub-Telemetrie pausiert der System-Watchdog nach einer kurzen Frist nur
Fahrantrieb und Route. Erst nach der langen Ausfallfrist verriegelt er den
Gesamtstopp inklusive Maehdeck. Nach Rueckkehr der Pose wird eine zuvor aktive
autonome Route automatisch am gespeicherten Resume-Punkt fortgesetzt.

## 📁 Projektstruktur

```
raspberry_pi/
├── config/
│   ├── __init__.py
│   ├── settings.py          # Zentrale Konfiguration
│   └── constants.py         # Alle Konstanten (GPIO, PWM, Raten)
│
├── core/
│   ├── __init__.py
│   ├── motor_controller.py  # Orchestrator (vereinfacht)
│   ├── gpio_manager.py      # GPIO-Abstraktion
│   └── can_handler.py       # CAN-Bus-Kommunikation
│
├── subsystems/
│   ├── __init__.py
│   ├── pwm_controller.py    # Motor-PWM mit Ramping
│   ├── light_controller.py  # Licht-Relais
│   ├── mower_controller.py  # Mäher-Steuerung
│   └── safety_controller.py # Sicherheitsschalter
│
├── navigation/              # 🚀 Für zukünftige Erweiterung
│   ├── __init__.py
│   ├── waypoint_planner.py  # Waypoint-Navigation
│   ├── path_optimizer.py    # Pfad-Optimierung
│   └── area_calculator.py   # Flächenberechnung
│
├── web/
│   ├── __init__.py
│   ├── app.py               # Flask-App
│   ├── routes.py            # API-Routes
│   ├── websocket_handler.py # WebSocket für Joystick
│   └── templates/
│       └── index.html
│
├── utils/
│   ├── __init__.py
│   ├── logger.py            # Logging-System
│   └── exceptions.py        # Custom Exceptions
│
└── motor_controller.py      # Entry Point (vereinfacht)
```

## 🔄 Datenfluss

```
Web-Interface (Joystick/API)
    ↓
MotorController (Orchestrator)
    ├→ PWMController (Motor-Steuerung)
    ├→ LightController (Licht)
    ├→ MowerController (Mäher)
    ├→ SafetyController (Sicherheit)
    └→ CANHandler (Sensor Hub)
         ↓
    Sensor-Daten zurück
```

## 🛡️ Sicherheitskonzept

1. **Hierarchische Kontrolle**
   - Safety-Pin hat höchste Priorität
   - CAN-Disable stoppt autonome Befehle
   - Joystick nur wenn CAN disabled

2. **Timeout-Mechanismen**
   - Joystick-Timeout: 1.0s
   - Command-Timeout: 2.0s
   - Automatischer Notaus bei Timeout

3. **State-Management**
   - Klare Zustände (IDLE, MANUAL, AUTONOMOUS, EMERGENCY)
   - Zustandsübergänge validiert

## 🚀 Zukünftige Module

### Navigation (Phase 2)
- Waypoint-Planung mit GPS
- Pfad-Optimierung (Dijkstra/A*)
- Flächenberechnung & Mähbereichsverwaltung
- RTK-GPS Integration (Sensor Hub)

### Autonomie (Phase 3)
- Autonome Mährouten
- Hindernis-Vermeidung
- Rückkehr zur Basis
- Batterie-Management

### Monitoring (Phase 4)
- Telemetrie-Dashboard
- Fehlerbehandlung & Logging
- Performance-Metriken
- Remote-Diagnostik

## 💾 Konfiguration

Alle Einstellungen in `config/settings.py`:
```python
# GPIO-Pins
GPIO_PWM_LEFT = 19
GPIO_PWM_RIGHT = 18
GPIO_LIGHT = 22
GPIO_MOWER_RELAY = 23
GPIO_MOWER_PWM = 12
GPIO_SAFETY = 17

# PWM-Parameter
PWM_FREQUENCY = 50  # Hz
PWM_NEUTRAL = 1500  # μs
PWM_MIN = 1000
PWM_MAX = 2000

# Ramping-Raten
ACCELERATION_RATE = 25      # μs/s
DECELERATION_RATE = 800     # μs/s
BRAKE_RATE = 1500           # μs/s

# Mäher-Parameter
MOWER_DUTY_MIN = 16
MOWER_DUTY_MAX = 84
MOWER_PWM_FREQUENCY = 1000

# Timeouts
JOYSTICK_TIMEOUT = 1.0
COMMAND_TIMEOUT = 2.0
SAFETY_DEBOUNCE = 0.5
```

## 🔌 API-Struktur

```
GET  /api/status              # System-Status
POST /api/can/toggle          # CAN aktivieren/deaktivieren
POST /api/joystick            # Joystick-Input
POST /api/light/toggle        # Licht an/aus
POST /api/mower/toggle        # Mäher an/aus
POST /api/mower/speed         # Mäher-Geschwindigkeit
GET  /api/sensor/status       # Sensor-Daten
POST /api/sensor/restart      # Sensor Hub neustarten
```

## 📊 Implementierungs-Reihenfolge

1. ✅ Config-System
2. ✅ GPIO-Manager
3. ✅ Subsystem-Klassen
4. ✅ PWM-Controller
5. ✅ CAN-Handler
6. ✅ Web-Interface
7. ✅ Hauptklasse vereinfachen
8. 🚀 Navigation-Module (später)

---

**Status**: Architektur-Plan erstellt | **Nächster Schritt**: Config-System implementieren
