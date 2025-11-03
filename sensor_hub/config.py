"""
Quassel UGV Sensor Hub - Konfiguration
RTK-GPS + IMU Sensor Fusion für Raspberry Pi Zero 2W

WICHTIG: Sensitive Daten (Passwörter, API-Keys) gehören in .env Datei!
Siehe README.md für Setup-Anleitung.
"""

import os
from dotenv import load_dotenv

# .env Datei laden
load_dotenv()

# ============================================================================
# GPS KONFIGURATION (Holybro UM982)
# ============================================================================
GPS_PORT = '/dev/serial0'           # UART Port für UM982
GPS_BAUDRATE = 230400              # UM982 Baud Rate
GPS_TIMEOUT = 5.0                  # Timeout für GPS-Daten (Sekunden)

# ============================================================================
# NTRIP KONFIGURATION (RTK-Korrekturdaten)
# ============================================================================
NTRIP_ENABLED = True                # NTRIP aktivieren
NTRIP_HOST = os.getenv('NTRIP_HOST', 'your-ntrip-server.com')
NTRIP_PORT = int(os.getenv('NTRIP_PORT', '2101'))
NTRIP_MOUNTPOINT = os.getenv('NTRIP_MOUNTPOINT', 'MOUNTPOINT')
NTRIP_USERNAME = os.getenv('NTRIP_USERNAME', '')  # Aus .env laden!
NTRIP_PASSWORD = os.getenv('NTRIP_PASSWORD', '')  # Aus .env laden!
NTRIP_TIMEOUT = 10.0                # NTRIP Verbindungs-Timeout
NTRIP_RECONNECT_INTERVAL = 30.0     # Reconnect-Versuch nach X Sekunden

# ============================================================================
# IMU KONFIGURATION (ICM-42688-P)
# ============================================================================
IMU_ENABLED = True                  # IMU aktivieren
IMU_ADDRESS = 0x69                  # I2C Adresse (0x68 wenn AD0=GND, 0x69 wenn AD0=VCC)
IMU_BUS = 1                         # I2C Bus Nummer
IMU_SAMPLE_RATE = 200               # Hz

# ============================================================================
# WEB-INTERFACE KONFIGURATION
# ============================================================================
WEB_HOST = '0.0.0.0'                # Listen auf allen Interfaces
WEB_PORT = 8080                     # Web-Port (nicht 80, da Pi 3 das nutzt)
WEB_DEBUG = False                   # Debug-Modus
WEB_UPDATE_RATE = 2                 # Hz (Updates pro Sekunde)

# ============================================================================
# SENSOR FUSION KONFIGURATION
# ============================================================================
FUSION_RATE = 50                    # Hz (20ms Updates)
TRAIL_LENGTH = 100                  # Anzahl der Positionen im Trail

# ============================================================================
# CAN-BUS KONFIGURATION
# ============================================================================
CAN_ENABLED = True                  # CAN aktivieren
CAN_INTERFACE = 'can0'              # CAN Interface
CAN_BITRATE = 1000000               # 1 Mbps (einheitlich mit Motor Controller)

# ============================================================================
# LOGGING KONFIGURATION
# ============================================================================
LOG_LEVEL = 'INFO'                  # DEBUG, INFO, WARNING, ERROR
LOG_FILE = '/var/log/sensor_hub.log'  # Log-Datei
LOG_FORMAT = '[%(asctime)s] %(levelname)s - %(message)s'

