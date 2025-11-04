#!/usr/bin/env python3
"""
Quassel UGV Motor Controller - Main Entry Point
Modulare Architektur mit separaten Komponenten
"""

import argparse
import logging
import signal
import sys
import time
import yaml
from pathlib import Path

from .config import Config
from .hardware.gpio_controller import GPIOController
from .hardware.pwm_controller import PWMController
from .hardware.safety_monitor import SafetyMonitor
from .communication.can_handler import CANHandler
from .control.motor_control import MotorControl
from .control.joystick_handler import JoystickHandler
from .web.web_server import WebServer


class MotorControllerApp:
    """
    Haupt-Anwendung für Motor Controller
    Orchestriert alle Komponenten
    """
    
    def __init__(self, config: Config):
        """
        Initialisiert Motor Controller App
        
        Args:
            config: Config-Instanz
        """
        self.config = config
        self.logger = self._setup_logging()
        
        # Komponenten
        self.gpio: GPIOController = None
        self.pwm: PWMController = None
        self.safety: SafetyMonitor = None
        self.can: CANHandler = None
        self.motor: MotorControl = None
        self.joystick: JoystickHandler = None
        self.web: WebServer = None
        
        # Shutdown-Flag
        self.running = False
        
        # Signal-Handler registrieren
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _setup_logging(self) -> logging.Logger:
        """
        Konfiguriert Logging
        
        Returns:
            Logger-Instanz
        """
        # Root-Logger konfigurieren
        log_level = getattr(logging, self.config.logging.level.upper(), logging.INFO)
        
        handlers = []
        
        # Console-Handler
        if self.config.logging.console:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(log_level)
            console_handler.setFormatter(logging.Formatter(self.config.logging.format))
            handlers.append(console_handler)
        
        # File-Handler
        if self.config.logging.file_enabled:
            try:
                file_handler = logging.FileHandler(self.config.logging.file)
                file_handler.setLevel(log_level)
                file_handler.setFormatter(logging.Formatter(self.config.logging.format))
                handlers.append(file_handler)
            except Exception as e:
                print(f"⚠️ Logging-Datei konnte nicht erstellt werden: {e}")
        
        # Root-Logger konfigurieren
        logging.basicConfig(
            level=log_level,
            format=self.config.logging.format,
            handlers=handlers
        )
        
        return logging.getLogger(__name__)
    
    def _signal_handler(self, signum, frame):
        """Signal-Handler für SIGINT/SIGTERM"""
        self.logger.info(f"Signal {signum} empfangen - Shutdown wird eingeleitet")
        self.shutdown()
    
    def initialize(self):
        """Initialisiert alle Komponenten"""
        self.logger.info("=" * 60)
        self.logger.info("Quassel UGV Motor Controller v2.0")
        self.logger.info("=" * 60)
        
        try:
            # GPIO-Controller (Singleton)
            self.logger.info("Initialisiere GPIO-Controller...")
            self.gpio = GPIOController()

            # GPIO-Pins für Licht und Mäher-Relais initialisieren
            if self.config.light.enabled:
                self.gpio.setup_output(self.config.light.pin, initial_state=0)  # GPIO.LOW
                self.logger.info(f"✅ Licht-Relais initialisiert (GPIO{self.config.light.pin})")

            if self.config.mower.enabled:
                self.gpio.setup_output(self.config.mower.relay_pin, initial_state=0)  # GPIO.LOW
                self.logger.info(f"✅ Mäher-Relais initialisiert (GPIO{self.config.mower.relay_pin})")

            # PWM-Controller
            self.logger.info("Initialisiere PWM-Controller...")
            self.pwm = PWMController(
                self.config.pwm,
                self.config.mower,
                self.gpio
            )
            
            # Safety-Monitor
            self.logger.info("Initialisiere Safety-Monitor...")
            self.safety = SafetyMonitor(self.config.safety, self.gpio)
            
            # CAN-Handler
            self.logger.info("Initialisiere CAN-Handler...")
            self.can = CANHandler(self.config.can)
            
            # Motor-Control
            self.logger.info("Initialisiere Motor-Control...")
            self.motor = MotorControl(self.pwm, self.config)
            
            # Joystick-Handler
            self.logger.info("Initialisiere Joystick-Handler...")
            self.joystick = JoystickHandler(self.motor, self.safety)
            
            # Web-Server
            if self.config.web.enabled:
                self.logger.info("Initialisiere Web-Server...")
                self.web = WebServer(
                    self.config.web,
                    self.motor,
                    self.joystick,
                    self.can,
                    self.gpio
                )
                # Hardware-Referenzen setzen
                self.web.set_hardware_refs(
                    self.config.light,
                    self.config.mower,
                    self.pwm
                )
            
            # Callbacks verbinden
            self._setup_callbacks()
            
            self.logger.info("=" * 60)
            self.logger.info("✅ Alle Komponenten erfolgreich initialisiert")
            self.logger.info("=" * 60)
        
        except Exception as e:
            self.logger.critical(f"❌ Initialisierung fehlgeschlagen: {e}", exc_info=True)
            raise
    
    def _setup_callbacks(self):
        """Verbindet Callbacks zwischen Komponenten"""
        # Safety Monitor -> Motor Control (Emergency Stop)
        self.safety.set_emergency_stop_callback(self.motor.emergency_stop)
        
        # CAN Handler -> Sensor Data Logging
        if self.config.monitor:
            self.can.set_sensor_data_callback(self._log_sensor_data)
    
    def _log_sensor_data(self, data: dict):
        """Callback für Sensor-Daten-Logging"""
        if not self.config.quiet:
            self.logger.info(f"📡 Sensor-Daten: {data}")
    
    def start(self):
        """Startet alle Komponenten"""
        self.logger.info("Starte Komponenten...")
        
        try:
            # CAN-Reader starten
            if self.can:
                self.can.start_reader()
            
            # Safety-Watchdog starten
            if self.safety:
                self.safety.start_watchdog()
            
            # Web-Server starten
            if self.web:
                self.web.start()
            
            self.running = True
            self.logger.info("✅ Alle Komponenten gestartet")
            self.logger.info("Motor Controller läuft - Drücke Ctrl+C zum Beenden")
        
        except Exception as e:
            self.logger.critical(f"❌ Start fehlgeschlagen: {e}", exc_info=True)
            raise
    
    def run(self):
        """Haupt-Loop"""
        try:
            while self.running:
                time.sleep(0.1)
        
        except KeyboardInterrupt:
            self.logger.info("Keyboard Interrupt empfangen")
        
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Fährt alle Komponenten herunter"""
        if not self.running:
            return
        
        self.running = False
        self.logger.info("=" * 60)
        self.logger.info("Shutdown wird durchgeführt...")
        self.logger.info("=" * 60)
        
        try:
            # Web-Server stoppen
            if self.web:
                self.logger.info("Stoppe Web-Server...")
                self.web.cleanup()
            
            # Safety-Watchdog stoppen
            if self.safety:
                self.logger.info("Stoppe Safety-Watchdog...")
                self.safety.cleanup()
            
            # CAN-Reader stoppen
            if self.can:
                self.logger.info("Stoppe CAN-Reader...")
                self.can.cleanup()
            
            # Motor-Control stoppen
            if self.motor:
                self.logger.info("Stoppe Motor-Control...")
                self.motor.cleanup()
            
            # PWM-Controller cleanup
            if self.pwm:
                self.logger.info("PWM-Controller cleanup...")
                self.pwm.cleanup()
            
            # GPIO-Controller cleanup
            if self.gpio:
                self.logger.info("GPIO-Controller cleanup...")
                self.gpio.cleanup()
            
            self.logger.info("=" * 60)
            self.logger.info("✅ Shutdown abgeschlossen")
            self.logger.info("=" * 60)
        
        except Exception as e:
            self.logger.error(f"❌ Shutdown-Fehler: {e}", exc_info=True)


def main():
    """Main Entry Point"""
    parser = argparse.ArgumentParser(
        description='Quassel UGV Motor Controller v2.0',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--config',
        type=str,
        help='Pfad zur YAML-Konfigurationsdatei'
    )
    
    # Legacy CLI-Argumente (für Rückwärtskompatibilität)
    parser.add_argument('--pwm', action='store_true', help='Hardware-PWM aktivieren')
    parser.add_argument('--pins', default='18,19', help='PWM-Pins (right,left)')
    parser.add_argument('--web', action='store_true', help='Web-Interface aktivieren')
    parser.add_argument('--web-port', type=int, default=80, help='Web-Port')
    parser.add_argument('--can', default='can0', help='CAN-Interface')
    parser.add_argument('--bitrate', type=int, default=1000000, help='CAN-Bitrate')
    parser.add_argument('--quiet', action='store_true', help='Keine Ausgabe')
    
    args = parser.parse_args()
    
    # Konfiguration laden
    if args.config:
        # Aus YAML-Datei laden
        try:
            config = Config.from_yaml(args.config)
            print(f"✅ Konfiguration geladen: {args.config}")
        except Exception as e:
            print(f"❌ Fehler beim Laden der Konfiguration: {e}")
            sys.exit(1)
    else:
        # Default-Konfiguration mit CLI-Overrides
        config = Config.default()
        
        # CLI-Argumente überschreiben Config
        if args.pwm:
            config.pwm.enabled = True
        if args.pins:
            pins = list(map(int, args.pins.split(',')))
            config.pwm.pins = {'right': pins[0], 'left': pins[1]}
        if args.web:
            config.web.enabled = True
        if args.web_port:
            config.web.port = args.web_port
        if args.can:
            config.can.interface = args.can
        if args.bitrate:
            config.can.bitrate = args.bitrate
        if args.quiet:
            config.quiet = True
            config.logging.console = False
    
    # App erstellen und starten
    try:
        app = MotorControllerApp(config)
        app.initialize()
        app.start()
        app.run()
    
    except Exception as e:
        print(f"❌ Kritischer Fehler: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

