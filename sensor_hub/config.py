"""Quassel UGV Sensor Hub - Konfiguration für GPS, WitMotion-IMU und CAN."""

import os
from dotenv import load_dotenv

# .env Datei laden
load_dotenv()


def _env_flag(name: str, default: bool) -> bool:
    """Liest boolesche Umgebungsvariable robust ein."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')

# ============================================================================
# GPS KONFIGURATION (Holybro UM982)
# ============================================================================
GPS_PORT = os.getenv('GPS_PORT', '/dev/serial/by-id/usb-FTDI_FT231X_USB_UART_*')
GPS_BAUDRATE = int(os.getenv('GPS_BAUDRATE', '230400'))
GPS_TIMEOUT = float(os.getenv('GPS_TIMEOUT', '5.0'))

# ============================================================================
# NTRIP KONFIGURATION (RTK-Korrekturdaten)
# ============================================================================
NTRIP_ENABLED = _env_flag('NTRIP_ENABLED', True)
NTRIP_HOST = os.getenv('NTRIP_HOST', 'your-ntrip-server.com')
NTRIP_PORT = int(os.getenv('NTRIP_PORT', '2101'))
NTRIP_MOUNTPOINT = os.getenv('NTRIP_MOUNTPOINT', 'MOUNTPOINT')
NTRIP_USERNAME = os.getenv('NTRIP_USERNAME', '')  # Aus .env laden!
NTRIP_PASSWORD = os.getenv('NTRIP_PASSWORD', '')  # Aus .env laden!
NTRIP_TIMEOUT = float(os.getenv('NTRIP_TIMEOUT', '10.0'))
NTRIP_RECONNECT_INTERVAL = float(os.getenv('NTRIP_RECONNECT_INTERVAL', '30.0'))

# ============================================================================
# IMU KONFIGURATION
# ============================================================================
IMU_ENABLED = _env_flag('IMU_ENABLED', False)
IMU_TYPE = os.getenv('IMU_TYPE', 'witmotion').strip().lower()
IMU_PORT = os.getenv('IMU_PORT', '/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0')
IMU_BAUDRATE = int(os.getenv('IMU_BAUDRATE', '9600'))
IMU_TIMEOUT = float(os.getenv('IMU_TIMEOUT', '1.0'))
IMU_SAMPLE_RATE = int(os.getenv('IMU_SAMPLE_RATE', '200'))

# ============================================================================
# WEB-INTERFACE KONFIGURATION
# ============================================================================
WEB_HOST = os.getenv('WEB_HOST', '0.0.0.0')
WEB_PORT = int(os.getenv('WEB_PORT', '8080'))
WEB_DEBUG = _env_flag('WEB_DEBUG', False)
WEB_UPDATE_RATE = int(os.getenv('WEB_UPDATE_RATE', '2'))

# ============================================================================
# TELEMETRIE KONFIGURATION
# ============================================================================
CAN_SEND_RATE = int(os.getenv('CAN_SEND_RATE', '10'))

# ============================================================================
# CAN-BUS KONFIGURATION
# ============================================================================
CAN_ENABLED = _env_flag('CAN_ENABLED', True)
CAN_INTERFACE = os.getenv('CAN_INTERFACE', 'can0')
CAN_BITRATE = int(os.getenv('CAN_BITRATE', '1000000'))
CAN_SENSOR_HUB_ID = int(os.getenv('CAN_SENSOR_HUB_ID', '0x100'), 0)
CAN_CONTROLLER_ID = int(os.getenv('CAN_CONTROLLER_ID', '0x200'), 0)
CAN_MAX_FRAME_SIZE = int(os.getenv('CAN_MAX_FRAME_SIZE', '6'))
CAN_FRAME_TIMEOUT = float(os.getenv('CAN_FRAME_TIMEOUT', '1.0'))

# ============================================================================
# LOGGING KONFIGURATION
# ============================================================================
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', '/var/log/sensor_hub.log')
LOG_FORMAT = os.getenv('LOG_FORMAT', '[%(asctime)s] %(levelname)s - %(message)s')

