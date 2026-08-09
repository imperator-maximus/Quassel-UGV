"""Quassel UGV Sensor Hub - Konfiguration für GPS, WitMotion-IMU und CAN."""

import os
from pathlib import Path
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
# Kommen so lange keine RTCM-Bytes, obwohl der Socket noch verbunden ist, gilt
# die Verbindung als tot und wird neu aufgebaut. Der Caster laesst den Socket
# bei einem Ausfall minutenlang offen, ohne Daten zu senden; ohne diese
# Schwelle haengt RTK bis zum serverseitigen Timeout (~7 min) auf GPS FIX.
NTRIP_STALE_TIMEOUT = float(os.getenv('NTRIP_STALE_TIMEOUT', '10.0'))

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

# ----------------------------------------------------------------------------
# ZUGANGSSCHUTZ
# ----------------------------------------------------------------------------
# Der Webserver ist über eine Portfreigabe aus dem Internet erreichbar und
# liefert die metergenaue Position des Fahrzeugs. Ohne Passwort liest sie jeder,
# der die Adresse kennt. Das Passwort gehört in die .env, niemals in den Code
# (siehe SECURITY.md).
#
# WEB_AUTH_PASSWORD akzeptiert Klartext oder einen Werkzeug-Hash
# (pbkdf2:... / scrypt:...). Denselben Wert braucht der Raspberry in
# SENSOR_HUB_TELEMETRY_PASSWORD, sonst bleibt die Pose aus.
WEB_AUTH_ENABLED = _env_flag('WEB_AUTH_ENABLED', True)
WEB_AUTH_USERNAME = os.getenv('WEB_AUTH_USERNAME', 'ugv')
WEB_AUTH_PASSWORD = os.getenv('WEB_AUTH_PASSWORD', '')
WEB_AUTH_REALM = os.getenv('WEB_AUTH_REALM', 'Quassel UGV SensorHub')
WEB_AUTH_MAX_FAILURES = int(os.getenv('WEB_AUTH_MAX_FAILURES', '8'))
WEB_AUTH_LOCKOUT_S = float(os.getenv('WEB_AUTH_LOCKOUT_S', '60.0'))
VEHICLE_GEOMETRY_PATH = os.getenv('VEHICLE_GEOMETRY_PATH', str(Path(__file__).with_name('vehicle_geometry.json')))

# ============================================================================
# TELEMETRIE KONFIGURATION
# ============================================================================
CAN_SEND_RATE = int(os.getenv('CAN_SEND_RATE', '10'))
# Nur der periodische 0x100-Telemetrie-Versand (Empfang von Befehlen bleibt aktiv).
# Auf False setzen, wenn die Telemetrie per WLAN (/api/telemetry) abgeholt wird,
# um den gestoerten CAN-Bus zu entlasten.
CAN_TELEMETRY_ENABLED = _env_flag('CAN_TELEMETRY_ENABLED', True)

# ============================================================================
# CAN-BUS KONFIGURATION
# ============================================================================
CAN_ENABLED = _env_flag('CAN_ENABLED', False)
CAN_INTERFACE = os.getenv('CAN_INTERFACE', 'can0')
CAN_BITRATE = int(os.getenv('CAN_BITRATE', '250000'))
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
