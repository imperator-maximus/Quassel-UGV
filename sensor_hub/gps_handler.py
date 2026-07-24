"""
GPS Handler für Holybro UM982 RTK-GPS
Liest NMEA-Daten und extrahiert Position, Heading und RTK-Status
Verwendet pynmea2 für robustes NMEA-Parsing mit Checksummen-Validierung
"""

import serial
import threading
import time
import logging
from datetime import datetime
from typing import Dict, Optional
import pynmea2

logger = logging.getLogger(__name__)


def _normalize_heading(angle: float) -> float:
    """Normalisiert Heading auf [0, 360)."""
    return angle % 360.0


class GPSHandler:
    """Verwaltet GPS-Kommunikation und Datenverarbeitung mit pynmea2"""
    
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
        self.last_raw_gga = None  # Letzter roher GGA-Satz für NTRIP
        
        # Thread-Sicherheit
        self.lock = threading.Lock()

    def _update_heading(self, heading: float):
        """Aktualisiert das zuletzt bekannte GPS-Heading."""
        with self.lock:
            self.heading = _normalize_heading(float(heading))

    def _parse_raw_heading_sentence(self, sentence: str) -> bool:
        """Parst Heading aus rohen NMEA-Sätzen, die pynmea2 evtl. nicht kennt.

        Relevant für UM982 insbesondere bei `THS` und talker-spezifischen `..HDT`-Sätzen.
        """
        if not sentence.startswith('$'):
            return False

        try:
            body = sentence[1:].split('*', 1)[0]
            parts = body.split(',')
            sentence_id = parts[0]
            fields = parts[1:]

            if sentence_id.endswith('HDT') and fields and fields[0]:
                self._update_heading(float(fields[0]))
                return True

            if sentence_id.endswith('THS') and len(fields) >= 2 and fields[0]:
                mode = (fields[1] or '').strip().upper()
                if mode in {'A', 'E', 'M', 'S'}:
                    self._update_heading(float(fields[0]))
                    return True

        except (ValueError, IndexError):
            return False

        return False
    
    def connect(self) -> bool:
        """Verbindet mit GPS-Gerät"""
        try:
            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            self.running = True
            self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.reader_thread.start()
            logger.info(f"✅ GPS verbunden: {self.port} @ {self.baudrate} baud")
            return True
        except Exception as e:
            logger.error(f"❌ GPS Verbindungsfehler: {e}")
            return False
    
    def disconnect(self):
        """Trennt GPS-Verbindung"""
        self.running = False
        if self.reader_thread:
            self.reader_thread.join(timeout=2.0)
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        logger.info("GPS getrennt")
    
    def _reader_loop(self):
        """Liest NMEA-Sätze in Schleife"""
        while self.running:
            try:
                serial_port = self.serial_port
                if serial_port is None:
                    time.sleep(0.1)
                    continue

                # readline() blocks until a complete NMEA line arrives or the
                # configured serial timeout expires.  Checking in_waiting in a
                # tight loop used to consume an entire CPU core and starved the
                # SensorHub HTTP telemetry threads.
                line = serial_port.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    self._parse_nmea(line)
            except Exception as e:
                logger.debug(f"GPS Read-Fehler: {e}")
                time.sleep(0.1)
    
    def _parse_nmea(self, sentence: str):
        """Parst NMEA-Sätze mit pynmea2 (robust mit Checksummen-Validierung)"""
        if not sentence.startswith('$'):
            return

        # Vorab rohes Heading parsen, damit auch Sätze ohne pynmea2-Support funktionieren.
        self._parse_raw_heading_sentence(sentence)
        
        try:
            msg = pynmea2.parse(sentence)
            
            # GGA: Position, Höhe, Fix-Qualität
            if isinstance(msg, pynmea2.GGA):
                with self.lock:
                    # Fix Quality: 0=invalid, 1=GPS, 2=DGPS, 4=RTK Fixed, 5=RTK Float
                    fix_quality = msg.gps_qual if msg.gps_qual else 0
                    
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
                    
                    # Position
                    if msg.latitude:
                        self.latitude = msg.latitude
                    if msg.longitude:
                        self.longitude = msg.longitude
                    
                    # Altitude
                    if msg.altitude:
                        self.altitude = msg.altitude
                    
                    # Satelliten
                    if msg.num_sats:
                        self.satellites = msg.num_sats
                    
                    self.last_update = time.time()
                    self.last_update_time = datetime.now()
                    # Speichere rohen GGA-Satz für NTRIP
                    self.last_raw_gga = sentence
            
            # HDT: Heading True (von Dual-Antenna, genauer als RMC)
            elif isinstance(msg, pynmea2.HDT):
                if msg.heading:
                    self._update_heading(msg.heading)
        
        except pynmea2.ParseError:
            # Ignoriere Parse-Fehler (z.B. korrupte Sätze)
            logger.debug(f"NMEA Parse-Fehler (ignoriert): {sentence[:50]}")
        except Exception as e:
            logger.debug(f"NMEA Verarbeitungsfehler: {e}")
    
    def write_data(self, data: bytes):
        """
        Schreibt Daten an den seriellen Port des GPS
        Öffentliche Methode für Kapselung (z.B. für NTRIP-Daten)
        """
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(data)
                logger.debug(f"📤 {len(data)} Bytes an GPS gesendet")
            except Exception as e:
                logger.warning(f"⚠️ Fehler beim Schreiben auf GPS-Port: {e}")
    
    def get_last_raw_gga(self) -> Optional[str]:
        """Gibt den letzten rohen GGA-Satz zurück (für NTRIP)"""
        with self.lock:
            return self.last_raw_gga
    
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
                'is_connected': self.serial_port is not None and self.serial_port.is_open,
                'last_update': self.last_update,
                'last_update_time': self.last_update_time.isoformat() if self.last_update_time else None
            }
    
    def get_bing_maps_url(self) -> str:
        """Generiert Bing Maps URL für aktuelle Position"""
        with self.lock:
            # Prüfe auf einen validen Status, nicht nur auf Koordinaten != 0
            # (0.0, 0.0) wäre Äquator vor Afrikas Küste - nicht sinnvoll)
            if self.rtk_status not in ["NO GPS", ""]:
                return f"https://www.bing.com/maps?cp={self.latitude}~{self.longitude}&lvl=18"
        return "https://www.bing.com/maps"
