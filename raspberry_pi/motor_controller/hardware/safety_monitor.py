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
        self.trigger_emergency_stop()
    
    def set_emergency_stop_callback(self, callback: Callable):
        """
        Setzt Emergency Stop Callback
        
        Args:
            callback: Funktion die bei Emergency Stop aufgerufen wird
        """
        self.emergency_stop_callback = callback
    
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
        if self.watchdog_running:
            self.logger.warning("Watchdog läuft bereits")
            return
        
        self.watchdog_running = True
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
                
                # 100ms Wartezeit
                self._stop_event.wait(0.1)
            
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
                'joystick_timeout': self.config.joystick_timeout
            }
    
    def cleanup(self):
        """Cleanup Safety Monitor"""
        self.stop_watchdog()
        self.logger.info("Safety Monitor cleanup durchgeführt")
    
    def __del__(self):
        """Destruktor - Cleanup bei Objektzerstörung"""
        self.cleanup()

