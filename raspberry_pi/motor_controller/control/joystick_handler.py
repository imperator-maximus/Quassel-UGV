#!/usr/bin/env python3
"""
Joystick Handler - Verarbeitung von Joystick-Eingaben
Verwaltet Joystick-Status und Timeout-Überwachung
"""

import logging
import threading
import time
from typing import Optional, Tuple


class JoystickHandler:
    """
    Joystick-Handler für Web-Interface
    - Joystick-Status-Verwaltung
    - Timeout-Überwachung
    - Thread-Safe Zugriff
    """
    
    def __init__(self, motor_control, safety_monitor, max_speed: float = 100.0):
        """
        Initialisiert Joystick-Handler

        Args:
            motor_control: MotorControl-Instanz
            safety_monitor: SafetyMonitor-Instanz
            max_speed: Startwert der Geschwindigkeitsbegrenzung in Prozent.
                Kommt aus ``web.max_speed_percent``, damit der Schieberegler
                in der Oberflaeche und das Fahrzeug von Anfang an denselben
                Wert meinen.
        """
        self.logger = logging.getLogger(__name__)
        self.motor = motor_control
        self.safety = safety_monitor

        # Joystick-Status
        self.enabled = False
        self.x = 0.0
        self.y = 0.0
        self.last_update = 0
        self.max_speed = max(0.0, min(100.0, float(max_speed)))  # Prozent

        # Thread-Safety
        self._lock = threading.Lock()
    
    def update(self, x: float, y: float):
        """
        Aktualisiert Joystick-Position (Thread-Safe)
        
        Args:
            x: X-Achse (-1.0 bis 1.0)
            y: Y-Achse (-1.0 bis 1.0)
        """
        if hasattr(self.safety, 'is_motion_allowed') and not self.safety.is_motion_allowed():
            self.motor.emergency_stop()
            self.logger.warning("Joystick-Befehl wegen verriegeltem Sicherheitsstopp verworfen")
            return False

        with self._lock:
            self.x = max(-1.0, min(1.0, x))
            self.y = max(-1.0, min(1.0, y))
            self.last_update = time.time()
            self.enabled = True
            # Die Begrenzung wirkt erst hier, auf dem Kommando an den Antrieb.
            # Gespeichert bleibt die rohe Knueppelstellung, damit die Anzeige
            # weiterhin zeigt, wohin der Benutzer gezogen hat.
            factor = self.max_speed / 100.0
            command_x = self.x * factor
            command_y = self.y * factor

        # Safety Monitor aktualisieren
        self.safety.update_joystick_time()

        # Motor-Steuerung aktualisieren (ohne Ramping für direkte Kontrolle)
        self.motor.set_joystick(command_x, command_y, use_ramping=False)

        self.logger.debug(
            f"Joystick: x={self.x:.2f}, y={self.y:.2f} "
            f"-> {command_x:.2f}/{command_y:.2f} bei {self.max_speed:.0f}%"
        )
        return True
    
    def disable(self):
        """Deaktiviert Joystick-Steuerung"""
        with self._lock:
            self.enabled = False
            self.x = 0.0
            self.y = 0.0
        
        # Motoren auf Neutral
        self.motor.emergency_stop()
        self.logger.info("Joystick deaktiviert")
    
    def get_position(self) -> Tuple[float, float]:
        """
        Gibt aktuelle Joystick-Position zurück (Thread-Safe)
        
        Returns:
            Tuple (x, y)
        """
        with self._lock:
            return self.x, self.y
    
    def is_enabled(self) -> bool:
        """
        Prüft ob Joystick aktiviert ist (Thread-Safe)
        
        Returns:
            True wenn aktiviert, False sonst
        """
        with self._lock:
            return self.enabled
    
    def set_max_speed(self, max_speed: float):
        """
        Setzt maximale Geschwindigkeit (Thread-Safe)

        Args:
            max_speed: Maximale Geschwindigkeit in Prozent (0-100)
        """
        with self._lock:
            self.max_speed = max(0.0, min(100.0, max_speed))

        self.logger.info(f"Max Speed: {self.max_speed}%")

    def get_status(self) -> dict:
        """
        Gibt Joystick-Status zurück (Thread-Safe)

        Returns:
            Dictionary mit Status-Informationen
        """
        with self._lock:
            return {
                'enabled': self.enabled,
                'x': self.x,
                'y': self.y,
                'last_update': self.last_update,
                'max_speed': self.max_speed
            }
