#!/usr/bin/env python3
"""
ICM-42688-P IMU Handler
6-DoF Inertial Measurement Unit (Accelerometer + Gyroscope)
I2C Communication on Raspberry Pi Zero 2W
"""

import smbus2
import struct
import time
import threading
import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)


class ICM42688P:
    """ICM-42688-P IMU Sensor Handler"""
    
    # Register Adressen (ICM-42688-P)
    REG_WHO_AM_I = 0x75          # Device ID (sollte 0x47 sein)

    # === CORRECT REGISTER ADDRESSES (FROM DATASHEET, BANK 0) ===
    # 14-Byte zusammenhängender Block: Temp(2) + Accel(6) + Gyro(6)
    REG_TEMP_DATA1 = 0x1D        # Temperature High Byte (Start des 14-Byte-Blocks)
    REG_TEMP_DATA0 = 0x1E        # Temperature Low Byte
    REG_ACCEL_DATA_X1 = 0x1F     # Accel X High Byte
    REG_ACCEL_DATA_X0 = 0x20     # Accel X Low Byte
    REG_ACCEL_DATA_Y1 = 0x21     # Accel Y High Byte
    REG_ACCEL_DATA_Y0 = 0x22     # Accel Y Low Byte
    REG_ACCEL_DATA_Z1 = 0x23     # Accel Z High Byte
    REG_ACCEL_DATA_Z0 = 0x24     # Accel Z Low Byte
    REG_GYRO_DATA_X1 = 0x25      # Gyro X High Byte
    REG_GYRO_DATA_X0 = 0x26      # Gyro X Low Byte
    REG_GYRO_DATA_Y1 = 0x27      # Gyro Y High Byte
    REG_GYRO_DATA_Y0 = 0x28      # Gyro Y Low Byte
    REG_GYRO_DATA_Z1 = 0x29      # Gyro Z High Byte
    REG_GYRO_DATA_Z0 = 0x2A      # Gyro Z Low Byte (Ende des 14-Byte-Blocks)
    # ==========================================================

    REG_PWR_MGMT0 = 0x4E         # Power Management
    REG_ACCEL_CONFIG0 = 0x50     # Accelerometer Config
    REG_GYRO_CONFIG0 = 0x4F      # Gyroscope Config
    REG_INT_CONFIG = 0x14        # Interrupt Config
    REG_INT_STATUS = 0x19        # Interrupt Status
    REG_SIGNAL_PATH_RESET = 0x4B # Signal Path Reset
    REG_DEVICE_CONFIG = 0x11     # Device Config
    
    # Skalierungsfaktoren (ICM-42688-P bei ±2g und ±250°/s)
    ACCEL_SCALE_2G = 16384.0     # LSB/g bei ±2g
    GYRO_SCALE_250DPS = 131.0    # LSB/(°/s) bei ±250°/s
    TEMP_SCALE = 132.48          # LSB/°C (Temperatur-Empfindlichkeit)
    TEMP_OFFSET = 25.0           # Offset bei 0 LSB (Raumtemperatur)
    
    def __init__(self, bus: int = 1, address: int = 0x68, sample_rate: int = 200):
        """
        Initialisiert IMU
        
        Args:
            bus: I2C Bus Nummer (1 für Raspberry Pi)
            address: I2C Adresse (0x68 oder 0x69)
            sample_rate: Sample Rate in Hz (100, 200, 500, 1000)
        """
        self.bus_num = bus
        self.address = address
        self.sample_rate = sample_rate
        self.bus = None
        self.running = False
        self.connected = False
        
        # Sensor-Daten
        self.accel = {'x': 0.0, 'y': 0.0, 'z': 0.0}  # m/s²
        self.gyro = {'x': 0.0, 'y': 0.0, 'z': 0.0}   # °/s
        self.temperature = 0.0                         # °C
        
        # Thread für kontinuierliches Lesen
        self.read_thread = None
        self.lock = threading.Lock()
    
    def connect(self) -> bool:
        """Verbindet sich mit dem Sensor"""
        try:
            self.bus = smbus2.SMBus(self.bus_num)
            logger.info(f"✅ I2C Bus {self.bus_num} geöffnet")

            # WHO_AM_I Register auslesen
            try:
                device_id = self.bus.read_byte_data(self.address, self.REG_WHO_AM_I)
                logger.info(f"✅ WHO_AM_I gelesen: 0x{device_id:02x}")

                if device_id == 0x47:
                    logger.info(f"✅ ICM-42688-P erkannt")
                else:
                    logger.warning(f"⚠️  Unerwartete Device ID: 0x{device_id:02x}")
            except Exception as e:
                logger.warning(f"⚠️  WHO_AM_I Fehler: {e}")

            # Sensor konfigurieren
            self._configure_sensor()

            self.connected = True
            self.running = True

            # Read-Thread starten
            self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.read_thread.start()

            logger.info(f"✅ IMU verbunden auf I2C Bus {self.bus_num}, Adresse 0x{self.address:02x}")
            return True

        except Exception as e:
            logger.error(f"❌ IMU-Verbindung fehlgeschlagen: {e}")
            if self.bus:
                try:
                    self.bus.close()
                except:
                    pass
            return False
    
    def _configure_sensor(self):
        """Konfiguriert den Sensor korrekt"""
        try:
            # 1. Reset Signal Path
            self.bus.write_byte_data(self.address, self.REG_SIGNAL_PATH_RESET, 0x01)
            time.sleep(0.1)
            logger.debug("✅ Signal Path Reset")

            # 2. Power Management: Accel & Gyro im Low Noise Mode
            # 0x0F = Accel LN (11), Gyro LN (11)
            self.bus.write_byte_data(self.address, self.REG_PWR_MGMT0, 0x0F)
            time.sleep(0.1)
            logger.debug("✅ Power Management konfiguriert")

            # 3. ODR (Sample Rate) bestimmen
            # ODR Bits: 1000Hz=0x06, 200Hz=0x07, 100Hz=0x08, 50Hz=0x09
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
            # FS_SEL = 011 (Bits 7-5) -> ±2g
            # ODR = odr_bits (Bits 3-0)
            accel_config = (0b011 << 5) | odr_bits
            self.bus.write_byte_data(self.address, self.REG_ACCEL_CONFIG0, accel_config)
            time.sleep(0.05)
            logger.debug(f"✅ Accelerometer Config: 0x{accel_config:02X}")

            # 5. Gyroscope Config: ±250 dps, ODR
            # FS_SEL = 011 (Bits 7-5) -> ±250 dps
            # ODR = odr_bits (Bits 3-0)
            gyro_config = (0b011 << 5) | odr_bits
            self.bus.write_byte_data(self.address, self.REG_GYRO_CONFIG0, gyro_config)
            time.sleep(0.05)
            logger.debug(f"✅ Gyroscope Config: 0x{gyro_config:02X}")

            # Warten auf Sensor-Stabilisierung
            time.sleep(0.1)
            logger.info(f"✅ Sensor konfiguriert: ±2g, ±250dps @ {self.sample_rate}Hz")

        except Exception as e:
            logger.warning(f"⚠️  Sensor-Konfiguration: {e}")
    
    def _read_loop(self):
        """Liest kontinuierlich Sensor-Daten"""
        while self.running:
            try:
                self._read_sensor_data()
                time.sleep(1.0 / self.sample_rate)
            except Exception as e:
                logger.debug(f"⚠️  Sensor-Read Fehler: {e}")
                time.sleep(0.01)
    
    def _read_sensor_data(self):
        """Liest Rohdaten vom Sensor aus dem korrekten zusammenhängenden Register-Block"""
        try:
            # 1. Lese ALLE 14 Bytes am Stück (Temp + Accel + Gyro)
            # Der Block ist zusammenhängend und startet bei 0x1D (TEMP_DATA1)
            data_block = self.bus.read_i2c_block_data(
                self.address, self.REG_TEMP_DATA1, 14
            )

            if len(data_block) < 14:
                logger.debug(f"⚠️  Unvollständige Daten: {len(data_block)} Bytes")
                return

            # 2. Daten entpacken (Big-Endian) - Reihenfolge im Block: Temp(1), Accel(3), Gyro(3)
            # struct format '>hhhhhhh' is correct for 7 x 16-bit signed integers in big-endian
            temp_raw, \
            accel_x_raw, accel_y_raw, accel_z_raw, \
            gyro_x_raw, gyro_y_raw, gyro_z_raw = struct.unpack('>hhhhhhh', bytes(data_block))

            # 3. In physikalische Einheiten konvertieren
            with self.lock:
                # Temperatur: LSB zu °C
                self.temperature = self.TEMP_OFFSET + (temp_raw / self.TEMP_SCALE)

                # Beschleunigung: LSB zu m/s²
                self.accel['x'] = (accel_x_raw / self.ACCEL_SCALE_2G) * 9.81
                self.accel['y'] = (accel_y_raw / self.ACCEL_SCALE_2G) * 9.81
                self.accel['z'] = (accel_z_raw / self.ACCEL_SCALE_2G) * 9.81

                # Drehrate: LSB zu °/s
                self.gyro['x'] = gyro_x_raw / self.GYRO_SCALE_250DPS
                self.gyro['y'] = gyro_y_raw / self.GYRO_SCALE_250DPS
                self.gyro['z'] = gyro_z_raw / self.GYRO_SCALE_250DPS

        except struct.error as e:
            logger.debug(f"⚠️  Struct-Fehler beim Entpacken der IMU-Daten: {e}")
        except OSError as e:
            # Log specific OSError for I2C issues
            logger.debug(f"⚠️  I2C Lese-Fehler (OSError): {e}")
        except Exception as e:
            # Catch other potential exceptions during I2C read or processing
            logger.debug(f"⚠️  Allgemeiner IMU-Daten-Fehler: {e}")
    
    def get_data(self) -> Dict:
        """Gibt aktuelle Sensor-Daten zurück"""
        with self.lock:
            return {
                'accel': self.accel.copy(),
                'gyro': self.gyro.copy(),
                'temperature': self.temperature,
                'timestamp': time.time()
            }
    
    def get_accel(self) -> Dict[str, float]:
        """Gibt Beschleunigung in m/s² zurück"""
        with self.lock:
            return self.accel.copy()
    
    def get_gyro(self) -> Dict[str, float]:
        """Gibt Drehrate in °/s zurück"""
        with self.lock:
            return self.gyro.copy()
    
    def get_temperature(self) -> float:
        """Gibt Temperatur in °C zurück"""
        with self.lock:
            return self.temperature
    
    def disconnect(self):
        """Trennt Verbindung zum Sensor"""
        self.running = False
        if self.read_thread:
            self.read_thread.join(timeout=1.0)
        if self.bus:
            self.bus.close()
        self.connected = False
        logger.info("✅ IMU getrennt")

