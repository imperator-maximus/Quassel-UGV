#!/usr/bin/env python3
"""
Orange Cube RC Skid Steering Configuration Script

Konfiguriert den Orange Cube für RC-Fernbedienung mit Skid Steering.
Setzt alle notwendigen Parameter für 2-Motor Skid Steering mit DroneCAN ESCs.

Author: Beyond Robotics Integration
Date: 2024
"""

import time
import sys
import argparse
from pymavlink import mavutil

# Standard-Verbindungseinstellungen
DEFAULT_CONNECTION = 'COM4'  # Orange Cube USB-Verbindung
DEFAULT_BAUDRATE = 115200

# RC und Skid Steering Parameter
RC_SKID_PARAMETERS = {
    # ============================================================================
    # RC INPUT CONFIGURATION
    # ============================================================================
    
    # RC Channel Mapping (Standard Skid Steering)
    'RC_MAP_ROLL': 1,         # Steering auf Kanal 1 (Aileron)
    'RC_MAP_PITCH': 2,        # Pitch auf Kanal 2 (Elevator) - nicht verwendet
    'RC_MAP_THROTTLE': 3,     # Throttle auf Kanal 3
    'RC_MAP_YAW': 4,          # Yaw auf Kanal 4 (Rudder) - nicht verwendet
    
    # RC Channel Calibration (Standard RC-Werte)
    'RC1_MIN': 1000,          # Steering minimum
    'RC1_MAX': 2000,          # Steering maximum
    'RC1_TRIM': 1500,         # Steering neutral
    'RC1_DZ': 10,             # Steering deadzone
    
    'RC3_MIN': 1000,          # Throttle minimum
    'RC3_MAX': 2000,          # Throttle maximum
    'RC3_TRIM': 1500,         # Throttle neutral
    'RC3_DZ': 10,             # Throttle deadzone
    
    # ============================================================================
    # SKID STEERING CONFIGURATION
    # ============================================================================
    
    # Skid Steering aktivieren
    'SKID_STEER_OUT': 1,      # Skid Steering Output aktivieren
    'SKID_STEER_IN': 1,       # Skid Steering Input aktivieren
    
    # Servo-Funktionen für Skid Steering
    'SERVO1_FUNCTION': 73,    # ThrottleLeft (Skid Steering)
    'SERVO2_FUNCTION': 74,    # ThrottleRight (Skid Steering)
    
    # ============================================================================
    # DRONECAN ESC CONFIGURATION (2-Motor Setup)
    # ============================================================================
    
    # DroneCAN ESC Parameter (bereits konfiguriert, aber zur Sicherheit)
    'CAN_D1_UC_ESC_BM': 3,    # ESC-Bitmask für 2 ESCs (Bits 0 und 1)
    'SERVO_BLH_MASK': 3,      # BlHeli-Mask für 2 Servos
    'SERVO_BLH_AUTO': 1,      # Automatische BlHeli-Erkennung
    
    # ============================================================================
    # FAILSAFE CONFIGURATION
    # ============================================================================
    
    # RC Failsafe
    'FS_ACTION': 2,           # Failsafe Action: 2 = HOLD
    'FS_TIMEOUT': 5,          # Failsafe Timeout in Sekunden
    'FS_THR_ENABLE': 1,       # Throttle Failsafe aktivieren
    'FS_THR_VALUE': 975,      # Throttle Failsafe Wert (unter RC3_MIN)
    
    # ============================================================================
    # ROVER MODE CONFIGURATION
    # ============================================================================
    
    # Rover-spezifische Parameter
    'MODE1': 0,               # Manual Mode
    'MODE2': 4,               # Hold Mode
    'MODE3': 10,              # Auto Mode
    
    # Arming/Disarming
    'ARMING_REQUIRE': 0,      # Kein Arming erforderlich für Manual Mode
    'ARMING_CHECK': 0,        # Arming Checks deaktivieren (für Tests)
    
    # ============================================================================
    # LOGGING CONFIGURATION
    # ============================================================================
    
    'LOG_DISARMED': 1,        # Logging auch im nicht-armierten Zustand
    'LOG_BACKEND_TYPE': 1,    # File logging
}

