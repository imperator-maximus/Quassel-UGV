#!/usr/bin/env python3
"""
Web Server - Flask-basiertes Web-Interface mit Socket.IO
REST API + WebSocket für UGV-Steuerung
"""

import logging
import threading
import time
import json
from pathlib import Path
from typing import Optional

from ..mapping.nogo_monitor import NoGoZoneMonitor
from ..navigation.navigation_controller import NavigationController
from ..simulation.path_simulator import MowingPathSimulator, SimulationParameters
from .auth import LoginThrottle, WebAuthGuard
from . import status_delta

try:
    from flask import Flask, render_template, jsonify, request, session
    from flask_socketio import SocketIO, emit
    FLASK_AVAILABLE = True
    SOCKETIO_AVAILABLE = True
except ImportError as e:
    FLASK_AVAILABLE = False
    SOCKETIO_AVAILABLE = False
    logging.warning(f"Flask/SocketIO nicht verfügbar - Web-Interface deaktiviert: {e}")


class WebServer:
    """
    Web-Server für UGV-Steuerung
    - REST API für Status und Steuerung
    - Joystick-Interface
    - Light/Mower-Steuerung
    """
    
    # Ausschlussliste fuer Push-Meldungen: nur diese Zustaende gelten als in
    # Ordnung. Jeder andere ist eine Stoerung - auch einer, den es heute noch
    # gar nicht gibt. Bewusst so herum: wer hier eine Ergaenzung vergisst,
    # bekommt eine Meldung zu viel, nicht eine zu wenig.
    QUIET_PLAN_STATES = frozenset({
        'idle',           # nichts los
        'running',        # faehrt
        'rtk_wait',       # wartet auf Fix, loest sich meist in Sekunden
        'completed',      # Plan durch
        'paused',         # vom Benutzer pausiert
        'stopped',        # vom Benutzer beendet
        'stopping',       # beendet gerade
        'shutdown',       # Dienst faehrt herunter
        'cleared',        # Wegpunkte geleert
        'repositioning',  # rangiert an den Bahnanfang - Normalbetrieb
    })

    # Diese Zustaende meldet der Safety-Monitor selbst, mit der echten Ursache.
    # Hier nochmal zu melden ergaebe zwei Toene fuer denselben Vorgang.
    SAFETY_REPORTED_STATES = frozenset({'safety_stop'})

    # Reine Kosmetik: Klartext fuer den Betreff. Diese Liste entscheidet nicht,
    # ob gemeldet wird - fehlt ein Zustand hier, steht sein technischer Name im
    # Betreff. Lieber unschoen als stumm.
    PLAN_FAULT_TITLES = {
        'error': 'Planfahrt abgebrochen',
        'mower_fault': 'Mähdeck-Störung',
        'nogo_stop': 'No-Go-Zone erreicht',
        'rtk_lost': 'RTK-Fix verloren',
        'safety_stop': 'Sicherheitsstopp',
        'service_restart': 'Dienst neu gestartet',
        'geofence': 'Geofence verlassen',
        'divergence_stop': 'Fahrzeug läuft vom Wegpunkt weg',
        'cross_track_stop': 'Zu weit neben der Bahn',
        'heading_block': 'Kurs blockiert',
        'align_stall': 'Ausrichtung kommt nicht voran',
        'track_stall': 'Kein Bahnfortschritt',
        'watchdog': 'Navigations-Watchdog',
    }

    def __init__(self, config, motor_control, joystick_handler, can_handler, gpio_controller, navigation_controller=None, mapping_recorder=None, safety_monitor=None, notifier=None, battery=None, network=None):
        """
        Initialisiert Web-Server

        Args:
            config: WebConfig-Instanz
            motor_control: MotorControl-Instanz
            joystick_handler: JoystickHandler-Instanz
            can_handler: CANHandler-Instanz
            gpio_controller: GPIOController-Instanz
            notifier: optionaler PushNotifier fuer Stoerungsmeldungen
            battery: optionaler BatteryMonitor fuer den Ladezustand
            network: optionaler NetworkMonitor fuer das aktive WLAN
        """
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.motor = motor_control
        self.joystick = joystick_handler
        self.can = can_handler
        self.gpio = gpio_controller
        self.navigation = navigation_controller
        self.mapping = mapping_recorder
        self.safety = safety_monitor
        self.notifier = notifier
        self.battery = battery
        self.network = network

        # Flask-App
        self.flask_available = FLASK_AVAILABLE
        self.socketio_available = SOCKETIO_AVAILABLE
        self.app: Optional[Flask] = None
        self.socketio: Optional[SocketIO] = None
        self.auth: Optional[WebAuthGuard] = None
        self.server_thread: Optional[threading.Thread] = None
        self.running = False
        
        # Zusätzliche Hardware-Referenzen (für Light/Mower)
        self.light_config = None
        self.odrive_mower = None
        
        # Status
        self.can_enabled = bool(getattr(self.can, 'can_enabled', True))
        self.light_state = False
        self.mower_state = False
        self._plan_lock = threading.Lock()
        self._resume_lock = threading.Lock()
        self._simulation_lock = threading.Lock()
        self._simulation_state_lock = threading.Lock()
        self._simulation_cancel_event = threading.Event()
        self._simulation_state = {
            'running': False,
            'phase': 'idle',
            'started_at': None,
        }
        self._plan_thread: Optional[threading.Thread] = None
        self._plan_stop_event = threading.Event()
        self._plan_pause_event = threading.Event()
        self._active_executable_segments = []
        self._active_plan_map_name = None
        self._active_plan_summary = {}
        self._last_resume_save = 0.0
        self._plan_status = {
            'running': False,
            'state': 'idle',
            'active_index': 0,
            'total': 0,
            'last_error': None,
            'current_segment': None,
        }
        # Ein Sicherheitsstopp beendet den Prozess, damit systemd ihn sauber
        # neu startet. Der Planstatus lebt aber nur im Prozess - nach dem
        # Neustart stand der Benutzer vor einem stummen System: Fahrzeug
        # steht, Maeher aus, keine Meldung (real 08.08., 21:06 und 21:18, je
        # ODrive-USB-Haenger). Beim ersten Statusabruf wird deshalb aus dem
        # gespeicherten Wiederaufsetzpunkt nachgetragen, was zuletzt war.
        self._stop_reason_restored = False
        # Anlaeufe des automatischen Fortsetzens nach einem USB-Haenger, und
        # der Bahnindex, ab dem wieder Fortschritt zaehlt.
        self._auto_resume_count = 0
        self._auto_resume_anchor_index = None

        # Statusuebertragung als Differenz. Der Grundstand ist der zuletzt
        # gesendete Status; die laufende Nummer laesst den Browser merken,
        # wenn ihm eine Differenz fehlt, und einen vollen Stand nachfordern.
        self._status_lock = threading.Lock()
        self._status_baseline: Optional[dict] = None
        self._status_seq = 0
        self._status_clients = 0
        
        if self.flask_available:
            self._init_flask()
    
    def set_hardware_refs(self, light_config, odrive_mower=None):
        """
        Setzt Hardware-Referenzen für Light/Mower-Steuerung

        Args:
            light_config: LightConfig-Instanz
            odrive_mower: ODrive-Mähdeck-Instanz
        """
        self.light_config = light_config
        self.odrive_mower = odrive_mower
    
    def _init_flask(self):
        """Initialisiert Flask-App mit Socket.IO"""
        try:
            template_folder = self._resolve_web_path(self.config.template_folder)
            static_folder = self._resolve_web_path(self.config.static_folder)
            self.app = Flask(
                __name__,
                template_folder=str(template_folder),
                static_folder=str(static_folder)
            )
            self.app.config['SECRET_KEY'] = self.config.secret_key
            # Das Sitzungscookie gibt den WebSocket frei. 'Lax' verhindert, dass
            # der Browser es an Verbindungen anhaengt, die eine fremde Seite
            # aufbaut.
            self.app.config['SESSION_COOKIE_HTTPONLY'] = True
            self.app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
            # Die statischen Dateien tragen einen Versionsstempel im Pfad
            # (?v=...). Damit darf der Browser sie lange behalten, statt sie
            # bei jedem Aufruf des Fahrzeugs neu ueber die SIM-Karte zu holen.
            self.app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 30 * 24 * 3600

            self._init_auth()

            allowed_origins = self._configured_origins()

            @self.app.after_request
            def add_cors_headers(response):
                # Die Oberflaeche laedt ausschliesslich relative Pfade und
                # braucht keine CORS-Freigabe. Ein pauschales '*' wuerde jeder
                # fremden Seite erlauben, Antworten dieses Servers zu lesen.
                origin = request.headers.get('Origin')
                if origin and WebAuthGuard._origin_host(origin) in allowed_origins:
                    response.headers['Access-Control-Allow-Origin'] = origin
                    response.headers['Access-Control-Allow-Credentials'] = 'true'
                    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
                    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,PATCH,DELETE,OPTIONS'
                    response.headers['Vary'] = 'Origin'
                return response

            @self.app.after_request
            def compress_response(response):
                return self._compress_response(response)

            @self.app.before_request
            def enforce_authentication():
                return self._enforce_authentication()

            # Socket.IO initialisieren
            if self.socketio_available:
                self.socketio = SocketIO(
                    self.app,
                    # Eine Prueffunktion statt einer Liste. Eine Liste ersetzt
                    # in engineio die Vorgabe "nur die eigene Herkunft" - und
                    # genau daran ist am 27.08. der Zugang ueber die alte
                    # Portfreigabe gestorben: Die Seite lud noch, der
                    # Steuerkanal wurde abgewiesen, der Joystick war tot.
                    cors_allowed_origins=self._socket_origin_allowed,
                    async_mode='threading',
                    logger=False,
                    engineio_logger=False,
                    ping_timeout=60,
                    ping_interval=25
                )
                self._setup_socketio_events()
                self.logger.info("✅ Socket.IO initialisiert")
            else:
                self.logger.warning("⚠️ Socket.IO nicht verfügbar - nur REST API")

            self._setup_routes()
            self.logger.info("✅ Flask-App initialisiert")

        except Exception as e:
            self.logger.error(f"❌ Flask-Initialisierung fehlgeschlagen: {e}")
            self.flask_available = False
            self.socketio_available = False

    # HTML, JavaScript und JSON sind Text und lassen sich auf etwa ein Fuenftel
    # zusammendrucken. Ueber die SIM-Karte ist das bei 90 kB Oberflaeche je
    # Seitenaufruf der Unterschied zwischen spuerbar und egal. Komprimiert wird
    # erst ab einer Mindestgroesse - bei kurzen Antworten kostet der
    # gzip-Rahmen mehr, als er spart.
    COMPRESSIBLE_TYPES = (
        'text/', 'application/json', 'application/javascript', 'image/svg+xml',
    )

    def _compress_response(self, response):
        try:
            if response.direct_passthrough or response.status_code >= 300:
                return response
            if response.headers.get('Content-Encoding'):
                return response
            content_type = (response.headers.get('Content-Type') or '').lower()
            if not content_type.startswith(self.COMPRESSIBLE_TYPES):
                return response

            response.headers['Vary'] = ', '.join(
                filter(None, [response.headers.get('Vary'), 'Accept-Encoding'])
            )
            accepted = (request.headers.get('Accept-Encoding') or '').lower()
            if 'gzip' not in accepted:
                return response

            minimum = int(getattr(self.config, 'compress_min_bytes', 1024) or 0)
            data = response.get_data()
            if len(data) < minimum:
                return response

            import gzip
            # mtime=0: Ohne festen Zeitstempel unterscheidet sich das Ergebnis
            # bei jedem Aufruf, und der ETag der Antwort waere wertlos.
            packed = gzip.compress(data, compresslevel=6, mtime=0)
            if len(packed) >= len(data):
                return response
            response.set_data(packed)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = str(len(packed))
        except Exception as e:  # Komprimierung ist Beiwerk, nie ein Ausfallgrund
            self.logger.debug(f"Komprimierung uebersprungen: {e}")
        return response

    def _socket_origin_allowed(self, origin, environ=None) -> bool:
        """Entscheidet, wer den Steuerkanal oeffnen darf.

        Erlaubt ist zweierlei: dieselbe Herkunft wie der Request selbst -
        unabhaengig vom Schema, denn hinter einem TLS-Reverse-Proxy kommt die
        Anfrage unverschluesselt an - und jede ausdruecklich konfigurierte.

        Das Schema bewusst zu ignorieren ist vertretbar, weil ueber den
        Steuerkanal ohnehin die Anmeldung entscheidet; der Herkunftsvergleich
        haelt nur fremde Webseiten fern, und die stehen auf einem anderen Host.
        """
        if not origin:
            # Kein Browser. Ein solcher Client bringt keine fremden
            # Zugangsdaten mit; ueber ihn entscheidet die Anmeldung.
            return True
        origin_host = WebAuthGuard._origin_host(origin)
        if not origin_host:
            return False
        if origin_host in self._configured_origins():
            return True
        target = ''
        if environ:
            target = (
                environ.get('HTTP_X_FORWARDED_HOST')
                or environ.get('HTTP_HOST')
                or ''
            ).split(',')[0].strip()
        return bool(target) and WebAuthGuard._origin_host(target) == origin_host

    def _configured_origins(self):
        """Zusaetzlich erlaubte Origins, auf den blossen Host reduziert."""
        raw = getattr(self.config, 'allowed_origins', None) or []
        return WebAuthGuard._normalize_origins(raw)

    def _init_auth(self):
        """Baut den Zugangsschutz aus der Konfiguration auf."""
        auth_enabled = bool(getattr(self.config, 'auth_enabled', True))
        username = getattr(self.config, 'auth_username', '') or ''
        password = getattr(self.config, 'auth_password', '') or ''

        throttle = LoginThrottle(
            max_failures=int(getattr(self.config, 'auth_max_failures', 8)),
            lockout_s=float(getattr(self.config, 'auth_lockout_s', 60.0)),
        )
        self.auth = WebAuthGuard(
            username=username,
            password=password,
            realm=getattr(self.config, 'auth_realm', 'Quassel UGV'),
            allowed_origins=getattr(self.config, 'allowed_origins', None),
            enabled=auth_enabled,
            throttle=throttle,
            logger=self.logger,
        )

        if not auth_enabled:
            self.logger.warning(
                "⚠️ Web-Zugangsschutz ist ABGESCHALTET - jeder mit Netzzugang "
                "kann Fahrantrieb und Mähdeck steuern"
            )
        elif not self.auth.configured:
            self.logger.critical(
                "🔒 Kein Web-Passwort gesetzt (UGV_WEB_PASSWORD) - "
                "der Server antwortet auf jede Anfrage mit 503"
            )
        else:
            self.logger.info("🔒 Web-Zugangsschutz aktiv (Benutzer %s)", username)

    def _enforce_authentication(self):
        """before_request-Hook: laesst nur angemeldete Aufrufer durch."""
        decision = self.auth.authorize(
            method=request.method,
            headers=request.headers,
            host=request.host,
            remote_addr=request.remote_addr or '',
        )

        if decision.allowed:
            # Der WebSocket-Handshake traegt keinen Authorization-Header. Das
            # Sitzungscookie ist der Nachweis, dass diese Sitzung sich bereits
            # ueber HTTP angemeldet hat.
            if self.auth.enabled:
                session['authenticated'] = True
                session.permanent = False
            return None

        response = jsonify({'error': decision.message})
        response.status_code = decision.status
        if decision.challenge:
            response.headers['WWW-Authenticate'] = (
                f'Basic realm="{self.auth.realm}", charset="UTF-8"'
            )
        if decision.retry_after:
            response.headers['Retry-After'] = str(decision.retry_after)
        return response

    @staticmethod
    def _resolve_web_path(path: str) -> Path:
        folder = Path(path).expanduser()
        if folder.is_absolute():
            return folder
        return Path.cwd() / folder
    
    def _setup_routes(self):
        """Definiert Flask-Routen"""
        
        @self.app.route('/')
        def index():
            # Die Oberflaeche ist 90 kB gross und aendert sich nur beim
            # Ausrollen. Mit ETag beantwortet der Server den zweiten Aufruf mit
            # 304 und uebertraegt gar nichts mehr.
            response = self.app.make_response(render_template('index.html'))
            response.headers['Cache-Control'] = 'no-cache'
            response.add_etag()
            return response.make_conditional(request)
        
        @self.app.route('/api/status')
        def api_status():
            """Gibt System-Status zurück"""
            return jsonify({
                'can_enabled': self.can_enabled,
                'can_status': self._can_api_status(),
                'motor_status': self.motor.get_status(),
                'joystick_status': self.joystick.get_status(),
                'sensor_data': self.can.get_sensor_data(),
                'navigation_status': self.navigation.get_status() if self.navigation else {'state': 'disabled'},
                'plan_execution_status': self.get_plan_execution_status(),
                'mapping_status': self.mapping.get_status() if self.mapping else {'state': 'disabled'},
                'safety_status': self.safety.get_status() if self.safety else {},
                'battery_status': (
                    self.battery.get_status() if self.battery else {'enabled': False}
                ),
                'notification_status': (
                    self.notifier.get_status() if self.notifier else {'enabled': False}
                ),
                'network_status': (
                    self.network.get_status() if self.network else {'enabled': False}
                ),
                'light_state': self.light_state,
                # Der Schieberegler liest diesen Wert beim Laden. Bisher gab es
                # ihn nur im WebSocket-Status, nicht ueber HTTP.
                'max_speed_percent': self.joystick.get_status().get('max_speed', 100),
                **self._mower_api_status()
            })
        
        @self.app.route('/api/notifications/test', methods=['POST'])
        def api_notifications_test():
            """Schickt eine Testmeldung, damit die Kette pruefbar ist.

            Ohne das muesste man einen echten Fehler provozieren, um zu sehen,
            ob Topic, Netz und Telefon zusammenpassen.
            """
            if not self.notifier or not getattr(self.notifier, 'enabled', False):
                return jsonify({
                    'success': False,
                    'error': 'Push-Meldungen sind nicht aktiv',
                    'status': self.notifier.get_status() if self.notifier else {},
                }), 503
            queued = self.notifier.info(
                f'test:{time.time():.0f}',
                'UGV: Testmeldung',
                'Wenn du das liest, funktioniert der Meldeweg.',
            )
            return jsonify({
                'success': bool(queued),
                'status': self.notifier.get_status(),
            })

        @self.app.route('/api/can/toggle', methods=['POST'])
        def api_can_toggle():
            """Schaltet CAN Ein/Aus"""
            self.can_enabled = not self.can_enabled
            self.can.can_enabled = self.can_enabled
            
            if not self.can_enabled:
                if self.safety:
                    self.safety.trigger_system_stop("CAN manuell deaktiviert")
                else:
                    self.motor.emergency_stop()
                    self.joystick.disable()
            
            self.logger.info(f"CAN {'aktiviert' if self.can_enabled else 'deaktiviert'}")
            return jsonify({'can_enabled': self.can_enabled})

        @self.app.route('/api/safety/reset', methods=['POST'])
        def api_safety_reset():
            """Entriegelt nach manueller Bestaetigung nur bei gesundem CAN."""
            if not self.safety:
                return jsonify({'success': False, 'error': 'Safety Monitor nicht verfuegbar'}), 503
            if self.odrive_mower:
                cleared, clear_error = self.odrive_mower.prepare_safety_reset()
                if not cleared:
                    return jsonify({
                        'success': False,
                        'error': clear_error,
                        'safety_status': self.safety.get_status(),
                    }), 409
                time.sleep(0.25)
            success, error = self.safety.reset_system_stop()
            payload = {
                'success': success,
                'error': error,
                'safety_status': self.safety.get_status(),
            }
            return jsonify(payload), (200 if success else 409)
        
        @self.app.route('/api/odrive/clear-errors', methods=['POST'])
        def api_odrive_clear_errors():
            """Loescht ODrive-Fehler auf ausdrueckliche Anweisung.

            Der Safety-Reset raeumt bewusst nur Watchdog-Fehler weg; alles
            andere soll ein Mensch angesehen haben. Es fehlte aber der Weg,
            danach auch zu entscheiden - dem Bediener blieb nur, zum Fahrzeug
            zu gehen und die Versorgung zu trennen, denn die Fehler liegen im
            Arbeitsspeicher der Boards. Dieser Aufruf tut dasselbe, ohne den
            Weg dorthin, und verlangt dafuer eine ausdrueckliche Bestaetigung.
            """
            if not self.odrive_mower or not self.odrive_mower.enabled:
                return jsonify({
                    'success': False,
                    'error': 'Kein ODrive-Maehdeck konfiguriert',
                }), 503
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or data.get('confirm') is not True:
                # Kein Standardwert und kein Umschalten: Wer Fehler an einer
                # Maschine mit Messern wegraeumt, soll das gesagt haben.
                return jsonify({
                    'success': False,
                    'error': "Bestaetigung erforderlich: {'confirm': true}",
                }), 400

            success, error, geloescht = self.odrive_mower.clear_all_errors()
            klartext = ', '.join(
                f'node {node}=0x{wert:08X}'
                for node, wert in sorted(geloescht.items())
            ) or 'keine'
            if success:
                self.logger.warning(
                    'ODrive-Fehler auf Anweisung geloescht: %s', klartext
                )
                self._notify_auto_resume(
                    'recovery',
                    'UGV: ODrive-Fehler geloescht',
                    f'Auf Anweisung geloescht: {klartext}',
                )
            else:
                self.logger.error(
                    'ODrive-Fehler blieben trotz Anweisung aktiv: %s', error
                )
            return jsonify({
                'success': success,
                'error': error,
                'cleared': {str(node): wert for node, wert in geloescht.items()},
                'cleared_text': klartext,
            }), (200 if success else 409)

        @self.app.route('/api/light/toggle', methods=['POST'])
        def api_light_toggle():
            """Schaltet Licht Ein/Aus"""
            if self.light_config and self.light_config.enabled:
                self.light_state = not self.light_state
                self.gpio.output(self.light_config.pin, self.light_state)
                self.logger.info(f"Licht {'ein' if self.light_state else 'aus'}")

            return jsonify({'success': True, 'light_state': self.light_state})
        
        @self.app.route('/api/mower/toggle', methods=['POST'])
        def api_mower_toggle():
            """Setzt den Maehdeck-Zustand ausschliesslich explizit.

            Ein fehlender, unlesbarer oder nicht-boolescher Zustand darf das
            Maehdeck niemals implizit umschalten oder starten.
            """
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify(self._mower_api_status(
                    success=False,
                    error="Gueltiges JSON mit booleschem Feld 'state' erforderlich",
                )), 400

            if 'state' in data:
                desired_state = data['state']
            elif 'enabled' in data:
                # Expliziter Legacy-Alias; auch hier kein Toggle-Fallback.
                desired_state = data['enabled']
            else:
                return jsonify(self._mower_api_status(
                    success=False,
                    error="Boolesches Feld 'state' erforderlich",
                )), 400

            if not isinstance(desired_state, bool):
                return jsonify(self._mower_api_status(
                    success=False,
                    error="Feld 'state' muss true oder false sein",
                )), 400

            if self.odrive_mower and self.odrive_mower.enabled:
                rpm = data.get('rpm')
                if desired_state is True:
                    if rpm is not None:
                        try:
                            rpm = int(rpm)
                        except (TypeError, ValueError):
                            return jsonify(self._mower_api_status(
                                success=False,
                                error="Feld 'rpm' muss eine Ganzzahl sein",
                            )), 400
                    status = self.odrive_mower.start(rpm) if rpm is not None else self.odrive_mower.start()
                else:
                    status = self.odrive_mower.stop()
                self.mower_state = status['running']
                return jsonify(self._mower_api_status(success=status.get('success', True), error=status.get('error')))

            return jsonify(self._mower_api_status(
                success=False,
                error="Kein Mähdeck konfiguriert",
            )), 503
        
        @self.app.route('/api/mower/speed', methods=['POST'])
        def api_mower_speed():
            """Setzt Mäher-Geschwindigkeit"""
            data = request.get_json(silent=True) or {}

            if self.odrive_mower and self.odrive_mower.enabled:
                rpm = data.get('rpm', data.get('speed', self.odrive_mower.target_rpm))
                status = self.odrive_mower.set_rpm(int(rpm))
                self.mower_state = status['running']
                return jsonify(self._mower_api_status(success=status.get('success', True), error=status.get('error')))

            return jsonify(self._mower_api_status(
                success=False,
                error="Kein Mähdeck konfiguriert",
            )), 503
        
        @self.app.route('/api/joystick', methods=['POST'])
        def api_joystick():
            """Verarbeitet Joystick-Input"""
            data = request.get_json()
            x = data.get('x', 0.0)
            y = data.get('y', 0.0)
            self.joystick.update(x, y)
            
            return jsonify({'success': True})
        
        @self.app.route('/api/sensor/status', methods=['GET'])
        def api_sensor_status():
            """Fordert Sensor-Status an"""
            self.can.request_sensor_status()
            return jsonify({
                'request': 'sent',
                'sensor_data': self.can.get_sensor_data()
            })
        
        @self.app.route('/api/sensor/restart', methods=['POST'])
        def api_sensor_restart():
            """Startet Sensor Hub neu"""
            success = self.can.restart_sensor_hub()
            return jsonify({'success': success})

        @self.app.route('/api/network/preferred', methods=['POST'])
        def api_network_preferred():
            """Holt das Fahrzeug ins Wunschnetz zurueck.

            Der Wechsel kappt die Verbindung, ueber die dieser Aufruf kam. Die
            Antwort bestaetigt deshalb nur den Anstoss; das Ergebnis steht
            danach in `network_status.last_switch`.
            """
            if not self.network:
                return jsonify({'success': False, 'error': 'Netzueberwachung deaktiviert'}), 503
            result = self.network.switch_to_preferred()
            status_code = 200 if result.get('success') else 409
            return jsonify({**result, 'network_status': self.network.get_status()}), status_code

        @self.app.route('/api/navigation/waypoints', methods=['GET', 'POST', 'DELETE', 'OPTIONS'])
        def api_navigation_waypoints():
            """Setzt, liefert oder löscht Wegpunkte."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.navigation:
                return jsonify({'error': 'Navigation deaktiviert'}), 503

            if request.method == 'GET':
                return jsonify(self.navigation.get_status())

            if request.method == 'DELETE':
                self.navigation.clear_waypoints()
                return jsonify({'success': True, **self.navigation.get_status()})

            data = request.get_json(silent=True) or {}
            raw_waypoints = data if isinstance(data, list) else data.get('waypoints')
            if raw_waypoints is None:
                return jsonify({'error': 'POST erwartet {"waypoints": [...]}' }), 400
            try:
                waypoints = self.navigation.set_waypoints(
                    raw_waypoints,
                    mode=data.get('mode', 'goto') if isinstance(data, dict) else 'goto',
                    lookahead_m=data.get('lookahead_m') if isinstance(data, dict) else None,
                )
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
            return jsonify({'success': True, 'waypoints': waypoints, **self.navigation.get_status()})

        @self.app.route('/api/navigation/start', methods=['POST', 'OPTIONS'])
        def api_navigation_start():
            """Startet die Wegpunktnavigation."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.navigation:
                return jsonify({'error': 'Navigation deaktiviert'}), 503
            if not self.navigation.start():
                return jsonify({'success': False, **self.navigation.get_status()}), 400
            return jsonify({'success': True, **self.navigation.get_status()})

        @self.app.route('/api/mapping/status', methods=['GET', 'OPTIONS'])
        def api_mapping_status():
            """Gibt Drive-around Mapping-Status zurück."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            return jsonify(self.mapping.get_status())

        @self.app.route('/api/mapping/start', methods=['POST', 'OPTIONS'])
        def api_mapping_start():
            """Startet eine Drive-around Aufnahme."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            data = request.get_json(silent=True) or {}
            return jsonify({'success': True, **self.mapping.start(clear=data.get('clear', True))})

        @self.app.route('/api/mapping/stop', methods=['POST', 'OPTIONS'])
        def api_mapping_stop():
            """Stoppt eine Drive-around Aufnahme."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            return jsonify({'success': True, **self.mapping.stop()})

        @self.app.route('/api/mapping/point', methods=['POST', 'OPTIONS'])
        def api_mapping_point():
            """Speichert die aktuelle korrigierte Pose als Polygonpunkt."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            data = request.get_json(silent=True) or {}
            result = self.mapping.add_current_point(force=bool(data.get('force', False)))
            return jsonify(result), 200 if result.get('success') else 400

        @self.app.route('/api/mapping/clear', methods=['POST', 'OPTIONS'])
        def api_mapping_clear():
            """Löscht die aktuelle Aufnahme im Speicher."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            return jsonify({'success': True, **self.mapping.clear()})

        @self.app.route('/api/mapping/save', methods=['POST', 'OPTIONS'])
        def api_mapping_save():
            """Speichert die aktuelle Boundary als GeoJSON FeatureCollection."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            data = request.get_json(silent=True) or {}
            result = self.mapping.save(data.get('name', ''))
            return jsonify(result), 200 if result.get('success') else 400

        @self.app.route('/api/mapping/maps', methods=['GET', 'OPTIONS'])
        def api_mapping_maps():
            """Listet gespeicherte Karten."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            main_only = str(request.args.get('main_only', '')).lower() in ('1', 'true', 'yes')
            maps = self.mapping.list_main_maps() if main_only else self.mapping.list_maps()
            return jsonify({'maps': maps})

        @self.app.route('/api/mapping/maps/<map_name>', methods=['GET', 'DELETE', 'PATCH', 'OPTIONS'])
        def api_mapping_map(map_name):
            """Lädt, löscht oder benennt eine gespeicherte Karte um."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            try:
                if request.method == 'GET':
                    result = self.mapping.load_map(map_name)
                elif request.method == 'DELETE':
                    result = self.mapping.delete_map(map_name)
                else:
                    data = request.get_json(silent=True) or {}
                    result = self.mapping.rename_map(map_name, data.get('name', ''))
            except ValueError as exc:
                result = {'success': False, 'error': str(exc)}
            return jsonify(result), 200 if result.get('success') else 400

        @self.app.route('/api/mapping/maps/<map_name>/boundary', methods=['PUT', 'OPTIONS'])
        def api_mapping_map_boundary(map_name):
            """Aktualisiert die Boundary-Punkte einer Karte."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            data = request.get_json(silent=True) or {}
            try:
                result = self.mapping.update_boundary_points(map_name, data.get('points') or [])
            except ValueError as exc:
                result = {'success': False, 'error': str(exc)}
            return jsonify(result), 200 if result.get('success') else 400

        @self.app.route('/api/mapping/maps/<map_name>/analysis', methods=['GET', 'OPTIONS'])
        def api_mapping_map_analysis(map_name):
            """Analysiert Hauptfläche plus sub_<Name>* Ausschlussflächen."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            try:
                result = self.mapping.analyze_map_with_subs(map_name)
            except ValueError as exc:
                result = {'success': False, 'error': str(exc)}
            return jsonify(result), 200 if result.get('success') else 400

        @self.app.route('/api/mapping/maps/<map_name>/plan', methods=['GET', 'OPTIONS'])
        def api_mapping_map_plan(map_name):
            """Erzeugt eine erste Bahn-Vorschau, ohne Fahrbefehle zu senden."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            try:
                result = self.mapping.plan_contour_lanes(
                    map_name,
                    cut_width_m=request.args.get('cut_width_m', 0.45),
                    overlap_m=request.args.get('overlap_m', 0.10),
                    outer_margin_m=request.args.get('outer_margin_m', 0.0),
                    sub_margin_m=request.args.get('sub_margin_m', 0.25),
                    max_ring_turn_deg=request.args.get('max_ring_turn_deg', 155.0),
                    max_lane_curvature_deg_per_m=request.args.get(
                        'max_lane_curvature_deg_per_m', 20.0
                    ),
                    sub_contour_count=request.args.get('sub_contour_count', 3),
                    rest_pattern=request.args.get('rest_pattern', 'parallel'),
                )
            except ValueError as exc:
                result = {'success': False, 'error': str(exc)}
            return jsonify(result), 200 if result.get('success') else 400

        @self.app.route('/api/mapping/plans', methods=['GET', 'OPTIONS'])
        def api_mapping_plans():
            """Listet gespeicherte Bahnpläne."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            return jsonify({'plans': self.mapping.list_plans()})

        @self.app.route('/api/mapping/maps/<map_name>/plan/save', methods=['POST', 'OPTIONS'])
        def api_mapping_map_plan_save(map_name):
            """Speichert eine berechnete Bahnplanung, ohne Fahrbefehle zu senden."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            data = request.get_json(silent=True) or {}
            result = self.mapping.save_plan(map_name, data.get('plan') or data)
            return jsonify(result), 200 if result.get('success') else 400

        @self.app.route('/api/mapping/maps/<map_name>/plan/load', methods=['GET', 'OPTIONS'])
        def api_mapping_map_plan_load(map_name):
            """Lädt einen gespeicherten Bahnplan, ohne Ausführung zu starten."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            result = self.mapping.load_plan(map_name)
            return jsonify(result), 200 if result.get('success') else 404

        @self.app.route('/api/mapping/maps/<map_name>/plan/check', methods=['POST', 'OPTIONS'])
        def api_mapping_map_plan_check(map_name):
            """Prüft einen gespeicherten oder übergebenen Plan vor jeder Ausführung."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            data = request.get_json(silent=True) or {}
            plan = data.get('plan') if isinstance(data, dict) else None
            start_pose = self.can.get_sensor_data()
            start_segment_index = data.get('start_segment_index')
            if start_segment_index is None and data.get('resume'):
                # Fortsetzen faehrt ab dem Wiederaufsetzpunkt, nicht ab Bahn 0.
                # Ohne diese Aufloesung prueft der Vorabcheck eine voellig
                # andere Route als die spaeter gefahrene und lehnt mitten auf
                # der Flaeche mit "Anfahrt zu Bahn 0" ab (07.08.: Fahrzeug bei
                # Bahn 65, Ablehnung +49.8 Grad zur Bahn 0).
                start_segment_index = self._resume_start_segment_index(map_name, plan)
            result = self.mapping.check_plan(
                map_name,
                plan=plan,
                start_segment_index=start_segment_index,
                start_coordinate=data.get('start_coordinate'),
                start_pose=start_pose,
            )
            self._apply_heading_block_check(result, start_pose)
            self._bind_expected_route(result, data)
            if result.get('success'):
                self.logger.info(
                    "Plan-Check bereit: map=%s start_segment_index=%r start_coordinate=%r "
                    "route=%s segments=%s",
                    map_name,
                    start_segment_index,
                    data.get('start_coordinate'),
                    result.get('route_signature'),
                    self._route_log_summary(result.get('executable_segments') or []),
                )
            if not result.get('success'):
                self.logger.warning(
                    "Plan-Check abgelehnt: map=%s start_segment_index=%r "
                    "start_coordinate=%r browser_plan=%s errors=%s warnings=%s error=%s",
                    map_name,
                    start_segment_index,
                    data.get('start_coordinate'),
                    plan is not None,
                    result.get('errors'),
                    result.get('warnings'),
                    result.get('error'),
                )
            return jsonify(result), 200 if result.get('success') else 400

        @self.app.route('/api/mapping/maps/<map_name>/plan/nogo-check', methods=['POST', 'OPTIONS'])
        def api_mapping_map_plan_nogo_check(map_name):
            """Prüft die aktuelle Fahrzeugpose gegen die No-Go-Zonen eines Plans."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            data = request.get_json(silent=True) or {}
            plan = data.get('plan') if isinstance(data, dict) else None
            if plan is None:
                loaded = self.mapping.load_plan(map_name)
                if not loaded.get('success'):
                    return jsonify(loaded), 404
                plan = loaded.get('plan')
            result = self.mapping.check_nogo(plan)
            return jsonify({'success': True, 'nogo_status': result})

        @self.app.route('/api/mapping/maps/<map_name>/plan/simulate', methods=['POST', 'OPTIONS'])
        def api_mapping_map_plan_simulate(map_name):
            """Runs the production navigation controller without hardware."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'success': False, 'error': 'Mapping deaktiviert'}), 503
            if not self.navigation or not getattr(self.navigation, 'config', None):
                return jsonify({'success': False, 'error': 'Navigation deaktiviert'}), 503
            if self._plan_status.get('running'):
                return jsonify({
                    'success': False,
                    'safe': False,
                    'state': 'simulation_busy',
                    'reason': 'Simulation ist während einer realen Planfahrt deaktiviert',
                }), 409
            if not self._simulation_lock.acquire(blocking=False):
                # A closed/reloaded browser cannot abort its old synchronous
                # request. Supersede that orphaned calculation and briefly
                # wait for the simulator's cancellation checkpoint.
                self._simulation_cancel_event.set()
                if not self._simulation_lock.acquire(timeout=2.0):
                    return jsonify({
                        'success': False,
                        'safe': False,
                        'state': 'simulation_busy',
                        'reason': 'Vorherige Simulation wird noch beendet – bitte erneut starten',
                        'simulation_status': self._get_simulation_state(),
                    }), 409
            data = request.get_json(silent=True) or {}
            self._simulation_cancel_event.clear()
            self._set_simulation_state({
                'running': True,
                'phase': 'route_building',
                'started_at': time.time(),
                'map_name': map_name,
                'step_count': 0,
            })
            try:
                plan = data.get('plan') if isinstance(data.get('plan'), dict) else None
                if plan is None:
                    loaded = self.mapping.load_plan(map_name)
                    if not loaded.get('success'):
                        return jsonify(loaded), 404
                    plan = loaded.get('plan')
                start_pose = data.get('start_pose') if isinstance(data.get('start_pose'), dict) else None
                if data.get('use_current_pose') is True and self.can:
                    start_pose = self.can.get_sensor_data()
                try:
                    simulator = MowingPathSimulator(
                        self.mapping.plans,
                        self.navigation.config,
                        getattr(self.motor, 'pwm_config', None),
                    )
                    result = simulator.simulate(
                        plan,
                        start_segment_index=data.get('start_segment_index'),
                        start_coordinate=data.get('start_coordinate'),
                        start_heading_deg=data.get('start_heading_deg'),
                        start_pose=start_pose,
                        parameters=SimulationParameters.from_payload(data.get('parameters')),
                        max_source_segments=data.get('max_source_segments'),
                        cancel_event=self._simulation_cancel_event,
                        progress_callback=self._set_simulation_state,
                    )
                    self.logger.info(
                        "Plan-Simulation: map=%s start_segment_index=%r start_coordinate=%r "
                        "current_pose=%s route=%s segments=%s safe=%s state=%s",
                        map_name,
                        data.get('start_segment_index'),
                        data.get('start_coordinate'),
                        data.get('use_current_pose') is True,
                        result.get('route_signature'),
                        self._route_log_summary(result.get('segments') or []),
                        result.get('safe'),
                        result.get('state'),
                    )
                except (TypeError, ValueError) as exc:
                    result = {
                        'success': False,
                        'safe': False,
                        'state': 'simulation_error',
                        'reason': str(exc),
                    }
            finally:
                final_state = {
                    'running': False,
                    'phase': result.get('state', 'finished') if 'result' in locals() else 'error',
                    'finished_at': time.time(),
                }
                self._set_simulation_state(final_state)
                self._simulation_lock.release()
            return jsonify(result), 200 if result.get('success') else 400

        @self.app.route('/api/mapping/maps/<map_name>/plan/simulate/status', methods=['GET'])
        def api_mapping_map_plan_simulate_status(map_name):
            return jsonify({'success': True, **self._get_simulation_state()})

        @self.app.route('/api/mapping/maps/<map_name>/plan/simulate/cancel', methods=['POST', 'OPTIONS'])
        def api_mapping_map_plan_simulate_cancel(map_name):
            if request.method == 'OPTIONS':
                return ('', 204)
            state = self._get_simulation_state()
            self._simulation_cancel_event.set()
            return jsonify({
                'success': True,
                'cancel_requested': bool(state.get('running')),
            })

        @self.app.route('/api/mapping/maps/<map_name>/plan/playback', methods=['POST', 'OPTIONS'])
        def api_mapping_map_plan_playback(map_name):
            """Compiles the exact executable route for fast browser playback."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping or not getattr(self.mapping, 'plans', None):
                return jsonify({'success': False, 'error': 'Mapping deaktiviert'}), 503
            data = request.get_json(silent=True) or {}
            plan = data.get('plan') if isinstance(data.get('plan'), dict) else None
            if plan is None:
                loaded = self.mapping.load_plan(map_name)
                if not loaded.get('success'):
                    return jsonify(loaded), 404
                plan = loaded.get('plan')

            plan_name = plan.get('map_name', plan.get('name', ''))
            sanitize = self.mapping.plans._sanitize_name
            if sanitize(plan_name) != sanitize(map_name):
                return jsonify({
                    'success': False,
                    'error': 'Plan passt nicht zur aktuell gewählten Karte',
                }), 400

            start_coordinate = data.get('start_coordinate')
            use_current_pose = data.get('use_current_pose') is True
            continuation_pose = data.get('continuation_pose')
            if isinstance(continuation_pose, dict):
                start_pose = continuation_pose
                start_coordinate = None
            elif use_current_pose:
                start_pose = self.can.get_sensor_data() if self.can else None
                if self.mapping.plans._pose_coord(start_pose) is None:
                    return jsonify({
                        'success': False,
                        'error': 'Keine aktuelle RTK/GPS-Pose für die simulierte Anfahrt vorhanden',
                    }), 400
            else:
                try:
                    selected = self.mapping.plans._validated_coord(start_coordinate)
                except ValueError as exc:
                    return jsonify({'success': False, 'error': str(exc)}), 400
                if selected is None:
                    return jsonify({
                        'success': False,
                        'error': 'Keine Abfahrposition gewählt',
                    }), 400
                # Starting on the slider position must not create a fictitious
                # positioning leg. The selected coordinate is the simulated pose.
                start_pose = {'longitude': selected[0], 'latitude': selected[1]}

            try:
                chunk_size = max(1, min(20, int(data.get('max_source_segments', 8))))
                segments = self.mapping.plans.executable_segments(
                    plan,
                    start_segment_index=data.get('start_segment_index'),
                    start_coordinate=start_coordinate,
                    start_pose=start_pose,
                    max_source_segments=chunk_size,
                    # Playback is preview-only. Legacy unsafe transitions may
                    # therefore be recalculated by the runtime router here;
                    # real execution remains blocked by check_plan().
                    allow_unsafe_plan=True,
                )
            except (TypeError, ValueError) as exc:
                return jsonify({'success': False, 'error': str(exc)}), 400

            source_sequence = [
                item for item in plan.get('sequence') or []
                if self.mapping.plans._coords(item)
                and int(item.get('segment_index', -1)) >= int(data.get('start_segment_index') or 0)
            ]
            remaining_source = source_sequence[chunk_size:]
            next_source_segment_index = (
                int(remaining_source[0].get('segment_index')) if remaining_source else None
            )
            total_length_m = sum(float(item.get('length_m', 0.0) or 0.0) for item in segments)
            return jsonify({
                'success': True,
                'map_name': map_name,
                'executable_segments': segments,
                'executable_segment_count': len(segments),
                'total_length_m': round(total_length_m, 2),
                'source_segment_count': min(chunk_size, len(source_sequence)),
                'has_more': bool(remaining_source),
                'next_source_segment_index': next_source_segment_index,
                'summary': self.mapping.plans.summarize_plan(plan),
                'vehicle': {'length_m': 1.15, 'width_m': 0.79},
                'start_mode': 'current_rtk' if use_current_pose else 'selected_position',
            })

        @self.app.route('/api/mapping/maps/<map_name>/plan/execute', methods=['POST', 'OPTIONS'])
        def api_mapping_map_plan_execute(map_name):
            """Ausführung ist vorbereitet, startet aber nicht ohne separate Freigabe."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            data = request.get_json(silent=True) or {}
            resume = bool(data.get('resume', False))
            if resume:
                resume_started = self.resume_plan_execution(map_name)
                return jsonify(resume_started), 200 if resume_started.get('success') else 409
            start_pose = self.can.get_sensor_data()
            result = self.mapping.check_plan(
                map_name,
                start_segment_index=data.get('start_segment_index'),
                start_coordinate=data.get('start_coordinate'),
                start_pose=start_pose,
            )
            self._apply_heading_block_check(result, start_pose)
            self._bind_expected_route(result, data)
            if not result.get('success'):
                return jsonify({'success': False, 'error': 'Planprüfung fehlgeschlagen', **result}), 400
            self.logger.info(
                "Plan-Execute gebunden: map=%s start_segment_index=%r start_coordinate=%r "
                "route=%s segments=%s",
                map_name,
                data.get('start_segment_index'),
                data.get('start_coordinate'),
                result.get('route_signature'),
                self._route_log_summary(result.get('executable_segments') or []),
            )
            loaded = self.mapping.load_plan(map_name)
            plan = loaded.get('plan') if loaded.get('success') else None
            started = self.start_plan_execution(result.get('executable_segments', []), result.get('summary') or {}, plan)
            return jsonify(started), 200 if started.get('success') else 409

        @self.app.route('/api/mapping/maps/<map_name>/plan/pause', methods=['POST', 'OPTIONS'])
        def api_mapping_map_plan_pause(map_name):
            """Pausiert die Plan-Ausführung und hält einen Resume-Punkt."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.mapping:
                return jsonify({'error': 'Mapping deaktiviert'}), 503
            self.pause_plan_execution(reason='paused')
            return jsonify({'success': True, 'plan_execution_status': self.get_plan_execution_status()})

        @self.app.route('/api/navigation/stop', methods=['POST', 'OPTIONS'])
        def api_navigation_stop():
            """Stoppt die Wegpunktnavigation."""
            if request.method == 'OPTIONS':
                return ('', 204)
            if not self.navigation:
                return jsonify({'error': 'Navigation deaktiviert'}), 503
            self.stop_plan_execution(clear_resume=True)
            self.navigation.stop()
            return jsonify({'success': True, **self.navigation.get_status()})

    def _set_simulation_state(self, update):
        with self._simulation_state_lock:
            self._simulation_state.update(dict(update or {}))

    def _get_simulation_state(self):
        with self._simulation_state_lock:
            state = dict(self._simulation_state)
        started_at = state.get('started_at')
        if state.get('running') and started_at:
            state['wall_time_s'] = round(max(0.0, time.time() - started_at), 1)
        return state

    def _bind_expected_route(self, result, data):
        """Bind Play to the exact controller route most recently simulated."""
        expected = data.get('expected_route_signature')
        if not expected or not result.get('success'):
            return
        try:
            count = int(data.get('expected_route_segment_count'))
        except (TypeError, ValueError):
            count = 0
        executable = result.get('executable_segments') or []
        if count < 1 or count > len(executable):
            result['success'] = False
            result.setdefault('errors', []).append(
                'Simulationssignatur hat keinen gültigen Routenhorizont'
            )
            return
        actual = self.mapping.plans.route_signature(executable[:count])
        result['route_signature'] = actual
        result['route_signature_segment_count'] = count
        if actual != str(expected):
            result['success'] = False
            result.setdefault('errors', []).append(
                'Abfahrposition, Fahrzeugausrichtung oder Route haben sich seit der Simulation geändert; bitte erneut simulieren'
            )

    def _heading_block_findings(self, result, start_pose):
        """Stellen der kompilierten Route, an denen der Regler sperren wird.

        Der Regler stoppt jede Bahn, deren Winkelfehler am Anfang
        ``track_heading_block_deg`` erreicht (``_handle_track_pose``). Bisher
        fiel das erst auf der Fläche auf: Play lief an, das Fahrzeug fuhr bis
        zur Stelle und blieb dort stehen. Hier wird dieselbe Größe vorab
        gerechnet - mit der Funktion des Reglers, nicht mit einer Näherung.

        Diese Prüfung sitzt bewusst im Web-Server und nicht im PlanManager:
        nur hier liegen Plan und Navigationskonfiguration zusammen. Der
        PlanManager importiert sonst nichts aus ``navigation`` und soll es
        auch nicht - das würde die Schichtung umdrehen.
        """
        if not self.navigation or not self.mapping:
            return [], None
        segments = result.get('executable_segments') or []
        if not segments:
            return [], None
        try:
            limits = (self.navigation.get_status() or {}).get('limits') or {}
            block_deg = float(limits['track_heading_block_deg'])
        except (AttributeError, KeyError, TypeError, ValueError):
            return [], None
        # Lookahead aus der Konfiguration, nicht aus ``limits``: dort steht der
        # zuletzt gesetzte Wert, den ein manueller Waypoint-Aufruf verändert
        # haben kann. Der Planlauf ruft ``set_waypoints`` ohne ``lookahead_m``
        # auf und bekommt damit immer den Konfigurationswert.
        lookahead_m = float(getattr(self.navigation.config, 'track_lookahead_m', 0.8))

        headings = self.mapping.plans.segment_start_headings(segments, start_pose)
        first_mow_index = next(
            (index for index, item in enumerate(segments) if item.get('type') == 'mow'),
            None,
        )
        findings = []
        for index, segment in enumerate(segments):
            heading = headings[index]
            # Nur Track-Segmente: die Sperre sitzt hinter der Verzweigung auf
            # ``mode == 'track'``, ein Goto mit einzelnem Zielpunkt läuft nie
            # in sie hinein.
            if heading is None or segment.get('mode') != 'track':
                continue
            error = NavigationController.track_start_heading_error_deg(
                segment.get('coordinates') or [],
                heading,
                direction=segment.get('direction', 'forward'),
                lookahead_m=lookahead_m,
            )
            # Der Regler vergleicht mit >=, nicht mit >.
            if error is None or abs(error) < block_deg:
                continue
            findings.append({
                'route_index': index,
                'type': segment.get('type'),
                'label': self._route_segment_label(segments, index),
                'heading_error_deg': round(error, 1),
                'limit_deg': round(block_deg, 1),
            })
        return findings, first_mow_index

    @staticmethod
    def _route_segment_label(segments, index):
        """Segmentnummer des Plans zu einer Stelle der kompilierten Route."""
        segment = segments[index]
        if segment.get('type') == 'mow':
            number = segment.get('source_index')
            return f'Bahn {number}' if number is not None else 'Bahn'
        prefix = 'Anfahrt' if segment.get('type') == 'positioning' else 'Übergang'
        for follower in segments[index + 1:]:
            if follower.get('type') != 'mow':
                continue
            number = follower.get('source_index')
            return f'{prefix} zu Bahn {number}' if number is not None else prefix
        return prefix

    def _apply_heading_block_check(self, result, start_pose):
        """Grosse Einlenkwinkel melden - als Hinweis, nicht als Ablehnung.

        Bis zum 27.08.2026 lehnte diese Pruefung einen Plan ab, wenn schon die
        Anfahrt oder die erste Bahn ueber der Winkelsperre lag. Das war
        folgerichtig, solange die Sperre im Regler nach drei Posen zuschlug -
        der Start haette nichts gebracht. Genau diese drei Posen waren aber der
        Fehler: ein Drittel einer Sekunde, kuerzer als jede Drehung, und das
        Eindrehen kam nie zum Zug.

        Der Regler entscheidet jetzt danach, ob der Winkel kleiner wird. Ein
        grosser Winkel am Bahnanfang ist damit kein Grund mehr, gar nicht erst
        loszufahren - er ist der Normalfall beim Einlenken. Gestoppt wird nur
        noch, wer sich nicht eindreht, und das kann diese Pruefung aus
        geplanten Kursen nicht vorhersagen.
        """
        if not result.get('success'):
            return
        findings, _first_mow_index = self._heading_block_findings(result, start_pose)
        if not findings:
            return
        result['heading_blocks'] = findings
        limit = findings[0]['limit_deg']
        detail = '; '.join(
            f"{finding['label']} {finding['heading_error_deg']:+.1f}°"
            for finding in findings
        )
        result.setdefault('warnings', []).append(
            f'{len(findings)} Stelle(n) verlangen ein Einlenken ueber '
            f'{limit:.0f}°: {detail}. Das Fahrzeug dreht dort ein; gestoppt '
            f'wird nur, wenn der Winkel dabei nicht kleiner wird '
            f'(aus geplanten Kursen gerechnet, real weicht der Kurs ab)'
        )

    @staticmethod
    def _route_log_summary(segments):
        return [
            {
                'type': item.get('type'),
                'source': item.get('source_index'),
                'direction': item.get('direction'),
                'length_m': round(float(
                    item.get('length_m', item.get('planned_length_m', 0.0)) or 0.0
                ), 2),
                'state': item.get('state'),
            }
            for item in list(segments)[:8]
        ]

    def start_plan_execution(self, executable_segments, summary, plan=None):
        if not self.navigation:
            return {'success': False, 'error': 'Navigation deaktiviert'}
        if not executable_segments:
            return {'success': False, 'error': 'Keine ausführbaren Segmente im Plan'}
        with self._plan_lock:
            if self._plan_status.get('running'):
                return {'success': False, 'error': 'Plan-Ausführung läuft bereits'}
            self._plan_stop_event.clear()
            self._plan_pause_event.clear()
            self._active_executable_segments = list(executable_segments)
            self._active_plan_map_name = summary.get('map_name')
            self._active_plan_summary = dict(summary)
            self._plan_status = {
                'running': True,
                'state': 'running',
                'active_index': 0,
                'total': len(executable_segments),
                'last_error': None,
                'current_segment': None,
                'summary': summary,
            }
            self._plan_thread = threading.Thread(
                target=self._run_plan_segments,
                args=(list(executable_segments), plan),
                daemon=True,
            )
            self._plan_thread.start()
        return {'success': True, 'plan_execution_status': self.get_plan_execution_status()}

    def resume_plan_execution(self, map_name):
        resume = self._load_resume_state(map_name)
        if not resume:
            return {'success': False, 'error': 'Kein Resume-Punkt vorhanden'}
        loaded = self.mapping.load_plan(map_name) if self.mapping else {}
        if not loaded.get('success'):
            return loaded or {'success': False, 'error': 'Mähplan nicht gefunden'}
        plan = loaded.get('plan')

        # New compact resume format: regenerate the remaining route from the
        # persisted map plan instead of rewriting the full plan plus route
        # every two seconds. Keep legacy support for existing resume files.
        source_index = self._resume_source_index(plan, resume)
        if source_index is not None:
            checked = self.mapping.check_plan(
                map_name,
                plan=plan,
                start_segment_index=source_index,
                start_pose=resume.get('pose'),
            )
            if not checked.get('success'):
                return checked
            segments = checked.get('executable_segments') or []
            summary = checked.get('summary') or resume.get('summary') or {'map_name': map_name}
        else:
            segments = self._resume_segments_from_state(resume)
            summary = resume.get('summary') or {'map_name': map_name}
        return self.start_plan_execution(segments, summary, plan=plan)

    @staticmethod
    def _resume_source_index(plan, resume):
        source_index = resume.get('source_segment_index')
        current_segment = resume.get('current_segment') or {}
        if source_index is None or current_segment.get('type') == 'mow':
            return source_index
        # Transition indices identify the lane they leave. Resuming that
        # index would mow the completed lane again. Advance old and new
        # compact snapshots to the next actual source segment instead.
        following_indices = sorted({
            int(item.get('segment_index'))
            for item in (plan.get('sequence') or [])
            if item.get('segment_index') is not None
            and int(item.get('segment_index')) > int(source_index)
        })
        return following_indices[0] if following_indices else None

    def _resume_start_segment_index(self, map_name, plan=None):
        """Loest den Wiederaufsetzpunkt genauso auf wie die Ausfuehrung.

        Der Vorabcheck muss dieselbe Route beurteilen, die anschliessend
        gefahren wird. Sonst lehnt er eine Fortsetzung wegen einer Stelle ab,
        die gar nicht mehr angefahren wird.
        """
        resume = self._load_resume_state(map_name)
        if not resume:
            return None
        if plan is None:
            loaded = self.mapping.load_plan(map_name) if self.mapping else {}
            if not loaded.get('success'):
                return None
            plan = loaded.get('plan')
        return self._resume_source_index(plan or {}, resume)

    def resume_paused_plan_execution(self):
        """Setzt einen intern pausierten Plan nach Ende des alten Threads fort."""
        with self._plan_lock:
            map_name = self._active_plan_map_name
            plan_thread = self._plan_thread
        if not map_name:
            return {'success': False, 'error': 'Kein pausierter Plan vorhanden'}
        if (
            plan_thread
            and plan_thread.is_alive()
            and plan_thread is not threading.current_thread()
        ):
            plan_thread.join(timeout=1.0)
        if plan_thread and plan_thread.is_alive():
            return {'success': False, 'error': 'Pausierter Plan wird noch beendet'}
        return self.resume_plan_execution(map_name)

    def pause_plan_execution(self, reason='paused', detail=None):
        self._plan_pause_event.set()
        self._save_resume_state(reason=reason, detail=detail)
        with self._plan_lock:
            previous_state = self._plan_status.get('state')
            was_running = bool(self._plan_status.get('running'))
            if was_running:
                self._plan_status['state'] = reason
                self._plan_status['running'] = False
            last_error = self._plan_status.get('last_error')
        if was_running:
            self._notify_plan_transition(previous_state, reason, last_error)
        if self.navigation:
            self.navigation.stop(reason=reason)

    def stop_mower(self, reason='plan_finished'):
        """Schaltet das Maehdeck ab, wenn die Planfahrt endgueltig endet.

        Bewusst nicht beim Pausieren: eine kurze Telemetriepause oder ein
        RTK-Aussetzer setzt die Fahrt an derselben Stelle fort, und ein
        Deckneustart kostet mehrere Sekunden sequenzieller Achsvalidierung.
        Ist der Plan dagegen fertig oder abgebrochen, steht das Fahrzeug
        unbegrenzt - dann duerfen die Messer nicht weiterlaufen.
        """
        try:
            if self.odrive_mower and getattr(self.odrive_mower, 'enabled', False):
                status = self.odrive_mower.stop()
                if not status.get('success', True):
                    self.logger.error(
                        'Maehdeck nach %s nicht gestoppt: %s',
                        reason,
                        status.get('error'),
                    )
                    return
            else:
                return
            self.logger.info('🌾 Mähdeck ausgeschaltet: %s', reason)
        except Exception as exc:
            self.logger.exception('Maehdeck-Abschaltung nach %s fehlgeschlagen: %s', reason, exc)

    def stop_plan_execution(self, clear_resume=False):
        self._plan_stop_event.set()
        self._plan_pause_event.clear()
        with self._plan_lock:
            if self._plan_status.get('running'):
                self._plan_status['state'] = 'stopping'
        if self.navigation:
            self.navigation.stop(reason='plan_stopped')
        self.stop_mower(reason='plan_stopped')
        if clear_resume and self._active_plan_map_name:
            self._delete_resume_state(self._active_plan_map_name)

    def _restore_last_stop_reason(self):
        """Nach einem Neustart nachtragen, warum die Fahrt zuletzt endete.

        Der Wiederaufsetzpunkt liegt auf der Platte und wird erst geloescht,
        wenn ein Plan sauber zu Ende oder bewusst beendet wird. Existiert er
        beim Start noch, ist eine Fahrt offen - und der Grund darin ist das
        Einzige, was den Absturz ueberlebt hat.

        Das setzt auch ``_active_plan_map_name``, denn ohne den meldet
        ``get_plan_execution_status`` kein ``resume_available``, und dann
        fehlt in der Oberflaeche der Knopf zum Fortsetzen - obwohl der
        Wiederaufsetzpunkt daliegt (real 08.08.).
        """
        if self._stop_reason_restored:
            return
        self._stop_reason_restored = True
        if not self.mapping or self._active_plan_map_name:
            return
        # Das hier ist eine Zusatzinformation. Der Statusabruf haengt an jeder
        # Anzeige und an der Sicherheitsanzeige - er darf daran nie scheitern.
        try:
            plans_dir = self.mapping.plans.plans_dir
            candidates = sorted(
                plans_dir.glob('*.resume.json'),
                key=lambda path: path.stat().st_mtime,
            )
            if not candidates:
                return
            resume = json.loads(candidates[-1].read_text(encoding='utf-8'))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning('Wiederaufsetzpunkt nicht lesbar: %s', exc)
            return
        if not isinstance(resume, dict):
            return
        map_name = resume.get('map_name')
        if not map_name:
            return

        reason = str(resume.get('reason') or 'unbekannt')
        stopped_at = resume.get('timestamp')
        when = (
            time.strftime('%H:%M', time.localtime(stopped_at))
            if isinstance(stopped_at, (int, float)) and stopped_at > 0 else '?'
        )
        lane = resume.get('source_segment_index')
        where = '' if lane is None else f', Bahn {lane}'
        # Ein bewusst pausierter Plan ist keine Stoerung - der behaelt seinen
        # Zustand und bleibt ohne Fehlertext, sonst schlaegt die Oberflaeche
        # Alarm, wo nichts passiert ist.
        with self._plan_lock:
            self._active_plan_map_name = map_name
            if reason == 'paused':
                self._plan_status['state'] = 'paused'
                restart_message = None
            else:
                self._plan_status['state'] = 'service_restart'
                restart_message = (
                    f'Dienst wurde neu gestartet; davor endete die Fahrt um '
                    f'{when} Uhr mit "{reason}"{where}. Fortsetzen ist moeglich.'
                )
                self._plan_status['last_error'] = restart_message
            self._plan_status['active_index'] = resume.get('active_index') or 0
        self.logger.warning(
            'Offener Plan nach Neustart gefunden: map=%s reason=%s Bahn=%r um %s',
            map_name, reason, lane, when,
        )
        # Dieser Zustand entsteht ohne Zustandswechsel im laufenden Prozess -
        # der Prozess ist ja neu. Deshalb hier direkt melden statt ueber
        # _notify_plan_transition.
        if restart_message and self.notifier:
            try:
                self.notifier.fault(
                    'plan',
                    'UGV: Dienst neu gestartet',
                    restart_message,
                )
            except Exception as exc:  # noqa: BLE001 - Melden ist Nebensache
                self.logger.error('Push-Meldung zum Neustart fehlgeschlagen: %s', exc)

    def get_plan_execution_status(self):
        self._restore_last_stop_reason()
        with self._plan_lock:
            status = dict(self._plan_status)
            if isinstance(status.get('current_segment'), dict):
                status['current_segment'] = dict(status['current_segment'])
            # Welcher Plan offen ist, stand bisher nur in ``summary`` - und die
            # entsteht erst beim Start im selben Prozess. Eine Oberflaeche, die
            # sich waehrend der Fahrt dazuschaltet, konnte den laufenden Plan
            # deshalb nicht benennen und auch nicht nachladen. Der Name gehoert
            # zum Zustand und wird jetzt immer mitgeschickt.
            status['map_name'] = self._active_plan_map_name
            if self._active_plan_map_name:
                resume_path = self._resume_path(self._active_plan_map_name)
                status['resume_available'] = bool(resume_path and resume_path.exists())
            return status

    def _run_plan_segments(self, executable_segments, plan):
        try:
            nogo_monitor = self._build_nogo_monitor(plan or {})
            if nogo_monitor is not None:
                initial_check = self._check_nogo(nogo_monitor)
                if not initial_check.get('ok'):
                    raise RuntimeError(initial_check.get('reason') or 'No-Go-Check blockiert')
            for index, segment in enumerate(executable_segments):
                if self._plan_stop_event.is_set():
                    self._set_plan_status(running=False, state='stopped', active_index=index)
                    return
                if self._plan_pause_event.is_set():
                    self._set_plan_status(running=False, state='paused', active_index=index)
                    return
                coords = segment.get('coordinates') or []
                waypoints = [{'longitude': coord[0], 'latitude': coord[1]} for coord in coords]
                if not waypoints:
                    continue
                mode = segment.get('mode', 'goto')
                direction = segment.get('direction', 'forward')
                self._set_plan_status(
                    running=True,
                    state='running',
                    active_index=index,
                    current_segment={
                        'type': segment.get('type'),
                        'source_type': segment.get('source_type'),
                        'source_index': segment.get('source_index'),
                        'mode': mode,
                        'direction': direction,
                        'route_kind': segment.get('route_kind'),
                        'length_m': segment.get('length_m', 0.0),
                    },
                )
                versuche = 0
                while True:
                    self.navigation.set_waypoints(waypoints, mode=mode, direction=direction)
                    if not self.navigation.start():
                        raise RuntimeError(self.navigation.get_status().get('last_error') or 'Navigation konnte nicht starten')
                    if self._wait_for_navigation_segment(nogo_monitor):
                        break
                    with self._plan_lock:
                        zustand = self._plan_status.get('state')
                    if (
                        zustand not in self.PLAN_REPOSITION_STATES
                        or versuche >= self.PLAN_REPOSITION_ATTEMPTS
                    ):
                        return
                    versuche += 1
                    if not self._reposition_to_segment(
                        segment, plan, nogo_monitor, versuche
                    ):
                        return
            if self._active_plan_map_name:
                self._delete_resume_state(self._active_plan_map_name)
            self.stop_mower(reason='plan_completed')
            self._set_plan_status(running=False, state='completed', active_index=len(executable_segments), current_segment=None)
        except Exception as exc:
            self.logger.error('Plan-Ausführung fehlgeschlagen: %s', exc)
            if self.navigation:
                self.navigation.stop(reason='plan_error')
            self._set_plan_status(running=False, state='error', last_error=str(exc))

    # Fehler, die eine falsche Stellung beschreiben, keinen Defekt. Dafuer
    # gibt es ein Manoever - erst rangieren, dann melden.
    PLAN_REPOSITION_STATES = frozenset({'cross_track_stop', 'heading_block'})
    # Danach uebernimmt der Mensch. Ohne Grenze wuerde ein Fahrzeug, das den
    # Bahnanfang nicht erreicht, endlos hin und her setzen. Drei statt zwei,
    # seit ein Anlauf auch nur die Nase drehen kann: Dann ist der erste das
    # Drehen und erst der zweite die Anfahrt.
    PLAN_REPOSITION_ATTEMPTS = 3

    def _reposition_to_segment(self, segment, plan, nogo_monitor, versuch):
        """Bringt das Fahrzeug an den Anfang des Segments - notfalls rangierend.

        Aufgerufen, wenn die Bahnverfolgung gemeldet hat, dass sie die Bahn
        nicht erreicht. Der Bahnregler kann seitlich heranziehen, aber nicht
        rangieren; die Wegplanung kann beides und kennt die Sperrzonen.
        """
        if not self.mapping or not self.navigation:
            return False
        coords = segment.get('coordinates') or []
        pose = self.can.get_sensor_data() or {}
        gps = pose.get('gps') or {}
        lat = gps.get('lat')
        lon = gps.get('lon')
        if lat is None or lon is None or not coords:
            return False

        zuege = self._reposition_legs(
            segment, plan, [float(lon), float(lat)], pose.get('heading')
        )
        if not zuege:
            self.logger.warning(
                'Kein Rangierweg zum Bahnanfang konstruierbar - Fehler bleibt stehen'
            )
            return False

        self.logger.warning(
            '↩️ Rangieren zum Bahnanfang (Versuch %d/%d): %d Zug/Zuege, %s',
            versuch,
            self.PLAN_REPOSITION_ATTEMPTS,
            len(zuege),
            ', '.join(
                f"{zug.get('direction', 'forward')} {float(zug.get('length_m') or 0.0):.2f} m"
                for zug in zuege
            ),
        )
        for nummer, zug in enumerate(zuege, start=1):
            weg = [
                {'longitude': coord[0], 'latitude': coord[1]}
                for coord in (zug.get('coordinates') or [])
            ]
            if len(weg) < 2:
                return False
            self._set_plan_status(
                running=True,
                state='repositioning',
                last_error=None,
                current_segment={
                    'type': 'positioning',
                    'source_type': segment.get('type'),
                    'source_index': segment.get('source_index'),
                    'mode': zug.get('mode', 'track'),
                    'direction': zug.get('direction', 'forward'),
                    'route_kind': zug.get('route_kind', 'reposition'),
                    'length_m': zug.get('length_m', 0.0),
                    'leg': nummer,
                    'legs': len(zuege),
                },
            )
            self.navigation.set_waypoints(
                weg,
                mode=zug.get('mode', 'track'),
                direction=zug.get('direction', 'forward'),
            )
            if not self.navigation.start():
                return False
            if not self._wait_for_navigation_segment(nogo_monitor):
                return False
        self._set_plan_status(running=True, state='running', last_error=None)
        return True

    def _reposition_legs(self, segment, plan, from_coord, heading_deg):
        """Waehlt zwischen gerader Anfahrt und Wendemanoever.

        Die Anfahrt ist der Regelfall: Steht das Fahrzeug neben seiner Bahn,
        faehrt es hin. Sie kann aber keine Nase drehen - und genau das war am
        27.08. um 23:15 Uhr das Problem: Das Fahrzeug stand auf dem
        Bahnanfang, nur um 160° verdreht, und bekam zweimal eine gerade
        Anfahrt (3,24 m und 0,38 m), die der Regler nach je drei Posen wieder
        sperrte. Gedreht hat sich dabei nichts.

        Deshalb wird hier vorher gerechnet, ob die gebaute Anfahrt ueberhaupt
        angefahren werden kann. Sperrt der Regler schon ihren Anfang, ist sie
        wertlos, und es uebernimmt das Rangieren - vor und zurueck, bis die
        Nase passt.
        """
        anfahrt = self.mapping.plans.approach_segment_from_pose(
            plan or {},
            list(from_coord),
            segment.get('coordinates') or [],
            direction=segment.get('direction', 'forward'),
            to_segment_index=segment.get('source_index'),
            start_heading_deg=heading_deg,
        )
        if self._approach_is_usable(anfahrt, heading_deg):
            return [anfahrt]

        # Gedreht wird auf den Kurs, den der naechste Weg verlangt: die eben
        # gebaute Anfahrt, wenn es eine gibt - sonst das Segment selbst. Steht
        # das Fahrzeug schon auf dessen Anfang, laesst sich naemlich gar keine
        # Anfahrt bauen: Sie fuehrt von diesem Punkt zu diesem Punkt. Genau das
        # kam am 27.08. um 23:15 Uhr als 0,38-m-Weg heraus.
        naechster = anfahrt if self._has_length(anfahrt) else segment
        ziel = self.mapping.plans.segment_entry_heading(
            naechster.get('coordinates') or [],
            naechster.get('direction', 'forward'),
        )
        manoever = self.mapping.plans.turn_legs_from_pose(
            plan or {}, list(from_coord), heading_deg, ziel
        )
        if manoever:
            return list(manoever)
        if anfahrt:
            # Ohne Manoever bleibt nur die Anfahrt, von der wir wissen, dass
            # der Regler sie sperrt. Sie trotzdem zu fahren hiesse, denselben
            # Abbruch noch einmal zu erzeugen - der Fehler ist ehrlicher.
            self.logger.warning(
                'Anfahrt zum Bahnanfang liegt hinter der Winkelsperre und '
                'kein Wendemanoever ist konstruierbar'
            )
        return []

    # Kuerzer ist kein Weg, sondern der Standpunkt selbst. Am 27.08. um 23:15
    # Uhr kamen so 0,38 m und 0,00 m heraus, weil das Fahrzeug auf dem
    # Bahnanfang stand: Beide wurden als Rangierweg gefahren, beide aenderten
    # nichts, und danach stand der Plan.
    MIN_REPOSITION_LEG_M = 0.5

    def _has_length(self, weg):
        return bool(
            weg
            and len(weg.get('coordinates') or []) >= 2
            and float(weg.get('length_m') or 0.0) >= self.MIN_REPOSITION_LEG_M
        )

    def _approach_is_usable(self, anfahrt, heading_deg):
        """Taugt diese Anfahrt ueberhaupt als Rangierweg?"""
        if not anfahrt:
            return False
        if len(anfahrt.get('coordinates') or []) < 2:
            return False
        if float(anfahrt.get('length_m') or 0.0) < self.MIN_REPOSITION_LEG_M:
            return False
        return not self._leg_starts_blocked(anfahrt, heading_deg)

    def _leg_starts_blocked(self, leg, heading_deg):
        """Sperrt der Regler diesen Zug schon an seinem Anfang?

        Dieselbe Groesse, die ``_heading_block_findings`` fuer den ganzen Plan
        rechnet - hier fuer einen einzelnen Zug, bevor er gefahren wird.
        """
        if heading_deg is None or not self.navigation:
            return False
        coords = leg.get('coordinates') or []
        if len(coords) < 2 or leg.get('mode') != 'track':
            return False
        try:
            limits = (self.navigation.get_status() or {}).get('limits') or {}
            block_deg = float(limits['track_heading_block_deg'])
        except (AttributeError, KeyError, TypeError, ValueError):
            return False
        lookahead_m = float(getattr(self.navigation.config, 'track_lookahead_m', 0.8))
        error = NavigationController.track_start_heading_error_deg(
            coords,
            float(heading_deg),
            direction=leg.get('direction', 'forward'),
            lookahead_m=lookahead_m,
        )
        return error is not None and abs(error) >= block_deg

    def _wait_for_navigation_segment(self, nogo_monitor=None):
        while not self._plan_stop_event.is_set():
            if self._plan_pause_event.is_set():
                self._save_resume_state(reason='paused')
                if self.navigation:
                    self.navigation.stop(reason='paused')
                self._set_plan_status(running=False, state='paused')
                return False
            if not self._rtk_available() and not self._await_rtk_recovery():
                return False
            mower_fault = self._mower_fault_reason()
            if mower_fault:
                self._save_resume_state(reason='mower_fault')
                if self.navigation:
                    self.navigation.stop(reason='mower_fault')
                self._set_plan_status(
                    running=False,
                    state='mower_fault',
                    last_error=mower_fault,
                )
                return False
            if nogo_monitor is not None:
                nogo = self._check_nogo(nogo_monitor)
                if not nogo.get('ok'):
                    message = nogo.get('reason') or 'No-Go-Zone verletzt'
                    if self.navigation:
                        self.navigation.stop(reason='nogo_stop')
                    self._set_plan_status(running=False, state='nogo_stop', last_error=message, nogo_status=nogo)
                    return False
                self._set_plan_status(nogo_status=nogo)
            status = self.navigation.get_status()
            state = status.get('state')
            if not status.get('running'):
                if state == 'completed':
                    return True
                self._set_plan_status(running=False, state=state or 'stopped', last_error=status.get('last_error'))
                return False
            time.sleep(0.05)
        if self.navigation:
            self.navigation.stop(reason='plan_stopped')
        self._set_plan_status(running=False, state='stopped')
        return False

    def _set_plan_status(self, **updates):
        with self._plan_lock:
            previous_state = self._plan_status.get('state')
            self._plan_status.update(updates)
            current_state = self._plan_status.get('state')
            last_error = self._plan_status.get('last_error')
            should_save = bool(self._plan_status.get('running'))
        # Ausserhalb des Locks: Melden darf den Planstatus nicht aufhalten.
        self._notify_plan_transition(previous_state, current_state, last_error)
        if should_save:
            self._save_resume_state(reason='running')

    def _notify_plan_transition(self, previous_state, current_state, last_error):
        """Schickt eine Push-Meldung, wenn der Plan in einen Fehlerzustand geht.

        Bewertet wird allein der Zustand, nicht das ``running``-Flag: sonst
        bliebe ein Fehler stumm, der das Flag stehen laesst oder auftritt, bevor
        der Plan ueberhaupt als laufend markiert ist. Und bewertet wird die
        Flanke, nicht der Dauerzustand - ``_set_plan_status`` laeuft im
        Sekundentakt (RTK-Countdown) und wuerde sonst dauernd dasselbe melden.
        """
        if not self.notifier or current_state == previous_state:
            return
        if current_state in self.SAFETY_REPORTED_STATES:
            # Der Safety-Monitor meldet denselben Vorgang bereits, und zwar mit
            # der tatsaechlichen Ursache statt nur "Plan gestoppt".
            return
        try:
            if current_state not in self.QUIET_PLAN_STATES:
                title = self.PLAN_FAULT_TITLES.get(
                    current_state, f'Planfahrt gestoppt ({current_state})'
                )
                self.notifier.fault(
                    'plan',
                    f'UGV: {title}',
                    last_error or f'Mähplan gestoppt: {current_state}',
                )
            elif current_state == 'running':
                self.notifier.recovery(
                    'plan', 'UGV: Fahrt läuft wieder', 'Der Mähplan wird fortgesetzt.'
                )
            elif current_state == 'completed':
                self.notifier.recovery(
                    'plan', 'UGV: Mähplan fertig', 'Der Plan wurde vollständig abgefahren.'
                )
        except Exception as exc:  # noqa: BLE001 - Melden ist Nebensache
            self.logger.error('Push-Meldung zum Planstatus fehlgeschlagen: %s', exc)

    def _rtk_available(self):
        if not self.mapping:
            return False
        return self.mapping.plans.pose_rtk_ok(self.can.get_sensor_data())

    def _mower_fault_reason(self):
        """Bricht die Planfahrt ab, wenn das laufende Deck nicht gesund ist.

        Der zentrale Safety-Watchdog stoppt denselben Fehler ebenfalls. Diese
        zweite, unabhaengige Pruefung sorgt dafuer, dass der Plan auch dann
        anhaelt und einen Wiederaufsetzpunkt schreibt, wenn der Watchdog
        deaktiviert ist. Ein absichtlich ausgeschaltetes Deck gilt als gesund,
        damit reine Transferfahrten nicht abbrechen.
        """
        mower = self.odrive_mower
        if not mower or not getattr(mower, 'enabled', False):
            return None
        try:
            healthy, reason = mower.runtime_health()
        except Exception as exc:
            self.logger.error('Maehdeck-Healthcheck fehlgeschlagen: %s', exc)
            return f'Maehdeck-Healthcheck fehlgeschlagen: {exc}'
        if healthy:
            return None
        return reason or 'Maehdeck nicht betriebsbereit'

    def _await_rtk_recovery(self):
        """Haelt das Fahrzeug bei RTK-Verlust an, statt den Plan abzubrechen.

        Baeume am Feldrand druecken den Fix regelmaessig fuer einige Sekunden
        auf FLOAT. Auf einer FLOAT-Loesung weiterzufahren waere falsch (20-50
        cm Fehler), deshalb friert die Navigation sofort ein - der Plan bleibt
        aber am Leben und laeuft an genau derselben Stelle weiter, sobald der
        Fix stabil zurueck ist. Erst nach ``rtk_lost_timeout_s`` wird wie
        zuvor hart abgebrochen.

        Gibt True zurueck, wenn die Fahrt fortgesetzt wurde.
        """
        nav_config = getattr(self.navigation, 'config', None)
        stable_s = max(0.0, float(getattr(nav_config, 'rtk_resume_stable_s', 2.0)))
        timeout_s = max(0.0, float(getattr(nav_config, 'rtk_lost_timeout_s', 90.0)))

        if self.navigation:
            self.navigation.pause(reason='rtk_wait')
        self._save_resume_state(reason='rtk_wait')
        self._set_plan_status(
            running=True,
            state='rtk_wait',
            last_error=f'RTK verloren - warte bis zu {timeout_s:.0f}s auf Fix',
        )
        self.logger.warning(
            '⏸️ RTK verloren - Plan pausiert, warte bis zu %.0fs auf erneuten Fix',
            timeout_s,
        )

        deadline = time.monotonic() + timeout_s
        stable_since = None
        last_countdown = 0.0
        while time.monotonic() < deadline:
            # Stop und Pause behandelt der aufrufende Loop selbst.
            if self._plan_stop_event.is_set() or self._plan_pause_event.is_set():
                return False
            now = time.monotonic()
            if self._rtk_available():
                if stable_since is None:
                    stable_since = now
                elif (now - stable_since) >= stable_s:
                    if self.navigation and self.navigation.resume():
                        self.logger.info('▶️ RTK zurueck - Plan wird fortgesetzt')
                        self._set_plan_status(running=True, state='running', last_error=None)
                        return True
                    # Ein fehlgeschlagenes resume() heisst, dass gerade eine
                    # andere Sicherheitsstufe die Fahrt sperrt. Weiter warten,
                    # statt den Plan deswegen zu verlieren.
                    stable_since = None
            else:
                stable_since = None
            if now - last_countdown >= 1.0:
                last_countdown = now
                self._set_plan_status(
                    running=True,
                    state='rtk_wait',
                    last_error=(
                        f'RTK verloren - warte auf Fix '
                        f'(noch {max(0.0, deadline - now):.0f}s)'
                    ),
                )
            time.sleep(0.1)

        message = f'RTK laenger als {timeout_s:.0f}s verloren - Plan-Ausführung gestoppt'
        self._save_resume_state(reason='rtk_lost')
        if self.navigation:
            self.navigation.stop(reason='rtk_lost')
        self._set_plan_status(running=False, state='rtk_lost', last_error=message)
        self.logger.error('🛑 %s', message)
        return False

    def _build_nogo_monitor(self, plan):
        try:
            # The generated route already follows the mowing contour.  Treat
            # only explicit exclusion/sub-map polygons as runtime stop zones;
            # a small RTK/controller offset at the outer contour must not
            # prevent navigation from starting.
            return NoGoZoneMonitor(plan, enforce_outer_boundary=False)
        except ValueError as exc:
            self.logger.warning('No-Go-Monitor deaktiviert: %s', exc)
            self._set_plan_status(nogo_status={'ok': True, 'state': 'disabled', 'reason': str(exc)})
            return None

    def _check_nogo(self, monitor):
        return monitor.check_pose(self.can.get_sensor_data())

    # Kennzeichen des bekannten Haengers im gespeicherten Klartext. Nur dieser
    # eine Fall laeuft automatisch wieder an.
    USB_STALL_MARKER = 'ODrive USB haengt'

    def _maybe_auto_resume_after_usb_stall(self):
        """Setzt nach einem haengenden USB-Aufruf von allein fort.

        Der Haenger ist bekannt und harmlos: ``libfibre`` blockiert seinen
        Thread ohne Zeitgrenze, der Prozess beendet sich deshalb selbst und
        systemd startet neu. Danach stand das Fahrzeug bisher mitten auf der
        Wiese und wartete auf einen Menschen - bei einem Fehler, der
        regelmaessig auftritt und mit dem Maehen nichts zu tun hat.

        Automatisch angelaufen wird ausschliesslich dieser eine Fall. Jeder
        andere Sicherheitsstopp hat eine andere Ursache und wartet weiter.
        """
        if not bool(getattr(self.config, 'auto_resume_after_usb_stall', True)):
            return
        map_name = self._active_plan_map_name
        if not map_name:
            return
        resume = self._load_resume_state(map_name) or {}
        if self.USB_STALL_MARKER not in str(resume.get('detail') or ''):
            return

        versuche = int(resume.get('auto_resume_count') or 0)
        grenze = int(getattr(self.config, 'auto_resume_max_attempts', 3) or 3)
        if versuche >= grenze:
            # Haengt der Transport wirklich fest, waere die Kette sonst
            # Neustart, Messer an, Haenger, Neustart - ohne Ende.
            self.logger.error(
                "Kein automatischer Anlauf mehr: %d Versuche ohne Fortschritt",
                versuche,
            )
            self._notify_auto_resume(
                'fault',
                'UGV: Fahrt laeuft nicht mehr von allein an',
                f'Nach {versuche} Anlaeufen ohne Fortschritt wartet das '
                f'Fahrzeug auf dich.',
            )
            return

        self._auto_resume_count = versuche + 1
        self._auto_resume_anchor_index = int(resume.get('active_index') or 0)
        thread = threading.Thread(
            target=self._auto_resume_worker,
            args=(map_name, resume),
            daemon=True,
        )
        thread.start()

    def _auto_resume_worker(self, map_name, resume):
        """Wartet auf gesunde Verhaeltnisse und faehrt dann weiter."""
        gesund, hindernis = self._wait_for_healthy_restart()
        if not gesund:
            self.logger.warning("Automatischer Anlauf abgebrochen: %s", hindernis)
            self._notify_auto_resume(
                'fault',
                'UGV: Fahrt konnte nicht von allein anlaufen',
                f'{hindernis} - das Fahrzeug wartet auf dich.',
            )
            return

        rpm = int(resume.get('mower_rpm') or 0)
        if (
            resume.get('mower_running')
            and rpm > 0
            and self.odrive_mower
            and self.odrive_mower.enabled
        ):
            status = self.odrive_mower.start(rpm)
            if not status.get('success', True):
                self.logger.error(
                    "Maehdeck laeuft nicht wieder an: %s", status.get('error')
                )
                self._notify_auto_resume(
                    'fault',
                    'UGV: Maehdeck laeuft nicht wieder an',
                    f"{status.get('error') or 'unbekannter Fehler'} - das "
                    f"Fahrzeug wartet auf dich.",
                )
                return
            self.mower_state = bool(status.get('running'))

        ergebnis = self.resume_plan_execution(map_name)
        if not ergebnis.get('success'):
            self.logger.error(
                "Automatische Fortsetzung fehlgeschlagen: %s",
                ergebnis.get('error'),
            )
            self._notify_auto_resume(
                'fault',
                'UGV: Fahrt konnte nicht von allein anlaufen',
                f"{ergebnis.get('error') or 'unbekannter Fehler'} - das "
                f"Fahrzeug wartet auf dich.",
            )
            return

        self.logger.info(
            "Fahrt nach USB-Haenger automatisch fortgesetzt (Versuch %d)",
            self._auto_resume_count,
        )
        self._notify_auto_resume(
            'recovery',
            'UGV: Fahrt laeuft wieder',
            f'Nach einem USB-Haenger am Maehdeck automatisch fortgesetzt '
            f'(Anlauf {self._auto_resume_count}), Maehdeck bei {rpm} U/min.',
        )

    def _wait_for_healthy_restart(self):
        """Wartet, bis Pose, RTK und ODrive einen Anlauf erlauben."""
        frist_s = float(
            getattr(self.config, 'auto_resume_health_timeout_s', 120.0) or 120.0
        )
        ende = time.monotonic() + frist_s
        hindernis = 'Zustand nach dem Neustart unklar'
        while time.monotonic() < ende and self.running:
            hindernis = self._restart_health_problem()
            if hindernis is None:
                return True, None
            time.sleep(2.0)
        return False, hindernis

    def _restart_health_problem(self):
        """Was einem Anlauf gerade entgegensteht, oder None."""
        try:
            if self.safety:
                safety = self.safety.get_status()
                if safety.get('system_stop_latched'):
                    return 'Sicherheitsstopp verriegelt'
                if safety.get('motion_hold_active'):
                    return 'Fahrpause aktiv'
            status = self._can_api_status()
            if not status.get('sensor_hub', {}).get('online'):
                return 'SensorHub ohne Telemetrie'
            odrives = status.get('odrives', {})
            fehlerhafte = sorted(
                str(node)
                for node, wert in (odrives.get('nodes') or {}).items()
                if wert.get('error')
            )
            if fehlerhafte:
                return f"ODrive-Fehler an Knoten {', '.join(fehlerhafte)}"
            if not odrives.get('all_online', True):
                return 'ODrive nicht vollstaendig online'
            rtk = str((self.can.get_sensor_data() or {}).get('rtk_status') or '')
            if 'FIX' not in rtk.upper():
                return f"RTK nicht fix ({rtk or 'unbekannt'})"
        except Exception as exc:  # noqa: BLE001 - lieber warten als anlaufen
            return f'Zustand nicht lesbar: {exc}'
        return None

    def _notify_auto_resume(self, method, title, message):
        """Meldet jeden Anlauf - er passiert, ohne dass jemand hingesehen hat."""
        if not self.notifier:
            return
        try:
            getattr(self.notifier, method)('auto_resume', title, message)
        except Exception as exc:  # noqa: BLE001 - Melden ist Nebensache
            self.logger.error('Push-Meldung zum Anlauf fehlgeschlagen: %s', exc)

    def _resume_path(self, map_name):
        if not self.mapping:
            return None
        return self.mapping.plans.plans_dir / f"{self.mapping.plans._sanitize_name(map_name)}.resume.json"

    def _save_resume_state(self, reason='running', detail=None):
        with self._resume_lock:
            now = time.time()
            if reason == 'running' and now - self._last_resume_save < 2.0:
                return
            self._last_resume_save = now
            map_name = self._active_plan_map_name
            if not map_name or not self._active_executable_segments:
                return
            status = self.get_plan_execution_status()
            pose = self.can.get_sensor_data()
            active_index = int(status.get('active_index') or 0)
            current_segment = status.get('current_segment') or {}
            source_index = current_segment.get('source_index')
            if current_segment.get('type') != 'mow':
                # Transition indices refer to the lane they leave, not the
                # lane that follows. Resume at the next actual mowing segment
                # and let check_plan route there from the persisted pose.
                source_index = None
                for segment in self._active_executable_segments[active_index + 1:]:
                    if segment.get('source_index') is not None:
                        source_index = segment.get('source_index')
                        break
            # Fortschritt setzt die Anlaufbremse zurueck: Wer eine Bahn
            # weiter gekommen ist, hat gemaeht und nicht nur neu gestartet.
            if (
                self._auto_resume_anchor_index is not None
                and active_index > self._auto_resume_anchor_index
            ):
                self._auto_resume_count = 0
                self._auto_resume_anchor_index = None
            payload = {
                'schema': 'raspberrycan.mowing_resume.v2',
                'map_name': map_name,
                'reason': reason,
                # Der Klartext des Stopps. 'safety_stop' allein sagt nicht, ob
                # ein bekannter USB-Haenger oder etwas Ernstes dahinter steckt.
                'detail': str(detail) if detail else None,
                # Damit das Maehdeck mit derselben Drehzahl wieder anlaeuft.
                # Beides sind einfache Attribute ohne USB-Zugriff - an dieser
                # Stelle haengt der Transport moeglicherweise gerade.
                'mower_rpm': int(getattr(self.odrive_mower, 'commanded_rpm', 0) or 0),
                'mower_running': bool(self.mower_state),
                'auto_resume_count': int(self._auto_resume_count),
                'timestamp': time.time(),
                'active_index': active_index,
                'source_segment_index': source_index,
                'current_segment': current_segment,
                'pose': pose,
                'summary': self._active_plan_summary,
            }
            path = self._resume_path(map_name)
            if path is None:
                return
            temp_path = path.with_name(f'.{path.name}.tmp')
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temp_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
                temp_path.replace(path)
            except Exception as exc:
                self.logger.warning('Resume-State konnte nicht gespeichert werden: %s', exc)
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_resume_state(self, map_name):
        path = self._resume_path(map_name)
        if path is None or not path.exists():
            return None
        with self._resume_lock:
            try:
                return json.loads(path.read_text(encoding='utf-8'))
            except Exception as exc:
                self.logger.warning('Resume-State konnte nicht gelesen werden: %s', exc)
                return None

    def _delete_resume_state(self, map_name):
        path = self._resume_path(map_name)
        with self._resume_lock:
            if path and path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass

    def _resume_segments_from_state(self, resume):
        segments = list(resume.get('executable_segments') or [])
        active_index = max(0, int(resume.get('active_index') or 0))
        remaining = segments[active_index:]
        if not remaining:
            return segments
        pose = resume.get('pose') or {}
        remaining[0] = self._trim_segment_from_pose(dict(remaining[0]), pose)
        return remaining

    def _trim_segment_from_pose(self, segment, pose):
        coords = segment.get('coordinates') or []
        if segment.get('mode') != 'track' or len(coords) < 2:
            return segment
        parsed = self._pose_lonlat(pose)
        if parsed is None:
            return segment
        current = [parsed[0], parsed[1]]
        best_index = self._nearest_polyline_segment(coords, current)
        if best_index is None:
            return segment
        segment['coordinates'] = [current] + coords[best_index + 1:]
        if len(segment['coordinates']) < 2:
            segment['coordinates'] = coords
        return segment

    @staticmethod
    def _pose_lonlat(pose):
        if not isinstance(pose, dict):
            return None
        gps = pose.get('gps') if isinstance(pose.get('gps'), dict) else {}
        lat = pose.get('latitude', pose.get('lat', gps.get('lat', gps.get('latitude'))))
        lon = pose.get('longitude', pose.get('lon', pose.get('lng', gps.get('lon', gps.get('lng', gps.get('longitude'))))))
        try:
            return float(lon), float(lat)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _nearest_polyline_segment(coords, point):
        best = None
        px, py = point
        for index in range(len(coords) - 1):
            ax, ay = coords[index]
            bx, by = coords[index + 1]
            dx = bx - ax
            dy = by - ay
            denom = dx * dx + dy * dy
            if denom <= 1e-18:
                t = 0.0
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denom))
            qx = ax + dx * t
            qy = ay + dy * t
            dist = (px - qx) ** 2 + (py - qy) ** 2
            candidate = (dist, index)
            if best is None or candidate < best:
                best = candidate
        return None if best is None else best[1]

    def _socket_session_authenticated(self) -> bool:
        """Prueft, ob der WebSocket-Handshake zu einer angemeldeten Sitzung gehoert."""
        if not self.auth or not self.auth.enabled:
            return True
        if not self.auth.configured:
            return False
        if session.get('authenticated'):
            return True
        # Nicht-Browser-Clients koennen sich beim Handshake direkt ausweisen.
        credentials = self.auth.parse_basic_auth(
            request.headers.get('Authorization', '')
        )
        if credentials and self.auth.check_credentials(*credentials):
            return True
        return False

    def _setup_socketio_events(self):
        """Definiert Socket.IO Event-Handler"""
        if not self.socketio:
            return

        @self.socketio.on('connect')
        def handle_connect():
            """Client verbunden.

            Der Handshake laeuft am before_request-Hook vorbei, weil Socket.IO
            ihn auf WSGI-Ebene abfaengt. Ohne diese Pruefung waere der
            WebSocket ein unauthentifizierter Steuerkanal - ``joystick_update``
            faehrt das Fahrzeug.
            """
            if not self._socket_session_authenticated():
                self.logger.warning(
                    "🔒 WebSocket-Verbindung ohne Anmeldung abgewiesen (%s)",
                    request.remote_addr,
                )
                return False

            self.logger.info("🔌 WebSocket Client verbunden")
            with self._status_lock:
                self._status_clients += 1
            # Der neue Client kennt noch keinen Stand und bekommt deshalb den
            # vollen - aber nur er, nicht alle.
            self._emit_full_status(to=request.sid)
            return None

        @self.socketio.on('disconnect')
        def handle_disconnect():
            """Client getrennt"""
            self.logger.info("🔌 WebSocket Client getrennt")
            with self._status_lock:
                self._status_clients = max(0, self._status_clients - 1)
            # Joystick deaktivieren bei Disconnect
            self.joystick.disable()

        @self.socketio.on('request_status_full')
        def handle_request_status_full():
            """Der Browser hat eine Differenz verpasst und holt den vollen Stand."""
            if not self._socket_session_authenticated():
                return
            self._emit_full_status(to=request.sid)

        @self.socketio.on('joystick_update')
        def handle_joystick_update(data):
            """Joystick-Position Update.

            Die Antwort auf jeden Stossbefehl war frueher eine PWM-Sendung an
            alle Clients - bei 50 Eingaben je Sekunde ein zweiter Datenstrom
            neben dem Status. Die PWM-Werte stehen ohnehin im Status, der
            waehrend der Fahrt im schnellen Takt laeuft.
            """
            x = data.get('x', 0.0)
            y = data.get('y', 0.0)
            self.joystick.update(x, y)

        @self.socketio.on('joystick_release')
        def handle_joystick_release():
            """Joystick losgelassen"""
            self.joystick.disable()

        @self.socketio.on('max_speed_update')
        def handle_max_speed_update(data):
            """Max Speed Update"""
            max_speed = data.get('max_speed', 100)
            self.joystick.set_max_speed(max_speed)
            self.logger.info(f"Max Speed: {max_speed}%")

    def _mower_api_status(self, success=True, error=None):
        if self.odrive_mower and self.odrive_mower.enabled:
            status = self.odrive_mower.get_status(success=success, error=error)
            startup_status = status.get('startup_status', {})
            mower_starting = bool(startup_status.get('active'))
            # The internal controller marks itself busy before sequential
            # validation. The UI may say EIN only after every axis has passed
            # validation and the periodic command thread owns the blades.
            commanded = bool(
                status.get('command_running', status['running'])
                and not mower_starting
            )
            # A frozen status is not a running mower. Reporting EIN from values
            # that stopped updating is exactly how a dead deck kept looking
            # healthy while the vehicle carried on mowing nothing.
            stale = bool(status.get('odrive_missing_heartbeats'))
            stalled = bool(status.get('transport_stall'))
            mower_fault = bool(commanded and (stale or stalled))
            verified_running = bool(commanded and not mower_fault)
            return {
                'success': status['success'],
                'mower_mode': f"odrive_{status.get('transport', 'can')}",
                'mower_enabled': status['enabled'],
                'mower_state': verified_running,
                'mower_command_running': verified_running,
                # The toggle inverts this value; it must follow the host command
                # and not the display state, otherwise a fault would turn the
                # AUS button into an EIN button.
                'mower_commanded': commanded,
                'mower_fault': mower_fault,
                'mower_stale': stale,
                'mower_transport_stall': status.get('transport_stall'),
                'mower_command_loop_age_s': status.get('command_loop_age_s'),
                'mower_starting': mower_starting,
                'mower_active_axis_nodes': status.get('active_axis_nodes', []),
                'mower_speed': status['rpm'],
                'mower_rpm': status['rpm'],
                'mower_commanded_rpm': status['commanded_rpm'],
                'mower_min_rpm': status['min_rpm'],
                'mower_max_rpm': status['max_rpm'],
                'mower_default_rpm': status['default_rpm'],
                'mower_ramp_rate_rpm_s': status['ramp_rate_rpm_s'],
                'mower_node_id': status['node_id'],
                'mower_node_ids': status.get('node_ids', [status['node_id']]),
                'mower_axis_state': status['axis_state'],
                'error': status['error'],
                'mower_error': status['error'],
                'odrive_error': status.get('odrive_error', 0),
                'odrive_state': status.get('odrive_state', 0),
                'odrive_errors': status.get('odrive_errors', {}),
                'odrive_states': status.get('odrive_states', {}),
                'odrive_missing_heartbeats': status.get('odrive_missing_heartbeats', []),
                'odrive_heartbeat_ages': status.get('odrive_heartbeat_ages', {}),
                'odrive_currents': status.get('odrive_currents', {}),
                'odrive_sensorless': status.get('odrive_sensorless', {}),
                'mower_startup_status': startup_status,
                'mower_sequential_start_enabled': status.get(
                    'sequential_start_enabled', False
                ),
                'mower_current_monitor_enabled': status.get('current_monitor_enabled', False),
                'mower_current_trip_a': status.get('current_trip_a'),
                'mower_current_trip_duration_s': status.get('current_trip_duration_s'),
            }

        # Ohne ODrive-Mähdeck gibt es keinen zweiten Antriebsweg mehr: der
        # GPIO-PWM-Pfad ist entfallen. Der Status meldet dann schlicht, dass
        # kein Deck konfiguriert ist.
        return {
            'success': success,
            'mower_mode': 'none',
            'mower_enabled': False,
            'mower_state': False,
            'mower_command_running': False,
            'mower_commanded': False,
            'mower_fault': False,
            'mower_stale': False,
            'mower_transport_stall': None,
            'mower_command_loop_age_s': None,
            'mower_starting': False,
            'mower_active_axis_nodes': [],
            'mower_speed': 0,
            'mower_rpm': None,
            'mower_commanded_rpm': None,
            'mower_min_rpm': None,
            'mower_max_rpm': None,
            'mower_default_rpm': None,
            'mower_ramp_rate_rpm_s': None,
            'mower_node_id': None,
            'mower_node_ids': [],
            'mower_axis_state': None,
            'mower_error': error,
            'odrive_error': 0,
            'odrive_state': 0,
            'odrive_errors': {},
            'odrive_states': {},
            'odrive_missing_heartbeats': [],
            'odrive_heartbeat_ages': {},
            'odrive_currents': {},
            'odrive_sensorless': {},
            'mower_startup_status': {},
            'mower_sequential_start_enabled': False,
            'mower_current_monitor_enabled': False,
            'mower_current_trip_a': None,
            'mower_current_trip_duration_s': None,
        }

    def _can_api_status(self):
        """CAN-Interface sowie SensorHub- und ODrive-Erreichbarkeit."""
        expected_nodes = []
        heartbeat_timeout_s = 1.0
        odrive_transport = None
        if self.odrive_mower and self.odrive_mower.enabled:
            expected_nodes = self.odrive_mower.node_ids
            heartbeat_timeout_s = float(self.odrive_mower.config.heartbeat_timeout_s)
            odrive_transport = getattr(self.odrive_mower, 'transport', 'can')
        status = self.can.get_status(
            expected_odrive_node_ids=expected_nodes if odrive_transport == 'can' else [],
            sensor_timeout_s=2.0,
            odrive_timeout_s=heartbeat_timeout_s,
        )
        if odrive_transport == 'usb':
            mower = self.odrive_mower.get_status()
            missing = set(mower.get('odrive_missing_heartbeats', []))
            errors = mower.get('odrive_errors', {})
            states = mower.get('odrive_states', {})
            ages = mower.get('odrive_heartbeat_ages', {})
            currents = mower.get('odrive_currents', {})
            nodes = {}
            for node_id in expected_nodes:
                node_current = currents.get(node_id, currents.get(str(node_id), {}))
                node_error = errors.get(node_id, errors.get(str(node_id)))
                nodes[str(node_id)] = {
                    'online': node_id not in missing,
                    'age_s': ages.get(node_id, ages.get(str(node_id))),
                    'error': node_error,
                    'state': states.get(node_id, states.get(str(node_id))),
                    'iq_setpoint_a': node_current.get('setpoint_a'),
                    'iq_measured_a': node_current.get('measured_a'),
                    'iq_age_s': node_current.get('age_s'),
                }
            error_nodes = [node_id for node_id in expected_nodes if nodes[str(node_id)]['error']]
            online_count = sum(1 for node in nodes.values() if node['online'])
            status['odrives'] = {
                'transport': 'usb',
                'expected_node_ids': list(expected_nodes),
                'online_count': online_count,
                'expected_count': len(expected_nodes),
                'all_online': online_count == len(expected_nodes),
                'error_node_ids': error_nodes,
                'all_healthy': online_count == len(expected_nodes) and not error_nodes,
                'nodes': nodes,
                'usb_boards': mower.get('usb_boards', {}),
            }
            status['network_healthy'] = bool(
                status['sensor_hub']['online'] and status['odrives']['all_healthy']
            )
        return status

    def _build_status_payload(self):
        """Stellt den vollstaendigen Status zusammen, gerundet auf Anzeigemass."""
        status = {
            'can_enabled': self.can_enabled,
            'pwm_enabled': True,
            'monitor_enabled': True,
            'can_status': self._can_api_status(),
            'motor_status': self.motor.get_status(),
            'joystick_status': self.joystick.get_status(),
            'joystick_enabled': self.joystick.get_status().get('enabled', False),
            'sensor_data': self.can.get_sensor_data(),
            'navigation_status': self.navigation.get_status() if self.navigation else {'state': 'disabled'},
            'plan_execution_status': self.get_plan_execution_status(),
            'mapping_status': self.mapping.get_status() if self.mapping else {'state': 'disabled'},
            'safety_status': self.safety.get_status() if self.safety else {},
            'battery_status': (
                self.battery.get_status() if self.battery else {'enabled': False}
            ),
            'network_status': (
                self.network.get_status() if self.network else {'enabled': False}
            ),
            'light_state': self.light_state,
            'light_enabled': self.light_config.enabled if self.light_config else False,
            **self._mower_api_status(),
            'current_pwm': self.motor.get_status().get('current_pwm', {'left': 1500, 'right': 1500}),
            'max_speed_percent': self.joystick.get_status().get('max_speed', 100)
        }
        return status_delta.quantize(status)

    # Ohne Zuhoerer ist jede Sendung reines Datenvolumen. Der Status wird
    # deshalb nur erzeugt, solange mindestens eine Oberflaeche offen ist.
    def _emit_status_update(self):
        """Sendet die Aenderung gegenueber der letzten Sendung an alle Clients."""
        if not self.socketio:
            return

        status = self._build_status_payload()
        with self._status_lock:
            baseline = self._status_baseline
            patch = status_delta.diff(baseline, status)
            if baseline is not None and not patch:
                # Nichts geaendert: Die Verbindung haelt der Socket.IO-Ping
                # offen, dafuer braucht es keine leere Nutzlast.
                return
            self._status_baseline = status
            self._status_seq += 1
            seq = self._status_seq

        if baseline is None:
            # Erster Stand ueberhaupt. Es gibt noch niemanden, der eine
            # Differenz anwenden koennte - der volle Stand geht beim Verbinden
            # gezielt an den einzelnen Client.
            return
        self.socketio.emit('status_delta', {'seq': seq, 'patch': patch})

    def _emit_full_status(self, to=None):
        """Sendet den vollen Stand - beim Verbinden und wenn eine Differenz fehlt.

        Vorher wird der gemeinsame Grundstand aufgefrischt. Ohne das bekaeme
        ein neuer Client den Stand, der beim Abmelden des letzten uebrig blieb,
        und alle anderen wuerden auf einer anderen Nummer weiterrechnen.
        """
        if not self.socketio:
            return

        self._emit_status_update()
        with self._status_lock:
            status = self._status_baseline
            seq = self._status_seq

        self.socketio.emit('status_update', {'seq': seq, 'status': status}, to=to)

    # Anzeigetakt. Steht das Fahrzeug, reicht ein Stand je Sekunde; sobald
    # etwas laeuft, will der Bediener seine Eingabe sofort bestaetigt sehen.
    # Beide Takte senden nur Differenzen, der schnelle kostet daher wenig.
    def _status_interval(self) -> float:
        idle = float(getattr(self.config, 'status_interval_idle_s', 1.0) or 1.0)
        active = float(getattr(self.config, 'status_interval_active_s', 0.25) or 0.25)
        return active if self._vehicle_is_busy() else idle

    def _vehicle_is_busy(self) -> bool:
        """Ist gerade etwas in Bewegung oder gestoert?"""
        try:
            if self.joystick.get_status().get('enabled'):
                return True
            if self._plan_status.get('running'):
                return True
            if self.navigation and self.navigation.get_status().get('running'):
                return True
            if self.mapping and self.mapping.get_status().get('recording'):
                return True
            if self.odrive_mower and self.odrive_mower.enabled:
                mower = self.odrive_mower.get_status()
                if mower.get('running') or mower.get('startup_status', {}).get('active'):
                    return True
            if self.safety:
                safety = self.safety.get_status()
                if safety.get('system_stop_latched') or safety.get('motion_hold_active'):
                    return True
        except Exception:
            # Der Takt ist Kosmetik. Faellt die Ermittlung aus, wird eben
            # langsamer gesendet - der Status selbst bleibt korrekt.
            return False
        return False

    def start(self):
        """Startet Web-Server"""
        if not self.flask_available or not self.app:
            self.logger.error("Flask nicht verfügbar - Web-Server kann nicht gestartet werden")
            return
        
        if self.running:
            self.logger.warning("Web-Server läuft bereits")
            return
        
        self.running = True
        # Nicht warten, bis jemand die Oberflaeche oeffnet: Ein offener
        # Wiederaufsetzpunkt bedeutet, dass die letzte Fahrt abgebrochen ist.
        # Genau das soll die Push-Meldung ja mitteilen.
        self._restore_last_stop_reason()
        self._maybe_auto_resume_after_usb_stall()
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

        # Status-Update-Thread starten (alle 100ms)
        if self.socketio:
            self.status_thread = threading.Thread(target=self._status_update_loop, daemon=True)
            self.status_thread.start()

        self.logger.info(f"✅ Web-Server gestartet auf {self.config.host}:{self.config.port}")
    
    def _status_update_loop(self):
        """Sendet regelmaessig die Statusaenderungen an offene Oberflaechen."""
        import time
        while self.running:
            interval = 1.0
            try:
                interval = self._status_interval()
                if self._status_clients > 0:
                    self._emit_status_update()
            except Exception as e:
                self.logger.error(f"❌ Status-Update Fehler: {e}")
                interval = 1.0
            time.sleep(interval)

    def _run_server(self):
        """Läuft Web-Server"""
        try:
            if self.socketio:
                # Socket.IO Server
                self.socketio.run(
                    self.app,
                    host=self.config.host,
                    port=self.config.port,
                    debug=False,
                    use_reloader=False,
                    allow_unsafe_werkzeug=True
                )
            else:
                # Fallback: Nur Flask
                self.app.run(
                    host=self.config.host,
                    port=self.config.port,
                    debug=False,
                    use_reloader=False
                )
        except Exception as e:
            self.logger.error(f"❌ Web-Server Fehler: {e}")
            self.running = False
    
    def stop(self):
        """Stoppt Web-Server"""
        if not self.running:
            return
        
        self.running = False
        # Flask hat keinen eingebauten Stop-Mechanismus
        # Server läuft als Daemon-Thread und wird automatisch beendet
        self.logger.info("Web-Server gestoppt")
    
    def get_status(self) -> dict:
        """
        Gibt Web-Server-Status zurück
        
        Returns:
            Dictionary mit Status-Informationen
        """
        return {
            'flask_available': self.flask_available,
            'running': self.running,
            'host': self.config.host,
            'port': self.config.port
        }
    
    def cleanup(self):
        """Cleanup Web-Server"""
        self.stop()
        self.logger.info("Web-Server cleanup durchgeführt")
    
    def __del__(self):
        """Destruktor - Cleanup bei Objektzerstörung"""
        self.cleanup()
