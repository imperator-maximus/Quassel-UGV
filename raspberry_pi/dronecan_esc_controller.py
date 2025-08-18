#!/usr/bin/env python3
"""
DroneCAN ESC Controller - Monitoring + PWM-Ausgabe
Verwendet neue Kalibrierungsdaten mit verbesserten Orange Cube Parametern
Neue Werte: Rückwärts ~-8000, Neutral ~0, Vorwärts ~+8000

Modi:
- Monitor: Zeigt DroneCAN ESC-Kommandos mit kalibrierten % und PWM-Werten
- PWM: Gibt PWM-Signale an GPIO-Pins aus (Hardware-PWM für Sicherheit)
- Both: Monitor + PWM gleichzeitig

Sicherheitsfeatures:
- Hardware-PWM für Freeze-Schutz
- Signal-Handler für sauberes Shutdown
- Timeout-Überwachung
"""

import time
import dronecan
import json
import argparse
import signal
import sys
import atexit
import threading
import queue
import socket
import base64

# Flask/SocketIO imports werden nur bei Bedarf geladen (siehe _init_web_interface)

class CalibratedESCController:
    def __init__(self, enable_pwm=False, pwm_pins=[18, 19], enable_monitor=True, quiet=False,
                 enable_ramping=True, acceleration_rate=25, deceleration_rate=800, brake_rate=1500,
                 enable_web=False, web_port=80, safety_pin=17, light_enabled=True, light_pin=22,
                 mower_enabled=True, mower_relay_pin=23, mower_pwm_pin=12, enable_rtk=False,
                 ntrip_host="openrtk-mv.de", ntrip_port=2101, ntrip_user="", ntrip_pass="",
                 ntrip_mountpoint="VRS_3_4G_MV"):
        # Druck-Entprellung für Not-Aus-Ausgaben
        self._last_emergency_print = 0.0
        # Kalibrierungswerte AKTUALISIERT mit neuen Orange Cube Parametern
        # Motor 0 = Rechts, Motor 1 = Links
        # Neue Werte: Rückwärts ~-8000, Neutral ~0, Vorwärts ~+8000
        self.calibration = {
            'left': {
                'neutral': -114,    # AKTUALISIERT: Motor 1 Neutral-Wert aus neuer Kalibrierung
                'min': -8191,       # Minimum bei Vollgas rückwärts
                'max': 8191,        # Maximum bei Vollgas vorwärts
                'forward_max': 8191, # Max bei reinem Vorwärts
                'reverse_min': -8191 # Min bei reinem Rückwärts
            },
            'right': {
                'neutral': 0,       # AKTUALISIERT: Motor 0 Neutral-Wert aus neuer Kalibrierung
                'min': -8191,       # Minimum bei Vollgas rückwärts
                'max': 8191,        # Maximum bei Vollgas vorwärts
                'forward_max': 8191, # Max bei reinem Vorwärts
                'reverse_min': -8191 # Min bei reinem Rückwärts
            }
        }

        # Konfiguration
        self.enable_pwm = enable_pwm
        self.enable_monitor = enable_monitor
        self.quiet = quiet
        self.pwm_pins = {'left': pwm_pins[1], 'right': pwm_pins[0]}  # Links=GPIO19, Rechts=GPIO18

        # Sicherheitsschaltleiste Konfiguration
        self.safety_pin = safety_pin
        self.safety_enabled = True  # Sicherheitsschaltleiste aktiviert
        self.last_safety_trigger = 0  # Entprellung

        # Licht-Steuerung Konfiguration
        self.light_enabled = light_enabled
        self.light_pin = light_pin
        self.light_state = False  # Licht initial aus

        # Mäher-Steuerung Konfiguration
        self.mower_enabled = mower_enabled
        self.mower_relay_pin = mower_relay_pin
        self.mower_pwm_pin = mower_pwm_pin
        self.mower_state = False  # Mäher initial aus
        self.mower_speed = 0  # Geschwindigkeit 0-100%

        # PWM-Konfiguration für Mäher (16-84% Duty Cycle für 0.8V-4.2V)
        self.mower_pwm_frequency = 1000  # 1000 Hz
        self.mower_duty_min = 16  # 16% = ca. 0.8V (Leerlauf)
        self.mower_duty_max = 84  # 84% = ca. 4.2V (Vollgas)
        self.mower_duty_off = 0   # 0% = 0V (Disarmed/Fehler)

        # Web-Interface Konfiguration
        self.enable_web = enable_web
        self.web_port = web_port
        self.can_enabled = True  # CAN Ein/Aus Flag (Thread-sicher)
        self.web_thread = None
        self.flask_app = None
        self.socketio = None

        # PWM-Objekte
        self.pwm_objects = {}
        self.last_pwm_values = {'left': 1500, 'right': 1500}

        # Ramping-Konfiguration
        self.enable_ramping = enable_ramping
        self.acceleration_rate = acceleration_rate  # μs/Sekunde für Beschleunigung (langsam)
        self.deceleration_rate = deceleration_rate  # μs/Sekunde für Verzögerung (schnell)
        self.brake_rate = brake_rate                # μs/Sekunde für Bremsung zu Neutral (sehr schnell)

        # Ramping-Zustand
        self.current_pwm_values = {'left': 1500, 'right': 1500}  # Aktuelle PWM-Werte (gerampt)
        self.target_pwm_values = {'left': 1500, 'right': 1500}   # Ziel-PWM-Werte (vom DroneCAN)
        self.last_ramping_time = time.time()

        # Ausgabe-Dämpfung
        self.last_command = (0, 0)
        self.last_output_time = 0
        self.output_interval = 0.5  # Sekunden zwischen Ausgaben

        # Sicherheit
        self.last_command_time = time.time()
        self.command_timeout = 2.0  # 2 Sekunden Timeout

        # Joystick-Steuerung (Phase 2)
        self.joystick_enabled = False
        self.joystick_x = 0.0  # -1.0 bis +1.0 (links/rechts)
        self.joystick_y = 0.0  # -1.0 bis +1.0 (rückwärts/vorwärts)
        self.joystick_last_update = 0
        self.joystick_timeout = 1.0  # Sekunden
        self.max_speed_percent = 100.0  # Geschwindigkeitsbegrenzung

        # PWM initialisieren falls aktiviert
        if self.enable_pwm:
            self._init_pwm()

        # Licht-Steuerung initialisieren falls aktiviert
        if self.light_enabled:
            self._init_light()

        # Mäher-Steuerung initialisieren falls aktiviert
        if self.mower_enabled:
            self._init_mower()

        # Sicherheitsschaltleiste initialisieren
        self._init_safety_switch()

        # Web-Interface initialisieren falls aktiviert
        if self.enable_web:
            self._init_web_interface()

        # RTK-NTRIP initialisieren falls aktiviert
        self.enable_rtk = enable_rtk
        if self.enable_rtk:
            self.ntrip_config = {
                'host': ntrip_host,
                'port': ntrip_port,
                'user': ntrip_user,
                'pass': ntrip_pass,
                'mountpoint': ntrip_mountpoint
            }
            self.ntrip_socket = None
            self.gps_position = None
            self.last_gga_time = 0
            self.gga_interval = 10  # Sekunden zwischen GGA-Nachrichten

            # RTK Rate Limiting
            self.last_rtcm_time = 0
            self.rtcm_interval = 0.02  # Max 50 Hz RTCM-Übertragung (sehr schnell)
            self.rtcm_buffer = b''     # Buffer für RTCM-Daten

            self._init_rtk()

    def _init_pwm(self):
        """Initialisiert Hardware-PWM für sichere ESC-Steuerung"""
        try:
            import pigpio
            self.pi = pigpio.pi()

            if not self.pi.connected:
                raise Exception("Kann nicht mit pigpio daemon verbinden")

            # Hardware-PWM auf beiden Pins initialisieren
            for side, pin in self.pwm_pins.items():
                # Hardware-PWM mit 50Hz (20ms Periode)
                self.pi.hardware_PWM(pin, 50, 75000)  # 75000 = 7.5% = 1500μs bei 50Hz
                if not self.quiet:
                    print(f"✅ Hardware-PWM initialisiert: {side.capitalize()} Motor → GPIO{pin}")

            # Sicherheits-Handler registrieren
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            atexit.register(self._cleanup_pwm)
            atexit.register(self._cleanup_web)

            if not self.quiet:
                print("🛡️ Sicherheits-Handler registriert (SIGINT, SIGTERM, atexit)")

        except ImportError:
            print("❌ FEHLER: pigpio library nicht installiert!")
            print("   Installieren mit: sudo apt install pigpio python3-pigpio")
            print("   Daemon starten mit: sudo systemctl start pigpiod")
            sys.exit(1)
        except Exception as e:
            print(f"❌ PWM-Initialisierung fehlgeschlagen: {e}")
            sys.exit(1)

    def _init_light(self):
        """Initialisiert Licht-Steuerung auf GPIO22"""
        if not self.light_enabled:
            if not self.quiet:
                print("⚠️ Licht-Steuerung: Explizit deaktiviert")
            return

        # Import pigpio am Anfang für korrekten Scope
        try:
            import pigpio
        except ImportError as e:
            print(f"❌ FEHLER: pigpio library nicht verfügbar - {e}")
            print("   Installieren mit: sudo apt install pigpio python3-pigpio")
            print("   Licht-Steuerung deaktiviert")
            self.light_enabled = False
            return

        try:
            if not self.quiet:
                print(f"🔧 Initialisiere Licht-Steuerung auf GPIO{self.light_pin}...")

            # Verwende das bereits initialisierte pigpio-Objekt falls PWM aktiv
            if self.enable_pwm and hasattr(self, 'pi'):
                pi = self.pi
                if not self.quiet:
                    print("   Verwende bestehendes pigpio-Objekt (PWM)")
            else:
                # Separates pigpio-Objekt für GPIO-Steuerung
                pi = pigpio.pi()
                if not pi.connected:
                    raise Exception("Kann nicht mit pigpio daemon verbinden")
                self.pi_light = pi
                if not self.quiet:
                    print("   Neues pigpio-Objekt erstellt")

            # GPIO als Output konfigurieren
            pi.set_mode(self.light_pin, pigpio.OUTPUT)
            if not self.quiet:
                print(f"   GPIO{self.light_pin} als OUTPUT konfiguriert")

            # Initial ausschalten (LOW = Relais aus)
            pi.write(self.light_pin, 0)
            self.light_state = False
            if not self.quiet:
                print(f"   GPIO{self.light_pin} auf LOW gesetzt (Relais aus)")

            if not self.quiet:
                print(f"✅ Licht-Steuerung initialisiert auf GPIO{self.light_pin}")
                print(f"   Relais-Steuerung: HIGH = Ein, LOW = Aus")
                print(f"   Initial-Status: {'Ein' if self.light_state else 'Aus'}")

        except Exception as e:
            print(f"❌ FEHLER: Licht-Initialisierung fehlgeschlagen: {e}")
            print("   Details:")
            print(f"     - light_enabled: {self.light_enabled}")
            print(f"     - light_pin: {self.light_pin}")
            print(f"     - enable_pwm: {self.enable_pwm}")
            print(f"     - hasattr(self, 'pi'): {hasattr(self, 'pi')}")
            print("   System läuft ohne Licht-Steuerung weiter")
            self.light_enabled = False

    def _init_mower(self):
        """Initialisiert Mäher-Steuerung (Relais + PWM)"""
        if not self.mower_enabled:
            if not self.quiet:
                print("⚠️ Mäher-Steuerung: Explizit deaktiviert")
            return

        # Import pigpio am Anfang für korrekten Scope
        try:
            import pigpio
        except ImportError as e:
            print(f"❌ FEHLER: pigpio library nicht verfügbar - {e}")
            print("   Installieren mit: sudo apt install pigpio python3-pigpio")
            print("   Mäher-Steuerung deaktiviert")
            self.mower_enabled = False
            return

        try:
            if not self.quiet:
                print(f"🔧 Initialisiere Mäher-Steuerung...")
                print(f"   Relais: GPIO{self.mower_relay_pin}")
                print(f"   PWM: GPIO{self.mower_pwm_pin}")

            # Verwende das bereits initialisierte pigpio-Objekt falls PWM aktiv
            if self.enable_pwm and hasattr(self, 'pi'):
                pi = self.pi
                if not self.quiet:
                    print("   Verwende bestehendes pigpio-Objekt (PWM)")
            else:
                # Separates pigpio-Objekt für GPIO-Steuerung
                pi = pigpio.pi()
                if not pi.connected:
                    raise Exception("Kann nicht mit pigpio daemon verbinden")
                self.pi_mower = pi
                if not self.quiet:
                    print("   Neues pigpio-Objekt erstellt")

            # Relais-GPIO als Output konfigurieren
            pi.set_mode(self.mower_relay_pin, pigpio.OUTPUT)
            pi.write(self.mower_relay_pin, 0)  # Initial aus
            if not self.quiet:
                print(f"   GPIO{self.mower_relay_pin} als OUTPUT konfiguriert (Relais aus)")

            # PWM-GPIO als Output konfigurieren
            pi.set_mode(self.mower_pwm_pin, pigpio.OUTPUT)

            # PWM initialisieren mit 0% (Disarmed-Zustand)
            pi.hardware_PWM(self.mower_pwm_pin, self.mower_pwm_frequency,
                           int(self.mower_duty_off * 10000))  # pigpio erwartet Mikrosekunden * 10000
            if not self.quiet:
                print(f"   GPIO{self.mower_pwm_pin} PWM initialisiert ({self.mower_pwm_frequency}Hz, {self.mower_duty_off}% Duty)")

            # Initial-Status setzen
            self.mower_state = False
            self.mower_speed = 0

            if not self.quiet:
                print(f"✅ Mäher-Steuerung initialisiert")
                print(f"   Relais: HIGH = Ein, LOW = Aus")
                print(f"   PWM-Bereich: {self.mower_duty_min}%-{self.mower_duty_max}% ({self.mower_duty_min/100*5:.1f}V-{self.mower_duty_max/100*5:.1f}V)")
                print(f"   Initial-Status: Aus, 0% Geschwindigkeit")

        except Exception as e:
            print(f"❌ FEHLER: Mäher-Initialisierung fehlgeschlagen: {e}")
            print("   Details:")
            print(f"     - mower_enabled: {self.mower_enabled}")
            print(f"     - mower_relay_pin: {self.mower_relay_pin}")
            print(f"     - mower_pwm_pin: {self.mower_pwm_pin}")
            print(f"     - enable_pwm: {self.enable_pwm}")
            print(f"     - hasattr(self, 'pi'): {hasattr(self, 'pi')}")
            print("   System läuft ohne Mäher-Steuerung weiter")
            self.mower_enabled = False

    def _init_safety_switch(self):
        """Initialisiert Sicherheitsschaltleiste auf GPIO17"""
        if not self.safety_enabled:
            return

        # Import pigpio am Anfang für korrekten Scope
        try:
            import pigpio
        except ImportError:
            print("⚠️ WARNUNG: pigpio library nicht verfügbar - Sicherheitsschaltleiste deaktiviert")
            print("   Installieren mit: sudo apt install pigpio python3-pigpio")
            self.safety_enabled = False
            return

        try:
            # Verwende das bereits initialisierte pigpio-Objekt falls PWM aktiv
            if self.enable_pwm and hasattr(self, 'pi'):
                pi = self.pi
            else:
                # Separates pigpio-Objekt für GPIO-Überwachung
                pi = pigpio.pi()
                if not pi.connected:
                    raise Exception("Kann nicht mit pigpio daemon verbinden")
                self.pi_safety = pi

            # GPIO als Input mit Pull-Up konfigurieren
            pi.set_mode(self.safety_pin, pigpio.INPUT)
            pi.set_pull_up_down(self.safety_pin, pigpio.PUD_UP)

            # Interrupt für fallende Flanke (Schaltleiste gedrückt)
            pi.callback(self.safety_pin, pigpio.FALLING_EDGE, self._safety_switch_callback)

            if not self.quiet:
                print(f"🛡️ Sicherheitsschaltleiste initialisiert auf GPIO{self.safety_pin}")
                print(f"   Betätigungswiderstand: ≤ 500 Ohm")
                print(f"   Ansprechweg: 5,2 mm bei 100 mm/s")

        except Exception as e:
            print(f"⚠️ WARNUNG: Sicherheitsschaltleiste-Initialisierung fehlgeschlagen: {e}")
            print("   System läuft ohne Hardware-Sicherheitsschaltleiste weiter")
            self.safety_enabled = False

    def _safety_switch_callback(self, gpio, level, tick):
        """Callback für Sicherheitsschaltleiste (GPIO-Interrupt)"""
        current_time = time.time()

        # Entprellung: Mindestens 100ms zwischen Auslösungen
        if current_time - self.last_safety_trigger < 0.1:
            return

        self.last_safety_trigger = current_time

        # Nur bei fallender Flanke (Schaltleiste gedrückt) und wenn CAN noch aktiv
        if level == 0 and self.can_enabled:
            if not self.quiet:
                print(f"🚨 SICHERHEITSSCHALTLEISTE AUSGELÖST! GPIO{gpio} → Notaus aktiviert")

            # Bestehenden Notaus-Modus aktivieren
            self.can_enabled = False
            self._emergency_stop()

            # Web-Interface über Statusänderung informieren
            if self.enable_web and self.socketio:
                try:
                    self.socketio.emit('status_update', {
                        'can_enabled': self.can_enabled,
                        'safety_triggered': True,
                        'timestamp': current_time
                    })
                except Exception as e:
                    if not self.quiet:
                        print(f"⚠️ Web-Interface Benachrichtigung fehlgeschlagen: {e}")

        elif level == 0 and not self.can_enabled:
            # Schaltleiste gedrückt, aber bereits im Notaus-Modus
            if not self.quiet:
                print(f"🛡️ Sicherheitsschaltleiste gedrückt - bereits im Notaus-Modus")

    def _init_web_interface(self):
        """Initialisiert Web-Interface für Remote-Steuerung"""
        try:
            if not self.quiet:
                print("🔧 Initialisiere Web-Interface...")

            # Flask/SocketIO imports nur bei Bedarf laden mit besserer Fehlerbehandlung
            if not self.quiet:
                print("   Teste Flask Import...")

            # Schritt 1: Flask importieren
            try:
                from flask import Flask, render_template, jsonify, request
                if not self.quiet:
                    print("   ✅ Flask Import erfolgreich")
            except ImportError as e:
                raise ImportError(f"Flask nicht verfügbar: {e}")
            except Exception as e:
                raise Exception(f"Flask Import Segfault: {e}")

            # Schritt 2: SocketIO ÜBERSPRUNGEN (bekanntes Segfault-Problem)
            if not self.quiet:
                print("   ⚠️ SocketIO übersprungen (Segfault-Vermeidung)")
                print("   → Verwende Flask-only Modus (ohne WebSocket)")

            # Dummy-Funktionen für SocketIO-Kompatibilität
            def dummy_emit(*args, **kwargs):
                pass

            self.emit = dummy_emit
            self.socketio = None

            # Flask-Module als Klassenattribute speichern für andere Methoden
            self.render_template = render_template
            self.jsonify = jsonify
            self.request = request
            # self.emit bereits oben als dummy_emit gesetzt

            if not self.quiet:
                print("   Erstelle Flask App...")
            # Flask App erstellen
            self.flask_app = Flask(__name__, template_folder='templates', static_folder='static')
            self.flask_app.config['SECRET_KEY'] = 'ugv_dronecan_secret_2024'

            if not self.quiet:
                print("   SocketIO übersprungen (Flask-only Modus)")
            # SocketIO deaktiviert wegen Segfault-Problem
            # self.socketio bereits oben auf None gesetzt

            if not self.quiet:
                print("   Definiere Web-Routen...")
            # Web-Routen definieren
            self._setup_web_routes()

            if not self.quiet:
                print("   Starte Web-Server Thread...")
            # Web-Server in separatem Thread starten (mit Verzögerung für Stabilität)
            self.web_thread = threading.Thread(target=self._run_web_server_delayed, daemon=True)
            self.web_thread.start()

            if not self.quiet:
                print(f"🌐 Web-Interface gestartet auf Port {self.web_port}")
                print(f"   URL: http://raspberrycan:{self.web_port}")
                print(f"   👑 Quassel UGV Controller bereit!")

        except ImportError as e:
            print(f"❌ FEHLER: Flask/SocketIO Installation Problem!")
            print(f"   Details: {e}")
            print("   Lösungen:")
            print("   1. sudo pip3 install flask flask-socketio")
            print("   2. sudo apt install python3-flask python3-flask-socketio")
            print("   3. Ohne Web-Interface starten (--web Flag entfernen)")
            print("\n⚠️  WARNUNG: Fahre ohne Web-Interface fort...")
            self.enable_web = False
            return  # Nicht beenden, sondern ohne Web-Interface weitermachen
        except Exception as e:
            print(f"❌ Web-Interface-Initialisierung fehlgeschlagen: {e}")
            print("   Mögliche Ursachen:")
            print("   - Flask/SocketIO Dependency-Konflikte")
            print("   - Port 80 bereits belegt")
            print("   - Template/Static Ordner fehlen")
            import traceback
            traceback.print_exc()
            print("\n⚠️  WARNUNG: Fahre ohne Web-Interface fort...")
            self.enable_web = False
            return  # Nicht beenden, sondern ohne Web-Interface weitermachen

    def _init_rtk(self):
        """Initialisiert RTK-NTRIP-Client"""
        try:
            if not self.quiet:
                print(f"🛰️ RTK-NTRIP initialisiert:")
                print(f"   Server: {self.ntrip_config['host']}:{self.ntrip_config['port']}")
                print(f"   Mountpoint: {self.ntrip_config['mountpoint']}")

            # RTK-Thread starten
            self.rtk_thread = threading.Thread(target=self._rtk_worker, daemon=True)
            self.rtk_thread.start()

        except Exception as e:
            print(f"❌ RTK-Initialisierung Fehler: {e}")
            self.enable_rtk = False

    def _setup_web_routes(self):
        """Definiert Web-Routen für das Interface"""

        @self.flask_app.route('/')
        def index():
            return self.render_template('index.html')

        @self.flask_app.route('/api/status')
        def api_status():
            return self.jsonify({
                'can_enabled': self.can_enabled,
                'pwm_enabled': self.enable_pwm,
                'monitor_enabled': self.enable_monitor,
                'safety_enabled': self.safety_enabled,
                'safety_pin': self.safety_pin,
                'light_enabled': self.light_enabled,
                'light_state': getattr(self, 'light_state', False),
                'light_pin': self.light_pin,
                'mower_enabled': self.mower_enabled,
                'mower_state': getattr(self, 'mower_state', False),
                'mower_speed': getattr(self, 'mower_speed', 0),
                'mower_relay_pin': self.mower_relay_pin,
                'mower_pwm_pin': self.mower_pwm_pin,
                'last_command_time': getattr(self, 'last_command_time', 0),
                'current_pwm': getattr(self, 'last_pwm_values', {'left': 1500, 'right': 1500}),
                'joystick_enabled': getattr(self, 'joystick_enabled', False),
                'joystick_x': getattr(self, 'joystick_x', 0.0),
                'joystick_y': getattr(self, 'joystick_y', 0.0),
                'max_speed_percent': getattr(self, 'max_speed_percent', 100.0)
            })

        @self.flask_app.route('/api/can/toggle', methods=['POST'])
        def api_can_toggle():
            self.can_enabled = not self.can_enabled
            if not self.can_enabled:
                # Bei CAN-Deaktivierung sofort auf Neutral setzen
                self._emergency_stop()
            return self.jsonify({'can_enabled': self.can_enabled})

        @self.flask_app.route('/api/light/toggle', methods=['POST'])
        def api_light_toggle():
            if not self.quiet:
                print(f"🌐 API: Licht-Toggle angefordert (enabled={self.light_enabled})")

            if not self.light_enabled:
                if not self.quiet:
                    print("⚠️ API: Licht-Steuerung ist deaktiviert")
                return self.jsonify({
                    'success': False,
                    'error': 'Light control disabled',
                    'light_enabled': False,
                    'light_state': False
                })

            success = self.toggle_light()
            result = {
                'success': success,
                'light_enabled': self.light_enabled,
                'light_state': getattr(self, 'light_state', False)
            }

            if not self.quiet:
                print(f"🌐 API: Licht-Toggle Ergebnis: {result}")

            return self.jsonify(result)

        @self.flask_app.route('/api/mower/toggle', methods=['POST'])
        def api_mower_toggle():
            if not self.quiet:
                print(f"🌐 API: Mäher-Toggle angefordert (enabled={self.mower_enabled})")

            if not self.mower_enabled:
                if not self.quiet:
                    print("⚠️ API: Mäher-Steuerung ist deaktiviert")
                return self.jsonify({
                    'success': False,
                    'error': 'Mower control disabled',
                    'mower_enabled': False,
                    'mower_state': False,
                    'mower_speed': 0
                })

            success = self.toggle_mower()
            result = {
                'success': success,
                'mower_enabled': self.mower_enabled,
                'mower_state': getattr(self, 'mower_state', False),
                'mower_speed': getattr(self, 'mower_speed', 0)
            }

            if not self.quiet:
                print(f"🌐 API: Mäher-Toggle Ergebnis: {result}")

            return self.jsonify(result)

        @self.flask_app.route('/api/mower/speed', methods=['POST'])
        def api_mower_speed():
            try:
                data = self.request.get_json()
                speed = data.get('speed', 0)

                if not self.quiet:
                    print(f"🌐 API: Mäher-Geschwindigkeit angefordert: {speed}%")

                if not self.mower_enabled:
                    return self.jsonify({
                        'success': False,
                        'error': 'Mower control disabled',
                        'mower_speed': 0
                    })

                if not self.mower_state:
                    return self.jsonify({
                        'success': False,
                        'error': 'Mower is off',
                        'mower_speed': 0
                    })

                success = self.set_mower_speed(speed)
                result = {
                    'success': success,
                    'mower_speed': getattr(self, 'mower_speed', 0),
                    'mower_state': getattr(self, 'mower_state', False)
                }

                if not self.quiet:
                    print(f"🌐 API: Mäher-Geschwindigkeit Ergebnis: {result}")

                return self.jsonify(result)

            except Exception as e:
                print(f"❌ API: Mäher-Geschwindigkeit Fehler: {e}")
                return self.jsonify({
                    'success': False,
                    'error': str(e),
                    'mower_speed': 0
                })

        # SocketIO Event-Handler DEAKTIVIERT (Flask-only Modus)
        # @self.socketio.on('connect')
        # def handle_connect():
        #     if not self.quiet:
        #         print("🌐 Web-Client verbunden")
        #     self.emit('status_update', {
        #         'can_enabled': self.can_enabled,
        #         'connected': True,
        #         'max_speed_percent': self.max_speed_percent
        #     })

        # @self.socketio.on('disconnect')
        # def handle_disconnect():
        #     if not self.quiet:
        #         print("🌐 Web-Client getrennt")

        # Joystick Event-Handler DEAKTIVIERT (Flask-only Modus)
        # @self.socketio.on('joystick_update')
        def handle_joystick_update(data):
            """Verarbeitet Joystick-Input vom Web-Interface"""
            if self.can_enabled:
                if not self.quiet:
                    print("🚫 Joystick ignoriert - CAN ist aktiviert (Autonomie-Modus)")
                return  # Joystick nur aktiv wenn CAN DEAKTIVIERT (Not-Aus-Modus)

            try:
                # Joystick-Werte extrahieren
                x = float(data.get('x', 0.0))  # -1.0 bis +1.0
                y = float(data.get('y', 0.0))  # -1.0 bis +1.0

                # Begrenze Werte
                x = max(-1.0, min(1.0, x))
                y = max(-1.0, min(1.0, y))

                # Debug-Ausgabe für jede Eingabe
                if not self.quiet:
                    print(f"🕹️ Joystick-Input: X={x:.3f} Y={y:.3f}")

                # Joystick-Status aktualisieren
                self.joystick_x = x
                self.joystick_y = y
                self.joystick_last_update = time.time()
                self.joystick_enabled = True

                # Joystick zu Motor-Kommandos konvertieren
                self._process_joystick_input(x, y)

            except Exception as e:
                if not self.quiet:
                    print(f"❌ Joystick-Fehler: {e}")
                    import traceback
                    traceback.print_exc()

        # @self.socketio.on('joystick_release')
        def handle_joystick_release():
            """Behandelt Joystick-Release (zurück zu Neutral)"""
            self.joystick_x = 0.0
            self.joystick_y = 0.0
            self.joystick_last_update = time.time()

            # Motoren DIREKT auf Neutral setzen (nur wenn CAN deaktiviert - Not-Aus-Modus)
            if not self.can_enabled and self.enable_pwm:
                self._set_motor_pwm_direct('left', 1500)
                self._set_motor_pwm_direct('right', 1500)
                if not self.quiet:
                    print("🕹️ Joystick-Release: Motoren auf Neutral (DIREKT)")

        # @self.socketio.on('max_speed_update')
        def handle_max_speed_update(data):
            """Max Speed Slider Update vom Web-Interface"""
            try:
                max_speed = float(data.get('max_speed', 100.0))
                max_speed = max(10.0, min(100.0, max_speed))  # Begrenzen auf 10-100%

                self.max_speed_percent = max_speed

                if not self.quiet:
                    print(f"🎚️ Max Speed aktualisiert: {max_speed}%")

            except Exception as e:
                print(f"❌ Max Speed Update Fehler: {e}")

    def _run_web_server_delayed(self):
        """Läuft Web-Server in separatem Thread mit Verzögerung für Stabilität"""
        try:
            # Kurze Verzögerung um Initialisierung abzuschließen
            import time
            time.sleep(2)

            if not self.quiet:
                print("🌐 Starte Web-Server...")

            # Flask-only Modus (ohne SocketIO)
            self.flask_app.run(host='0.0.0.0',
                              port=self.web_port,
                              debug=False,
                              use_reloader=False)
        except Exception as e:
            if not self.quiet:
                print(f"❌ Web-Server Fehler: {e}")
                import traceback
                traceback.print_exc()

    def _run_web_server(self):
        """Läuft Web-Server in separatem Thread (Legacy-Methode)"""
        try:
            self.socketio.run(self.flask_app,
                            host='0.0.0.0',
                            port=self.web_port,
                            debug=False,
                            use_reloader=False,
                            log_output=False)
        except Exception as e:
            if not self.quiet:
                print(f"❌ Web-Server Fehler: {e}")

    def _signal_handler(self, signum, frame):
        """Signal-Handler für sauberes Shutdown"""
        print(f"\n🛑 Signal {signum} empfangen - Sicherheits-Shutdown...")
        self._emergency_stop()
        self._cleanup_web()
        # Forciertes Exit für Multi-Threading
        import os
        os._exit(0)

    def _emergency_stop(self):
        """Notfall-Stop: Alle Motoren auf Neutral + Mäher aus"""
        # Ausgabe höchstens alle 0.5s, um doppelte Logs zu vermeiden
        now = time.time()
        should_print = (now - getattr(self, '_last_emergency_print', 0)) > 0.5
        if self.enable_pwm and hasattr(self, 'pi'):
            for side, pin in self.pwm_pins.items():
                self.pi.hardware_PWM(pin, 50, 75000)  # 1500μs neutral
            if should_print:
                print("🚨 EMERGENCY STOP: Alle Motoren auf Neutral (1500μs)")
                self._last_emergency_print = now

        # Mäher bei Not-Aus ebenfalls ausschalten
        self.emergency_stop_mower()

    def toggle_light(self):
        """Schaltet das Licht um (an/aus)"""
        if not self.light_enabled:
            return False

        try:
            # Bestimme das pigpio-Objekt
            if self.enable_pwm and hasattr(self, 'pi'):
                pi = self.pi
            elif hasattr(self, 'pi_light'):
                pi = self.pi_light
            else:
                print("❌ Licht-Toggle fehlgeschlagen: Kein pigpio-Objekt verfügbar")
                return False

            # Status umschalten
            self.light_state = not self.light_state

            # GPIO setzen (HIGH = Relais ein, LOW = Relais aus)
            pi.write(self.light_pin, 1 if self.light_state else 0)

            if not self.quiet:
                status_text = "EIN" if self.light_state else "AUS"
                print(f"💡 Licht {status_text} (GPIO{self.light_pin} = {'HIGH' if self.light_state else 'LOW'})")

            return True

        except Exception as e:
            print(f"❌ Licht-Toggle fehlgeschlagen: {e}")
            return False

    def set_light(self, state):
        """Setzt das Licht auf einen bestimmten Zustand"""
        if not self.light_enabled:
            return False

        try:
            # Bestimme das pigpio-Objekt
            if self.enable_pwm and hasattr(self, 'pi'):
                pi = self.pi
            elif hasattr(self, 'pi_light'):
                pi = self.pi_light
            else:
                print("❌ Licht-Steuerung fehlgeschlagen: Kein pigpio-Objekt verfügbar")
                return False

            # Status setzen
            self.light_state = bool(state)

            # GPIO setzen (HIGH = Relais ein, LOW = Relais aus)
            pi.write(self.light_pin, 1 if self.light_state else 0)

            if not self.quiet:
                status_text = "EIN" if self.light_state else "AUS"
                print(f"💡 Licht {status_text} (GPIO{self.light_pin} = {'HIGH' if self.light_state else 'LOW'})")

            return True

        except Exception as e:
            print(f"❌ Licht-Steuerung fehlgeschlagen: {e}")
            return False

    def toggle_mower(self):
        """Schaltet den Mäher um (an/aus)"""
        if not self.mower_enabled:
            return False

        try:
            # Bestimme das pigpio-Objekt
            if self.enable_pwm and hasattr(self, 'pi'):
                pi = self.pi
            elif hasattr(self, 'pi_mower'):
                pi = self.pi_mower
            else:
                print("❌ Mäher-Toggle fehlgeschlagen: Kein pigpio-Objekt verfügbar")
                return False

            # Status umschalten
            self.mower_state = not self.mower_state

            if self.mower_state:
                # Mäher einschalten: Relais an + PWM auf Leerlauf
                pi.write(self.mower_relay_pin, 1)  # Relais ein
                # PWM auf Leerlauf (16% = 0.8V)
                duty_cycle_us = int(self.mower_duty_min * 10000)
                pi.hardware_PWM(self.mower_pwm_pin, self.mower_pwm_frequency, duty_cycle_us)
                self.mower_speed = 0  # Geschwindigkeit auf 0 setzen
            else:
                # Mäher ausschalten: PWM auf 0% + Relais aus
                pi.hardware_PWM(self.mower_pwm_pin, self.mower_pwm_frequency,
                               int(self.mower_duty_off * 10000))  # 0% = 0V
                pi.write(self.mower_relay_pin, 0)  # Relais aus
                self.mower_speed = 0

            if not self.quiet:
                status_text = "EIN" if self.mower_state else "AUS"
                relay_text = "HIGH" if self.mower_state else "LOW"
                pwm_duty = self.mower_duty_min if self.mower_state else self.mower_duty_off
                print(f"🌾 Mäher {status_text} (Relais GPIO{self.mower_relay_pin} = {relay_text}, PWM = {pwm_duty}%)")

            return True

        except Exception as e:
            print(f"❌ Mäher-Toggle fehlgeschlagen: {e}")
            return False

    def set_mower_speed(self, speed_percent):
        """Setzt die Mäher-Geschwindigkeit (0-100%)"""
        if not self.mower_enabled or not self.mower_state:
            return False

        try:
            # Eingabe validieren
            speed_percent = max(0, min(100, speed_percent))

            # Bestimme das pigpio-Objekt
            if self.enable_pwm and hasattr(self, 'pi'):
                pi = self.pi
            elif hasattr(self, 'pi_mower'):
                pi = self.pi_mower
            else:
                print("❌ Mäher-Geschwindigkeit fehlgeschlagen: Kein pigpio-Objekt verfügbar")
                return False

            # Konvertiere 0-100% zu 16-84% Duty Cycle (0.8V-4.2V)
            duty_range = self.mower_duty_max - self.mower_duty_min
            target_duty = self.mower_duty_min + ((speed_percent / 100.0) * duty_range)

            # PWM setzen
            duty_cycle_us = int(target_duty * 10000)  # pigpio erwartet Mikrosekunden * 10000
            pi.hardware_PWM(self.mower_pwm_pin, self.mower_pwm_frequency, duty_cycle_us)

            # Status speichern
            self.mower_speed = speed_percent

            if not self.quiet:
                voltage = (target_duty / 100.0) * 5.0  # Berechne Spannung
                print(f"🌾 Mäher-Geschwindigkeit: {speed_percent}% (PWM {target_duty:.1f}%, {voltage:.1f}V)")

            return True

        except Exception as e:
            print(f"❌ Mäher-Geschwindigkeit fehlgeschlagen: {e}")
            return False

    def emergency_stop_mower(self):
        """Not-Aus für Mäher: Sofort ausschalten"""
        if not self.mower_enabled:
            return

        try:
            # Bestimme das pigpio-Objekt
            if self.enable_pwm and hasattr(self, 'pi'):
                pi = self.pi
            elif hasattr(self, 'pi_mower'):
                pi = self.pi_mower
            else:
                return

            # Sofort ausschalten: PWM auf 0% + Relais aus
            pi.hardware_PWM(self.mower_pwm_pin, self.mower_pwm_frequency,
                           int(self.mower_duty_off * 10000))  # 0% = 0V
            pi.write(self.mower_relay_pin, 0)  # Relais aus

            # Status zurücksetzen
            self.mower_state = False
            self.mower_speed = 0

            if not self.quiet:
                print("🚨 MÄHER NOT-AUS: Mäher sofort ausgeschaltet")

        except Exception as e:
            print(f"❌ Mäher Not-Aus fehlgeschlagen: {e}")

    def _cleanup_pwm(self):
        """PWM-Cleanup beim Beenden"""
        if self.enable_pwm and hasattr(self, 'pi'):
            self._emergency_stop()
            self.pi.stop()
            if not self.quiet:
                print("🧹 PWM-Cleanup abgeschlossen")

        # Separates pigpio-Objekt für Sicherheitsschaltleiste cleanup
        if hasattr(self, 'pi_safety'):
            self.pi_safety.stop()
            if not self.quiet:
                print("🧹 Sicherheitsschaltleiste-Cleanup abgeschlossen")

        # Separates pigpio-Objekt für Licht-Steuerung cleanup
        if hasattr(self, 'pi_light'):
            # Licht ausschalten beim Beenden
            if self.light_enabled:
                self.pi_light.write(self.light_pin, 0)
                if not self.quiet:
                    print("💡 Licht ausgeschaltet beim Beenden")
            self.pi_light.stop()
            if not self.quiet:
                print("🧹 Licht-Steuerung-Cleanup abgeschlossen")

        # Separates pigpio-Objekt für Mäher-Steuerung cleanup
        if hasattr(self, 'pi_mower'):
            # Mäher sicher ausschalten beim Beenden
            if self.mower_enabled:
                self.pi_mower.hardware_PWM(self.mower_pwm_pin, self.mower_pwm_frequency,
                                          int(self.mower_duty_off * 10000))  # 0% PWM
                self.pi_mower.write(self.mower_relay_pin, 0)  # Relais aus
                if not self.quiet:
                    print("🌾 Mäher ausgeschaltet beim Beenden")
            self.pi_mower.stop()
            if not self.quiet:
                print("🧹 Mäher-Steuerung-Cleanup abgeschlossen")

    def _cleanup_web(self):
        """Web-Interface-Cleanup beim Beenden"""
        if self.enable_web and self.web_thread and self.web_thread.is_alive():
            if not self.quiet:
                print("🌐 Web-Interface wird beendet...")
            # Web-Thread ist daemon, wird automatisch beendet

    def _apply_ramping(self, side, target_pwm):
        """Wendet Ramping-Logik auf PWM-Werte an"""
        if not self.enable_ramping:
            return target_pwm

        current_time = time.time()
        dt = current_time - self.last_ramping_time

        # Minimale Zeitdifferenz für Stabilität
        if dt < 0.01:  # 10ms
            return self.current_pwm_values[side]

        current_pwm = self.current_pwm_values[side]
        pwm_diff = target_pwm - current_pwm

        if abs(pwm_diff) < 1:  # Bereits am Ziel
            return target_pwm

        # Bestimme Ramping-Rate basierend auf Situation
        neutral_threshold = 50  # μs um Neutral (1500μs)

        # Prüfe ob wir zu Neutral bremsen (Stopp)
        if (abs(target_pwm - 1500) < neutral_threshold and
            abs(current_pwm - 1500) > neutral_threshold):
            # Bremsung zu Neutral - sehr schnell
            rate = self.brake_rate
            direction = "BRAKE"
        elif abs(target_pwm) < abs(current_pwm):
            # Verzögerung - schnell
            rate = self.deceleration_rate
            direction = "DECEL"
        else:
            # Beschleunigung - langsam
            rate = self.acceleration_rate
            direction = "ACCEL"

        # Berechne maximale Änderung für diesen Zeitschritt
        max_change = rate * dt

        # Begrenze die Änderung
        if abs(pwm_diff) <= max_change:
            new_pwm = target_pwm  # Ziel erreicht
        else:
            new_pwm = current_pwm + (max_change if pwm_diff > 0 else -max_change)

        # Debug-Ausgabe (reduziert)
        if (not self.quiet and abs(pwm_diff) > 10 and
            time.time() - getattr(self, '_last_ramp_debug', 0) > 2.0):
            print(f"🏃 Ramping {side}: {current_pwm:.0f}→{target_pwm:.0f}μs "
                  f"({direction}, {rate}μs/s, Δ{pwm_diff:.0f})")
            self._last_ramp_debug = time.time()

        return new_pwm

    def _set_motor_pwm(self, side, pwm_us):
        """Setzt PWM-Wert für einen Motor (mit Sicherheitsprüfung und Ramping)"""
        if not self.enable_pwm or not hasattr(self, 'pi'):
            return

        # Sicherheitsbegrenzung
        pwm_us = max(1000, min(2000, pwm_us))

        # Ziel-PWM setzen für Ramping
        self.target_pwm_values[side] = pwm_us

        # Ramping anwenden
        ramped_pwm = self._apply_ramping(side, pwm_us)
        self.current_pwm_values[side] = ramped_pwm

        # Konvertiere μs zu pigpio duty cycle (0-1000000)
        # KORRIGIERT: Verwende die funktionierenden Test-Werte als Basis
        # 1500μs → 75000 duty (funktionierte), 2000μs → 100000 duty (funktionierte)
        duty_cycle = int(ramped_pwm * 50)

        pin = self.pwm_pins[side]
        self.pi.hardware_PWM(pin, 50, duty_cycle)
        self.last_pwm_values[side] = ramped_pwm

        # Debug-Ausgabe (reduziert)
        if not self.quiet and time.time() - getattr(self, '_last_pwm_debug', 0) > 5.0:
            print(f"🔧 PWM Debug: {side.capitalize()} GPIO{pin} = {ramped_pwm:.0f}μs")
            self._last_pwm_debug = time.time()

    def _set_motor_pwm_direct(self, side, pwm_us):
        """Setzt PWM-Wert DIREKT ohne Ramping (für Joystick-Input)"""
        if not self.enable_pwm or not hasattr(self, 'pi'):
            return

        # Sicherheitsbegrenzung
        pwm_us = max(1000, min(2000, pwm_us))

        # Konvertiere μs zu pigpio duty cycle (0-1000000)
        # KORRIGIERT: Verwende die funktionierenden Test-Werte als Basis
        # 1500μs → 75000 duty (funktionierte), 2000μs → 100000 duty (funktionierte)
        duty_cycle = int(pwm_us * 50)

        pin = self.pwm_pins[side]
        self.pi.hardware_PWM(pin, 50, duty_cycle)

        # Aktualisiere auch die internen Werte für Konsistenz
        self.current_pwm_values[side] = pwm_us
        self.target_pwm_values[side] = pwm_us
        self.last_pwm_values[side] = pwm_us

        # Debug-Ausgabe für Joystick
        if not self.quiet:
            print(f"⚡ DIREKT-PWM: {side.capitalize()} GPIO{pin} = {pwm_us}μs (ohne Ramping)")

    def _update_ramping(self):
        """Aktualisiert Ramping-Zustand (muss regelmäßig aufgerufen werden)"""
        if not self.enable_ramping or not self.enable_pwm:
            return

        current_time = time.time()

        # Prüfe ob Ramping noch aktiv ist
        for side in ['left', 'right']:
            if abs(self.current_pwm_values[side] - self.target_pwm_values[side]) > 1:
                # Ramping noch aktiv - PWM aktualisieren
                ramped_pwm = self._apply_ramping(side, self.target_pwm_values[side])
                self.current_pwm_values[side] = ramped_pwm

                # PWM Hardware aktualisieren
                if hasattr(self, 'pi'):
                    duty_cycle = int(ramped_pwm * 50)
                    pin = self.pwm_pins[side]
                    self.pi.hardware_PWM(pin, 50, duty_cycle)
                    self.last_pwm_values[side] = ramped_pwm

        self.last_ramping_time = current_time

    def _check_command_timeout(self):
        """Prüft Kommando-Timeout und setzt ggf. auf Neutral"""
        current_time = time.time()

        # Prüfe Joystick-Timeout
        if (self.joystick_enabled and
            current_time - self.joystick_last_update > self.joystick_timeout):
            self.joystick_enabled = False
            if not self.quiet:
                print("⚠️ Joystick-Timeout - Joystick deaktiviert")

        # Prüfe DroneCAN-Kommando-Timeout (nur wenn Joystick nicht aktiv)
        if (self.enable_pwm and not self.joystick_enabled and
            current_time - self.last_command_time > self.command_timeout):
            # Timeout erreicht - auf Neutral setzen (DIREKT ohne Ramping für sofortige Reaktion)
            self._set_motor_pwm_direct('left', 1500)
            self._set_motor_pwm_direct('right', 1500)
            if not self.quiet:
                print("⚠️ Kommando-Timeout - Motoren auf Neutral gesetzt (DIREKT)")
            self.last_command_time = current_time  # Reset um Spam zu vermeiden

    def _process_joystick_input(self, x, y):
        """Konvertiert Joystick-Input zu Motor-PWM-Werten (Skid Steering)"""
        if not self.enable_pwm or self.can_enabled:
            if not self.quiet:
                print(f"🚫 PWM ignoriert - PWM={self.enable_pwm}, CAN={self.can_enabled}")
            return  # Joystick nur aktiv wenn PWM enabled UND CAN deaktiviert

        # Geschwindigkeitsbegrenzung anwenden
        speed_factor = self.max_speed_percent / 100.0

        # VERBESSERT: Verstärktes Kurvenverhalten
        x_turn_factor = 1.3  # Verstärkt Drehmoment um 30%
        x_scaled = x * speed_factor * x_turn_factor
        y_scaled = y * speed_factor

        # Skid Steering Logic: X/Y zu Links/Rechts Motor
        # Y = Vorwärts/Rückwärts, X = Links/Rechts
        left_power = y_scaled + x_scaled   # Links = Vorwärts + Rechtsdrehung
        right_power = y_scaled - x_scaled  # Rechts = Vorwärts - Rechtsdrehung

        # Normalisierung falls Werte > 1.0
        max_power = max(abs(left_power), abs(right_power))
        if max_power > 1.0:
            left_power /= max_power
            right_power /= max_power

        # Konvertiere zu PWM-Werten (1000-2000μs)
        left_pwm = int(1500 + left_power * 500)   # -1.0→1000μs, 0→1500μs, +1.0→2000μs
        right_pwm = int(1500 + right_power * 500)

        # Sicherheitsbegrenzung
        left_pwm = max(1000, min(2000, left_pwm))
        right_pwm = max(1000, min(2000, right_pwm))

        # PWM setzen - DIREKT ohne Ramping für Joystick
        self._set_motor_pwm_direct('left', left_pwm)
        self._set_motor_pwm_direct('right', right_pwm)

        # Debug-Ausgabe (nur bei größeren Änderungen)
        if not self.quiet and hasattr(self, '_last_joystick_debug'):
            if abs(x - getattr(self, '_last_x', 0)) > 0.1 or abs(y - getattr(self, '_last_y', 0)) > 0.1:
                print(f"🕹️ Joystick: X={x:.2f}→{x_scaled:.2f} Y={y:.2f}→{y_scaled:.2f} | L={left_pwm}μs R={right_pwm}μs")
                self._last_x, self._last_y = x, y

        # WebSocket-Status an Client senden
        if hasattr(self, 'socketio') and self.socketio:
            self.socketio.emit('pwm_update', {
                'left': left_pwm,
                'right': right_pwm,
                'joystick_x': x,
                'joystick_y': y
            })
        
    def raw_to_percent(self, raw_value, motor_side):
        """Konvertiert Raw-Werte zu kalibrierten Prozent-Werten"""
        cal = self.calibration[motor_side]
        neutral = cal['neutral']

        if raw_value == neutral:
            return 0.0
        elif raw_value > neutral:
            # Vorwärts: neutral bis max → 0% bis +100%
            max_range = cal['forward_max'] - neutral
            if max_range == 0:
                return 0.0
            percent = ((raw_value - neutral) / max_range) * 100.0
        else:
            # Rückwärts: min bis neutral → -100% bis 0%
            min_range = neutral - cal['reverse_min']
            if min_range == 0:
                return 0.0
            percent = ((raw_value - neutral) / min_range) * 100.0

        return round(percent, 1)

    def raw_to_pwm(self, raw_value, motor_side):
        """Konvertiert DroneCAN Raw-Werte zu Standard PWM-Werten (1000-2000 μs)"""
        # KORRIGIERT: Verwendet jetzt kalibrierte Prozent-Werte für konsistente Umrechnung
        # Raw → Kalibrierte % → PWM μs

        # Zuerst kalibrierte Prozent-Werte berechnen
        percent = self.raw_to_percent(raw_value, motor_side)

        # Dann Prozent zu PWM konvertieren
        # 0% = 1500μs (Neutral), -100% = 1000μs, +100% = 2000μs
        pwm_us = int(1500 + (percent / 100.0) * 500)

        # Begrenze auf gültigen PWM-Bereich
        pwm_us = max(1000, min(2000, pwm_us))

        return pwm_us
    
    def analyze_direction(self, left_pct, right_pct):
        """Analysiert Bewegungsrichtung basierend auf kalibrierten Prozent-Werten"""
        threshold = 1.5  # REDUZIERT: Für bessere Diagonal-Erkennung (war 3.0)

        # Neutral/Stop
        if abs(left_pct) < threshold and abs(right_pct) < threshold:
            return "NEUTRAL"

        # Vorwärts/Rückwärts (beide Motoren gleiche Richtung)
        elif left_pct > threshold and right_pct > threshold:
            diff = abs(left_pct - right_pct)
            if diff < threshold * 2:  # Größere Toleranz für "geradeaus"
                return "FORWARD"
            elif left_pct > right_pct + threshold:
                return "FORWARD + TURN_LEFT"
            else:
                return "FORWARD + TURN_RIGHT"

        elif left_pct < -threshold and right_pct < -threshold:
            diff = abs(left_pct - right_pct)
            if diff < threshold * 2:  # Größere Toleranz für "geradeaus"
                return "REVERSE"
            elif left_pct < right_pct - threshold:
                return "REVERSE + TURN_LEFT"
            else:
                return "REVERSE + TURN_RIGHT"

        # Spot-Turns (ein Motor vorwärts, einer rückwärts)
        elif left_pct > threshold and right_pct < -threshold:
            return "TURN_LEFT (Spot)"
        elif left_pct < -threshold and right_pct > threshold:
            return "TURN_RIGHT (Spot)"

        # Einseitige Bewegungen (ein Motor aktiv, anderer neutral)
        elif left_pct > threshold and abs(right_pct) < threshold:
            return "TURN_LEFT"
        elif right_pct > threshold and abs(left_pct) < threshold:
            return "TURN_RIGHT"
        elif left_pct < -threshold and abs(right_pct) < threshold:
            return "REVERSE_LEFT"
        elif right_pct < -threshold and abs(left_pct) < threshold:
            return "REVERSE_RIGHT"

        # Diagonale Bewegungen (beide Motoren aktiv, aber unterschiedliche Stärke)
        elif left_pct > threshold and right_pct > 0 and right_pct < left_pct:
            return "FORWARD + TURN_LEFT"
        elif right_pct > threshold and left_pct > 0 and left_pct < right_pct:
            return "FORWARD + TURN_RIGHT"
        elif left_pct < -threshold and right_pct < 0 and right_pct > left_pct:
            return "REVERSE + TURN_LEFT"
        elif right_pct < -threshold and left_pct < 0 and left_pct > right_pct:
            return "REVERSE + TURN_RIGHT"
        else:
            return f"MIXED (L:{left_pct:.1f}% R:{right_pct:.1f}%)"
    
    def format_percent(self, percent):
        """Formatiert Prozent-Werte mit Vorzeichen"""
        if percent > 0:
            return f"+{percent}%"
        elif percent < 0:
            return f"{percent}%"
        else:
            return "0.0%"
    
    def esc_rawcommand_handler(self, event):
        """Handler für ESC Raw Commands mit Kalibrierung und PWM-Ausgabe"""
        if len(event.message.cmd) < 2:
            return

        # CAN-Enable-Check: Ignoriere Nachrichten wenn CAN deaktiviert
        if not self.can_enabled:
            # Bei deaktiviertem CAN: Motoren auf Neutral halten
            if self.enable_pwm:
                self._set_motor_pwm('left', 1500)
                self._set_motor_pwm('right', 1500)
            return

        # Joystick-Priorität: Ignoriere DroneCAN wenn Joystick aktiv
        if self.joystick_enabled:
            # Joystick hat Priorität - ignoriere DroneCAN-Kommandos
            # Aber aktualisiere trotzdem Timestamp für Monitor
            self.last_command_time = time.time()
            return

        # Motor-Zuordnung FINAL KORRIGIERT: Tausche Links/Rechts
        right_raw = event.message.cmd[0]  # Motor 0 = Rechts
        left_raw = event.message.cmd[1]   # Motor 1 = Links

        current_command = (left_raw, right_raw)
        current_time = time.time()

        # Kommando-Timestamp für Timeout-Überwachung aktualisieren
        self.last_command_time = current_time

        # Ausgabe-Dämpfung - nur Zeitbegrenzung, nicht Werte-Vergleich
        if self.enable_monitor and current_time - self.last_output_time < self.output_interval:
            # PWM trotzdem ausgeben, auch wenn Monitor gedämpft ist
            if self.enable_pwm:
                left_pwm = self.raw_to_pwm(left_raw, 'left')
                right_pwm = self.raw_to_pwm(right_raw, 'right')
                self._set_motor_pwm('left', left_pwm)
                self._set_motor_pwm('right', right_pwm)
            return

        self.last_command = current_command
        self.last_output_time = current_time

        # Kalibrierte Prozent-Werte berechnen
        left_percent = self.raw_to_percent(left_raw, 'left')
        right_percent = self.raw_to_percent(right_raw, 'right')

        # PWM-Werte berechnen (mit Kalibrierung)
        left_pwm = self.raw_to_pwm(left_raw, 'left')
        right_pwm = self.raw_to_pwm(right_raw, 'right')

        # PWM-Ausgabe (falls aktiviert)
        if self.enable_pwm:
            self._set_motor_pwm('left', left_pwm)
            self._set_motor_pwm('right', right_pwm)

        # Monitor-Ausgabe (falls aktiviert und nicht quiet)
        if self.enable_monitor and not self.quiet:
            # Richtungsanalyse
            direction = self.analyze_direction(left_percent, right_percent)

            # Formatierte Ausgabe
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            left_str = self.format_percent(left_percent)
            right_str = self.format_percent(right_percent)

            # Farbige Ausgabe je nach Richtung
            direction_emoji = {
                "NEUTRAL": "⏸️",
                "FORWARD": "⬆️",
                "REVERSE": "⬇️",
                "TURN_LEFT": "↰",
                "TURN_RIGHT": "↱",
                "TURN_LEFT (Spot)": "🔄",
                "TURN_RIGHT (Spot)": "🔃",
                "FORWARD + TURN_LEFT": "↗️",
                "FORWARD + TURN_RIGHT": "↖️",
                "REVERSE + TURN_LEFT": "↙️",
                "REVERSE + TURN_RIGHT": "↘️"
            }.get(direction, "🔀")

            print(f"\n[{timestamp}] 🚗 ESC RawCommand von Node ID {event.transfer.source_node_id}:")
            print(f"    {direction_emoji} L/R: Links={left_str:<7} | Rechts={right_str:<7} | {direction}")
            print(f"    🔧 Raw: Links={left_raw:4d} | Rechts={right_raw:4d} | Neutral: L={self.calibration['left']['neutral']} R={self.calibration['right']['neutral']}")
            print(f"    📡 PWM: Links={left_pwm:4d}μs | Rechts={right_pwm:4d}μs | Neutral=1500μs")
            if self.enable_pwm:
                print(f"    ⚡ GPIO: Links=GPIO{self.pwm_pins['left']} | Rechts=GPIO{self.pwm_pins['right']}")
            print("-" * 70)



    def _rtk_worker(self):
        """RTK-NTRIP Worker Thread"""
        reconnect_delay = 5

        while True:
            try:
                if not self.quiet:
                    print(f"🌐 Verbinde zu NTRIP: {self.ntrip_config['host']}:{self.ntrip_config['port']}")

                # NTRIP-Verbindung herstellen
                if self._connect_ntrip():
                    if not self.quiet:
                        print("✅ NTRIP-Verbindung erfolgreich")

                    # RTCM-Daten empfangen und weiterleiten
                    self._rtk_data_loop()
                else:
                    if not self.quiet:
                        print(f"❌ NTRIP-Verbindung fehlgeschlagen")

            except Exception as e:
                if not self.quiet:
                    print(f"❌ RTK-Worker Fehler: {e}")

            # Warten vor erneutem Verbindungsversuch
            if not self.quiet:
                print(f"⏳ Warte {reconnect_delay}s vor erneutem NTRIP-Versuch...")
            time.sleep(reconnect_delay)

    def _connect_ntrip(self):
        """Verbindung zum NTRIP-Server herstellen"""
        # Socket-Methode für ICY-Streams (funktioniert besser)
        return self._connect_ntrip_socket()



    def _connect_ntrip_socket(self):
        """Verbindung zum NTRIP-Server herstellen (Socket-Methode)"""
        try:
            # Socket erstellen
            self.ntrip_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.ntrip_socket.settimeout(5)

            # Verbinden
            if not self.quiet:
                print(f"🔌 Verbinde zu {self.ntrip_config['host']}:{self.ntrip_config['port']}...")
            self.ntrip_socket.connect((self.ntrip_config['host'], self.ntrip_config['port']))
            if not self.quiet:
                print(f"✅ Socket-Verbindung erfolgreich")

            # NTRIP-Request erstellen
            request = f"GET /{self.ntrip_config['mountpoint']} HTTP/1.1\r\n"
            request += f"Host: {self.ntrip_config['host']}:{self.ntrip_config['port']}\r\n"

            # Basic Authentication
            credentials = f"{self.ntrip_config['user']}:{self.ntrip_config['pass']}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            request += f"Authorization: Basic {encoded_credentials}\r\n"

            request += "User-Agent: NTRIP_Client/1.0\r\n"
            request += "Accept: */*\r\n"
            request += "\r\n"

            # Request senden
            if not self.quiet:
                print(f"📤 Sende NTRIP-Request...")
            self.ntrip_socket.send(request.encode())

            # Response als Bytes empfangen (KRITISCH: Nicht decode()!)
            if not self.quiet:
                print(f"📥 Warte auf Response...")
            self.ntrip_socket.settimeout(10)
            response_bytes = self.ntrip_socket.recv(1024)

            # Header-Ende suchen (\r\n\r\n)
            header_end = response_bytes.find(b'\r\n\r\n')
            if header_end == -1:
                if not self.quiet:
                    print(f"❌ Kein gültiger HTTP-Header gefunden")
                return False

            # Header extrahieren und prüfen
            header = response_bytes[:header_end].decode('utf-8', errors='ignore')
            if not self.quiet:
                print(f"📋 NTRIP Header: {repr(header)}")

            if "200 OK" not in header and "ICY 200 OK" not in header:
                if not self.quiet:
                    print(f"❌ NTRIP-Fehler: {header}")
                return False

            # Verbleibende Bytes nach Header sind RTCM-Daten
            rtcm_start = response_bytes[header_end + 4:]  # +4 für \r\n\r\n
            if rtcm_start:
                # Erste RTCM-Daten in Buffer speichern (KRITISCH!)
                self.rtcm_buffer = rtcm_start
                if not self.quiet:
                    print(f"💾 Erste RTCM-Daten gespeichert: {len(rtcm_start)} bytes")

            if not self.quiet:
                print(f"✅ NTRIP-Verbindung erfolgreich, Stream aktiv")
            return True

        except Exception as e:
            if not self.quiet:
                print(f"❌ NTRIP-Verbindung Fehler: {e}")
            if self.ntrip_socket:
                self.ntrip_socket.close()
                self.ntrip_socket = None
            return False

    def _rtk_data_loop(self):
        """Hauptschleife für RTCM-Datenempfang"""
        while True:
            try:
                # GGA-Nachricht senden (für VRS) - nur bei Socket-Methode
                # Curl kann keine bidirektionale Kommunikation - VRS funktioniert trotzdem oft
                if hasattr(self, 'ntrip_socket') and self.ntrip_socket:
                    current_time = time.time()
                    if current_time - self.last_gga_time > self.gga_interval:
                        self._send_gga_message()
                        self.last_gga_time = current_time

                # RTCM-Daten empfangen (nur Socket-Methode)
                if hasattr(self, 'ntrip_socket') and self.ntrip_socket:
                    self.ntrip_socket.settimeout(1)
                    rtcm_data = self.ntrip_socket.recv(1024)
                    if not rtcm_data:
                        if not self.quiet:
                            print("⚠️ NTRIP-Verbindung unterbrochen")
                        break
                else:
                    break

                if rtcm_data:
                    # RTCM-Daten filtern (KRITISCH: Nur gültige RTCM3-Nachrichten!)
                    filtered_rtcm = self._filter_rtcm_data(rtcm_data)
                    if filtered_rtcm:
                        # An Orange Cube über DroneCAN weiterleiten
                        self._send_rtcm_via_dronecan(filtered_rtcm)
                    elif not self.quiet:
                        print(f"⚠️ Keine gültigen RTCM-Daten in {len(rtcm_data)} bytes gefunden")

            except socket.timeout:
                # Timeout ist normal - weiter
                continue
            except Exception as e:
                if not self.quiet:
                    print(f"❌ RTCM-Empfang Fehler: {e}")
                break

        # Verbindung schließen
        if hasattr(self, 'ntrip_socket') and self.ntrip_socket:
            self.ntrip_socket.close()
            self.ntrip_socket = None

    def _send_gga_message(self):
        """Sendet GGA-Nachricht für VRS"""
        if not self.gps_position:
            # Fallback-Position (Schwerin, M-V)
            lat, lon = 53.5, 12.3
        else:
            lat, lon = self.gps_position

        # NMEA GGA-Nachricht erstellen
        lat_deg = int(abs(lat))
        lat_min = (abs(lat) - lat_deg) * 60
        lat_dir = 'N' if lat >= 0 else 'S'

        lon_deg = int(abs(lon))
        lon_min = (abs(lon) - lon_deg) * 60
        lon_dir = 'E' if lon >= 0 else 'W'

        # Realistische GPS-Qualitätsindikatoren
        quality = "2" if self.gps_position else "1"  # 2=DGPS, 1=GPS Fix
        satellites = "12" if self.gps_position else "08"  # Mehr Satelliten bei echter Position
        hdop = "0.8" if self.gps_position else "1.2"  # Bessere Genauigkeit bei echter Position

        gga = f"$GPGGA,{time.strftime('%H%M%S')}.00,"
        gga += f"{lat_deg:02d}{lat_min:07.4f},{lat_dir},"
        gga += f"{lon_deg:03d}{lon_min:07.4f},{lon_dir},"
        gga += f"{quality},{satellites},{hdop},50.0,M,0.0,M,,"

        # Checksum
        checksum = 0
        for char in gga[1:]:
            checksum ^= ord(char)
        gga += f"*{checksum:02X}\r\n"

        try:
            self.ntrip_socket.send(gga.encode())
            if not self.quiet:
                print(f"📍 GGA gesendet: {lat:.6f}, {lon:.6f}")
        except Exception as e:
            if not self.quiet:
                print(f"❌ GGA-Fehler: {e}")

    def _send_rtcm_via_dronecan(self, rtcm_data):
        """
        Sendet RTCM-Daten über DroneCAN an Orange Cube.
        Version 3.1: Sanftere Übertragung mit kleinerem Payload, Chunk-Limit pro Zyklus
        und robusteren Exception-Guards gegen Toggle-Bit-Fehler.
        """
        if not hasattr(self, 'dronecan_node') or not self.dronecan_node:
            return

        self.rtcm_buffer += rtcm_data

        # Intelligentes Buffer-Management: Nur an RTCM-Nachrichtengrenzen kürzen
        if len(self.rtcm_buffer) > 10240:
            # Suche nach letzter vollständiger RTCM-Nachricht
            safe_cutoff = self._find_last_complete_rtcm_boundary(self.rtcm_buffer)
            if safe_cutoff > 0:
                self.rtcm_buffer = self.rtcm_buffer[safe_cutoff:]
                if not self.quiet:
                    print(f"⚠️ RTCM-Buffer gekürzt an Nachrichtengrenze: {safe_cutoff} bytes entfernt")
            else:
                # Fallback: Buffer komplett leeren wenn keine gültigen Nachrichten
                self.rtcm_buffer = b''
                if not self.quiet:
                    print("⚠️ RTCM-Buffer komplett geleert - keine gültigen Nachrichten gefunden")

        current_time = time.time()
        if current_time - self.last_rtcm_time < 0.2:  # 5 Hz Rate
            return

        if not self.rtcm_buffer:
            return

        try:
            data_to_send = self.rtcm_buffer
            self.rtcm_buffer = b''
            max_payload = 60  # Weniger Fragmentierung pro UAVCAN-Transfer
            max_chunks_per_cycle = 6  # Vermeide lange Bursts

            if not self.quiet:
                print(f"✅ Beginne RTCM-Übertragung: {len(data_to_send)} bytes in {max_payload}-byte Chunks.")

            chunk_count = 0
            sent_this_cycle = 0
            while len(data_to_send) > 0:
                if sent_this_cycle >= max_chunks_per_cycle:
                    # Rest in den Buffer für den nächsten Zyklus zurücklegen
                    self.rtcm_buffer = data_to_send + self.rtcm_buffer
                    if not self.quiet:
                        print(f"⏸️ Sende-Pause nach {sent_this_cycle} Chunks – {len(data_to_send)} bytes verbleiben")
                    break

                chunk = data_to_send[:max_payload]
                data_to_send = data_to_send[max_payload:]
                chunk_count += 1
                sent_this_cycle += 1

                # Sende Chunk
                try:
                    rtcm_msg = dronecan.uavcan.equipment.gnss.RTCMStream(data=list(chunk))
                    self.dronecan_node.broadcast(rtcm_msg)
                    if not self.quiet and chunk_count <= 3:
                        print(f"📡 RTCMStream gesendet: {len(chunk)} bytes, Chunk #{chunk_count}")
                except Exception as e:
                    if not self.quiet:
                        print(f"❌ RTCMStream-Fehler: {e}")
                    # Fallback: Versuche alternative Übertragung
                    self._send_rtcm_alternative(chunk)

                # Intelligentes Throttling mit Verarbeitung, robust gegen Toggle-Bit-Fehler
                try:
                    self.dronecan_node.spin(0.02)  # 20ms Pause mit Queue-Verarbeitung
                except Exception as e:
                    msg = str(e)
                    if "Toggle bit value" in msg:
                        if not self.quiet:
                            print(f"⚠️ Toggle-Bit-Warnung während RTCM: {msg}")
                        # Weiter machen – Empfänger wird sich erholen
                    else:
                        if not self.quiet:
                            print(f"⚠️ Spin-Fehler während RTCM: {e}")

                if not self.quiet and chunk_count % 10 == 0:
                    print(f"📡 RTCM Chunk {chunk_count} gesendet ({len(chunk)} bytes)")

            self.last_rtcm_time = current_time

            if not self.quiet:
                print(f"📡 RTCM-Übertragung abgeschlossen: {chunk_count} Chunks gesendet")

        except Exception as e:
            if "TxQueueFull" in str(e.__class__.__name__):
                if not self.quiet:
                    print("⚠️ CAN TX Queue war voll, versuche es im nächsten Zyklus erneut.")
                self.rtcm_buffer = data_to_send + self.rtcm_buffer  # Daten nicht verlieren
            else:
                if not self.quiet:
                    print(f"❌ RTCM-DroneCAN Fehler: {e}")
                # Rest puffern, nicht verwerfen
                self.rtcm_buffer = data_to_send + self.rtcm_buffer

    def _filter_rtcm_data(self, data):
        """
        Filtert gültige RTCM3-Nachrichten aus ICY-Stream.
        VERBESSERT: Bessere Header-Validierung und CRC-Prüfung.
        """
        rtcm_data = b''
        i = 0
        messages_found = 0

        while i < len(data):
            # Suche nach RTCM3-Präambel (0xD3)
            if data[i] == 0xD3 and i + 5 < len(data):  # Mindestens 6 Bytes für Header
                # RTCM3-Header: D3 + 2 bytes Länge + 1 Byte reserviert + 2 Bytes Nachrichten-ID
                length_bytes = data[i+1:i+3]
                if len(length_bytes) == 2:
                    # Länge aus Header extrahieren (10 bits)
                    length = ((length_bytes[0] & 0x03) << 8) | length_bytes[1]

                    # Validierung: RTCM3-Nachrichten sind typisch 20-1023 bytes
                    if 6 <= length <= 1023:
                        # Komplette RTCM-Nachricht extrahieren (Header + Daten + CRC)
                        total_length = 3 + length + 3  # 3 Bytes Header + Länge + 3 Bytes CRC
                        if i + total_length <= len(data):
                            rtcm_msg = data[i:i + total_length]

                            # Optional: CRC24Q-Prüfung (vereinfacht)
                            if self._validate_rtcm_crc(rtcm_msg):
                                rtcm_data += rtcm_msg
                                messages_found += 1
                                if not self.quiet and messages_found <= 3:
                                    msg_type = ((rtcm_msg[3] << 4) | (rtcm_msg[4] >> 4)) & 0xFFF
                                    print(f"📡 RTCM3 Nachricht gefunden: Typ {msg_type}, Länge {length}")

                            i += total_length
                        else:
                            # Unvollständige Nachricht am Ende
                            break
                    else:
                        # Ungültige Länge, weitersuchen
                        i += 1
                else:
                    i += 1
            else:
                i += 1

        if not self.quiet and messages_found > 0:
            print(f"✅ {messages_found} gültige RTCM3-Nachrichten extrahiert ({len(rtcm_data)} bytes)")

        return rtcm_data

    def _validate_rtcm_crc(self, rtcm_msg):
        """
        Vereinfachte RTCM3 CRC24Q-Validierung.
        Für Produktionsumgebung sollte vollständige CRC-Implementierung verwendet werden.
        """
        if len(rtcm_msg) < 6:
            return False

        # Vereinfachte Prüfung: Letzten 3 Bytes sollten nicht alle 0x00 oder 0xFF sein
        crc_bytes = rtcm_msg[-3:]
        if crc_bytes == b'\x00\x00\x00' or crc_bytes == b'\xFF\xFF\xFF':
            return False

        # TODO: Vollständige CRC24Q-Implementierung für Produktionsumgebung
        return True

    def _find_last_complete_rtcm_boundary(self, buffer):
        """
        Findet die Position der letzten vollständigen RTCM-Nachricht im Buffer.
        Verhindert das Zerschneiden von RTCM-Nachrichten beim Buffer-Management.
        """
        last_boundary = 0
        i = 0

        while i < len(buffer):
            # Suche nach RTCM3-Präambel (0xD3)
            if buffer[i] == 0xD3 and i + 5 < len(buffer):
                length_bytes = buffer[i+1:i+3]
                if len(length_bytes) == 2:
                    # Länge extrahieren
                    length = ((length_bytes[0] & 0x03) << 8) | length_bytes[1]

                    if 6 <= length <= 1023:
                        total_length = 3 + length + 3  # Header + Daten + CRC
                        if i + total_length <= len(buffer):
                            # Vollständige Nachricht gefunden
                            last_boundary = i + total_length
                            i += total_length
                        else:
                            # Unvollständige Nachricht am Ende
                            break
                    else:
                        i += 1
                else:
                    i += 1
            else:
                i += 1

        return last_boundary

    def _send_rtcm_alternative(self, chunk):
        """
        Alternative RTCM-Übertragung falls RTCMStream fehlschlägt.
        Versucht verschiedene DroneCAN-Nachrichtentypen.
        """
        try:
            # Alternative 1: Als Raw-Daten über Debug-Nachricht
            if hasattr(dronecan.uavcan.protocol, 'debug') and hasattr(dronecan.uavcan.protocol.debug, 'LogMessage'):
                debug_msg = dronecan.uavcan.protocol.debug.LogMessage()
                debug_msg.level.value = 6  # INFO level
                debug_msg.source = "RTCM"
                debug_msg.text = f"RTCM:{chunk.hex()}"  # Hex-kodiert
                self.dronecan_node.broadcast(debug_msg)

                if not self.quiet:
                    print(f"📡 RTCM als Debug-Nachricht gesendet: {len(chunk)} bytes")
                return True

        except Exception as e:
            if not self.quiet:
                print(f"❌ Alternative RTCM-Übertragung fehlgeschlagen: {e}")

        return False



