#!/usr/bin/env python3
"""
Orange Cube SBUS Configuration Script

Konfiguriert den Orange Cube für SBUS RC-Empfänger.
Setzt die notwendigen SERIAL-Parameter für SBUS-Unterstützung.

Author: Beyond Robotics Integration
Date: 2024
"""

import time
import sys
import argparse
from pymavlink import mavutil

# Standard-Verbindungseinstellungen
DEFAULT_CONNECTION = 'COM4'
DEFAULT_BAUDRATE = 115200

# SBUS Parameter
SBUS_PARAMETERS = {
    # SBUS auf SERIAL1 (Standard SBUS-Port)
    'SERIAL1_PROTOCOL': 23,    # SBUS Protocol
    'SERIAL1_BAUD': 100000,    # SBUS Baudrate (100k)
    
    # RC Input Konfiguration
    'RC_PROTOCOLS': 1,         # SBUS aktivieren (Bit 0)
    'RSSI_TYPE': 3,            # SBUS RSSI
    
    # Backup: Falls SERIAL1 nicht funktioniert, versuche SERIAL2
    'SERIAL2_PROTOCOL': 23,    # SBUS Protocol (Backup)
    'SERIAL2_BAUD': 100000,    # SBUS Baudrate (Backup)
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
    time.sleep(0.2)

def configure_sbus(connection):
    """Konfiguriere SBUS Parameter"""
    print("\n📡 Konfiguriere SBUS...")
    
    total_params = len(SBUS_PARAMETERS)
    current_param = 0
    
    for param_name, param_value in SBUS_PARAMETERS.items():
        current_param += 1
        print(f"[{current_param}/{total_params}] {param_name} = {param_value}")
        set_parameter(connection, param_name, param_value)
    
    print("✅ SBUS Parameter gesetzt!")

def verify_sbus_config(connection):
    """Überprüfe SBUS Konfiguration"""
    print("\n🔍 Überprüfe SBUS Konfiguration...")
    
    # Wichtige SBUS Parameter anfordern
    sbus_params = ['SERIAL1_PROTOCOL', 'SERIAL1_BAUD', 'RC_PROTOCOLS']
    
    for param_name in sbus_params:
        connection.mav.param_request_read_send(
            connection.target_system,
            connection.target_component,
            param_name.encode('utf-8'),
            -1
        )
        time.sleep(0.1)
    
    print("✅ SBUS Konfiguration überprüft!")

def test_sbus_power(connection):
    """Teste SBUS Stromversorgung"""
    print("\n⚡ SBUS Stromversorgung Test...")
    print("📋 Manuelle Checks:")
    print("1. Orange Cube eingeschaltet? ✓")
    print("2. SBUS-Empfänger richtig angeschlossen?")
    print("   - Signal → SBUS Signal Pin")
    print("   - + → SBUS +5V Pin") 
    print("   - GND → SBUS GND Pin")
    print("3. LED am SBUS-Empfänger leuchtet?")
    print("4. Fernbedienung eingeschaltet und gebunden?")
    
    print("\n💡 Falls immer noch kein Strom:")
    print("- Externe 5V-Versorgung für SBUS-Empfänger verwenden")
    print("- Nur Signal-Pin an Orange Cube, Strom separat")

def main():
    parser = argparse.ArgumentParser(description='Orange Cube SBUS Konfiguration')
    parser.add_argument('--connection', default=DEFAULT_CONNECTION,
                        help=f'Verbindungsstring (Standard: {DEFAULT_CONNECTION})')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help=f'Baudrate (Standard: {DEFAULT_BAUDRATE})')
    
    args = parser.parse_args()
    
    print("📡 Orange Cube SBUS Konfiguration")
    print("=" * 50)
    
    # Verbindung herstellen
    connection = connect_to_orange_cube(args.connection, args.baudrate)
    if not connection:
        sys.exit(1)
    
    try:
        # SBUS konfigurieren
        configure_sbus(connection)
        
        # Konfiguration überprüfen
        verify_sbus_config(connection)
        
        # Stromversorgung Test-Info
        test_sbus_power(connection)
        
        print("\n🎉 SBUS Konfiguration abgeschlossen!")
        print("\n📋 Nächste Schritte:")
        print("1. Orange Cube neu starten (Stromversorgung trennen/verbinden)")
        print("2. SBUS-Empfänger Stromversorgung prüfen")
        print("3. RC-Test mit python rc_test_guide.py")
        print("4. Falls kein Strom: Externe 5V-Versorgung verwenden")
        
    except KeyboardInterrupt:
        print("\n⚠️ SBUS Konfiguration abgebrochen")
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
