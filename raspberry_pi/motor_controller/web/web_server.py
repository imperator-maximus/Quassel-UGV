#!/usr/bin/env python3
"""
Web Server - Flask-basiertes Web-Interface mit Socket.IO
REST API + WebSocket für UGV-Steuerung
"""

import logging
import threading
from typing import Optional

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
    
    def __init__(self, config, motor_control, joystick_handler, can_handler, gpio_controller):
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
        
        # Status
        self.can_enabled = True
        self.light_state = False
        self.mower_state = False
        
        if self.flask_available:
            self._init_flask()
    
    def set_hardware_refs(self, light_config, mower_config, pwm_controller):
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
    
    def _init_flask(self):
        """Initialisiert Flask-App mit Socket.IO"""
        try:
            self.app = Flask(
                __name__,
                template_folder=self.config.template_folder,
                static_folder=self.config.static_folder
            )
            self.app.config['SECRET_KEY'] = self.config.secret_key

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
                'can_status': self.can.get_status(),
                'motor_status': self.motor.get_status(),
                'joystick_status': self.joystick.get_status(),
                'sensor_data': self.can.get_sensor_data(),
                'light_state': self.light_state,
                'mower_state': self.mower_state,
                'mower_speed': self.pwm_controller.get_mower_speed() if self.pwm_controller else 0
            })
        
        @self.app.route('/api/can/toggle', methods=['POST'])
        def api_can_toggle():
            """Schaltet CAN Ein/Aus"""
            self.can_enabled = not self.can_enabled
            
            if not self.can_enabled:
                self.motor.emergency_stop()
                self.joystick.disable()
            
            self.logger.info(f"CAN {'aktiviert' if self.can_enabled else 'deaktiviert'}")
            return jsonify({'can_enabled': self.can_enabled})
        
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
            """Schaltet Mäher Ein/Aus"""
            if self.mower_config and self.mower_config.enabled:
                self.mower_state = not self.mower_state
                self.gpio.output(self.mower_config.relay_pin, self.mower_state)

                # Wenn ausgeschaltet, PWM auf 0
                if not self.mower_state and self.pwm_controller:
                    self.pwm_controller.stop_mower()

                self.logger.info(f"Mäher {'ein' if self.mower_state else 'aus'}")

            return jsonify({'success': True, 'mower_state': self.mower_state})
        
        @self.app.route('/api/mower/speed', methods=['POST'])
        def api_mower_speed():
            """Setzt Mäher-Geschwindigkeit"""
            data = request.get_json()

            if self.mower_config and self.mower_config.enabled and 'speed' in data:
                speed = max(0, min(100, int(data['speed'])))

                if self.pwm_controller:
                    self.pwm_controller.set_mower_speed(speed)
                    self.logger.info(f"Mäher-Geschwindigkeit: {speed}%")

            return jsonify({
                'success': True,
                'mower_speed': self.pwm_controller.get_mower_speed() if self.pwm_controller else 0
            })
        
        @self.app.route('/api/joystick', methods=['POST'])
        def api_joystick():
            """Verarbeitet Joystick-Input"""
            if not self.can_enabled:
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
            if not self.can_enabled:
                x = data.get('x', 0.0)
                y = data.get('y', 0.0)
                self.joystick.update(x, y)
                # PWM-Werte zurücksenden
                self._emit_pwm_update()

        @self.socketio.on('joystick_release')
        def handle_joystick_release():
            """Joystick losgelassen"""
            if not self.can_enabled:
                self.joystick.disable()
                self._emit_pwm_update()

        @self.socketio.on('max_speed_update')
        def handle_max_speed_update(data):
            """Max Speed Update"""
            max_speed = data.get('max_speed', 100)
            self.joystick.set_max_speed(max_speed)
            self.logger.info(f"Max Speed: {max_speed}%")

    def _emit_status_update(self):
        """Sendet Status-Update an alle Clients"""
        if not self.socketio:
            return

        status = {
            'can_enabled': self.can_enabled,
            'pwm_enabled': True,
            'monitor_enabled': True,
            'can_status': self.can.get_status(),
            'motor_status': self.motor.get_status(),
            'joystick_status': self.joystick.get_status(),
            'joystick_enabled': self.joystick.get_status().get('enabled', False),
            'sensor_data': self.can.get_sensor_data(),
            'light_state': self.light_state,
            'light_enabled': self.light_config.enabled if self.light_config else False,
            'mower_state': self.mower_state,
            'mower_enabled': self.mower_config.enabled if self.mower_config else False,
            'mower_speed': self.pwm_controller.get_mower_speed() if self.pwm_controller else 0,
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