def load_calibration_from_file(filename='guided_esc_calibration.json'):
    """Lädt Kalibrierungsdaten aus JSON-Datei (optional)"""
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        
        # Extrahiert relevante Kalibrierungswerte aus neuer JSON-Datei
        calibration = {
            'left': {
                'neutral': int(data['step_data']['NEUTRAL']['left']['avg']),  # AKTUALISIERT: -114
                'min': int(data['global_ranges']['left']['min']),             # -8191
                'max': int(data['global_ranges']['left']['max']),             # +8191
                'forward_max': int(data['step_data']['FORWARD']['left']['max']),
                'reverse_min': int(data['step_data']['REVERSE']['left']['min'])
            },
            'right': {
                'neutral': int(data['step_data']['NEUTRAL']['right']['avg']), # AKTUALISIERT: 0
                'min': int(data['global_ranges']['right']['min']),            # -8191
                'max': int(data['global_ranges']['right']['max']),            # +8191
                'forward_max': int(data['step_data']['FORWARD']['right']['max']),
                'reverse_min': int(data['step_data']['REVERSE']['right']['min'])
            }
        }
        
        print(f"✅ Kalibrierungsdaten geladen aus: {filename}")
        return calibration
        
    except FileNotFoundError:
        print(f"⚠️  Kalibrierungsdatei {filename} nicht gefunden - verwende Standard-Werte")
        return None
    except Exception as e:
        print(f"❌ Fehler beim Laden der Kalibrierung: {e}")
        return None

