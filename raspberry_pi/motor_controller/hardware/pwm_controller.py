#!/usr/bin/env python3
"""
PWM Controller - Hardware-PWM-Steuerung für Motoren und Mäher
Verwendet pigpio für präzise Hardware-PWM-Signale
"""

import logging
import threading
from typing import Dict, Optional
from ..config import PWMConfig, MowerConfig


class PWMController:
    """
    PWM-Controller für Motor- und Mäher-Steuerung
    Verwendet pigpio für Hardware-PWM (GPIO 18/19 für Motoren, GPIO 12 für Mäher)
    """
    
    def __init__(self, pwm_config: PWMConfig, mower_config: MowerConfig, gpio_controller):
        """
        Initialisiert PWM-Controller
        
        Args:
            pwm_config: PWM-Konfiguration
            mower_config: Mäher-Konfiguration
            gpio_controller: GPIO-Controller-Instanz (Singleton)
        """
        self.logger = logging.getLogger(__name__)
        self.config = pwm_config
        self.mower_config = mower_config
        self.gpio = gpio_controller
        self.pi = gpio_controller.get_pigpio()
        
        self._lock = threading.Lock()  # Thread-Safety für PWM-Zugriffe
        
        # Motor-PWM-Status
        self.motor_enabled = pwm_config.enabled
        self.current_values: Dict[str, int] = {
            'left': pwm_config.neutral_value,
            'right': pwm_config.neutral_value
        }
        
        # Mäher-PWM-Status
        self.mower_enabled = mower_config.enabled
        self.mower_speed = 0  # 0-100%
        
        if self.motor_enabled:
            self._init_motor_pwm()
        
        if self.mower_enabled:
            self._init_mower_pwm()
    
    def _init_motor_pwm(self):
        """Initialisiert Hardware-PWM für Motoren"""
        if not self.pi:
            self.logger.error("❌ pigpio nicht verfügbar - Motor-PWM deaktiviert")
            self.motor_enabled = False
            return

        try:
            for side, pin in self.config.pins.items():
                # Hardware-PWM: 50Hz, 1500μs (neutral)
                # Duty cycle berechnen: (1500μs / 20000μs) * 1000000 = 75000
                duty_cycle = int((self.config.neutral_value / 20000.0) * 1000000)
                self.pi.hardware_PWM(
                    pin,
                    self.config.frequency,
                    duty_cycle  # 0-1000000 (0-100%)
                )
                self.logger.info(f"✅ Motor-PWM initialisiert: {side.upper()}=GPIO{pin}")

        except Exception as e:
            self.logger.error(f"❌ Motor-PWM Initialisierung fehlgeschlagen: {e}")
            self.motor_enabled = False
    
    def _init_mower_pwm(self):
        """Initialisiert Hardware-PWM für Mäher"""
        if not self.pi:
            self.logger.error("❌ pigpio nicht verfügbar - Mäher-PWM deaktiviert")
            self.mower_enabled = False
            return
        
        try:
            # Hardware-PWM für Mäher: 1000Hz, 0% Duty Cycle (aus)
            self.pi.hardware_PWM(
                self.mower_config.pwm_pin,
                self.mower_config.pwm_frequency,
                0  # 0% Duty Cycle
            )
            self.logger.info(f"✅ Mäher-PWM initialisiert: GPIO{self.mower_config.pwm_pin}")
        
        except Exception as e:
            self.logger.error(f"❌ Mäher-PWM Initialisierung fehlgeschlagen: {e}")
            self.mower_enabled = False
    
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
        
        # Wert begrenzen
        value = max(self.config.min_value, min(self.config.max_value, value))

        try:
            with self._lock:
                pin = self.config.pins[side]
                # Duty cycle berechnen: (value_μs / 20000μs) * 1000000
                duty_cycle = int((value / 20000.0) * 1000000)
                self.pi.hardware_PWM(pin, self.config.frequency, duty_cycle)
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
    
    def set_mower_speed(self, speed: int) -> bool:
        """
        Setzt Mäher-Geschwindigkeit (Thread-Safe)
        
        Args:
            speed: Geschwindigkeit 0-100%
            
        Returns:
            True bei Erfolg, False bei Fehler
        """
        if not self.mower_enabled or not self.pi:
            return False
        
        # Geschwindigkeit begrenzen
        speed = max(0, min(100, speed))
        
        try:
            with self._lock:
                # Duty Cycle berechnen: 0% -> duty_off, 100% -> duty_max
                if speed == 0:
                    duty_cycle = self.mower_config.duty_off
                else:
                    # Linear mapping: 1-100% -> duty_min-duty_max
                    duty_cycle = self.mower_config.duty_min + (
                        (speed / 100.0) * (self.mower_config.duty_max - self.mower_config.duty_min)
                    )
                
                # Duty Cycle in Hardware-PWM-Format konvertieren (0-1000000)
                duty_cycle_hw = int(duty_cycle * 10000)  # % -> 0-1000000
                
                self.pi.hardware_PWM(
                    self.mower_config.pwm_pin,
                    self.mower_config.pwm_frequency,
                    duty_cycle_hw
                )
                
                self.mower_speed = speed
                self.logger.debug(f"Mäher-Geschwindigkeit: {speed}% (Duty: {duty_cycle:.1f}%)")
            
            return True
        
        except Exception as e:
            self.logger.error(f"❌ Mäher-PWM Fehler: {e}")
            return False
    
    def get_mower_speed(self) -> int:
        """
        Gibt aktuelle Mäher-Geschwindigkeit zurück (Thread-Safe)
        
        Returns:
            Geschwindigkeit 0-100%
        """
        with self._lock:
            return self.mower_speed
    
    def stop_mower(self) -> bool:
        """
        Stoppt Mäher (0% Duty Cycle)
        
        Returns:
            True bei Erfolg, False bei Fehler
        """
        return self.set_mower_speed(0)
    
    def cleanup(self):
        """Cleanup PWM-Ressourcen"""
        try:
            if self.motor_enabled and self.pi:
                self.set_motor_neutral()
                self.logger.info("Motoren auf Neutral gesetzt")
            
            if self.mower_enabled and self.pi:
                self.stop_mower()
                self.logger.info("Mäher gestoppt")
        
        except Exception as e:
            self.logger.error(f"❌ PWM cleanup fehlgeschlagen: {e}")
    
    def __del__(self):
        """Destruktor - Cleanup bei Objektzerstörung"""
        self.cleanup()

