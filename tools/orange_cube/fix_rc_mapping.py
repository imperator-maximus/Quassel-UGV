#!/usr/bin/env python3
"""
Orange Cube RC Mapping Fix

Korrigiert RC_MAP_THROTTLE von Kanal 3 auf Kanal 2.
Löst das Problem: Throttle kommt auf RC2, nicht RC3.

Author: Beyond Robotics Integration
Date: 2024
"""

import time
import sys
from pymavlink import mavutil

# Standard-Verbindungseinstellungen
DEFAULT_CONNECTION = 'COM4'
DEFAULT_BAUDRATE = 115200

# KORRIGIERTE RC-Parameter basierend auf find_throttle_channel.py Ergebnissen
RC_FIX_PARAMETERS = {
    # ANALYSE deiner RC-Werte:
    # Links: RC1=995, RC2=1995    → RC1 niedrig, RC2 hoch
    # Rechts: RC1=2115, RC2=1166  → RC1 hoch, RC2 niedrig
    # Vorne: RC1=1995, RC2=1995   → Beide hoch
    # Zurück: RC1=995, RC2=995    → Beide niedrig
    # → Dein Controller macht MIXED CHANNELS, nicht separates Throttle/Steering!

    # Versuche verschiedene RC-Mappings
    'RC_MAP_ROLL': 1,         # RC1 für Steering (Links/Rechts)
    'RC_MAP_THROTTLE': 2,     # RC2 für Throttle (Vor/Zurück)

    # Alternative: Versuche umgekehrt
    # 'RC_MAP_ROLL': 2,         # RC2 für Steering
    # 'RC_MAP_THROTTLE': 1,     # RC1 für Throttle

    # RC1 Kalibrierung (deine gemessenen Werte)
    'RC1_MIN': 995,           # RC1 minimum (Links/Zurück)
    'RC1_MAX': 2115,          # RC1 maximum (Rechts/Vorne)
    'RC1_TRIM': 1555,         # RC1 center (995+2115)/2
    'RC1_DZ': 50,             # RC1 deadzone

    # RC2 Kalibrierung (deine gemessenen Werte)
    'RC2_MIN': 1166,          # RC2 minimum (Rechts/Zurück)
    'RC2_MAX': 1995,          # RC2 maximum (Links/Vorne)
    'RC2_TRIM': 1580,         # RC2 center (1166+1995)/2
    'RC2_DZ': 50,             # RC2 deadzone

    # Skid Steering Frame
    'FRAME_TYPE': 1,          # Skid Steering
    'FRAME_CLASS': 2,         # Rover
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

def fix_rc_mapping(connection):
    """Korrigiere RC-Mapping und Kalibrierung"""
    print("\n🔧 KORRIGIERE RC-MAPPING:")
    print("=" * 50)
    print("🎯 Problem: Throttle war auf RC3, ist aber auf RC2")
    print("✅ Lösung: RC_MAP_THROTTLE = 2")
    print()

    total_params = len(RC_FIX_PARAMETERS)
    current_param = 0

    for param_name, param_value in RC_FIX_PARAMETERS.items():
        current_param += 1
        print(f"[{current_param}/{total_params}] {param_name} = {param_value}")
        set_parameter(connection, param_name, param_value)

    print("✅ RC-Mapping korrigiert!")

def main():
    print("🔧 Orange Cube RC Mapping Fix")
    print("=" * 50)
    print("Korrigiert RC_MAP_THROTTLE von Kanal 3 auf Kanal 2")
    print("Verwendet ECHTE gemessene RC-Werte für Kalibrierung")
    print()

    # Verbindung herstellen
    connection = connect_to_orange_cube(DEFAULT_CONNECTION, DEFAULT_BAUDRATE)
    if not connection:
        sys.exit(1)

    try:
        # RC-Mapping korrigieren
        fix_rc_mapping(connection)

        print("\n🎉 RC-Mapping Fix abgeschlossen!")
        print("\n📊 DEINE RC-WERTE ANALYSE:")
        print("   Links: RC1=995, RC2=1995    → RC1 niedrig, RC2 hoch")
        print("   Rechts: RC1=2115, RC2=1166  → RC1 hoch, RC2 niedrig")
        print("   Vorne: RC1=1995, RC2=1995   → Beide hoch")
        print("   Zurück: RC1=995, RC2=995    → Beide niedrig")
        print("   → MIXED CHANNELS! Nicht separates Throttle/Steering!")
        print()
        print("📋 NÄCHSTE SCHRITTE:")
        print("1. Orange Cube neu starten")
        print("2. Beyond Robotics Board testen:")
        print("   python ../monitor_real_esc_commands.py")
        print("3. Teste alle 4 Stick-Richtungen!")
        print()
        print("🎯 ERWARTETES ERGEBNIS (wenn RC-Mapping stimmt):")
        print("   Vorne:  Motors: 8100, 8100  →  ESC: [1994, 1994]")
        print("   Links:  Motors: 8100, 0     →  ESC: [1994, 1500]")
        print("   Rechts: Motors: 0, 8100     →  ESC: [1500, 1994]")
        print("   Zurück: Motors: -8100, -8100 → ESC: [1006, 1006]")
        print()
        print("❌ Falls immer noch falsch: RC-Mapping umkehren!")
        print("   Editiere fix_rc_mapping.py und tausche RC1 ↔ RC2")

    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
