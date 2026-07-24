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

try:
    from flask import Flask, render_template, jsonify, request
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
    
    def __init__(self, config, motor_control, joystick_handler, can_handler, gpio_controller, navigation_controller=None, mapping_recorder=None, safety_monitor=None):
        """
        Initialisiert Web-Server
        
        Args:
            config: WebConfig-Instanz
            motor_control: MotorControl-Instanz
            joystick_handler: JoystickHandler-Instanz
            can_handler: CANHandler-Instanz
            gpio_controller: GPIOController-Instanz
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
        
        # Flask-App
        self.flask_available = FLASK_AVAILABLE
        self.socketio_available = SOCKETIO_AVAILABLE
        self.app: Optional[Flask] = None
        self.socketio: Optional[SocketIO] = None
        self.server_thread: Optional[threading.Thread] = None
        self.running = False
        
        # Zusätzliche Hardware-Referenzen (für Light/Mower)
        self.light_config = None
        self.mower_config = None
        self.pwm_controller = None
        self.odrive_mower = None
        
        # Status
        self.can_enabled = bool(getattr(self.can, 'can_enabled', True))
        self.light_state = False
        self.mower_state = False
        self._plan_lock = threading.Lock()
        self._resume_lock = threading.Lock()
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
        
        if self.flask_available:
            self._init_flask()
    
    def set_hardware_refs(self, light_config, mower_config, pwm_controller, odrive_mower=None):
        """
        Setzt Hardware-Referenzen für Light/Mower-Steuerung
        
        Args:
            light_config: LightConfig-Instanz
            mower_config: MowerConfig-Instanz
            pwm_controller: PWMController-Instanz
        """
        self.light_config = light_config
        self.mower_config = mower_config
        self.pwm_controller = pwm_controller
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

            @self.app.after_request
            def add_cors_headers(response):
                response.headers['Access-Control-Allow-Origin'] = '*'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
                response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,PATCH,DELETE,OPTIONS'
                return response

            # Socket.IO initialisieren
            if self.socketio_available:
                self.socketio = SocketIO(
                    self.app,
                    cors_allowed_origins="*",
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
            return render_template('index.html')
        
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
                'light_state': self.light_state,
                **self._mower_api_status()
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

            if self.mower_config and self.mower_config.enabled:
                self.mower_state = desired_state
                self.gpio.output(self.mower_config.relay_pin, self.mower_state)

                # Wenn ausgeschaltet, PWM auf 0
                if not self.mower_state and self.pwm_controller:
                    self.pwm_controller.stop_mower()

                self.logger.info(f"Mäher {'ein' if self.mower_state else 'aus'}")

            return jsonify(self._mower_api_status())
        
        @self.app.route('/api/mower/speed', methods=['POST'])
        def api_mower_speed():
            """Setzt Mäher-Geschwindigkeit"""
            data = request.get_json(silent=True) or {}

            if self.odrive_mower and self.odrive_mower.enabled:
                rpm = data.get('rpm', data.get('speed', self.odrive_mower.target_rpm))
                status = self.odrive_mower.set_rpm(int(rpm))
                self.mower_state = status['running']
                return jsonify(self._mower_api_status(success=status.get('success', True), error=status.get('error')))

            if self.mower_config and self.mower_config.enabled and 'speed' in data:
                speed = max(0, min(100, int(data['speed'])))

                if self.pwm_controller:
                    self.pwm_controller.set_mower_speed(speed)
                    self.logger.info(f"Mäher-Geschwindigkeit: {speed}%")

            return jsonify(self._mower_api_status())
        
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
                    sub_contour_count=request.args.get('sub_contour_count', 3),
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
            result = self.mapping.check_plan(
                map_name,
                plan=plan,
                start_segment_index=data.get('start_segment_index'),
                start_coordinate=data.get('start_coordinate'),
                start_pose=self.can.get_sensor_data(),
            )
            if not result.get('success'):
                self.logger.warning(
                    "Plan-Check abgelehnt: map=%s start_segment_index=%r "
                    "start_coordinate=%r browser_plan=%s errors=%s warnings=%s error=%s",
                    map_name,
                    data.get('start_segment_index'),
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
            result = self.mapping.check_plan(
                map_name,
                start_segment_index=data.get('start_segment_index'),
                start_coordinate=data.get('start_coordinate'),
                start_pose=self.can.get_sensor_data(),
            )
            if not result.get('success'):
                return jsonify({'success': False, 'error': 'Planprüfung fehlgeschlagen', **result}), 400
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
        source_index = resume.get('source_segment_index')
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

    def pause_plan_execution(self, reason='paused'):
        self._plan_pause_event.set()
        self._save_resume_state(reason=reason)
        with self._plan_lock:
            if self._plan_status.get('running'):
                self._plan_status['state'] = reason
                self._plan_status['running'] = False
        if self.navigation:
            self.navigation.stop(reason=reason)

    def stop_plan_execution(self, clear_resume=False):
        self._plan_stop_event.set()
        self._plan_pause_event.clear()
        with self._plan_lock:
            if self._plan_status.get('running'):
                self._plan_status['state'] = 'stopping'
        if self.navigation:
            self.navigation.stop(reason='plan_stopped')
        if clear_resume and self._active_plan_map_name:
            self._delete_resume_state(self._active_plan_map_name)

    def get_plan_execution_status(self):
        with self._plan_lock:
            status = dict(self._plan_status)
            if isinstance(status.get('current_segment'), dict):
                status['current_segment'] = dict(status['current_segment'])
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
                self.navigation.set_waypoints(waypoints, mode=mode, direction=direction)
                if not self.navigation.start():
                    raise RuntimeError(self.navigation.get_status().get('last_error') or 'Navigation konnte nicht starten')
                if not self._wait_for_navigation_segment(nogo_monitor):
                    return
            if self._active_plan_map_name:
                self._delete_resume_state(self._active_plan_map_name)
            self._set_plan_status(running=False, state='completed', active_index=len(executable_segments), current_segment=None)
        except Exception as exc:
            self.logger.error('Plan-Ausführung fehlgeschlagen: %s', exc)
            if self.navigation:
                self.navigation.stop(reason='plan_error')
            self._set_plan_status(running=False, state='error', last_error=str(exc))

    def _wait_for_navigation_segment(self, nogo_monitor=None):
        while not self._plan_stop_event.is_set():
            if self._plan_pause_event.is_set():
                self._save_resume_state(reason='paused')
                if self.navigation:
                    self.navigation.stop(reason='paused')
                self._set_plan_status(running=False, state='paused')
                return False
            if not self._rtk_available():
                message = 'RTK verloren - Plan-Ausführung gestoppt'
                self._save_resume_state(reason='rtk_lost')
                if self.navigation:
                    self.navigation.stop(reason='rtk_lost')
                self._set_plan_status(running=False, state='rtk_lost', last_error=message)
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
            self._plan_status.update(updates)
            should_save = bool(self._plan_status.get('running'))
        if should_save:
            self._save_resume_state(reason='running')

    def _rtk_available(self):
        if not self.mapping:
            return False
        return self.mapping.plans.pose_rtk_ok(self.can.get_sensor_data())

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

    def _resume_path(self, map_name):
        if not self.mapping:
            return None
        return self.mapping.plans.plans_dir / f"{self.mapping.plans._sanitize_name(map_name)}.resume.json"

    def _save_resume_state(self, reason='running'):
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
            if source_index is None:
                # Positioning/transfer segments have no source index. Resume
                # at the next actual mowing segment and let check_plan create
                # the short positioning leg from the current pose.
                for segment in self._active_executable_segments[active_index:]:
                    if segment.get('source_index') is not None:
                        source_index = segment.get('source_index')
                        break
            payload = {
                'schema': 'raspberrycan.mowing_resume.v2',
                'map_name': map_name,
                'reason': reason,
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

    def _setup_socketio_events(self):
        """Definiert Socket.IO Event-Handler"""
        if not self.socketio:
            return

        @self.socketio.on('connect')
        def handle_connect():
            """Client verbunden"""
            self.logger.info("🔌 WebSocket Client verbunden")
            # Initial Status senden
            self._emit_status_update()

        @self.socketio.on('disconnect')
        def handle_disconnect():
            """Client getrennt"""
            self.logger.info("🔌 WebSocket Client getrennt")
            # Joystick deaktivieren bei Disconnect
            self.joystick.disable()

        @self.socketio.on('joystick_update')
        def handle_joystick_update(data):
            """Joystick-Position Update"""
            x = data.get('x', 0.0)
            y = data.get('y', 0.0)
            self.joystick.update(x, y)
            # PWM-Werte zurücksenden
            self._emit_pwm_update()

        @self.socketio.on('joystick_release')
        def handle_joystick_release():
            """Joystick losgelassen"""
            self.joystick.disable()
            self._emit_pwm_update()

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
            verified_running = bool(
                status.get('command_running', status['running'])
                and not mower_starting
            )
            return {
                'success': status['success'],
                'mower_mode': f"odrive_{status.get('transport', 'can')}",
                'mower_enabled': status['enabled'],
                'mower_state': verified_running,
                'mower_command_running': verified_running,
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

        speed = self.pwm_controller.get_mower_speed() if self.pwm_controller else 0
        return {
            'success': success,
            'mower_mode': 'gpio_pwm',
            'mower_enabled': self.mower_config.enabled if self.mower_config else False,
            'mower_state': self.mower_state,
            'mower_command_running': self.mower_state,
            'mower_starting': False,
            'mower_active_axis_nodes': [],
            'mower_speed': speed,
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

    def _emit_status_update(self):
        """Sendet Status-Update an alle Clients"""
        if not self.socketio:
            return

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
            'light_state': self.light_state,
            'light_enabled': self.light_config.enabled if self.light_config else False,
            **self._mower_api_status(),
            'current_pwm': self.motor.get_status().get('current_pwm', {'left': 1500, 'right': 1500}),
            'max_speed_percent': self.joystick.get_status().get('max_speed', 100)
        }

        self.socketio.emit('status_update', status)

    def _emit_pwm_update(self):
        """Sendet PWM-Update an alle Clients"""
        if not self.socketio:
            return

        motor_status = self.motor.get_status()
        current_pwm = motor_status.get('current_pwm', {'left': 1500, 'right': 1500})

        self.socketio.emit('pwm_update', {
            'left': int(current_pwm['left']),
            'right': int(current_pwm['right'])
        })

    def start(self):
        """Startet Web-Server"""
        if not self.flask_available or not self.app:
            self.logger.error("Flask nicht verfügbar - Web-Server kann nicht gestartet werden")
            return
        
        if self.running:
            self.logger.warning("Web-Server läuft bereits")
            return
        
        self.running = True
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

        # Status-Update-Thread starten (alle 100ms)
        if self.socketio:
            self.status_thread = threading.Thread(target=self._status_update_loop, daemon=True)
            self.status_thread.start()

        self.logger.info(f"✅ Web-Server gestartet auf {self.config.host}:{self.config.port}")
    
    def _status_update_loop(self):
        """Sendet regelmäßig Status-Updates (100ms)"""
        import time
        while self.running:
            try:
                self._emit_status_update()
                time.sleep(0.1)  # 100ms = 10 Hz
            except Exception as e:
                self.logger.error(f"❌ Status-Update Fehler: {e}")
                time.sleep(1.0)

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
