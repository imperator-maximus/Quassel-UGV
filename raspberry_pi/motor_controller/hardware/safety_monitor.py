#!/usr/bin/env python3
"""
Safety Monitor - Sicherheitsüberwachung mit Timeout-Watchdog
Überwacht Sicherheitsschalter, Timeouts und Emergency Stop
"""

import logging
import threading
import time
from typing import Callable, Optional

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False


class SafetyMonitor:
    """
    Sicherheitsüberwachung für UGV
    - Sicherheitsschaltleiste (Emergency Stop)
    - Command-Timeout-Überwachung
    - Joystick-Timeout-Überwachung
    """
    
    def __init__(self, config, gpio_controller):
        """
        Initialisiert Safety Monitor
        
        Args:
            config: SafetyConfig-Instanz
            gpio_controller: GPIO-Controller-Instanz
        """
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.gpio = gpio_controller
        
        # Sicherheitsschalter
        self.safety_enabled = config.enabled
        self.last_safety_trigger = 0
        
        # Timeout-Überwachung
        self.last_command_time = time.time()
        self.last_joystick_time = 0
        self.joystick_active = False
        
        # Emergency Stop Callback
        self.emergency_stop_callback: Optional[Callable] = None
        self.system_stop_callback: Optional[Callable] = None
        self.can_health_check: Optional[Callable] = None
        self.system_stop_latched = False
        self.system_stop_reason: Optional[str] = None
        self.system_stop_time: Optional[float] = None
        self._watchdog_started_monotonic = 0.0
        
        # Watchdog-Thread
        self.watchdog_running = False
        self.watchdog_thread: Optional[threading.Thread] = None
        
        # Thread-Safety
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        
        if self.safety_enabled:
            self._init_safety_switch()
    
    def _init_safety_switch(self):
        """Initialisiert Sicherheitsschalter"""
        if not GPIO_AVAILABLE:
            self.logger.warning("RPi.GPIO nicht verfügbar - Sicherheitsschalter deaktiviert")
            self.safety_enabled = False
            return
        
        try:
            success = self.gpio.setup_input(
                self.config.pin,
                GPIO.PUD_UP if GPIO_AVAILABLE else 0
            )
            
            if success:
                self.gpio.add_event_detect(
                    self.config.pin,
                    GPIO.FALLING if GPIO_AVAILABLE else 0,
                    callback=self._safety_callback,
                    bouncetime=int(self.config.debounce_time * 1000)
                )
                self.logger.info(f"✅ Sicherheitsschalter initialisiert (GPIO{self.config.pin})")
            else:
                self.safety_enabled = False
        
        except Exception as e:
            self.logger.error(f"❌ Sicherheitsschalter Initialisierung fehlgeschlagen: {e}")
            self.safety_enabled = False
    
    def _safety_callback(self, channel):
        """Callback für Sicherheitsschalter (mit Debouncing)"""
        current_time = time.time()
        
        with self._lock:
            # Debouncing
            if current_time - self.last_safety_trigger < self.config.debounce_time:
                return
            
            self.last_safety_trigger = current_time
        
        self.logger.warning("🚨 SICHERHEITSSCHALTER AUSGELÖST!")
        self.trigger_system_stop("Sicherheitsschalter ausgeloest")
    
    def set_emergency_stop_callback(self, callback: Callable):
        """
        Setzt Emergency Stop Callback
        
        Args:
            callback: Funktion die bei Emergency Stop aufgerufen wird
        """
        self.emergency_stop_callback = callback

    def set_system_stop_callback(self, callback: Callable):
        """Setzt den Callback fuer einen verriegelten Gesamtsystem-Stopp."""
        self.system_stop_callback = callback

    def set_can_health_check(self, callback: Callable):
        """Setzt eine Funktion, die ``(healthy, reason)`` zurueckgibt."""
        self.can_health_check = callback

    def trigger_system_stop(self, reason: str):
        """Verriegelt die Bewegung und stoppt Fahrantrieb sowie Maehdeck."""
        with self._lock:
            if self.system_stop_latched:
                return
            self.system_stop_latched = True
            self.system_stop_reason = str(reason)
            self.system_stop_time = time.time()

        self.logger.critical("🚨 SYSTEM-SICHERHEITSSTOPP: %s", reason)
        if self.system_stop_callback:
            try:
                self.system_stop_callback(str(reason))
            except Exception as e:
                self.logger.exception("System-Stopp Callback Fehler: %s", e)
        else:
            self.trigger_emergency_stop()

    def is_motion_allowed(self) -> bool:
        """Nur ein nicht verriegeltes System darf Antriebe starten."""
        with self._lock:
            return not self.system_stop_latched

    def reset_system_stop(self) -> tuple[bool, str | None]:
        """Loest die Verriegelung nur bei aktuell gesundem CAN-Netz."""
        if self.can_health_check:
            try:
                healthy, reason = self.can_health_check()
            except Exception as exc:
                return False, f"CAN-Healthcheck fehlgeschlagen: {exc}"
            if not healthy:
                return False, str(reason or "CAN-Netz nicht gesund")

        with self._lock:
            self.system_stop_latched = False
            self.system_stop_reason = None
            self.system_stop_time = None
        self.logger.info("✅ System-Sicherheitsstopp zurueckgesetzt")
        return True, None
    
    def trigger_emergency_stop(self):
        """Löst Emergency Stop aus"""
        if self.emergency_stop_callback:
            try:
                self.emergency_stop_callback()
            except Exception as e:
                self.logger.error(f"❌ Emergency Stop Callback Fehler: {e}")
    
    def update_command_time(self):
        """Aktualisiert letzten Command-Zeitstempel"""
        with self._lock:
            self.last_command_time = time.time()
    
    def update_joystick_time(self):
        """Aktualisiert letzten Joystick-Zeitstempel"""
        with self._lock:
            self.last_joystick_time = time.time()
            self.joystick_active = True
    
    def check_command_timeout(self) -> bool:
        """
        Prüft Command-Timeout
        
        Returns:
            True wenn Timeout überschritten, False sonst
        """
        with self._lock:
            elapsed = time.time() - self.last_command_time
            return elapsed > self.config.command_timeout
    
    def check_joystick_timeout(self) -> bool:
        """
        Prüft Joystick-Timeout
        
        Returns:
            True wenn Timeout überschritten, False sonst
        """
        with self._lock:
            if not self.joystick_active:
                return False
            
            elapsed = time.time() - self.last_joystick_time
            return elapsed > self.config.joystick_timeout
    
    def start_watchdog(self):
        """Startet Watchdog-Thread"""
        can_watchdog_enabled = bool(getattr(self.config, 'can_watchdog_enabled', False))
        if not self.config.enabled and not can_watchdog_enabled:
            self.logger.info("Safety Watchdog deaktiviert")
            return

        if self.watchdog_running:
            self.logger.warning("Watchdog läuft bereits")
            return
        
        self.watchdog_running = True
        self._watchdog_started_monotonic = time.monotonic()
        self._stop_event.clear()
        self.watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self.watchdog_thread.start()
        self.logger.info("✅ Safety Watchdog gestartet")
    
    def stop_watchdog(self):
        """Stoppt Watchdog-Thread"""
        if not self.watchdog_running:
            return
        
        self.watchdog_running = False
        self._stop_event.set()
        
        if self.watchdog_thread:
            self.watchdog_thread.join(timeout=2.0)
        
        self.logger.info("Safety Watchdog gestoppt")
    
    def _watchdog_loop(self):
        """Watchdog-Loop - Überwacht Timeouts"""
        self.logger.info("Watchdog-Loop gestartet")
        
        while not self._stop_event.is_set():
            try:
                # Command-Timeout prüfen
                if self.check_command_timeout():
                    self.logger.warning("⚠️ Command-Timeout überschritten!")
                    self.trigger_emergency_stop()
                    with self._lock:
                        self.last_command_time = time.time()  # Reset
                
                # Joystick-Timeout prüfen
                if self.check_joystick_timeout():
                    self.logger.warning("⚠️ Joystick-Timeout überschritten!")
                    self.trigger_emergency_stop()
                    with self._lock:
                        self.joystick_active = False

                if bool(getattr(self.config, 'can_watchdog_enabled', False)) and self.can_health_check:
                    grace_s = float(getattr(self.config, 'can_watchdog_startup_grace_s', 5.0))
                    if time.monotonic() - self._watchdog_started_monotonic >= grace_s:
                        try:
                            healthy, reason = self.can_health_check()
                        except Exception as exc:
                            healthy, reason = False, f"CAN-Healthcheck fehlgeschlagen: {exc}"
                        if not healthy:
                            self.trigger_system_stop(reason or "CAN-Netz ausgefallen")
                
                # 100ms Wartezeit
                interval_s = float(getattr(self.config, 'can_watchdog_interval_s', 0.1))
                self._stop_event.wait(max(0.02, interval_s))
            
            except Exception as e:
                self.logger.error(f"❌ Watchdog-Loop Fehler: {e}")
                time.sleep(0.1)
        
        self.logger.info("Watchdog-Loop beendet")
    
    def get_status(self) -> dict:
        """
        Gibt aktuellen Safety-Status zurück
        
        Returns:
            Dictionary mit Status-Informationen
        """
        with self._lock:
            return {
                'safety_enabled': self.safety_enabled,
                'watchdog_running': self.watchdog_running,
                'last_command_time': self.last_command_time,
                'last_joystick_time': self.last_joystick_time,
                'joystick_active': self.joystick_active,
                'command_timeout': self.config.command_timeout,
                'joystick_timeout': self.config.joystick_timeout,
                'can_watchdog_enabled': bool(getattr(self.config, 'can_watchdog_enabled', False)),
                'system_stop_latched': self.system_stop_latched,
                'system_stop_reason': self.system_stop_reason,
                'system_stop_time': self.system_stop_time,
                'motion_allowed': not self.system_stop_latched,
            }
    
    def cleanup(self):
        """Cleanup Safety Monitor"""
        self.stop_watchdog()
        self.logger.info("Safety Monitor cleanup durchgeführt")
    
    def __del__(self):
        """Destruktor - Cleanup bei Objektzerstörung"""
        self.cleanup()
