#!/usr/bin/env python3
"""
Sensor Fusion Engine
Verantwortlich für:
- Komplementärfilter zur Berechnung von Roll/Pitch
- Gyro-Integration für Yaw
- GPS-Heading-Fusion zur Korrektur von Yaw-Drift (mit korrekter Winkel-Arithmetik)
- Korrekte Projektion der Gyro-Raten (Tilt-Kompensation)
"""

import time
import math
import threading
import logging
from typing import Dict, Optional

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
        self.gps_heading_weight = 0.05  # 5% GPS-Gewichtung pro Update
        
        self.lock = threading.Lock()
        
        logger.info("✅ Sensor Fusion Engine initialisiert")

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
            # 1. Roll/Pitch aus Accelerometer berechnen (in Grad)
            # Diese Werte sind nur im Ruhezustand/bei konstanter Geschw. zuverlässig
            accel_roll = math.atan2(accel['y'], accel['z']) * (180.0 / math.pi)
            accel_pitch = math.atan2(-accel['x'], 
                                   math.sqrt(accel['y']**2 + accel['z']**2)) * (180.0 / math.pi)

            # 2. Gyro-Integration (in Grad)
            # Dies ist die Integration der *rohen* Gyro-Raten
            gyro_roll = self.roll + gyro['x'] * self.dt
            gyro_pitch = self.pitch + gyro['y'] * self.dt

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
            yaw_rate = gyro['y'] * math.sin(roll_rad) + \
                       gyro['z'] * math.cos(roll_rad) * math.cos(pitch_rad)
            
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
                'heading': self.yaw
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

