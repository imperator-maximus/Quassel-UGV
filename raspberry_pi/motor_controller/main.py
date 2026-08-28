#!/usr/bin/env python3
"""
Quassel UGV Motor Controller - Main Entry Point
Modulare Architektur mit separaten Komponenten
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time
import yaml
from pathlib import Path

from .config import Config
from .hardware.gpio_controller import GPIOController
from .hardware.pwm_controller import PWMController
from .hardware.odrive_usb_mower import ODriveUSBMowerController
from .hardware.safety_monitor import SafetyMonitor
from .hardware.battery_monitor import BatteryMonitor
from .communication.network_monitor import NetworkMonitor
from .communication.push_notifier import PushNotifier
from .sensors.local_pose_source import LocalPoseSource
from .sensors.pose_cache import PoseCache
from .control.motor_control import MotorControl
from .control.joystick_handler import JoystickHandler
from .navigation.navigation_controller import NavigationController
from .mapping import MappingRecorder
from .web.web_server import WebServer


class MotorControllerApp:
    """
    Haupt-Anwendung für Motor Controller
    Orchestriert alle Komponenten
    """

    # Wartezeit auf den Maehdeck-Notstopp, bevor der Safety-Watchdog ihn
    # aufgibt und ohne ihn weiterarbeitet.
    MOWER_STOP_JOIN_TIMEOUT_S = 2.0

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
        self.pose_cache: PoseCache = None
        self.local_pose: LocalPoseSource = None
        self.odrive_mower: ODriveMowerController = None
        self.battery: BatteryMonitor = None
        self.network: NetworkMonitor = None
        self.motor: MotorControl = None
        self.joystick: JoystickHandler = None
        self.navigation: NavigationController = None
        self.mapping: MappingRecorder = None
        self.web: WebServer = None
        self.notifier: PushNotifier = None
        self._sensor_pause_resume_mode = None
        self._sensor_recovery_started_monotonic = None
        
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

            # GPIO-Pin für Licht initialisieren
            if self.config.light.enabled:
                self.gpio.setup_output(self.config.light.pin, initial_state=0)  # GPIO.LOW
                self.logger.info(f"✅ Licht-Relais initialisiert (GPIO{self.config.light.pin})")

            # PWM-Controller
            self.logger.info("Initialisiere PWM-Controller...")
            self.pwm = PWMController(
                self.config.pwm,
                self.gpio
            )
            
            # Push-Meldungen. Muss vor dem Safety-Monitor stehen, damit dessen
            # allererster Stopp bereits gemeldet werden kann.
            self.notifier = PushNotifier(self.config.notifications)

            # Safety-Monitor
            self.logger.info("Initialisiere Safety-Monitor...")
            self.safety = SafetyMonitor(self.config.safety, self.gpio)
            self.safety.set_notifier(self.notifier)
            
            # Pose-Zwischenspeicher. Er haelt nur die letzte Pose und ihr
            # Alter; wer sie fuellt, steht darunter.
            self.pose_cache = PoseCache()

            self.logger.info("Initialisiere lokale GNSS-Pose...")
            self.local_pose = LocalPoseSource(
                self.config.pose,
                self._on_local_sensor_data,
            )
            self.pose_cache.set_source_status_callback(self.local_pose.get_status)

            if self.config.odrive_mower.enabled:
                self.logger.info("Initialisiere ODrive-Maehdeck ueber USB...")
                self.odrive_mower = ODriveUSBMowerController(
                    self.config.odrive_mower,
                    self.safety,
                )

            # Batterieueberwachung
            self.battery = BatteryMonitor(self.config.battery, self.logger)

            # Netzueberwachung: zeigt an, in welchem WLAN das Fahrzeug haengt
            self.network = NetworkMonitor(self.config.network, self.logger)

            # Motor-Control
            self.logger.info("Initialisiere Motor-Control...")
            self.motor = MotorControl(self.pwm, self.config)
            
            # Joystick-Handler
            self.logger.info("Initialisiere Joystick-Handler...")
            self.joystick = JoystickHandler(
                self.motor,
                self.safety,
                max_speed=float(getattr(self.config.web, 'max_speed_percent', 100.0)),
            )

            # Navigation
            if self.config.navigation.enabled:
                # Der zentrale Pose-Watchdog muss zuerst pausieren koennen.
                # Sonst beendet der Watchdog der Navigation den Plan, bevor
                # die automatische Wiederaufnahme greift.
                pause_timeout = float(self.config.pose.pause_timeout_s)
                minimum_nav_timeout = pause_timeout + 1.0
                if float(self.config.navigation.watchdog_timeout_s) < minimum_nav_timeout:
                    self.logger.warning(
                        "Navigation-Watchdog %.1fs ist kuerzer als die "
                        "Pausenkette der Pose; verwende %.1fs",
                        self.config.navigation.watchdog_timeout_s,
                        minimum_nav_timeout,
                    )
                    self.config.navigation.watchdog_timeout_s = minimum_nav_timeout
                self.logger.info("Initialisiere Navigation...")
                self.navigation = NavigationController(
                    self.motor,
                    self.config.navigation,
                    safety_monitor=self.safety
                )

            # Drive-around Mapping
            if self.config.mapping.enabled:
                self.logger.info("Initialisiere Mapping...")
                self.mapping = MappingRecorder(
                    self.config.mapping.maps_dir,
                    self.pose_cache.get_sensor_data,
                    min_point_distance_m=self.config.mapping.min_point_distance_m
                )
            
            # Web-Server
            if self.config.web.enabled:
                self.logger.info("Initialisiere Web-Server...")
                self.web = WebServer(
                    self.config.web,
                    self.motor,
                    self.joystick,
                    self.pose_cache,
                    self.gpio,
                    self.navigation,
                    self.mapping,
                    self.safety,
                    notifier=self.notifier,
                    battery=self.battery,
                    network=self.network,
                )
                # Hardware-Referenzen setzen
                self.web.set_hardware_refs(
                    self.config.light,
                    self.odrive_mower
                )
                # Der Netzwaechter darf nicht mitten in eine Planfahrt
                # umschalten: Der Wechsel kappt die Verbindung fuer Sekunden,
                # und ueber sie kommt die Pose.
                if self.network:
                    self.network.set_busy_probe(
                        lambda: bool(
                            self.web.get_plan_execution_status().get('running')
                        )
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
        self.safety.set_system_stop_callback(self._system_safety_stop)
        self.safety.set_link_health_check(self._link_health_check)
        self.safety.set_motion_hold_check(self._sensor_motion_health_check)
        self.safety.set_motion_hold_callback(self._sensor_motion_pause)
        self.safety.set_motion_resume_callback(self._sensor_motion_resume)

        # Pose -> Logging + Navigation
        self.pose_cache.set_pose_callback(self._on_sensor_data)

        # Ein Maehdeckfehler muss das ganze Fahrzeug anhalten, nicht nur die
        # Messer - sonst faehrt der Plan mit stehendem Deck weiter.
        if self.odrive_mower:
            self.odrive_mower.set_system_stop_callback(self.safety.trigger_system_stop)

    def _on_sensor_data(self, data: dict):
        """Verteilt eingehende Pose auf Logging und Navigation."""
        if self.config.monitor and not self.config.quiet:
            # 5 Hz telemetry at INFO filled journald and made targeted fault
            # analysis unnecessarily expensive. It remains available when the
            # service is deliberately run with DEBUG logging.
            self.logger.debug(f"📡 Sensor-Daten: {data}")
        if self.navigation:
            self.navigation.on_pose_update(data)

    def _on_local_sensor_data(self, data: dict):
        """Speist die Pose des GNSS-Empfaengers in den Zwischenspeicher.

        Die Quelle meldet sich nur mit frischen Daten. Bleibt sie stumm,
        altert die Pose dort von selbst - dieselbe Kette, die frueher einen
        ausgefallenen SensorHub aufgefangen hat.
        """
        if self.pose_cache:
            self.pose_cache.inject_sensor_data(data)

    def _link_health_check(self) -> tuple[bool, str | None]:
        """Prueft Pose und Maehdeck - alles, was sicherer Betrieb braucht."""
        pose = self.pose_cache.get_status(
            pose_timeout_s=float(self.config.pose.telemetry_timeout_s)
        )
        # Die Pose ist nur waehrend einer aktiven Fahrt sicherheitsrelevant.
        # Beim Boot im Stillstand darf ein Empfaenger, der noch keinen Fix
        # hat, keinen permanenten Safety-Latch erzeugen, der spaeter sogar
        # manuelles Rangieren blockiert.
        if self._sensor_required_for_motion() and not pose['online']:
            return False, "GNSS-Pose-Timeout"
        # In IDLE the ODrives are not needed for propulsion, and mower start-up
        # validates every axis itself. Once the blades run, a stalled transport,
        # a stale status, an ODrive error, an axis that left closed loop and a
        # blade that stopped turning are all system-critical. ``runtime_health``
        # reads only stored values, so the very transport fault it looks for
        # cannot park this watchdog as well.
        if self.odrive_mower:
            mower_healthy, mower_reason = self.odrive_mower.runtime_health()
            if not mower_healthy:
                return False, mower_reason or "Maehdeck nicht betriebsbereit"
        return True, None

    def _sensor_motion_health_check(self) -> tuple[bool, str | None]:
        """Fordert bei kurzer Pose-Luecke nur eine Fahrpause an."""
        if not self._sensor_required_for_motion():
            self._sensor_recovery_started_monotonic = None
            return True, None
        pose = self.pose_cache.get_status(
            pose_timeout_s=float(self.config.pose.pause_timeout_s)
        )
        if not pose['online']:
            self._sensor_recovery_started_monotonic = None
            return False, "GNSS-Pose kurzzeitig unterbrochen"
        if self._sensor_pause_resume_mode:
            now = time.monotonic()
            if self._sensor_recovery_started_monotonic is None:
                self._sensor_recovery_started_monotonic = now
            stable_s = max(
                0.0,
                float(getattr(self.config.pose, 'resume_stable_s', 2.0)),
            )
            elapsed = now - self._sensor_recovery_started_monotonic
            if elapsed < stable_s:
                return False, (
                    f"GNSS-Pose stabilisiert sich "
                    f"({elapsed:.1f}/{stable_s:.1f} s)"
                )
        return True, None

    def _sensor_required_for_motion(self) -> bool:
        """True bei manueller/automatischer Fahrt oder laufender Sensorpause."""
        plan_running = bool(
            self.web and self.web.get_plan_execution_status().get('running')
        )
        navigation_running = bool(
            self.navigation and self.navigation.get_status().get('running')
        )
        # Manuelles Rangieren verwendet keine Pose. Es besitzt mit dem
        # Joystick-Timeout einen eigenen Dead-Man-Watchdog und darf nicht von
        # kurzen Empfangsluecken gestoppt werden.
        return bool(
            plan_running
            or navigation_running
            or self._sensor_pause_resume_mode
        )

    def _sensor_motion_pause(self, reason: str):
        """Pausiert nur Fahrzeug und Route; das Maehdeck darf weiterlaufen."""
        self.logger.warning("⏸️ Fahrzeug wird pausiert: %s", reason)
        plan_running = bool(
            self.web and self.web.get_plan_execution_status().get('running')
        )
        navigation_running = bool(
            self.navigation and self.navigation.get_status().get('running')
        )
        if plan_running:
            self._sensor_pause_resume_mode = 'plan'
        elif navigation_running:
            self._sensor_pause_resume_mode = 'navigation'
        else:
            self._sensor_pause_resume_mode = None

        # A short telemetry gap must not rebuild the plan from disk. Freeze
        # the live navigation object so waypoint index and track progress stay
        # byte-for-byte unchanged until telemetry is stable again.
        if self.navigation and navigation_running:
            self.navigation.pause(reason='sensor_pause')
        if self.joystick:
            self.joystick.disable()
        elif self.motor:
            self.motor.emergency_stop()

    def _sensor_motion_resume(self):
        """Setzt eine wegen kurzer Sensorluecke pausierte autonome Fahrt fort."""
        resume_mode = self._sensor_pause_resume_mode
        self._sensor_pause_resume_mode = None
        self._sensor_recovery_started_monotonic = None
        if not resume_mode or not self.safety.is_motion_allowed():
            return

        if resume_mode in ('plan', 'navigation') and self.navigation:
            if self.navigation.resume():
                self.logger.info(
                    "▶️ %s nach SensorHub-Pause exakt fortgesetzt",
                    'Mähplan' if resume_mode == 'plan' else 'Navigation',
                )
            else:
                self.logger.error("In-Memory-Fahrfortsetzung fehlgeschlagen")

    def _system_safety_stop(self, reason: str):
        """Stoppt Navigation, Fahrantrieb und alle Maehmotoren."""
        self.logger.critical("🛑 Gesamtsystem wird gestoppt: %s", reason)
        if self.web:
            try:
                # Der Klartext entscheidet spaeter, ob automatisch
                # fortgesetzt werden darf - 'safety_stop' allein sagt
                # nicht, ob ein USB-Haenger oder etwas Ernstes dahinter
                # steckt.
                self.web.pause_plan_execution(
                    reason='safety_stop', detail=reason
                )
            except Exception as exc:
                self.logger.error("Plan-Stopp fehlgeschlagen: %s", exc)
        if self.navigation:
            self.navigation.stop(reason='safety_stop')
        if self.joystick:
            self.joystick.disable()
        elif self.motor:
            self.motor.emergency_stop()
        if self.odrive_mower:
            self._stop_mower_without_blocking(reason)

    def _stop_mower_without_blocking(self, reason: str):
        """Stoppt die Messer, ohne den Safety-Watchdog mitzureissen.

        Der Notstopp spricht denselben Transport an, der den Ausfall ausgeloest
        haben kann. Blockiert er, darf er nicht den Thread festhalten, der
        anschliessend Joystick- und Kommando-Timeouts ueberwachen muss. Die
        Messer sind in diesem Fall bereits durch den ODrive-Hardware-Watchdog
        entwaffnet, weil die Kommandos ausbleiben.
        """
        stopper = threading.Thread(
            target=self._run_mower_emergency_stop,
            args=(reason,),
            name='mower-emergency-stop',
            daemon=True,
        )
        stopper.start()
        stopper.join(timeout=float(self.MOWER_STOP_JOIN_TIMEOUT_S))
        if stopper.is_alive():
            self.logger.critical(
                "🛑 Maehdeck-Notstopp haengt im Transport; "
                "ODrive-Hardware-Watchdog entwaffnet die Messer"
            )

    def _run_mower_emergency_stop(self, reason: str):
        try:
            self.odrive_mower.emergency_stop(reason)
        except Exception as exc:
            self.logger.exception("Maehdeck-Notstopp fehlgeschlagen: %s", exc)

    def start(self):
        """Startet alle Komponenten"""
        self.logger.info("Starte Komponenten...")
        
        try:
            # Zuerst der Meldeweg: Was beim Start schiefgeht, soll ankommen.
            if self.notifier:
                self.notifier.start()

            if self.local_pose:
                self.local_pose.start()
            if self.odrive_mower:
                self.odrive_mower.start_monitor()
            if self.battery:
                self.battery.start()
            if self.network:
                self.network.start()

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
                hang_reason = self._odrive_usb_hang_reason()
                if hang_reason:
                    # A native Fibre property call can block a Python thread
                    # indefinitely and cannot be cancelled from inside the
                    # process. Stop the vehicle, neutralise propulsion, then
                    # terminate so systemd can tear down Fibre completely. The
                    # independent ODrive watchdog has already disarmed any
                    # blade whose command stream stopped.
                    self.logger.critical("ODrive USB haengt: %s", hang_reason)
                    self._halt_for_transport_hang(hang_reason)
                    os._exit(70)
                time.sleep(0.1)
        
        except KeyboardInterrupt:
            self.logger.info("Keyboard Interrupt empfangen")
        
        finally:
            self.shutdown()

    def _halt_for_transport_hang(self, reason: str):
        """Bringt Fahrzeug und Plan zum Stehen, bevor der Prozess endet.

        Ohne diesen Schritt bliebe der Fahrantrieb auf dem letzten PWM-Wert
        stehen, und der Mähplan haette keinen Wiederaufsetzpunkt.
        """
        # Dieser Weg geht am SafetyMonitor vorbei und meldet deshalb selbst.
        # Ohne das bliebe genau der Fall stumm, der den Prozess beendet: das
        # Fahrzeug steht, die Messer sind aus, und die naechste Nachricht kaeme
        # erst nach dem Neustart (real 08.08., 21:06 und 21:18).
        if self.notifier:
            try:
                self.notifier.fault(
                    'system_stop',
                    'UGV: ODrive-USB hängt',
                    f'{reason} - Dienst wird neu gestartet.',
                )
            except Exception as exc:  # noqa: BLE001 - Melden ist Nebensache
                self.logger.error("Push-Meldung zum Transporthaenger: %s", exc)
        try:
            self._system_safety_stop(f"ODrive USB haengt: {reason}")
        except Exception as exc:
            self.logger.error("Sicherheitsstopp vor Prozessende fehlgeschlagen: %s", exc)
        try:
            if self.motor:
                self.motor.emergency_stop()
        except Exception as exc:
            self.logger.error("Fahrantrieb-Notstopp fehlgeschlagen: %s", exc)
        # Gleich folgt os._exit; ohne diesen Halt ginge genau die Meldung
        # verloren, die den Neustart erklaert.
        if self.notifier:
            self.notifier.flush(timeout_s=3.0)
        time.sleep(0.2)

    def _odrive_usb_hang_reason(self) -> str | None:
        """Meldet einen haengenden USB-Aufruf im Start *und* im Betrieb."""
        return (
            self._odrive_usb_startup_hang_reason()
            or self._odrive_usb_runtime_hang_reason()
        )

    def _odrive_usb_runtime_hang_reason(self) -> str | None:
        mower = self.odrive_mower
        if not mower:
            return None
        return mower.transport_stall_reason()

    def _odrive_usb_startup_hang_reason(self) -> str | None:
        mower = self.odrive_mower
        if not mower:
            return None
        status = mower.get_status()
        startup = status.get('startup_status') or {}
        if not startup.get('active'):
            return None
        started = startup.get('node_started_monotonic') or startup.get('started_monotonic')
        if started is None:
            return None
        timeout_s = max(
            3.0,
            float(getattr(mower.config, 'usb_startup_hang_timeout_s', 8.0)),
        )
        elapsed = time.monotonic() - float(started)
        if elapsed <= timeout_s:
            return None
        phase = startup.get('phase') or 'unbekannt'
        node_id = startup.get('node_id')
        return f"phase={phase} node={node_id} seit {elapsed:.1f}s (Limit {timeout_s:.1f}s)"
    
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

            # Navigation stoppen
            if self.navigation:
                self.logger.info("Stoppe Navigation...")
                self.navigation.shutdown()
            
            # Safety-Watchdog stoppen
            if self.safety:
                self.logger.info("Stoppe Safety-Watchdog...")
                self.safety.cleanup()

            if self.local_pose:
                self.logger.info("Stoppe lokale GNSS-Pose...")
                self.local_pose.stop()

            if self.odrive_mower:
                self.logger.info("Stoppe ODrive-Maehdeck...")
                self.odrive_mower.cleanup()

            if self.battery:
                self.logger.info("Stoppe Batterieueberwachung...")
                self.battery.stop()

            if self.network:
                self.logger.info("Stoppe Netzueberwachung...")
                self.network.stop()
            
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

            # Als Letztes: offene Meldungen sollen den Shutdown ueberleben.
            if self.notifier:
                self.notifier.flush(timeout_s=3.0)
                self.notifier.stop()

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
