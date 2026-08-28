#!/usr/bin/env python3
"""
PWM Controller - Servosignal fuer die Fahrmotoren

Erzeugt wird es von pigpio als Soft-PWM (`set_servo_pulsewidth`) statt wie
zuvor ueber die beiden Hardware-PWM-Kanaele des Pi. Der Grund ist die
Pinbindung: Hardware-PWM gibt es nur auf GPIO 12/13/18/19, und genau diese
Pins werden anderweitig gebraucht. pigpio erzeugt die Pulse per DMA - der
Jitter liegt im einstelligen Mikrosekundenbereich und damit weit unter dem,
was eine Endstufe an einem 1000-2000-us-Puls aufloest. (Der Soft-PWM aus
RPi.GPIO waere etwas anderes: ein Python-Thread, der unter Last um
Millisekunden verrutscht.)

Nach aussen aendert sich nichts - die Schnittstelle bleibt der Wert in
Mikrosekunden.

Das Maehdeck laeuft ueber die ODrives (siehe hardware/odrive_mower.py) und
nicht mehr ueber GPIO-PWM.
"""

import logging
import threading
from typing import Dict, Optional
from ..config import PWMConfig


class PWMController:
    """
    PWM-Controller fuer die Fahrmotoren

    Verwendet pigpio-Soft-PWM; der Pin kommt aus der Konfiguration und ist
    nicht mehr auf die Hardware-PWM-Kanaele beschraenkt.
    """

    # Grenzen, die pigpio fuer `set_servo_pulsewidth` zulaesst. Ein Wert
    # ausserhalb davon wird nicht etwa begrenzt, sondern als Fehler
    # abgewiesen - und ein abgewiesener Puls heisst: Der Motor laeuft mit
    # dem alten Wert weiter.
    PIGPIO_MIN_US = 500
    PIGPIO_MAX_US = 2500

    def __init__(self, pwm_config: PWMConfig, gpio_controller):
        """
        Initialisiert PWM-Controller
        
        Args:
            pwm_config: PWM-Konfiguration
            gpio_controller: GPIO-Controller-Instanz (Singleton)
        """
        self.logger = logging.getLogger(__name__)
        self.config = pwm_config
        self.gpio = gpio_controller
        self.pi = gpio_controller.get_pigpio()
        
        self._lock = threading.Lock()  # Thread-Safety für PWM-Zugriffe
        
        # Motor-PWM-Status
        self.motor_enabled = pwm_config.enabled
        self.current_values: Dict[str, int] = {
            'left': pwm_config.neutral_value,
            'right': pwm_config.neutral_value
        }

        if self.motor_enabled:
            self._init_motor_pwm()
    
    def _init_motor_pwm(self):
        """Legt beide Ausgaenge auf Neutral"""
        if not self.pi:
            self.logger.error("❌ pigpio nicht verfügbar - Motor-PWM deaktiviert")
            self.motor_enabled = False
            return

        # pigpio erzeugt Servopulse fest im 20-ms-Raster. Eine abweichende
        # Frequenz in der Konfiguration wuerde also stillschweigend ignoriert
        # - lieber einmal laut sagen als spaeter raten.
        if int(self.config.frequency) != 50:
            self.logger.warning(
                "PWM-Frequenz %s Hz aus der Konfiguration wird nicht verwendet: "
                "pigpio sendet Servopulse fest mit 50 Hz",
                self.config.frequency,
            )

        try:
            for side, pin in self.config.pins.items():
                self.pi.set_servo_pulsewidth(pin, self._pulse(self.config.neutral_value))
                self.logger.info(f"✅ Motor-PWM initialisiert: {side.upper()}=GPIO{pin}")

        except Exception as e:
            self.logger.error(f"❌ Motor-PWM Initialisierung fehlgeschlagen: {e}")
            self.motor_enabled = False

    def _pulse(self, value: int) -> int:
        """Begrenzt den Wert auf das, was Konfiguration und pigpio hergeben."""
        value = max(self.config.min_value, min(self.config.max_value, value))
        return int(max(self.PIGPIO_MIN_US, min(self.PIGPIO_MAX_US, value)))
    
    def set_motor_pwm(self, side: str, value: int) -> bool:
        """
        Setzt Motor-PWM-Wert (Thread-Safe)
        
        Args:
            side: 'left' oder 'right'
            value: PWM-Wert in μs (1000-2000)
            
        Returns:
            True bei Erfolg, False bei Fehler
        """
        if not self.motor_enabled or not self.pi:
            return False
        
        if side not in self.config.pins:
            self.logger.error(f"❌ Ungültige Motor-Seite: {side}")
            return False
        
        value = self._pulse(value)

        try:
            with self._lock:
                pin = self.config.pins[side]
                self.pi.set_servo_pulsewidth(pin, value)
                self.current_values[side] = value
            return True
        
        except Exception as e:
            self.logger.error(f"❌ Motor-PWM Fehler ({side}): {e}")
            return False
    
    def set_motor_pwm_both(self, left: int, right: int) -> bool:
        """
        Setzt beide Motor-PWM-Werte gleichzeitig (Thread-Safe)
        
        Args:
            left: PWM-Wert links in μs (1000-2000)
            right: PWM-Wert rechts in μs (1000-2000)
            
        Returns:
            True bei Erfolg, False bei Fehler
        """
        success = True
        success &= self.set_motor_pwm('left', left)
        success &= self.set_motor_pwm('right', right)
        return success
    
    def set_motor_neutral(self) -> bool:
        """
        Setzt beide Motoren auf Neutral (1500μs)
        
        Returns:
            True bei Erfolg, False bei Fehler
        """
        return self.set_motor_pwm_both(
            self.config.neutral_value,
            self.config.neutral_value
        )
    
    def get_motor_pwm(self, side: str) -> int:
        """
        Gibt aktuellen Motor-PWM-Wert zurück (Thread-Safe)
        
        Args:
            side: 'left' oder 'right'
            
        Returns:
            PWM-Wert in μs
        """
        with self._lock:
            return self.current_values.get(side, self.config.neutral_value)
    
    def get_motor_pwm_both(self) -> Dict[str, int]:
        """
        Gibt beide Motor-PWM-Werte zurück (Thread-Safe)
        
        Returns:
            Dictionary mit 'left' und 'right' PWM-Werten
        """
        with self._lock:
            return self.current_values.copy()
    
    def cleanup(self):
        """Cleanup PWM-Ressourcen"""
        try:
            if self.motor_enabled and self.pi:
                self.set_motor_neutral()
                self.logger.info("Motoren auf Neutral gesetzt")

        except Exception as e:
            self.logger.error(f"❌ PWM cleanup fehlgeschlagen: {e}")
    
    def __del__(self):
        """Destruktor - Cleanup bei Objektzerstörung"""
        self.cleanup()

