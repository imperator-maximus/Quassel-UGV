#!/usr/bin/env python3
"""
Orange Cube RC Channel Finder

Zeigt ALLE RC-Kanäle live an, um den echten Throttle-Kanal zu finden.
Löst das Problem: Throttle ist wahrscheinlich auf Kanal 2 statt 3.

Author: Beyond Robotics Integration
Date: 2024
"""

import time
import sys
from pymavlink import mavutil

# Standard-Verbindungseinstellungen
DEFAULT_CONNECTION = 'COM4'
DEFAULT_BAUDRATE = 115200

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

def monitor_all_rc_channels(connection):
    """Zeige alle RC-Kanäle live an"""
    print("\n🎮 ALLE RC-KANÄLE LIVE MONITOR")
    print("=" * 80)
    print("📋 ANWEISUNGEN:")
    print("1. Lassen Sie den Stick in NEUTRAL-Position")
    print("2. Dann bewegen Sie den Stick VOR/ZURÜCK")
    print("3. Schauen Sie, welcher Kanal sich ändert!")
    print("4. Das ist Ihr ECHTER Throttle-Kanal!")
    print("\nDrücken Sie Ctrl+C zum Beenden")
    print("=" * 80)
    
    try:
        while True:
            msg = connection.recv_match(type=['RC_CHANNELS_RAW', 'RC_CHANNELS'], blocking=True, timeout=1)
            if msg:
                # Alle Kanäle anzeigen
                channels = []
                for i in range(1, 9):  # RC1 bis RC8
                    chan_attr = f'chan{i}_raw'
                    value = getattr(msg, chan_attr, 0)
                    channels.append(f"RC{i}:{value:4d}")
                
                # Live-Anzeige (überschreibt vorherige Zeile)
                channel_display = " | ".join(channels)
                print(f"\r🎮 {channel_display}", end='', flush=True)
                
                time.sleep(0.1)  # 10Hz Update
            else:
                print("\r❌ Keine RC-Daten empfangen!", end='', flush=True)
                
    except KeyboardInterrupt:
        print("\n\n✅ RC-Monitor beendet")
        return True

def analyze_channels():
    """Hilfe zur Kanal-Analyse"""
    print("\n🔍 KANAL-ANALYSE HILFE:")
    print("=" * 50)
    print("📊 Was Sie sehen sollten:")
    print()
    print("🎯 STEERING (Links/Rechts):")
    print("   - RC1 sollte sich ändern: ~956 bis ~2038")
    print("   - Neutral: ~1495")
    print()
    print("🎯 THROTTLE (Vor/Zurück):")
    print("   - Einer der anderen Kanäle (RC2, RC3, RC4) ändert sich")
    print("   - Schauen Sie, welcher!")
    print()
    print("💡 HÄUFIGE KANÄLE:")
    print("   - RC1: Steering (Aileron)")
    print("   - RC2: Throttle (Elevator) ← WAHRSCHEINLICH HIER!")
    print("   - RC3: Throttle (Standard)")
    print("   - RC4: Yaw (Rudder)")

def main():
    print("🔍 Orange Cube RC Channel Finder")
    print("=" * 50)
    print("Findet den ECHTEN Throttle-Kanal!")
    print()
    
    # Verbindung herstellen
    connection = connect_to_orange_cube(DEFAULT_CONNECTION, DEFAULT_BAUDRATE)
    if not connection:
        sys.exit(1)
    
    try:
        # Hilfe anzeigen
        analyze_channels()
        
        input("\nDrücken Sie ENTER um den RC-Monitor zu starten...")
        
        # RC-Kanäle überwachen
        monitor_all_rc_channels(connection)
        
        print("\n🎯 NÄCHSTE SCHRITTE:")
        print("1. Notieren Sie sich den Kanal, der sich bei Vor/Zurück ändert")
        print("2. Das ist Ihr echter Throttle-Kanal!")
        print("3. Dann können wir RC_MAP_THROTTLE richtig setzen")
        
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
