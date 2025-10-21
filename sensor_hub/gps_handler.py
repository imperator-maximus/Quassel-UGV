"""
GPS Handler für Holybro UM982 RTK-GPS
Liest NMEA-Daten und extrahiert Position, Heading und RTK-Status
"""

import serial
import threading
import time
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class GPSHandler:
    """Verwaltet GPS-Kommunikation und Datenverarbeitung"""
    
    def __init__(self, port: str, baudrate: int, timeout: float = 5.0):
        """
        Initialisiert GPS Handler
        
        Args:
            port: UART Port (z.B. '/dev/serial0')
            baudrate: Baud Rate (230400 für UM982)
            timeout: Timeout für GPS-Daten
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_port = None
        self.running = False
        self.reader_thread = None
        
        # GPS-Daten
        self.latitude = 0.0
        self.longitude = 0.0
        self.altitude = 0.0
        self.heading = 0.0
        self.rtk_status = "NO GPS"  # NO GPS, GPS FIX, RTK FLOAT, RTK FIXED
        self.satellites = 0
        self.last_update = 0.0
        self.last_update_time = None
        
        # Thread-Sicherheit
        self.lock = threading.Lock()
    
    def connect(self) -> bool:
        """Verbindet mit GPS-Gerät"""
        try:
            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1.0
            )
            logger.info(f"✅ GPS verbunden: {self.port} @ {self.baudrate} baud")
            self.running = True
            self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.reader_thread.start()
            return True
        except Exception as e:
            logger.error(f"❌ GPS Verbindungsfehler: {e}")
            return False
    
    def disconnect(self):
        """Trennt GPS-Verbindung"""
        self.running = False
        if self.reader_thread:
            self.reader_thread.join(timeout=2.0)
        if self.serial_port:
            self.serial_port.close()
        logger.info("GPS getrennt")
    
    def _read_loop(self):
        """Liest kontinuierlich NMEA-Daten"""
        while self.running:
            try:
                if self.serial_port and self.serial_port.in_waiting:
                    line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        self._parse_nmea(line)
            except Exception as e:
                logger.warning(f"GPS Read-Fehler: {e}")
                time.sleep(0.1)
    
    def _parse_nmea(self, sentence: str):
        """Parst NMEA-Sätze"""
        try:
            if not sentence.startswith('$'):
                return
            
            parts = sentence.split(',')
            if len(parts) < 2:
                return
            
            msg_type = parts[0][1:6]  # z.B. "GPRMC", "GPGGA"
            
            # GGA: Position, Höhe, GPS-Status
            if msg_type == 'GPGGA' or msg_type == 'GNGGA':
                self._parse_gga(parts)
            
            # RMC: Position, Heading, Datum
            elif msg_type == 'GPRMC' or msg_type == 'GNRMC':
                self._parse_rmc(parts)
            
            # GSA: DOP und Satelliten-Info
            elif msg_type == 'GPGSA' or msg_type == 'GNGSA':
                self._parse_gsa(parts)
            
            # RTK-Status (UM982 spezifisch)
            elif msg_type == 'GPHDT':  # Heading True
                self._parse_hdt(parts)
        
        except Exception as e:
            logger.debug(f"NMEA Parse-Fehler: {e}")
    
    def _parse_gga(self, parts: list):
        """Parst GGA-Satz (Position, Höhe, Fix-Qualität)"""
        try:
            with self.lock:
                # Fix Quality: 0=invalid, 1=GPS, 2=DGPS, 4=RTK Fixed, 5=RTK Float
                fix_quality = int(parts[6]) if len(parts) > 6 else 0
                
                if fix_quality == 0:
                    self.rtk_status = "NO GPS"
                elif fix_quality == 1:
                    self.rtk_status = "GPS FIX"
                elif fix_quality == 2:
                    self.rtk_status = "DGPS"
                elif fix_quality == 4:
                    self.rtk_status = "RTK FIXED"
                elif fix_quality == 5:
                    self.rtk_status = "RTK FLOAT"
                
                # Latitude
                if len(parts) > 2 and parts[2]:
                    lat = float(parts[2][:2]) + float(parts[2][2:]) / 60.0
                    if parts[3] == 'S':
                        lat = -lat
                    self.latitude = lat
                
                # Longitude
                if len(parts) > 4 and parts[4]:
                    lon = float(parts[4][:3]) + float(parts[4][3:]) / 60.0
                    if parts[5] == 'W':
                        lon = -lon
                    self.longitude = lon
                
                # Altitude
                if len(parts) > 9 and parts[9]:
                    self.altitude = float(parts[9])
                
                # Satellites
                if len(parts) > 7 and parts[7]:
                    self.satellites = int(parts[7])
                
                self.last_update = time.time()
                self.last_update_time = datetime.now()
        
        except Exception as e:
            logger.debug(f"GGA Parse-Fehler: {e}")
    
    def _parse_rmc(self, parts: list):
        """Parst RMC-Satz (Position, Heading, Datum)"""
        try:
            with self.lock:
                # Status: A=aktiv, V=ungültig
                if len(parts) > 2 and parts[2] == 'A':
                    # Latitude
                    if len(parts) > 3 and parts[3]:
                        lat = float(parts[3][:2]) + float(parts[3][2:]) / 60.0
                        if parts[4] == 'S':
                            lat = -lat
                        self.latitude = lat
                    
                    # Longitude
                    if len(parts) > 5 and parts[5]:
                        lon = float(parts[5][:3]) + float(parts[5][3:]) / 60.0
                        if parts[6] == 'W':
                            lon = -lon
                        self.longitude = lon
                    
                    # Heading (True Course)
                    if len(parts) > 8 and parts[8]:
                        self.heading = float(parts[8])
                    
                    self.last_update = time.time()
                    self.last_update_time = datetime.now()
        
        except Exception as e:
            logger.debug(f"RMC Parse-Fehler: {e}")
    
    def _parse_gsa(self, parts: list):
        """Parst GSA-Satz (Satelliten-Info)"""
        try:
            # Satelliten-Anzahl aus aktiven Satelliten
            if len(parts) > 15:
                active_sats = sum(1 for i in range(3, 15) if parts[i])
                if active_sats > 0:
                    self.satellites = active_sats
        except Exception as e:
            logger.debug(f"GSA Parse-Fehler: {e}")
    
    def _parse_hdt(self, parts: list):
        """Parst HDT-Satz (Heading True)"""
        try:
            if len(parts) > 1 and parts[1]:
                self.heading = float(parts[1])
        except Exception as e:
            logger.debug(f"HDT Parse-Fehler: {e}")
    
    def get_status(self) -> Dict:
        """Gibt aktuellen GPS-Status zurück"""
        with self.lock:
            return {
                'latitude': self.latitude,
                'longitude': self.longitude,
                'altitude': self.altitude,
                'heading': self.heading,
                'rtk_status': self.rtk_status,
                'satellites': self.satellites,
                'last_update': self.last_update,
                'last_update_time': self.last_update_time.isoformat() if self.last_update_time else None,
                'is_connected': self.running
            }
    
    def get_coordinates(self) -> Tuple[float, float]:
        """Gibt Latitude, Longitude zurück"""
        with self.lock:
            return (self.latitude, self.longitude)
    
    def get_bing_maps_url(self) -> str:
        """Generiert Bing Maps URL für aktuelle Position"""
        with self.lock:
            if self.latitude == 0.0 and self.longitude == 0.0:
                return "https://www.bing.com/maps"
            return f"https://www.bing.com/maps?cp={self.latitude}~{self.longitude}&lvl=18"

