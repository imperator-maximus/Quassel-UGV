"""GPS-Handler fuer den UM982 mit Dual-Antenne.

Uebernommen vom SensorHub (``sensor_hub/gps_handler.py``) und an drei Stellen
geschaerft, weil die Pose hier nicht mehr ueber HTTP laeuft, sondern direkt in
die Sicherheitskette des Fahrzeugs:

1. Position und Heading fuehren getrennte Zeitstempel. Der Empfaenger kann
   weiter GGA liefern, waehrend die Heading-Loesung abreisst; beides in einem
   Alter zusammenzufassen wuerde den Kursverlust verstecken.
2. Ein nie empfangenes Heading ist ``None``, nicht ``0.0``. Auf dem SensorHub
   war 0.0 das Signal "kein Heading" und die IMU fing den Fall auf. Die IMU
   gibt es nicht mehr, und die Navigation uebernimmt jeden Heading-Wert, den
   sie bekommt - ein Vorgabewert von 0.0 waere nach dem Baseline-Offset ein
   Kurs von 90 Grad, den nie jemand gemessen hat.
3. Der Leseweg verkraftet einen USB-Aussetzer. Der Port wird neu geoeffnet
   statt den Thread still sterben zu lassen.

Alle Zeitmessungen laufen ueber ``time.monotonic()``. Das Fahrzeug zieht seine
Uhr per NTP nach; ein Sprung der Wanduhr darf die Pose nicht schlagartig alt
oder jung erscheinen lassen.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional

import serial

from .nmea import parse_gga, parse_heading, split_sentence

logger = logging.getLogger(__name__)

# Fix-Qualitaet aus dem GGA-Satz in die Bezeichnungen, die Oberflaeche und
# Navigation bereits kennen. Unbekannte Werte gelten als "GPS FIX", nie als
# RTK - eine zu optimistische Einstufung wuerde eine Fahrt freigeben, die die
# Genauigkeit nicht traegt.
_FIX_QUALITY_LABELS = {
    1: 'GPS FIX',
    2: 'DGPS',
    4: 'RTK FIXED',
    5: 'RTK FLOAT',
}


def normalize_heading(angle: float) -> float:
    """Normalisiert einen Winkel auf [0, 360)."""
    normalized = angle % 360.0
    if normalized < 0.0:
        normalized += 360.0
    return normalized


class GPSHandler:
    """Liest NMEA vom UM982 und haelt den letzten Stand vor."""

    def __init__(self, port: str, baudrate: int, timeout: float = 1.0,
                 reconnect_interval_s: float = 2.0):
        """
        Args:
            port: Serieller Port, idealerweise ueber /dev/serial/by-id/...
            baudrate: 230400 beim UM982
            timeout: Lesezeitlimit. Bewusst kurz: ``readline`` blockiert
                hoechstens so lange, damit der Thread beim Herunterfahren
                zuegig reagiert und ein stummer Empfaenger schnell auffaellt.
            reconnect_interval_s: Wartezeit zwischen zwei Oeffnungsversuchen.
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.reconnect_interval_s = reconnect_interval_s

        self.serial_port: Optional[serial.Serial] = None
        self.running = False
        self.reader_thread: Optional[threading.Thread] = None

        self.latitude: Optional[float] = None
        self.longitude: Optional[float] = None
        self.altitude = 0.0
        self.satellites = 0
        self.rtk_status = 'NO GPS'
        # None heisst: seit dem Start kam keine gueltige Heading-Loesung.
        self.heading: Optional[float] = None

        self._last_fix_monotonic = 0.0
        self._last_heading_monotonic = 0.0
        self._last_sentence_monotonic = 0.0
        self._last_raw_gga: Optional[str] = None

        self._sentences_ok = 0
        self._sentences_bad = 0
        self._reconnects = 0
        self._last_error: Optional[str] = None

        self._lock = threading.Lock()
        self._write_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------
    def start(self) -> bool:
        """Startet den Lesethread. Ein noch fehlender Port ist kein Fehler.

        Der Thread laeuft auch dann an, wenn der Empfaenger beim Start noch
        nicht da ist, und verbindet sich, sobald er auftaucht. Andernfalls
        haenge die Pose bis zum naechsten Neustart des Dienstes.
        """
        if self.running:
            return True
        self.running = True
        self.reader_thread = threading.Thread(
            target=self._reader_loop, name='gps-reader', daemon=True
        )
        self.reader_thread.start()
        logger.info("GPS-Lesethread gestartet: %s @ %d baud", self.port, self.baudrate)
        return True

    def stop(self):
        """Beendet den Lesethread und schliesst den Port."""
        self.running = False
        thread = self.reader_thread
        if thread is not None:
            thread.join(timeout=self.timeout + 1.0)
        self._close_port()
        logger.info("GPS-Lesethread beendet")

    def _open_port(self) -> bool:
        try:
            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
            )
            with self._lock:
                self._last_error = None
            logger.info("GPS verbunden: %s @ %d baud", self.port, self.baudrate)
            return True
        except Exception as exc:
            self.serial_port = None
            with self._lock:
                self._last_error = str(exc)
            return False

    def _close_port(self):
        port = self.serial_port
        self.serial_port = None
        if port is not None:
            try:
                port.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------
    def _reader_loop(self):
        """Liest zeilenweise NMEA und baut den Port bei Bedarf neu auf.

        ``readline()`` blockiert bis zum Zeilenende oder bis zum Zeitlimit -
        das ist bewusst so und laeuft ausserhalb der Sicherheitsschleife in
        einem eigenen Thread. Ein Abfragen von ``in_waiting`` in einer engen
        Schleife hatte auf dem SensorHub einen ganzen Kern belegt.
        """
        last_open_attempt = 0.0
        while self.running:
            if self.serial_port is None:
                now = time.monotonic()
                if now - last_open_attempt < self.reconnect_interval_s:
                    time.sleep(0.2)
                    continue
                last_open_attempt = now
                if not self._open_port():
                    logger.warning(
                        "GPS-Port %s nicht verfuegbar (%s) - neuer Versuch in %.1fs",
                        self.port, self._last_error, self.reconnect_interval_s,
                    )
                    continue
                self._reconnects += 1

            try:
                raw = self.serial_port.readline()
            except Exception as exc:
                # Ein USB-Wackler nimmt den Port mit. Schliessen und im
                # naechsten Durchlauf neu oeffnen, statt den Thread mit einer
                # toten Referenz weiterlaufen zu lassen.
                logger.warning("GPS-Lesefehler (%s) - oeffne Port neu", exc)
                with self._lock:
                    self._last_error = str(exc)
                self._close_port()
                continue

            if not raw:
                continue
            line = raw.decode('ascii', errors='ignore').strip()
            if line:
                self._handle_sentence(line)

    def _handle_sentence(self, sentence: str):
        """Verarbeitet eine Zeile; alles ausser GGA/HDT/THS wird verworfen."""
        if not sentence.startswith('$'):
            # Die proprietaeren #UNIHEADINGA-Bloecke des UM982 landen hier.
            return

        fields = split_sentence(sentence)
        if fields is None:
            with self._lock:
                self._sentences_bad += 1
            return

        sentence_id = fields[0]
        body = fields[1:]
        now = time.monotonic()

        with self._lock:
            self._sentences_ok += 1
            self._last_sentence_monotonic = now

        if sentence_id.endswith('GGA'):
            parsed = parse_gga(body)
            with self._lock:
                if parsed is None:
                    # Qualitaet 0 oder keine Position: der Empfaenger meldet
                    # sich, hat aber keine Loesung. Der Zeitstempel bleibt
                    # stehen, damit die Pose altert.
                    self.rtk_status = 'NO GPS'
                    return
                quality = int(parsed['quality'])
                self.rtk_status = _FIX_QUALITY_LABELS.get(quality, 'GPS FIX')
                self.latitude = float(parsed['latitude'])
                self.longitude = float(parsed['longitude'])
                self.altitude = float(parsed['altitude'])
                self.satellites = int(parsed['satellites'])
                self._last_fix_monotonic = now
                self._last_raw_gga = sentence
            return

        heading = parse_heading(sentence_id, body)
        if heading is not None:
            with self._lock:
                self.heading = normalize_heading(heading)
                self._last_heading_monotonic = now

    # ------------------------------------------------------------------
    # Schreiben (RTCM-Korrekturen)
    # ------------------------------------------------------------------
    def write_data(self, data: bytes) -> bool:
        """Schreibt RTCM-Korrekturen an den Empfaenger."""
        port = self.serial_port
        if port is None:
            return False
        try:
            with self._write_lock:
                port.write(data)
            return True
        except Exception as exc:
            logger.warning("Schreiben auf den GPS-Port fehlgeschlagen: %s", exc)
            return False

    def get_last_raw_gga(self) -> Optional[str]:
        """Letzter roher GGA-Satz - der NTRIP-Caster braucht ihn fuer VRS."""
        with self._lock:
            return self._last_raw_gga

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        """Momentaufnahme inklusive Alter von Position und Heading.

        ``fix_age_s`` und ``heading_age_s`` sind ``None``, solange noch nie
        etwas empfangen wurde. Aufrufer muessen beide Faelle behandeln - eine
        fehlende Angabe darf nie als "frisch" durchgehen.
        """
        now = time.monotonic()
        with self._lock:
            fix_age = (
                None if self._last_fix_monotonic <= 0.0
                else max(0.0, now - self._last_fix_monotonic)
            )
            heading_age = (
                None if self._last_heading_monotonic <= 0.0
                else max(0.0, now - self._last_heading_monotonic)
            )
            sentence_age = (
                None if self._last_sentence_monotonic <= 0.0
                else max(0.0, now - self._last_sentence_monotonic)
            )
            return {
                'latitude': self.latitude,
                'longitude': self.longitude,
                'altitude': self.altitude,
                'heading': self.heading,
                'rtk_status': self.rtk_status,
                'satellites': self.satellites,
                'is_connected': self.serial_port is not None,
                'fix_age_s': fix_age,
                'heading_age_s': heading_age,
                'sentence_age_s': sentence_age,
                'sentences_ok': self._sentences_ok,
                'sentences_bad': self._sentences_bad,
                'reconnects': self._reconnects,
                'last_error': self._last_error,
                'port': self.port,
            }