def main():
    # Command-Line-Argumente parsen
    parser = argparse.ArgumentParser(
        description='DroneCAN ESC Controller - Monitoring + PWM-Ausgabe',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python3 dronecan_esc_controller.py                    # Nur Monitor
  python3 dronecan_esc_controller.py --pwm              # Monitor + PWM mit Ramping
  python3 dronecan_esc_controller.py --pwm --quiet      # Nur PWM (kein Monitor)
  python3 dronecan_esc_controller.py --pins 12,13       # Andere GPIO-Pins
  python3 dronecan_esc_controller.py --pwm --no-ramping # PWM ohne Ramping (sofort)
  python3 dronecan_esc_controller.py --pwm --accel-rate 100 --brake-rate 2000  # Angepasste Ramping-Raten
  python3 dronecan_esc_controller.py --pwm --web        # PWM + Web-Interface (Port 80)
  python3 dronecan_esc_controller.py --pwm --web --web-port 8080  # Web-Interface auf Port 8080
        """
    )

    parser.add_argument('--pwm', action='store_true',
                       help='PWM-Ausgabe aktivieren (Hardware-PWM)')
    parser.add_argument('--pins', default='18,19',
                       help='GPIO-Pins für PWM (Format: rechts,links) (default: 18,19)')
    parser.add_argument('--quiet', '-q', action='store_true',
                       help='Keine Monitor-Ausgabe (nur PWM)')
    parser.add_argument('--no-monitor', action='store_true',
                       help='Monitor komplett deaktivieren')

    # Ramping-Parameter
    parser.add_argument('--no-ramping', action='store_true',
                       help='Ramping deaktivieren (sofortige PWM-Änderungen)')
    parser.add_argument('--accel-rate', type=int, default=25,
                       help='Beschleunigungsrate in μs/Sekunde (default: 25, sehr langsam)')
    parser.add_argument('--decel-rate', type=int, default=800,
                       help='Verzögerungsrate in μs/Sekunde (default: 800, schnell)')
    parser.add_argument('--brake-rate', type=int, default=1500,
                       help='Bremsrate zu Neutral in μs/Sekunde (default: 1500, sehr schnell)')

    parser.add_argument('--interface', default='can0',
                       help='CAN-Interface (default: can0)')
    parser.add_argument('--bitrate', type=int, default=1000000,
                       help='CAN-Bitrate (default: 1000000)')
    parser.add_argument('--node-id', type=int, default=100,
                       help='DroneCAN Node-ID (default: 100)')

    # Web-Interface Argumente
    parser.add_argument('--web', action='store_true',
                       help='Web-Interface aktivieren (default: deaktiviert)')
    parser.add_argument('--web-port', type=int, default=80,
                       help='Web-Interface Port (default: 80)')

    # Sicherheitsschaltleiste Argumente
    parser.add_argument('--safety-pin', type=int, default=17,
                       help='GPIO-Pin für Sicherheitsschaltleiste (default: 17)')
    parser.add_argument('--no-safety', action='store_true',
                       help='Sicherheitsschaltleiste deaktivieren')

    # Licht-Steuerung Argumente
    parser.add_argument('--light-pin', type=int, default=22,
                       help='GPIO-Pin für Licht-Relais (default: 22)')
    parser.add_argument('--no-light', action='store_true',
                       help='Licht-Steuerung deaktivieren')

    # Mäher-Steuerung Argumente
    parser.add_argument('--mower-relay-pin', type=int, default=23,
                       help='GPIO-Pin für Mäher-Relais (default: 23)')
    parser.add_argument('--mower-pwm-pin', type=int, default=12,
                       help='GPIO-Pin für Mäher-PWM (default: 12)')
    parser.add_argument('--no-mower', action='store_true',
                       help='Mäher-Steuerung deaktivieren')

    # RTK-NTRIP Argumente
    parser.add_argument('--rtk', action='store_true',
                       help='RTK-NTRIP-Client aktivieren')
    parser.add_argument('--ntrip-host', type=str, default='openrtk-mv.de',
                       help='NTRIP-Server Host (default: openrtk-mv.de)')
    parser.add_argument('--ntrip-port', type=int, default=2101,
                       help='NTRIP-Server Port (default: 2101)')
    parser.add_argument('--ntrip-user', type=str, required=False,
                       help='NTRIP-Benutzername (erforderlich für --rtk)')
    parser.add_argument('--ntrip-pass', type=str, required=False,
                       help='NTRIP-Passwort (erforderlich für --rtk)')
    parser.add_argument('--ntrip-mountpoint', type=str, default='openrtk_mv',
                       help='NTRIP-Mountpoint (default: openrtk_mv)')

    args = parser.parse_args()

    # GPIO-Pins parsen
    try:
        pin_parts = args.pins.split(',')
        if len(pin_parts) != 2:
            raise ValueError("Pins müssen im Format 'rechts,links' angegeben werden")
        pwm_pins = [int(pin_parts[0]), int(pin_parts[1])]  # [rechts, links]
    except ValueError as e:
        print(f"❌ Ungültige Pin-Konfiguration: {e}")
        sys.exit(1)

    # RTK-Validierung
    if args.rtk:
        if not args.ntrip_user or not args.ntrip_pass:
            print("❌ Fehler: --rtk benötigt --ntrip-user und --ntrip-pass")
            sys.exit(1)

    # Konfiguration
    enable_monitor = not args.no_monitor
    enable_pwm = args.pwm
    quiet = args.quiet

    if args.no_monitor and not args.pwm:
        print("❌ Fehler: --no-monitor ohne --pwm macht keinen Sinn")
        sys.exit(1)

    # Header ausgeben
    if not quiet:
        print("🎯 DroneCAN ESC Controller - Monitoring + PWM-Ausgabe")
        print("🔧 Neue Orange Cube Parameter: Rückwärts ~-8000, Neutral ~0, Vorwärts ~+8000")
        if enable_pwm:
            print(f"⚡ Hardware-PWM: Rechts=GPIO{pwm_pins[0]}, Links=GPIO{pwm_pins[1]}")
            if not args.no_ramping:
                print(f"🏃 Ramping: Beschl.={args.accel_rate}μs/s, Verzög.={args.decel_rate}μs/s, Brems.={args.brake_rate}μs/s")
            else:
                print("⚡ Ramping: DEAKTIVIERT (sofortige PWM-Änderungen)")
        if args.web:
            print(f"🌐 Web-Interface: http://raspberrycan:{args.web_port}")
            if args.web_port == 80:
                print(f"   👑 Quassel UGV Controller: http://raspberrycan")
            print("   Features: CAN Ein/Aus, Joystick, Status-Monitor")
        if not args.no_safety:
            print(f"🛡️ Sicherheitsschaltleiste: GPIO{args.safety_pin} (≤500Ω, 5.2mm Ansprechweg)")
        else:
            print("⚠️ Sicherheitsschaltleiste: DEAKTIVIERT")
        if not args.no_light:
            print(f"💡 Licht-Steuerung: GPIO{args.light_pin} (Relais-Steuerung)")
        else:
            print("⚠️ Licht-Steuerung: DEAKTIVIERT")
        if not args.no_mower:
            print(f"🌾 Mäher-Steuerung: Relais=GPIO{args.mower_relay_pin}, PWM=GPIO{args.mower_pwm_pin}")
            print(f"   PWM-Bereich: 16%-84% (0.8V-4.2V), Frequenz: 1000Hz")
        else:
            print("⚠️ Mäher-Steuerung: DEAKTIVIERT")
        if args.rtk:
            print(f"🛰️ RTK-NTRIP: {args.ntrip_host}:{args.ntrip_port}/{args.ntrip_mountpoint}")
            print(f"   Benutzer: {args.ntrip_user}")
        print("="*70)

    # Controller erstellen
    controller = CalibratedESCController(
        enable_pwm=enable_pwm,
        pwm_pins=pwm_pins,
        enable_monitor=enable_monitor,
        quiet=quiet,
        enable_ramping=not args.no_ramping,
        acceleration_rate=args.accel_rate,
        deceleration_rate=args.decel_rate,
        brake_rate=args.brake_rate,
        enable_web=args.web,
        web_port=args.web_port,
        safety_pin=args.safety_pin,
        light_enabled=not args.no_light,
        light_pin=args.light_pin,
        mower_enabled=not args.no_mower,
        mower_relay_pin=args.mower_relay_pin,
        mower_pwm_pin=args.mower_pwm_pin,
        enable_rtk=args.rtk,
        ntrip_host=args.ntrip_host,
        ntrip_port=args.ntrip_port,
        ntrip_user=args.ntrip_user or "",
        ntrip_pass=args.ntrip_pass or "",
        ntrip_mountpoint=args.ntrip_mountpoint
    )

    # Sicherheitsschaltleiste deaktivieren falls gewünscht
    if args.no_safety:
        controller.safety_enabled = False

    # Versuche Kalibrierung aus Datei zu laden
    file_calibration = load_calibration_from_file()
    if file_calibration:
        controller.calibration = file_calibration
        if not quiet:
            print("🔧 Verwende NEUE Kalibrierungsdaten aus Datei")
    else:
        if not quiet:
            print("🔧 Verwende eingebaute AKTUALISIERTE Standard-Kalibrierung")

    if not quiet:
        print(f"\n📊 KALIBRIERUNGS-INFO:")
        print(f"   Links  - Neutral: {controller.calibration['left']['neutral']:4d} | Range: {controller.calibration['left']['min']}-{controller.calibration['left']['max']}")
        print(f"   Rechts - Neutral: {controller.calibration['right']['neutral']:4d} | Range: {controller.calibration['right']['min']}-{controller.calibration['right']['max']}")

    try:
        # DroneCAN Node initialisieren
        node = dronecan.make_node(args.interface, node_id=args.node_id, bitrate=args.bitrate)

        # Handler registrieren
        node.add_handler(dronecan.uavcan.equipment.esc.RawCommand, controller.esc_rawcommand_handler)

        # RTK-Support: Node-Referenz für RTK-Funktionen
        if controller.enable_rtk:
            controller.dronecan_node = node  # Node-Referenz für RTK-Funktionen
            # GPS-Handler entfernt - nicht nötig für RTK-Funktion

        if not quiet:
            print(f"\n🤖 DroneCAN Node gestartet ({args.interface}, {args.bitrate//1000} kbps, Node-ID {args.node_id})")
            if enable_monitor:
                print(f"📡 Kalibriertes Monitoring aktiv...")
            if enable_pwm:
                print(f"⚡ Hardware-PWM aktiv auf GPIO{pwm_pins[0]}/GPIO{pwm_pins[1]}")
            print(f"🚗 Warte auf ESC-Kommandos (System muss 'armed' sein)...")
            print(f"   Press Ctrl+C to stop")
            print("=" * 70)

        # Hauptschleife mit Timeout-Überwachung und Ramping-Updates
        while True:
            try:
                node.spin(timeout=0.1)  # Kürzeres Timeout für flüssiges Ramping
            except Exception as e:
                msg = str(e)
                if "Toggle bit value" in msg:
                    if not quiet:
                        print(f"⚠️ Toggle-Bit-Warnung: {msg}")
                else:
                    if not quiet:
                        print(f"⚠️ Spin-Fehler: {e}")
            # Timeout-Prüfung für PWM-Sicherheit
            if enable_pwm:
                controller._check_command_timeout()
                # Ramping-Updates für flüssige Bewegung
                controller._update_ramping()

    except KeyboardInterrupt:
        if not quiet:
            print("\n\n🛑 Controller beendet durch Benutzer")
            print("🎯 Sicherheits-Shutdown abgeschlossen!")

    except Exception as e:
        print(f"❌ Fehler: {e}")
        if enable_pwm:
            controller._emergency_stop()

if __name__ == "__main__":
    main()
