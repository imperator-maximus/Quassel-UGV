#!/usr/bin/env python3
"""
Motor Control - Skid Steering Logik und Ramping
Zentrale Motor-Steuerungslogik mit optionalem Ramping
"""

import logging
import threading
import time
from typing import Dict, Tuple


class MotorControl:
    """
    Motor-Steuerung für Skid Steering
    - Skid Steering Berechnung (Vorwärts/Rückwärts + Drehung)
    - Optionales Ramping (sanfte Beschleunigung/Bremsung)
    - Thread-Safe PWM-Verwaltung
    """
    
    def __init__(self, pwm_controller, config):
        """
        Initialisiert Motor Control
        
        Args:
            pwm_controller: PWM-Controller-Instanz
            config: PWMConfig und RampingConfig
        """
        self.logger = logging.getLogger(__name__)
        self.pwm = pwm_controller
        self.pwm_config = config.pwm
        self.ramping_config = config.ramping
        
        # Ramping
        self.ramping_enabled = config.ramping.enabled
        self.current_values: Dict[str, int] = {
            'left': self.pwm_config.neutral_value,
            'right': self.pwm_config.neutral_value
        }
        self.target_values: Dict[str, int] = {
            'left': self.pwm_config.neutral_value,
            'right': self.pwm_config.neutral_value
        }
        
        # Ramping-Thread
        self.ramping_running = False
        self.ramping_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        
        if self.ramping_enabled:
            self.start_ramping()
    
    def calculate_skid_steering(self, x: float, y: float) -> Tuple[int, int]:
        """
        Berechnet Skid Steering PWM-Werte
        
        Args:
            x: Joystick X-Achse (-1.0 bis 1.0, negativ=links, positiv=rechts)
            y: Joystick Y-Achse (-1.0 bis 1.0, negativ=rückwärts, positiv=vorwärts)
            
        Returns:
            Tuple (left_pwm, right_pwm) in μs
        """
        # Skid Steering Formel
        left_pwm = (
            self.pwm_config.neutral_value +
            (y * self.pwm_config.forward_factor) -
            (x * self.pwm_config.turn_factor)
        )
        
        right_pwm = (
            self.pwm_config.neutral_value +
            (y * self.pwm_config.forward_factor) +
            (x * self.pwm_config.turn_factor)
        )
        
        # Begrenzen auf min/max
        left_pwm = max(
            self.pwm_config.min_value,
            min(self.pwm_config.max_value, int(left_pwm))
        )
        right_pwm = max(
            self.pwm_config.min_value,
            min(self.pwm_config.max_value, int(right_pwm))
        )
        
        return left_pwm, right_pwm
    
    def set_motor_direct(self, left: int, right: int):
        """
        Setzt Motor-PWM direkt (ohne Ramping)
        
        Args:
            left: PWM-Wert links in μs
            right: PWM-Wert rechts in μs
        """
        self.pwm.set_motor_pwm_both(left, right)
        
        with self._lock:
            self.current_values['left'] = left
            self.current_values['right'] = right
            self.target_values['left'] = left
            self.target_values['right'] = right
    
    def set_motor_target(self, left: int, right: int):
        """
        Setzt Motor-PWM-Zielwerte (mit Ramping wenn aktiviert)
        
        Args:
            left: Ziel-PWM-Wert links in μs
            right: Ziel-PWM-Wert rechts in μs
        """
        with self._lock:
            self.target_values['left'] = left
            self.target_values['right'] = right
        
        # Wenn Ramping deaktiviert, direkt setzen
        if not self.ramping_enabled:
            self.set_motor_direct(left, right)
    
    def set_joystick(self, x: float, y: float, use_ramping: bool = False):
        """
        Setzt Motor-PWM basierend auf Joystick-Input
        
        Args:
            x: Joystick X-Achse (-1.0 bis 1.0)
            y: Joystick Y-Achse (-1.0 bis 1.0)
            use_ramping: True für Ramping, False für direkte Steuerung
        """
        left_pwm, right_pwm = self.calculate_skid_steering(x, y)
        
        if use_ramping:
            self.set_motor_target(left_pwm, right_pwm)
        else:
            self.set_motor_direct(left_pwm, right_pwm)
    
    def emergency_stop(self):
        """Notaus - Motoren sofort auf Neutral"""
        neutral = self.pwm_config.neutral_value
        self.set_motor_direct(neutral, neutral)
        self.logger.warning("🛑 EMERGENCY STOP - Motoren neutral")
    
    def start_ramping(self):
        """Startet Ramping-Thread"""
        if self.ramping_running:
            self.logger.warning("Ramping läuft bereits")
            return
        
        self.ramping_running = True
        self._stop_event.clear()
        self.ramping_thread = threading.Thread(target=self._ramping_loop, daemon=True)
        self.ramping_thread.start()
        self.logger.info("✅ Ramping gestartet")
    
    def stop_ramping(self):
        """Stoppt Ramping-Thread"""
        if not self.ramping_running:
            return
        
        self.ramping_running = False
        self._stop_event.set()
        
        if self.ramping_thread:
            self.ramping_thread.join(timeout=2.0)
        
        self.logger.info("Ramping gestoppt")
    
    def _ramping_loop(self):
        """Ramping-Loop - Sanfte Beschleunigung/Bremsung"""
        self.logger.info("Ramping-Loop gestartet")
        
        while not self._stop_event.is_set():
            try:
                dt = self.ramping_config.update_interval
                
                with self._lock:
                    for side in ['left', 'right']:
                        current = self.current_values[side]
                        target = self.target_values[side]
                        neutral = self.pwm_config.neutral_value
                        
                        if current == target:
                            continue
                        
                        # Rate bestimmen
                        if target == neutral:
                            # Bremsen zu Neutral
                            rate = self.ramping_config.brake_rate
                        elif abs(target - neutral) > abs(current - neutral):
                            # Beschleunigen
                            rate = self.ramping_config.acceleration_rate
                        else:
                            # Verzögern
                            rate = self.ramping_config.deceleration_rate
                        
                        # Maximale Änderung berechnen
                        max_change = rate * dt
                        
                        # Neue PWM berechnen
                        diff = target - current
                        if abs(diff) <= max_change:
                            new_value = target
                        else:
                            new_value = current + (max_change if diff > 0 else -max_change)
                        
                        self.current_values[side] = int(new_value)
                
                # PWM setzen
                self.pwm.set_motor_pwm_both(
                    self.current_values['left'],
                    self.current_values['right']
                )
                
                # Wartezeit
                self._stop_event.wait(dt)
            
            except Exception as e:
                self.logger.error(f"❌ Ramping-Loop Fehler: {e}")
                time.sleep(0.1)
        
        self.logger.info("Ramping-Loop beendet")
    
    def get_current_values(self) -> Dict[str, int]:
        """
        Gibt aktuelle PWM-Werte zurück (Thread-Safe)
        
        Returns:
            Dictionary mit 'left' und 'right' PWM-Werten
        """
        with self._lock:
            return self.current_values.copy()
    
    def get_target_values(self) -> Dict[str, int]:
        """
        Gibt Ziel-PWM-Werte zurück (Thread-Safe)
        
        Returns:
            Dictionary mit 'left' und 'right' PWM-Werten
        """
        with self._lock:
            return self.target_values.copy()
    
    def get_status(self) -> Dict[str, any]:
        """
        Gibt Motor-Control-Status zurück
        
        Returns:
            Dictionary mit Status-Informationen
        """
        return {
            'ramping_enabled': self.ramping_enabled,
            'ramping_running': self.ramping_running,
            'current_values': self.get_current_values(),
            'target_values': self.get_target_values()
        }
    
    def cleanup(self):
        """Cleanup Motor Control"""
        self.stop_ramping()
        self.emergency_stop()
        self.logger.info("Motor Control cleanup durchgeführt")
    
    def __del__(self):
        """Destruktor - Cleanup bei Objektzerstörung"""
        self.cleanup()

