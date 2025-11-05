#!/usr/bin/env python3
"""
ICM-42688-P IMU Handler (Treiber)
Verantwortlich für:
- Hardware-Kommunikation (I2C)
- Sensor-Konfiguration
- Lesen von ROHDATEN (Temp, Accel, Gyro)
- Kalibrierungs-METHODE (wird von außen aufgerufen)
"""

import smbus2
import struct
import time
import threading
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class ICM42688P:
    """ICM-42688-P IMU Sensor Handler (Reiner Treiber)"""
    
    # Register Adressen (ICM-42688-P, Bank 0)
    REG_WHO_AM_I = 0x75
    REG_TEMP_DATA1 = 0x1D      # Start des 14-Byte-Datenblocks
    REG_PWR_MGMT0 = 0x4E
    REG_ACCEL_CONFIG0 = 0x50
    REG_GYRO_CONFIG0 = 0x4F
    REG_SIGNAL_PATH_RESET = 0x4B
    
    # Skalierungsfaktoren (bei ±2g und ±250°/s)
    ACCEL_SCALE_2G = 16384.0
    GYRO_SCALE_250DPS = 131.0
    TEMP_SCALE = 132.48
    TEMP_OFFSET = 25.0
    
    def __init__(self, bus: int = 1, address: int = 0x68, sample_rate: int = 200):
        self.bus_num = bus
        self.address = address
        self.sample_rate = sample_rate
        self.bus = None
        self.running = False
        self.connected = False
        self.read_thread = None
        self.lock = threading.Lock()

        # Kalibrierungs-Daten (werden von außen gesetzt)
        self.gyro_bias = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        self.accel_offset = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        self.is_calibrated = False

        # Rohdaten-Speicher
        self.raw_accel = {'x': 0.0, 'y': 0.0, 'z': 0.0}  # m/s²
        self.raw_gyro = {'x': 0.0, 'y': 0.0, 'z': 0.0}   # °/s
        self.temperature = 0.0                            # °C

    def connect(self) -> bool:
        """Verbindet sich mit dem Sensor"""
        try:
            self.bus = smbus2.SMBus(self.bus_num)
            logger.info(f"✅ I2C Bus {self.bus_num} geöffnet")

            # WHO_AM_I Register auslesen (mit try-except, da manchmal I/O-Fehler auftreten)
            try:
                device_id = self.bus.read_byte_data(self.address, self.REG_WHO_AM_I)
                logger.info(f"✅ WHO_AM_I gelesen: 0x{device_id:02x}")

                if device_id == 0x47:
                    logger.info(f"✅ ICM-42688-P erkannt")
                else:
                    logger.warning(f"⚠️  Unerwartete Device ID: 0x{device_id:02x}")
            except Exception as e:
                logger.warning(f"⚠️  WHO_AM_I Fehler: {e}")
                # Trotzdem weitermachen - Sensor antwortet manchmal erst nach Konfiguration

            # Sensor konfigurieren
            self._configure_sensor()

            self.connected = True
            self.running = True
            self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.read_thread.start()
            logger.info(f"✅ IMU verbunden auf I2C Bus {self.bus_num}, Adresse 0x{self.address:02x}")
            return True

        except Exception as e:
            logger.error(f"❌ IMU-Verbindung fehlgeschlagen: {e}")
            if self.bus:
                self.bus.close()
            return False
    
    def _configure_sensor(self):
        """Konfiguriert den Sensor korrekt"""
        try:
            # 1. Reset Signal Path
            self.bus.write_byte_data(self.address, self.REG_SIGNAL_PATH_RESET, 0x01)
            time.sleep(0.1)
            logger.debug("✅ Signal Path Reset")

            # 2. Power Management: Accel & Gyro im Low Noise Mode
            self.bus.write_byte_data(self.address, self.REG_PWR_MGMT0, 0x0F)
            time.sleep(0.1)
            logger.debug("✅ Power Management konfiguriert")

            # 3. ODR (Sample Rate)
            if self.sample_rate >= 1000:
                odr_bits = 0x06
            elif self.sample_rate >= 200:
                odr_bits = 0x07
            elif self.sample_rate >= 100:
                odr_bits = 0x08
            else:
                odr_bits = 0x09  # 50Hz Standard
            logger.info(f"Setze ODR auf {self.sample_rate}Hz (Register-Bits: 0x{odr_bits:02X})")

            # 4. Accelerometer Config: ±2g, ODR
            accel_config = (0b011 << 5) | odr_bits
            self.bus.write_byte_data(self.address, self.REG_ACCEL_CONFIG0, accel_config)
            time.sleep(0.05)

            # 5. Gyroscope Config: ±250 dps, ODR
            gyro_config = (0b011 << 5) | odr_bits
            self.bus.write_byte_data(self.address, self.REG_GYRO_CONFIG0, gyro_config)
            time.sleep(0.05)
            
            time.sleep(0.1)
            logger.info(f"✅ Sensor konfiguriert: ±2g, ±250dps @ {self.sample_rate}Hz")

        except Exception as e:
            logger.warning(f"⚠️  Sensor-Konfiguration: {e}")
    
    def _read_loop(self):
        """Liest kontinuierlich Sensor-Daten"""
        sleep_duration = 1.0 / self.sample_rate
        while self.running:
            try:
                self._read_sensor_data()
                time.sleep(sleep_duration)
            except Exception as e:
                logger.debug(f"⚠️  Sensor-Read Fehler: {e}")
                time.sleep(0.1)  # Kurze Pause bei Fehler
    
    def _read_sensor_data(self):
        """Liest Rohdaten vom Sensor aus dem korrekten zusammenhängenden Register-Block"""
        try:
            # Lese ALLE 14 Bytes am Stück (Temp + Accel + Gyro)
            data_block = self.bus.read_i2c_block_data(
                self.address, self.REG_TEMP_DATA1, 14
            )

            if len(data_block) < 14:
                logger.debug(f"⚠️  Unvollständige Daten: {len(data_block)} Bytes")
                return

            # Daten entpacken (Big-Endian)
            temp_raw, \
            accel_x_raw, accel_y_raw, accel_z_raw, \
            gyro_x_raw, gyro_y_raw, gyro_z_raw = struct.unpack('>hhhhhhh', bytes(data_block))

            with self.lock:
                self.temperature = self.TEMP_OFFSET + (temp_raw / self.TEMP_SCALE)
                
                # Skalierte, aber *unkalibrierte* Rohdaten speichern
                self.raw_accel['x'] = (accel_x_raw / self.ACCEL_SCALE_2G) * 9.81
                self.raw_accel['y'] = (accel_y_raw / self.ACCEL_SCALE_2G) * 9.81
                self.raw_accel['z'] = (accel_z_raw / self.ACCEL_SCALE_2G) * 9.81

                self.raw_gyro['x'] = gyro_x_raw / self.GYRO_SCALE_250DPS
                self.raw_gyro['y'] = gyro_y_raw / self.GYRO_SCALE_250DPS
                self.raw_gyro['z'] = gyro_z_raw / self.GYRO_SCALE_250DPS

        except OSError as e:
            logger.debug(f"⚠️  I2C Lese-Fehler (OSError): {e}")
        except Exception as e:
            logger.debug(f"⚠️  IMU-Daten-Fehler: {e}")

    def calibrate(self, samples: int = 1000) -> bool:
        """
        Kalibriert Gyro und Accelerometer. 
        WICHTIG: IMU muss während Kalibrierung STILL liegen!
        """
        if not self.connected:
            logger.error("❌ IMU nicht verbunden - Kalibrierung nicht möglich")
            return False

        logger.info(f"🔧 Starte IMU-Kalibrierung mit {samples} Samples...")
        logger.info("⚠️  WICHTIG: IMU muss STILL liegen!")

        gyro_sum = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        accel_sum = {'x': 0.0, 'y': 0.0, 'z': 0.0}

        sample_count = 0
        while sample_count < samples:
            with self.lock:
                # Hole die *letzten gelesenen* Rohdaten
                gyro_sum['x'] += self.raw_gyro['x']
                gyro_sum['y'] += self.raw_gyro['y']
                gyro_sum['z'] += self.raw_gyro['z']
                accel_sum['x'] += self.raw_accel['x']
                accel_sum['y'] += self.raw_accel['y']
                accel_sum['z'] += self.raw_accel['z']
            sample_count += 1
            time.sleep(1.0 / self.sample_rate)  # Warte auf nächstes Sample

        with self.lock:
            self.gyro_bias['x'] = gyro_sum['x'] / samples
            self.gyro_bias['y'] = gyro_sum['y'] / samples
            self.gyro_bias['z'] = gyro_sum['z'] / samples

            self.accel_offset['x'] = accel_sum['x'] / samples
            self.accel_offset['y'] = accel_sum['y'] / samples
            self.accel_offset['z'] = (accel_sum['z'] / samples) - 9.81  # Z-Achse auf 9.81 normieren

            self.is_calibrated = True

        logger.info(f"✅ Kalibrierung abgeschlossen!")
        logger.info(f"   Gyro Bias: X={self.gyro_bias['x']:.3f}°/s, Y={self.gyro_bias['y']:.3f}°/s, Z={self.gyro_bias['z']:.3f}°/s")
        logger.info(f"   Accel Offset: X={self.accel_offset['x']:.3f}m/s², Y={self.accel_offset['y']:.3f}m/s², Z={self.accel_offset['z']:.3f}m/s²")
        return True

    def get_data(self) -> Dict:
        """Gibt die *kalibrierten* Sensor-Rohdaten zurück"""
        with self.lock:
            acc_x = self.raw_accel['x'] - self.accel_offset['x']
            acc_y = self.raw_accel['y'] - self.accel_offset['y']
            acc_z = self.raw_accel['z'] - self.accel_offset['z']
            
            gyro_x = self.raw_gyro['x'] - self.gyro_bias['x']
            gyro_y = self.raw_gyro['y'] - self.gyro_bias['y']
            gyro_z = self.raw_gyro['z'] - self.gyro_bias['z']

            return {
                'accel': {'x': acc_x, 'y': acc_y, 'z': acc_z},
                'gyro': {'x': gyro_x, 'y': gyro_y, 'z': gyro_z},
                'temperature': self.temperature,
                'is_calibrated': self.is_calibrated,
                'timestamp': time.time()
            }
    
    def disconnect(self):
        """Trennt Verbindung zum Sensor"""
        self.running = False
        if self.read_thread:
            self.read_thread.join(timeout=1.0)
        if self.bus:
            self.bus.close()
        self.connected = False
        logger.info("✅ IMU getrennt")

