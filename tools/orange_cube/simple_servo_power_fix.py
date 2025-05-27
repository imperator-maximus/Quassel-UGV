#!/usr/bin/env python3
"""
Simple Servo Power Fix - Ohne Bestätigung
"""

import time
from pymavlink import mavutil

def main():
    print("⚡ Simple Servo Power Fix")
    print("=" * 30)
    
    # Verbindung
    master = mavutil.mavlink_connection('COM4', baud=115200)
    master.wait_heartbeat()
    print("✅ Verbunden")
    
    # Parameter setzen (ohne Bestätigung)
    print("📝 Setze BRD_PWM_VOLT_SEL = 1")
    master.mav.param_set_send(
        master.target_system,
        master.target_component,
        'BRD_PWM_VOLT_SEL'.encode('utf-8'),
        1.0,
        mavutil.mavlink.MAV_PARAM_TYPE_REAL32
    )
    
    time.sleep(1)
    print("✅ Parameter gesendet!")
    print("\n🔄 Orange Cube neu starten (Strom aus/an)")
    print("🔌 SBUS-Empfänger sollte dann Strom bekommen")
    
    master.close()

if __name__ == "__main__":
    main()
