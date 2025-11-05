#!/usr/bin/env python3
"""
Sensor Fusion Engine
Verantwortlich für:
- Komplementärfilter zur Berechnung von Roll/Pitch
- Gyro-Integration für Yaw
- GPS-Heading-Fusion zur Korrektur von Yaw-Drift (mit korrekter Winkel-Arithmetik)
- Korrekte Projektion der Gyro-Raten (Tilt-Kompensation)
- Bewegungserkennung (Motion Detection) für ZUPT und adaptive GPS-Fusion
"""

import time
import math
import threading
import logging
from typing import Dict, Optional
from collections import deque

logger = logging.getLogger(__name__)

class SensorFusion:
    """
    Sensor Fusion Engine für IMU + GPS
    Berechnet Roll/Pitch/Yaw aus IMU-Rohdaten und fusioniert mit GPS-Heading
    """
    
    def __init__(self, sample_rate: int = 200):
        self.sample_rate = sample_rate
        self.dt = 1.0 / sample_rate

        # Orientierung (Roll/Pitch/Yaw in Grad)
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0

        # Komplementärfilter Parameter
        self.alpha = 0.98  # 98% Gyro, 2% Accel

        # GPS Heading Fusion
        self.gps_heading_weight = 0.05  # 5% GPS-Gewichtung pro Update (wird dynamisch angepasst)
        self.gps_heading_weight_stationary = 0.3  # 30% im Stillstand (schnellere Korrektur)
        self.gps_heading_weight_moving = 0.02  # 2% in Bewegung (Gyro dominiert)

        # Bewegungserkennung (Motion Detection)
        self.motion_threshold_gyro = 0.5  # °/s - Schwellwert für Stillstand
        self.motion_threshold_accel = 0.3  # m/s² - Schwellwert für Stillstand (X/Y)
        self.motion_window_size = int(0.5 * sample_rate)  # 0.5 Sekunden Fenster
        self.motion_history = deque(maxlen=self.motion_window_size)
        self.is_stationary = False

        # ZUPT (Zero-Velocity Update) für Gyro-Bias-Korrektur
        self.zupt_enabled = True
        self.zupt_learning_rate = 0.001  # Langsame Anpassung des Gyro-Bias
        self.gyro_bias = {'x': 0.0, 'y': 0.0, 'z': 0.0}

        self.lock = threading.Lock()

        logger.info("✅ Sensor Fusion Engine initialisiert (mit Motion Detection + ZUPT)")

    def _detect_motion(self, accel: Dict[str, float], gyro: Dict[str, float]) -> bool:
        """
        Erkennt, ob das Fahrzeug stillsteht oder sich bewegt.

        Kriterien für Stillstand:
        - Alle Gyro-Achsen < motion_threshold_gyro (0.5 °/s)
        - Accel X/Y < motion_threshold_accel (0.3 m/s²)
        - Bedingung muss für motion_window_size Samples erfüllt sein (~0.5s)

        Returns:
            True wenn Fahrzeug stillsteht, False wenn in Bewegung
        """
        # Prüfe ob alle Bewegungskriterien unter Schwellwert liegen
        gyro_still = (abs(gyro['x']) < self.motion_threshold_gyro and
                     abs(gyro['y']) < self.motion_threshold_gyro and
                     abs(gyro['z']) < self.motion_threshold_gyro)

        accel_still = (abs(accel['x']) < self.motion_threshold_accel and
                      abs(accel['y']) < self.motion_threshold_accel)

        is_still = gyro_still and accel_still

        # Füge zu Historie hinzu
        self.motion_history.append(is_still)

        # Stillstand nur wenn ALLE Samples im Fenster "still" sind
        return len(self.motion_history) == self.motion_window_size and all(self.motion_history)

    def _apply_zupt(self, gyro: Dict[str, float]):
        """
        Zero-Velocity Update (ZUPT): Korrigiert Gyro-Bias im Stillstand.

        Wenn das Fahrzeug stillsteht, müssen alle Gyro-Raten Null sein.
        Jede Abweichung ist Drift/Bias, den wir langsam korrigieren können.

        Args:
            gyro: Aktuelle Gyro-Messwerte in °/s
        """
        if not self.zupt_enabled or not self.is_stationary:
            return

        # Im Stillstand: Gyro-Messwerte sind reiner Bias
        # Passe Bias langsam an (exponentieller gleitender Durchschnitt)
        self.gyro_bias['x'] += self.zupt_learning_rate * gyro['x']
        self.gyro_bias['y'] += self.zupt_learning_rate * gyro['y']
        self.gyro_bias['z'] += self.zupt_learning_rate * gyro['z']

    def update(self, accel: Dict[str, float], gyro: Dict[str, float], gps_heading: Optional[float] = None):
        """
        Führt einen Fusions-Schritt aus.
        Wird typischerweise mit 200Hz von der IMU getriggert.

        Args:
            accel: Beschleunigung in m/s² {'x', 'y', 'z'}
            gyro: Drehrate in °/s {'x', 'y', 'z'}
            gps_heading: Optional GPS Heading in Grad (0-360°)
        """
        with self.lock:
            # 0. Bewegungserkennung
            self.is_stationary = self._detect_motion(accel, gyro)

            # ZUPT: Korrigiere Gyro-Bias im Stillstand
            self._apply_zupt(gyro)

            # Wende Bias-Korrektur auf Gyro-Werte an
            gyro_corrected = {
                'x': gyro['x'] - self.gyro_bias['x'],
                'y': gyro['y'] - self.gyro_bias['y'],
                'z': gyro['z'] - self.gyro_bias['z']
            }

            # Adaptive GPS-Fusion: Passe Gewichtung basierend auf Bewegungszustand an
            if self.is_stationary:
                # Im Stillstand: GPS-Heading ist 100% zuverlässig, nutze es stärker
                self.gps_heading_weight = self.gps_heading_weight_stationary
            else:
                # In Bewegung: Gyro ist schneller und genauer, GPS nur zur Drift-Korrektur
                self.gps_heading_weight = self.gps_heading_weight_moving
            # 1. Roll/Pitch aus Accelerometer berechnen (in Grad)
            # Diese Werte sind nur im Ruhezustand/bei konstanter Geschw. zuverlässig
            accel_roll = math.atan2(accel['y'], accel['z']) * (180.0 / math.pi)
            accel_pitch = math.atan2(-accel['x'],
                                   math.sqrt(accel['y']**2 + accel['z']**2)) * (180.0 / math.pi)

            # 2. Gyro-Integration (in Grad) - mit bias-korrigierten Werten
            gyro_roll = self.roll + gyro_corrected['x'] * self.dt
            gyro_pitch = self.pitch + gyro_corrected['y'] * self.dt

            # 3. Komplementärfilter für Roll & Pitch
            # 98% Gyro (schnell), 2% Accel (stabil)
            self.roll = self.alpha * gyro_roll + (1.0 - self.alpha) * accel_roll
            self.pitch = self.alpha * gyro_pitch + (1.0 - self.alpha) * accel_pitch

            # 4. Yaw-Integration (mit Neigungskompensation)
            # Konvertiere Roll/Pitch in Radian für Trig-Funktionen
            roll_rad = math.radians(self.roll)
            pitch_rad = math.radians(self.pitch)

            # Projiziere die 3D-Gyro-Raten auf die Welt-Hochachse, um die *wahre* Gierrate zu erhalten
            # Dies kompensiert die Neigung des Fahrzeugs
            # Formel: yaw_rate = gyro_y * sin(roll) + gyro_z * cos(roll) * cos(pitch)
            yaw_rate = gyro_corrected['y'] * math.sin(roll_rad) + \
                       gyro_corrected['z'] * math.cos(roll_rad) * math.cos(pitch_rad)

            # Integriere die kompensierte Gierrate
            self.yaw = self.yaw + yaw_rate * self.dt

            # 5. GPS Heading Fusion (falls GPS-Daten vorhanden)
            if gps_heading is not None:
                # KORREKTE Winkel-Interpolation (behandelt 359° -> 1°)
                diff = gps_heading - self.yaw
                
                # Finde den kürzesten Weg (Wrap-Around-Problem lösen)
                if diff > 180.0:
                    diff -= 360.0
                elif diff < -180.0:
                    diff += 360.0
                
                # Wende die Korrektur an (z.B. 5% des Fehlers pro Update)
                self.yaw += self.gps_heading_weight * diff

            # 6. Yaw auf 0-360° normalisieren
            self.yaw = self.yaw % 360.0
            if self.yaw < 0:
                self.yaw += 360.0

    def get_orientation(self) -> Dict[str, float]:
        """Gibt die fusionierte Orientierung zurück"""
        with self.lock:
            return {
                'roll': self.roll,
                'pitch': self.pitch,
                'yaw': self.yaw,
                'heading': self.yaw,
                'is_stationary': self.is_stationary,
                'gyro_bias': self.gyro_bias.copy(),
                'gps_weight': self.gps_heading_weight
            }
    
    def set_gps_heading_weight(self, weight: float):
        """
        Setzt die GPS-Heading-Gewichtung (0.0 - 1.0)
        
        Args:
            weight: Gewichtung für GPS-Heading (0.0 = nur IMU, 1.0 = nur GPS)
        """
        with self.lock:
            self.gps_heading_weight = max(0.0, min(1.0, weight))
            logger.info(f"GPS Heading Gewichtung: {self.gps_heading_weight:.2%}")
    
    def reset_yaw(self, yaw: float = 0.0):
        """
        Setzt Yaw auf einen bestimmten Wert (z.B. für Initialisierung mit GPS)

        Args:
            yaw: Neuer Yaw-Wert in Grad (0-360°)
        """
        with self.lock:
            self.yaw = yaw % 360.0
            if self.yaw < 0:
                self.yaw += 360.0
            logger.info(f"Yaw zurückgesetzt auf {self.yaw:.1f}°")

    def set_motion_thresholds(self, gyro_threshold: float = None, accel_threshold: float = None):
        """
        Konfiguriert die Schwellwerte für Bewegungserkennung.

        Args:
            gyro_threshold: Schwellwert für Gyro in °/s (Standard: 0.5)
            accel_threshold: Schwellwert für Accel in m/s² (Standard: 0.3)
        """
        with self.lock:
            if gyro_threshold is not None:
                self.motion_threshold_gyro = gyro_threshold
                logger.info(f"Motion Detection Gyro-Schwellwert: {gyro_threshold} °/s")
            if accel_threshold is not None:
                self.motion_threshold_accel = accel_threshold
                logger.info(f"Motion Detection Accel-Schwellwert: {accel_threshold} m/s²")

    def set_zupt_enabled(self, enabled: bool):
        """
        Aktiviert/Deaktiviert ZUPT (Zero-Velocity Update).

        Args:
            enabled: True um ZUPT zu aktivieren, False zum Deaktivieren
        """
        with self.lock:
            self.zupt_enabled = enabled
            logger.info(f"ZUPT {'aktiviert' if enabled else 'deaktiviert'}")

    def get_motion_status(self) -> Dict[str, any]:
        """
        Gibt den aktuellen Bewegungsstatus zurück.

        Returns:
            Dict mit Bewegungsinformationen
        """
        with self.lock:
            return {
                'is_stationary': self.is_stationary,
                'gyro_bias': self.gyro_bias.copy(),
                'gps_weight': self.gps_heading_weight,
                'zupt_enabled': self.zupt_enabled,
                'motion_threshold_gyro': self.motion_threshold_gyro,
                'motion_threshold_accel': self.motion_threshold_accel
            }

