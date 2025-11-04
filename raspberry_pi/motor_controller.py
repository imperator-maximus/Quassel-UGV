#!/usr/bin/env python3
"""
Quassel UGV Motor Controller - PWM Output + Web Interface
JSON-basierte CAN-Kommunikation mit Sensor Hub (Pi Zero 2W)

Features:
- Hardware-PWM Motor Control (GPIO 18/19)
- Web Interface mit Joystick-Steuerung
- CAN Bus Kommunikation (JSON-Format)
- Sicherheitsschaltleiste (Emergency Stop)
- Light & Mower Relay Control
"""

import time
import json
import argparse
import signal
import sys
import atexit
import threading
import can
import logging

# Flask/SocketIO imports werden nur bei Bedarf geladen (siehe _init_web_interface)

class MotorController:
    def __init__(self, enable_pwm=False, pwm_pins=[18, 19], enable_monitor=True, quiet=False,
                 enable_ramping=True, acceleration_rate=25, deceleration_rate=800, brake_rate=1500,
                 enable_web=False, web_port=80, safety_pin=17, light_enabled=True, light_pin=22,
                 mower_enabled=True, mower_relay_pin=23, mower_pwm_pin=12, can_interface='can0', can_bitrate=1000000):
        """
        Initialisiert den Motor Controller
        
        Args:
            enable_pwm: Hardware-PWM aktivieren
            pwm_pins: [right_pin, left_pin] für GPIO
            enable_monitor: Monitoring-Ausgabe
            quiet: Keine Ausgabe
            enable_ramping: Sanfte Beschleunigung/Bremsung
            acceleration_rate: Beschleunigungsrate (μs/s)
            deceleration_rate: Verzögerungsrate (μs/s)
            brake_rate: Bremsrate zu Neutral (μs/s)
            enable_web: Web-Interface aktivieren
            web_port: Web-Port (default 80)
            safety_pin: GPIO für Sicherheitsschalter
            light_enabled: Licht-Steuerung aktivieren
            light_pin: GPIO für Licht-Relais
            mower_enabled: Mäher-Steuerung aktivieren
            mower_relay_pin: GPIO für Mäher-Relais
            mower_pwm_pin: GPIO für Mäher-PWM
            can_interface: CAN-Interface (default 'can0')
            can_bitrate: CAN-Bitrate (default 1000000)
        """
        # Konfiguration
        self.enable_pwm = enable_pwm
        self.enable_monitor = enable_monitor
        self.quiet = quiet
        self.pwm_pins = {'left': pwm_pins[1], 'right': pwm_pins[0]}  # Links=GPIO19, Rechts=GPIO18
        
        # Sicherheitsschaltleiste
        self.safety_pin = safety_pin
        self.safety_enabled = True
        self.last_safety_trigger = 0
        
        # Licht-Steuerung
        self.light_enabled = light_enabled
        self.light_pin = light_pin
        self.light_state = False
        
        # Mäher-Steuerung
        self.mower_enabled = mower_enabled
        self.mower_relay_pin = mower_relay_pin
        self.mower_pwm_pin = mower_pwm_pin
        self.mower_state = False
        self.mower_speed = 0
        self.mower_pwm_frequency = 1000
        self.mower_duty_min = 16
        self.mower_duty_max = 84
        self.mower_duty_off = 0
        
        # Web-Interface
        self.enable_web = enable_web
        self.web_port = web_port
        self.can_enabled = True  # CAN Ein/Aus Flag
        self.web_thread = None
        self.flask_app = None
        
        # PWM-Objekte
        self.pwm_objects = {}
        self.last_pwm_values = {'left': 1500, 'right': 1500}
        
        # Ramping
        self.enable_ramping = enable_ramping
        self.acceleration_rate = acceleration_rate
        self.deceleration_rate = deceleration_rate
        self.brake_rate = brake_rate
        self.current_pwm_values = {'left': 1500, 'right': 1500}
        self.target_pwm_values = {'left': 1500, 'right': 1500}
        self.last_ramping_time = time.time()
        
        # Sicherheit
        self.last_command_time = time.time()
        self.command_timeout = 2.0
        
        # Joystick-Steuerung
        self.joystick_enabled = False
        self.joystick_x = 0.0
        self.joystick_y = 0.0
        self.joystick_last_update = 0
        self.joystick_timeout = 1.0
        self.max_speed_percent = 100.0
        
        # CAN-Bus
        self.can_interface = can_interface
        self.can_bitrate = can_bitrate
        self.can_bus = None
        self.can_reader_thread = None
        self.sensor_data = {}  # Letzte Sensor-Daten vom Sensor Hub
        self.can_frame_buffer = {}  # Buffer für Multi-Frame Nachrichten
        
        # Initialisierungen
        if self.enable_pwm:
            self._init_pwm()
        if self.light_enabled:
            self._init_light()
        if self.mower_enabled:
            self._init_mower()
        
        self._init_safety_switch()
        self._init_can_bus()
        
        if self.enable_web:
            self._init_web_interface()
        
        if not self.quiet:
            print("✅ Motor Controller initialisiert")
    
    def _init_pwm(self):
        """Initialisiert Hardware-PWM für Motor-Steuerung"""
        try:
            import RPi.GPIO as GPIO
            import pigpio
            
            self.gpio = GPIO
            self.pi = pigpio.pi()
            
            if not self.pi.connected:
                raise Exception("pigpio daemon nicht erreichbar")
            
            # GPIO-Pins als PWM konfigurieren
            for side, pin in self.pwm_pins.items():
                self.pi.hardware_PWM(pin, 50, 1500 * 1000)  # 50Hz, 1500μs (neutral)
            
            if not self.quiet:
                print(f"✅ Hardware-PWM initialisiert: Links={self.pwm_pins['left']}, Rechts={self.pwm_pins['right']}")
        
        except Exception as e:
            print(f"❌ PWM-Initialisierung Fehler: {e}")
            self.enable_pwm = False
    
    def _init_light(self):
        """Initialisiert Licht-Relais"""
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.light_pin, GPIO.OUT)
            GPIO.output(self.light_pin, GPIO.LOW)
            if not self.quiet:
                print(f"✅ Licht-Relais initialisiert (GPIO{self.light_pin})")
        except Exception as e:
            print(f"❌ Licht-Initialisierung Fehler: {e}")
            self.light_enabled = False
    
    def _init_mower(self):
        """Initialisiert Mäher-Steuerung"""
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.mower_relay_pin, GPIO.OUT)
            GPIO.output(self.mower_relay_pin, GPIO.LOW)
            if not self.quiet:
                print(f"✅ Mäher-Steuerung initialisiert (Relais GPIO{self.mower_relay_pin}, PWM GPIO{self.mower_pwm_pin})")
        except Exception as e:
            print(f"❌ Mäher-Initialisierung Fehler: {e}")
            self.mower_enabled = False
    
    def _init_safety_switch(self):
        """Initialisiert Sicherheitsschalter"""
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.safety_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(self.safety_pin, GPIO.FALLING, callback=self._safety_callback, bouncetime=200)
            if not self.quiet:
                print(f"✅ Sicherheitsschalter initialisiert (GPIO{self.safety_pin})")
        except Exception as e:
            print(f"❌ Sicherheitsschalter-Initialisierung Fehler: {e}")
            self.safety_enabled = False
    
    def _safety_callback(self, channel):
        """Callback für Sicherheitsschalter"""
        current_time = time.time()
        if current_time - self.last_safety_trigger < 0.5:
            return
        
        self.last_safety_trigger = current_time
        if not self.quiet:
            print("🚨 SICHERHEITSSCHALTER AUSGELÖST!")
        
        self.can_enabled = False
        self._emergency_stop()
    
    def _init_can_bus(self):
        """Initialisiert CAN-Bus für JSON-Kommunikation"""
        try:
            self.can_bus = can.interface.Bus(channel=self.can_interface,
                                             interface='socketcan')
                                             # bitrate nicht angeben, da CAN bereits via ip link konfiguriert ist
            
            self.can_reader_thread = threading.Thread(target=self._can_reader_loop, daemon=True)
            self.can_reader_thread.start()
            
            if not self.quiet:
                print(f"✅ CAN-Bus initialisiert ({self.can_interface}, {self.can_bitrate} bps)")
        
        except Exception as e:
            print(f"❌ CAN-Bus Initialisierung Fehler: {e}")
            self.can_bus = None
    
    def _can_reader_loop(self):
        """Liest CAN-Nachrichten und verarbeitet JSON (Multi-Frame Support)"""
        while True:
            try:
                if not self.can_bus:
                    time.sleep(0.1)
                    continue

                msg = self.can_bus.recv(timeout=1.0)
                if msg is None:
                    continue

                # Multi-Frame Nachricht verarbeiten
                if msg.arbitration_id == 0x100:  # Sensor Hub ID
                    json_str = self._process_can_multiframe(msg)
                    if json_str:
                        try:
                            data = json.loads(json_str)
                            self._process_sensor_data(data)
                        except Exception as e:
                            if not self.quiet:
                                print(f"⚠️ JSON-Decode Fehler: {e}")
                else:
                    # Andere CAN-IDs ignorieren oder anders verarbeiten
                    pass

            except Exception as e:
                if not self.quiet:
                    print(f"⚠️ CAN-Reader Fehler: {e}")
                time.sleep(0.1)

    def _process_can_multiframe(self, msg):
        """Verarbeitet Multi-Frame CAN-Nachrichten (6 Bytes Nutzdaten pro Frame)"""
        if len(msg.data) < 2:
            return None

        frame_idx = msg.data[0]
        total_frames = msg.data[1]
        chunk = msg.data[2:8]  # Max 6 Bytes Nutzdaten

        # Ersten Frame: Buffer initialisieren
        if frame_idx == 0:
            self.can_frame_buffer = {
                'total': total_frames,
                'frames': [None] * total_frames,
                'timestamp': time.time()
            }

        # Frame im Buffer speichern
        if 'frames' in self.can_frame_buffer and frame_idx < len(self.can_frame_buffer['frames']):
            self.can_frame_buffer['frames'][frame_idx] = chunk

        # Prüfen ob alle Frames empfangen
        if all(f is not None for f in self.can_frame_buffer.get('frames', [])):
            # Alle Frames zusammensetzen
            full_data = b''.join(self.can_frame_buffer['frames'])
            # Null-Bytes entfernen
            full_data = full_data.rstrip(b'\x00')
            # Buffer leeren
            self.can_frame_buffer = {}
            return full_data.decode('utf-8')

        return None
    
    def _process_sensor_data(self, data):
        """Verarbeitet Sensor-Daten vom Sensor Hub"""
        self.sensor_data = data
        if not self.quiet and self.enable_monitor:
            print(f"📡 Sensor-Daten: {data}")
    
    def _init_web_interface(self):
        """Initialisiert Web-Interface"""
        try:
            from flask import Flask, render_template, jsonify, request
            
            self.flask_app = Flask(__name__, template_folder='templates', static_folder='static')
            self.flask_app.config['SECRET_KEY'] = 'ugv_motor_controller_2024'
            
            self._setup_web_routes()
            
            self.web_thread = threading.Thread(target=self._run_web_server, daemon=True)
            self.web_thread.start()
            
            if not self.quiet:
                print(f"✅ Web-Interface gestartet auf Port {self.web_port}")
        
        except Exception as e:
            print(f"❌ Web-Interface Fehler: {e}")
            self.enable_web = False
    
    def _setup_web_routes(self):
        """Definiert Web-Routen"""
        from flask import render_template, jsonify, request
        
        @self.flask_app.route('/')
        def index():
            return render_template('index.html')
        
        @self.flask_app.route('/api/status')
        def api_status():
            return jsonify({
                'can_enabled': self.can_enabled,
                'pwm_enabled': self.enable_pwm,
                'sensor_data': self.sensor_data,
                'current_pwm': self.current_pwm_values,
                'joystick_enabled': self.joystick_enabled,
                'light_state': self.light_state,
                'mower_state': self.mower_state,
                'mower_speed': self.mower_speed
            })
        
        @self.flask_app.route('/api/can/toggle', methods=['POST'])
        def api_can_toggle():
            self.can_enabled = not self.can_enabled
            if not self.can_enabled:
                self._emergency_stop()
            return jsonify({'can_enabled': self.can_enabled})
        
        @self.flask_app.route('/api/light/toggle', methods=['POST'])
        def api_light_toggle():
            if self.light_enabled:
                self.light_state = not self.light_state
                self._set_light(self.light_state)
            return jsonify({'light_state': self.light_state})
        
        @self.flask_app.route('/api/mower/toggle', methods=['POST'])
        def api_mower_toggle():
            if self.mower_enabled:
                self.mower_state = not self.mower_state
                self._set_mower(self.mower_state)
            return jsonify({'mower_state': self.mower_state})
        
        @self.flask_app.route('/api/mower/speed', methods=['POST'])
        def api_mower_speed():
            data = request.get_json()
            if self.mower_enabled and 'speed' in data:
                self.mower_speed = max(0, min(100, data['speed']))
                self._set_mower_speed(self.mower_speed)
            return jsonify({'mower_speed': self.mower_speed})
        
        @self.flask_app.route('/api/joystick', methods=['POST'])
        def api_joystick():
            if not self.can_enabled:
                data = request.get_json()
                self.joystick_x = data.get('x', 0.0)
                self.joystick_y = data.get('y', 0.0)
                self.joystick_last_update = time.time()
                self.joystick_enabled = True
                self._process_joystick_input(self.joystick_x, self.joystick_y)
            return jsonify({'success': True})

        @self.flask_app.route('/api/sensor/status', methods=['GET'])
        def api_sensor_status():
            self.request_sensor_status()
            return jsonify({'request': 'sent', 'sensor_data': self.sensor_data})

        @self.flask_app.route('/api/sensor/restart', methods=['POST'])
        def api_sensor_restart():
            success = self.restart_sensor_hub()
            return jsonify({'success': success})
    
    def _run_web_server(self):
        """Läuft Web-Server"""
        try:
            self.flask_app.run(host='0.0.0.0', port=self.web_port, debug=False, use_reloader=False)
        except Exception as e:
            print(f"❌ Web-Server Fehler: {e}")
    
    def _emergency_stop(self):
        """Notaus - Motoren auf Neutral"""
        self._set_motor_pwm('left', 1500)
        self._set_motor_pwm('right', 1500)
        self.joystick_enabled = False
        if not self.quiet:
            print("🛑 NOTAUS aktiviert - Motoren neutral")
    
    def _set_motor_pwm(self, side, pwm_value):
        """Setzt Motor-PWM"""
        if not self.enable_pwm or not self.can_bus:
            return
        
        try:
            import pigpio
            pi = pigpio.pi()
            pin = self.pwm_pins[side]
            pi.hardware_PWM(pin, 50, pwm_value * 1000)
            self.current_pwm_values[side] = pwm_value
        except:
            pass
    
    def _set_light(self, state):
        """Setzt Licht-Relais"""
        try:
            import RPi.GPIO as GPIO
            GPIO.output(self.light_pin, GPIO.HIGH if state else GPIO.LOW)
        except:
            pass
    
    def _set_mower(self, state):
        """Setzt Mäher-Relais"""
        try:
            import RPi.GPIO as GPIO
            GPIO.output(self.mower_relay_pin, GPIO.HIGH if state else GPIO.LOW)
        except:
            pass
    
    def _set_mower_speed(self, speed):
        """Setzt Mäher-PWM-Geschwindigkeit"""
        pass  # TODO: PWM-Implementierung
    
    def _process_joystick_input(self, x, y):
        """Verarbeitet Joystick-Input"""
        if not self.enable_pwm or self.can_enabled:
            return

        # Skid Steering: x=Drehung, y=Vorwärts/Rückwärts
        left_pwm = 1500 + (y * 500) - (x * 300)
        right_pwm = 1500 + (y * 500) + (x * 300)

        # Begrenzen auf 1000-2000
        left_pwm = max(1000, min(2000, left_pwm))
        right_pwm = max(1000, min(2000, right_pwm))

        self._set_motor_pwm('left', left_pwm)
        self._set_motor_pwm('right', right_pwm)

    def send_can_command(self, cmd_type, data=None):
        """Sendet JSON-Befehl an Sensor Hub über CAN"""
        if not self.can_bus:
            return False

        try:
            msg_data = {'cmd': cmd_type}
            if data:
                msg_data.update(data)

            json_str = json.dumps(msg_data)
            msg = can.Message(arbitration_id=0x200, data=json_str.encode('utf-8')[:8], is_extended_id=False)
            self.can_bus.send(msg)

            if not self.quiet:
                print(f"📤 CAN-Befehl gesendet: {msg_data}")
            return True
        except Exception as e:
            print(f"❌ CAN-Befehl Fehler: {e}")
            return False

    def request_sensor_status(self):
        """Fordert Sensor-Status vom Sensor Hub an"""
        return self.send_can_command('status_request')

    def restart_sensor_hub(self):
        """Startet Sensor Hub neu"""
        return self.send_can_command('restart')


def main():
    parser = argparse.ArgumentParser(description='Quassel UGV Motor Controller')
    parser.add_argument('--pwm', action='store_true', help='Hardware-PWM aktivieren')
    parser.add_argument('--pins', default='18,19', help='PWM-Pins (right,left)')
    parser.add_argument('--web', action='store_true', help='Web-Interface aktivieren')
    parser.add_argument('--web-port', type=int, default=80, help='Web-Port')
    parser.add_argument('--can', default='can0', help='CAN-Interface')
    parser.add_argument('--bitrate', type=int, default=1000000, help='CAN-Bitrate')
    parser.add_argument('--quiet', action='store_true', help='Keine Ausgabe')
    
    args = parser.parse_args()
    
    pwm_pins = list(map(int, args.pins.split(',')))
    
    controller = MotorController(
        enable_pwm=args.pwm,
        pwm_pins=pwm_pins,
        enable_web=args.web,
        web_port=args.web_port,
        can_interface=args.can,
        can_bitrate=args.bitrate,
        quiet=args.quiet
    )
    
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n🛑 Controller beendet")


if __name__ == "__main__":
    main()