def connect_to_orange_cube(connection_string, baudrate):
    """Verbindung zum Orange Cube herstellen"""
    print(f"🔌 Verbinde mit Orange Cube auf {connection_string}...")
    
    try:
        master = mavutil.mavlink_connection(connection_string, baud=baudrate)
        master.wait_heartbeat()
        print(f"✅ Verbindung hergestellt! System ID: {master.target_system}")
        return master
    except Exception as e:
        print(f"❌ Verbindung fehlgeschlagen: {e}")
        return None

def set_parameter(connection, param_name, param_value):
    """Parameter auf dem Orange Cube setzen"""
    print(f"📝 Setze Parameter: {param_name} = {param_value}")
    
    connection.mav.param_set_send(
        connection.target_system,
        connection.target_component,
        param_name.encode('utf-8'),
        param_value,
        mavutil.mavlink.MAV_PARAM_TYPE_REAL32
    )
    
    # Warte auf Bestätigung
    time.sleep(0.1)

def configure_rc_skid_steering(connection):
    """Konfiguriere RC und Skid Steering Parameter"""
    print("\n🎮 Konfiguriere RC Skid Steering...")
    
    total_params = len(RC_SKID_PARAMETERS)
    current_param = 0
    
    for param_name, param_value in RC_SKID_PARAMETERS.items():
        current_param += 1
        print(f"[{current_param}/{total_params}] {param_name} = {param_value}")
        set_parameter(connection, param_name, param_value)
    
    print("✅ RC Skid Steering Parameter gesetzt!")

def verify_configuration(connection):
    """Überprüfe die wichtigsten Parameter"""
    print("\n🔍 Überprüfe Konfiguration...")
    
    # Wichtige Parameter zum Überprüfen
    important_params = [
        'RC_MAP_ROLL', 'RC_MAP_THROTTLE',
        'SERVO1_FUNCTION', 'SERVO2_FUNCTION',
        'SKID_STEER_OUT', 'SKID_STEER_IN',
        'CAN_D1_UC_ESC_BM'
    ]
    
    for param_name in important_params:
        connection.mav.param_request_read_send(
            connection.target_system,
            connection.target_component,
            param_name.encode('utf-8'),
            -1
        )
        time.sleep(0.1)
    
    print("✅ Konfiguration überprüft!")

def main():
    parser = argparse.ArgumentParser(description='Orange Cube RC Skid Steering Konfiguration')
    parser.add_argument('--connection', default=DEFAULT_CONNECTION,
                        help=f'Verbindungsstring (Standard: {DEFAULT_CONNECTION})')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help=f'Baudrate (Standard: {DEFAULT_BAUDRATE})')
    
    args = parser.parse_args()
    
    print("🚀 Orange Cube RC Skid Steering Konfiguration")
    print("=" * 50)
    
    # Verbindung herstellen
    connection = connect_to_orange_cube(args.connection, args.baudrate)
    if not connection:
        sys.exit(1)
    
    try:
        # RC und Skid Steering konfigurieren
        configure_rc_skid_steering(connection)
        
        # Konfiguration überprüfen
        verify_configuration(connection)
        
        print("\n🎉 RC Skid Steering Konfiguration abgeschlossen!")
        print("\n📋 Nächste Schritte:")
        print("1. Orange Cube neu starten (Stromversorgung trennen/verbinden)")
        print("2. RC-Empfänger anschließen und kalibrieren")
        print("3. Mit monitor_rc_input.py RC-Eingänge testen")
        print("4. System im Manual Mode testen")
        
    except KeyboardInterrupt:
        print("\n⚠️ Konfiguration abgebrochen")
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
