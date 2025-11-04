#!/usr/bin/env python3
"""
GPIO Controller - Zentrale GPIO-Verwaltung mit Singleton-Pattern
Verhindert mehrfache GPIO-Initialisierung und verwaltet pigpio-Instanz
"""

import logging
import threading
from typing import Optional

try:
    import RPi.GPIO as GPIO
    import pigpio
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logging.warning("RPi.GPIO oder pigpio nicht verfügbar - GPIO-Funktionen deaktiviert")


class GPIOController:
    """
    Singleton GPIO-Controller für zentrale GPIO-Verwaltung
    Verhindert mehrfache Initialisierung und verwaltet pigpio-Instanz
    """
    
    _instance: Optional['GPIOController'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton-Pattern: Nur eine Instanz erlaubt"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialisiert GPIO-Controller (nur beim ersten Aufruf)"""
        # Verhindert mehrfache Initialisierung
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self.logger = logging.getLogger(__name__)
        self.gpio_available = GPIO_AVAILABLE
        self.gpio_mode_set = False
        self.pigpio_instance: Optional[pigpio.pi] = None
        self.setup_pins = set()  # Tracking bereits konfigurierter Pins
        
        if self.gpio_available:
            self._init_gpio()
            self._init_pigpio()
    
    def _init_gpio(self):
        """Initialisiert RPi.GPIO (nur einmal)"""
        try:
            if not self.gpio_mode_set:
                GPIO.setmode(GPIO.BCM)
                self.gpio_mode_set = True
                self.logger.info("✅ RPi.GPIO initialisiert (BCM-Modus)")
        except Exception as e:
            self.logger.error(f"❌ RPi.GPIO Initialisierung fehlgeschlagen: {e}")
            self.gpio_available = False
    
    def _init_pigpio(self):
        """Initialisiert pigpio-Daemon-Verbindung (Singleton)"""
        try:
            if self.pigpio_instance is None:
                self.pigpio_instance = pigpio.pi()
                
                if not self.pigpio_instance.connected:
                    raise ConnectionError("pigpio daemon nicht erreichbar")
                
                self.logger.info("✅ pigpio-Daemon verbunden")
        except Exception as e:
            self.logger.error(f"❌ pigpio Initialisierung fehlgeschlagen: {e}")
            self.pigpio_instance = None
    
    def get_pigpio(self) -> Optional[pigpio.pi]:
        """Gibt pigpio-Instanz zurück (Singleton)"""
        return self.pigpio_instance
    
    def setup_output(self, pin: int, initial_state: int = GPIO.LOW if GPIO_AVAILABLE else 0):
        """
        Konfiguriert GPIO-Pin als Output
        
        Args:
            pin: GPIO-Pin-Nummer (BCM)
            initial_state: Initialer Zustand (GPIO.LOW oder GPIO.HIGH)
        """
        if not self.gpio_available:
            self.logger.warning(f"GPIO nicht verfügbar - Pin {pin} kann nicht konfiguriert werden")
            return False
        
        try:
            if pin not in self.setup_pins:
                GPIO.setup(pin, GPIO.OUT, initial=initial_state)
                self.setup_pins.add(pin)
                self.logger.debug(f"GPIO{pin} als Output konfiguriert")
            return True
        except Exception as e:
            self.logger.error(f"❌ GPIO{pin} Setup fehlgeschlagen: {e}")
            return False
    
    def setup_input(self, pin: int, pull_up_down: int = GPIO.PUD_OFF if GPIO_AVAILABLE else 0):
        """
        Konfiguriert GPIO-Pin als Input
        
        Args:
            pin: GPIO-Pin-Nummer (BCM)
            pull_up_down: Pull-Up/Down-Konfiguration
        """
        if not self.gpio_available:
            self.logger.warning(f"GPIO nicht verfügbar - Pin {pin} kann nicht konfiguriert werden")
            return False
        
        try:
            if pin not in self.setup_pins:
                GPIO.setup(pin, GPIO.IN, pull_up_down=pull_up_down)
                self.setup_pins.add(pin)
                self.logger.debug(f"GPIO{pin} als Input konfiguriert")
            return True
        except Exception as e:
            self.logger.error(f"❌ GPIO{pin} Setup fehlgeschlagen: {e}")
            return False
    
    def output(self, pin: int, state: bool):
        """
        Setzt GPIO-Output-Pin
        
        Args:
            pin: GPIO-Pin-Nummer (BCM)
            state: True=HIGH, False=LOW
        """
        if not self.gpio_available:
            return False
        
        try:
            GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)
            return True
        except Exception as e:
            self.logger.error(f"❌ GPIO{pin} Output fehlgeschlagen: {e}")
            return False
    
    def input(self, pin: int) -> bool:
        """
        Liest GPIO-Input-Pin
        
        Args:
            pin: GPIO-Pin-Nummer (BCM)
            
        Returns:
            True=HIGH, False=LOW
        """
        if not self.gpio_available:
            return False
        
        try:
            return GPIO.input(pin) == GPIO.HIGH
        except Exception as e:
            self.logger.error(f"❌ GPIO{pin} Input fehlgeschlagen: {e}")
            return False
    
    def add_event_detect(self, pin: int, edge: int, callback=None, bouncetime: int = 200):
        """
        Fügt Event-Detection für GPIO-Pin hinzu
        
        Args:
            pin: GPIO-Pin-Nummer (BCM)
            edge: GPIO.RISING, GPIO.FALLING, GPIO.BOTH
            callback: Callback-Funktion
            bouncetime: Debounce-Zeit in ms
        """
        if not self.gpio_available:
            return False
        
        try:
            GPIO.add_event_detect(pin, edge, callback=callback, bouncetime=bouncetime)
            self.logger.debug(f"Event-Detection für GPIO{pin} hinzugefügt")
            return True
        except Exception as e:
            self.logger.error(f"❌ Event-Detection für GPIO{pin} fehlgeschlagen: {e}")
            return False
    
    def cleanup(self):
        """Cleanup GPIO-Ressourcen"""
        try:
            if self.pigpio_instance:
                self.pigpio_instance.stop()
                self.pigpio_instance = None
                self.logger.info("pigpio-Verbindung geschlossen")
            
            if self.gpio_available and self.gpio_mode_set:
                GPIO.cleanup()
                self.gpio_mode_set = False
                self.setup_pins.clear()
                self.logger.info("GPIO cleanup durchgeführt")
        except Exception as e:
            self.logger.error(f"❌ GPIO cleanup fehlgeschlagen: {e}")
    
    def __del__(self):
        """Destruktor - Cleanup bei Objektzerstörung"""
        self.cleanup()

