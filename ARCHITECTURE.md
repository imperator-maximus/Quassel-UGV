# Quassel UGV - Skalierbare Architektur

Der verbindliche aktuelle Hardware- und Transportstand steht in
[`CURRENT_PRODUCTION.md`](CURRENT_PRODUCTION.md).

## 🎯 Vision
Modulare, erweiterbare Plattform für autonome Rasenmäher mit:
- Waypoint-Navigation & Pfadplanung
- Flächenberechnung & Mähbereichsverwaltung
- Echtzeit-Telemetrie & Monitoring
- Sicherheitssysteme & Notfallbehandlung
- Web-Interface & Remote-Steuerung

## Verbindlicher Produktionsstand

Alles haengt direkt am Raspberry Pi: der GNSS-Empfaenger ueber eine serielle
USB-Verbindung, die beiden ODrive-v3.x-Boards ueber zwei USB/Fibre-Leitungen.
Die drei verwendeten Maehachsen werden ueber USB-Seriennummer und Achsindex
eindeutig zugeordnet.

CAN-Bus und SensorHub sind ausgebaut, ihr Code ist aus dem Repository entfernt.
Sie duerfen nicht wieder als Produktionsabhaengigkeit eingefuehrt werden.

| Einsatz | Aktiver Transport | Profil |
|---------|-------------------|--------|
| GNSS-Empfaenger UM982 → Raspberry | serielle USB-Verbindung | Port ueber `/dev/serial/by-id` |
| RTK-Korrekturen → Raspberry | NTRIP ueber Mobilfunk | Mountpoint `openrtk_mv` |
| Raspberry → ODrive Board A/B | zwei direkte USB/Fibre-Leitungen | Seriennummer + Axis 0/1 |

Die Pose entsteht damit auf dem Fahrzeugrechner selbst. Bleibt sie aus,
pausiert der System-Watchdog nach einer kurzen Frist nur Fahrantrieb und
Route. Erst nach der langen Ausfallfrist verriegelt er den Gesamtstopp
inklusive Maehdeck. Nach Rueckkehr der Pose wird eine zuvor aktive autonome
Route automatisch am gespeicherten Resume-Punkt fortgesetzt.

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
│   └── pose_cache.py        # Zwischenspeicher der GNSS-Pose
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
    └→ PoseCache ← LocalPoseSource (GNSS über USB)
         ↓
    Pose zurück
```

## 🛡️ Sicherheitskonzept

1. **Hierarchische Kontrolle**
   - Safety-Pin hat höchste Priorität
   - Eine veraltete Pose pausiert Fahrantrieb und Route
   - Manuelles Rangieren bleibt erlaubt, es braucht keine Pose

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
- RTK-GPS Integration (NTRIP am Raspberry)

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

# Mähdeck: läuft über die ODrives (odrive_mower), nicht über GPIO-PWM

# Timeouts
JOYSTICK_TIMEOUT = 1.0
COMMAND_TIMEOUT = 2.0
SAFETY_DEBOUNCE = 0.5
```

## 🔌 API-Struktur

```
GET  /api/status              # System-Status
POST /api/joystick            # Joystick-Input
POST /api/light/toggle        # Licht an/aus
POST /api/mower/toggle        # Mäher an/aus
POST /api/mower/speed         # Mäher-Geschwindigkeit
GET  /api/sensor/status       # Pose samt Alter
```

## 📊 Implementierungs-Reihenfolge

1. ✅ Config-System
2. ✅ GPIO-Manager
3. ✅ Subsystem-Klassen
4. ✅ PWM-Controller
5. ✅ Pose-Zwischenspeicher
6. ✅ Web-Interface
7. ✅ Hauptklasse vereinfachen
8. 🚀 Navigation-Module (später)

---

**Status**: Architektur-Plan erstellt | **Nächster Schritt**: Config-System implementieren
