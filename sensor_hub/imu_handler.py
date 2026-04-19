#!/usr/bin/env python3
"""IMU-Handler für den WitMotion USB-Sensor."""

import logging
import struct
import threading
import time
from typing import Dict, Set

try:
    import serial
except ImportError:  # pragma: no cover - optional in tests
    serial = None

logger = logging.getLogger(__name__)


def _normalize_heading(angle: float) -> float:
    """Normalisiert Winkel in den Bereich 0-360°."""
    normalized = angle % 360.0
    if normalized < 0:
        normalized += 360.0
    return normalized


class WitMotionUSBIMU:
    """WitMotion USB-IMU mit klassischem 0x55/0x51..0x54 Binärprotokoll."""

    FRAME_HEADER = 0x55
    FRAME_SIZE = 11
    FRAME_ACCEL = 0x51
    FRAME_GYRO = 0x52
    FRAME_ANGLE = 0x53
    FRAME_MAG = 0x54

    REQUIRED_FRAMES = {FRAME_ACCEL, FRAME_GYRO, FRAME_ANGLE}
    ACCEL_RANGE_G = 16.0
    GYRO_RANGE_DPS = 2000.0
    ANGLE_RANGE_DEG = 180.0

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 1.0, sample_rate: int = 100):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.sample_rate = sample_rate
        self.serial_port = None
        self.running = False
        self.connected = False
        self.read_thread = None
        self.lock = threading.Lock()
        self._rx_buffer = bytearray()
        self._frames_seen: Set[int] = set()
        self.last_packet_time = None

        self.raw_accel = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        self.raw_gyro = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        self.raw_angles = {'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0}
        self.raw_mag = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        self.temperature = 0.0
        self.is_calibrated = False
        self.is_stationary = False

    def connect(self) -> bool:
        """Öffnet die serielle Verbindung und wartet auf valide WitMotion Frames."""
        try:
            if serial is None:
                raise ImportError("pyserial nicht installiert")

            self.serial_port = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            self.running = True
            self.connected = True
            self._rx_buffer.clear()
            self._frames_seen.clear()

            self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.read_thread.start()

            deadline = time.time() + max(2.0, self.timeout * 5.0)
            while time.time() < deadline:
                with self.lock:
                    if self.REQUIRED_FRAMES.issubset(self._frames_seen):
                        logger.info(f"✅ WitMotion liefert Frames auf {self.port} @ {self.baudrate} Baud")
                        return True
                time.sleep(0.05)

            logger.warning("⚠️  WitMotion-Port geöffnet, aber keine vollständige Frame-Folge empfangen")
            self.disconnect()
            return False

        except Exception as e:
            logger.error(f"❌ WitMotion-Verbindung fehlgeschlagen: {e}")
            self.disconnect()
            return False

    def _read_loop(self):
        """Liest kontinuierlich Daten vom seriellen Port."""
        while self.running:
            try:
                chunk = self.serial_port.read(64)
                if not chunk:
                    continue
                self._process_bytes(chunk)
            except Exception as e:
                if self.running:
                    logger.debug(f"⚠️  WitMotion Read Fehler: {e}")
                time.sleep(0.1)

    def _process_bytes(self, data: bytes):
        """Verarbeitet einen Byte-Stream und extrahiert vollständige 11-Byte Frames."""
        if not data:
            return

        with self.lock:
            self._rx_buffer.extend(data)

            while len(self._rx_buffer) >= self.FRAME_SIZE:
                if self._rx_buffer[0] != self.FRAME_HEADER:
                    del self._rx_buffer[0]
                    continue

                frame = bytes(self._rx_buffer[:self.FRAME_SIZE])
                del self._rx_buffer[:self.FRAME_SIZE]

                checksum = sum(frame[:10]) & 0xFF
                if checksum != frame[10]:
                    logger.debug("⚠️  WitMotion Checksum-Fehler verworfen")
                    continue

                self._process_frame_locked(frame)

    def _process_frame_locked(self, frame: bytes):
        """Aktualisiert die zuletzt empfangenen Sensorwerte."""
        frame_type = frame[1]
        d1, d2, d3, d4 = struct.unpack('<hhhh', frame[2:10])

        self.last_packet_time = time.time()
        self._frames_seen.add(frame_type)

        if frame_type == self.FRAME_ACCEL:
            scale = self.ACCEL_RANGE_G * 9.81 / 32768.0
            self.raw_accel['x'] = d1 * scale
            self.raw_accel['y'] = d2 * scale
            self.raw_accel['z'] = d3 * scale
            self.temperature = d4 / 100.0

        elif frame_type == self.FRAME_GYRO:
            scale = self.GYRO_RANGE_DPS / 32768.0
            self.raw_gyro['x'] = d1 * scale
            self.raw_gyro['y'] = d2 * scale
            self.raw_gyro['z'] = d3 * scale
            self.temperature = d4 / 100.0

        elif frame_type == self.FRAME_ANGLE:
            scale = self.ANGLE_RANGE_DEG / 32768.0
            self.raw_angles['roll'] = d1 * scale
            self.raw_angles['pitch'] = d2 * scale
            self.raw_angles['yaw'] = d3 * scale

        elif frame_type == self.FRAME_MAG:
            self.raw_mag['x'] = float(d1)
            self.raw_mag['y'] = float(d2)
            self.raw_mag['z'] = float(d3)

        self.is_calibrated = self.REQUIRED_FRAMES.issubset(self._frames_seen)
        self.is_stationary = (
            abs(self.raw_gyro['x']) < 1.0 and
            abs(self.raw_gyro['y']) < 1.0 and
            abs(self.raw_gyro['z']) < 1.0 and
            abs(self.raw_accel['x']) < 0.5 and
            abs(self.raw_accel['y']) < 0.5
        )

    def get_data(self) -> Dict:
        """Gibt die zuletzt empfangenen Rohdaten zurück."""
        with self.lock:
            return {
                'accel': self.raw_accel.copy(),
                'gyro': self.raw_gyro.copy(),
                'mag': self.raw_mag.copy(),
                'temperature': self.temperature,
                'is_calibrated': self.is_calibrated,
                'timestamp': self.last_packet_time or time.time(),
                'orientation_source': 'witmotion_native'
            }

    def get_orientation(self) -> Dict:
        """Gibt die native WitMotion-Orientierung zurück."""
        with self.lock:
            yaw = _normalize_heading(self.raw_angles['yaw'])
            return {
                'roll': self.raw_angles['roll'],
                'pitch': self.raw_angles['pitch'],
                'yaw': yaw,
                'heading': yaw,
                'is_stationary': self.is_stationary,
                'gyro_bias': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                'gps_weight': 0.0,
                'source': 'witmotion_native'
            }

    def get_motion_status(self) -> Dict:
        """Gibt einfachen Bewegungsstatus für UI/API zurück."""
        with self.lock:
            return {
                'is_stationary': self.is_stationary,
                'gyro_bias': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                'gps_weight': 0.0,
                'zupt_enabled': False,
                'motion_threshold_gyro': 1.0,
                'motion_threshold_accel': 0.5,
                'source': 'witmotion_native'
            }

    def get_status(self) -> Dict:
        """Gibt generische Statusinformationen für API/UI zurück."""
        with self.lock:
            return {
                'connected': self.connected,
                'running': self.running,
                'imu_type': 'witmotion_usb',
                'port': self.port,
                'baudrate': self.baudrate,
                'sample_rate': self.sample_rate,
                'receiving_data': bool(self.last_packet_time and (time.time() - self.last_packet_time) < 2.0),
                'last_packet_time': self.last_packet_time,
                'orientation_source': 'witmotion_native'
            }

    def calibrate(self, samples: int = 0) -> bool:
        """Für WitMotion nicht erforderlich; erfolgreiche Frame-Erkennung reicht."""
        logger.info("ℹ️  WitMotion nutzt native Sensordaten, explizite Kalibrierung wird übersprungen")
        return self.is_calibrated

    def disconnect(self):
        """Schließt die serielle Verbindung sicher."""
        self.running = False
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=1.0)
        if self.serial_port:
            try:
                self.serial_port.close()
            except Exception:
                pass
        self.serial_port = None
        self.connected = False
        logger.info("✅ WitMotion getrennt")


def create_imu_handler(imu_type: str, **kwargs):
    """Erzeugt den passenden IMU-Handler anhand des konfigurierten Typs."""
    normalized = (imu_type or 'witmotion').strip().lower()

    if normalized in {'witmotion', 'witmotion_usb', 'usb'}:
        return WitMotionUSBIMU(
            port=kwargs.get('port', '/dev/ttyUSB0'),
            baudrate=kwargs.get('baudrate', 9600),
            timeout=kwargs.get('timeout', 1.0),
            sample_rate=kwargs.get('sample_rate', 100)
        )

    raise ValueError(f"Nicht unterstützter IMU-Typ für diesen Stand: {imu_type}")

