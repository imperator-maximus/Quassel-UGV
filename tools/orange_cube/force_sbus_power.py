#!/usr/bin/env python3
"""
Force SBUS Power Configuration

Versucht alle möglichen Parameter zu setzen um SBUS-Stromversorgung zu aktivieren.
"""

import time
import sys
from pymavlink import mavutil

DEFAULT_CONNECTION = 'COM4'
DEFAULT_BAUDRATE = 115200

# Alle möglichen Parameter für Servo/SBUS Stromversorgung
POWER_PARAMETERS = {
    # Servo Stromversorgung
    'BRD_PWM_VOLT_SEL': 1,     # 5V Servo-Versorgung
    'BRD_SERVO_VOLT': 1,       # Servo-Spannung aktivieren
    'BRD_SAFETY_DEFLT': 0,     # Safety Switch deaktivieren
    'BRD_SAFETYENABLE': 0,     # Safety komplett aus
    
    # SBUS auf verschiedenen Ports
    'SERIAL1_PROTOCOL': 23,    # SBUS auf SERIAL1
    'SERIAL1_BAUD': 100000,
    'SERIAL2_PROTOCOL': 23,    # SBUS auf SERIAL2 (Backup)
    'SERIAL2_BAUD': 100000,
    'SERIAL8_PROTOCOL': 23,    # SBUS auf SERIAL8 (CONS Port)
    'SERIAL8_BAUD': 100000,
    
    # RC Protokolle
    'RC_PROTOCOLS': 1,         # SBUS aktivieren
    'RSSI_TYPE': 3,           # SBUS RSSI
    
    # Servo Output aktivieren
    'SERVO_ENABLE': 1,         # Falls verfügbar
    'SERVO_VOLT_PIN': 1,       # Servo Voltage Pin
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

def set_parameter_force(connection, param_name, param_value):
    """Parameter setzen mit Fehlerbehandlung"""
    try:
        print(f"📝 Versuche: {param_name} = {param_value}")
        
        connection.mav.param_set_send(
            connection.target_system,
            connection.target_component,
            param_name.encode('utf-8'),
            param_value,
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32
        )
        
        time.sleep(0.1)
        print(f"   ✅ Gesendet")
        
    except Exception as e:
        print(f"   ❌ Fehler: {e}")

def main():
    print("⚡ Force SBUS Power Configuration")
    print("=" * 50)
    print("Versucht ALLE möglichen Parameter für SBUS-Stromversorgung zu setzen")
    print()
    
    # Verbindung herstellen
    connection = connect_to_orange_cube(DEFAULT_CONNECTION, DEFAULT_BAUDRATE)
    if not connection:
        sys.exit(1)
    
    try:
        print("🔧 Setze alle möglichen Stromversorgungs-Parameter...")
        
        for param_name, param_value in POWER_PARAMETERS.items():
            set_parameter_force(connection, param_name, param_value)
        
        print("\n🎉 Alle Parameter-Versuche abgeschlossen!")
        print("\n📋 Nächste Schritte:")
        print("1. Orange Cube KOMPLETT neu starten (Strom aus/an)")
        print("2. 10 Sekunden warten")
        print("3. SBUS-Empfänger Stromversorgung prüfen")
        print("4. Falls immer noch kein Strom:")
        print("   → Hardware-Problem oder Firmware unterstützt es nicht")
        print("   → Externe 5V-Versorgung verwenden")
        
    except KeyboardInterrupt:
        print("\n⚠️ Abgebrochen")
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
