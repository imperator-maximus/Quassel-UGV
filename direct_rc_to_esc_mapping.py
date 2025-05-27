#!/usr/bin/env python3
"""
DIRECT RC to ESC Mapping
Basierend auf deinen find_throttle_channel.py Ergebnissen:
RC1 und RC2 sind MIXED CHANNELS - direkte Motor-Werte!

RC1 → ESC1 (Linker Motor)
RC2 → ESC3 (Rechter Motor, da ESC2 kaputt ist)
"""

import time
from pymavlink import mavutil

def direct_rc_mapping():
    print("🎯 DIRECT RC to ESC Mapping...")
    print("📊 Deine RC-Werte Analysis:")
    print("   Links: RC1=995, RC2=1995    → RC1 niedrig, RC2 hoch")
    print("   Rechts: RC1=2115, RC2=1166  → RC1 hoch, RC2 niedrig")
    print("   Vorne: RC1=1995, RC2=1995   → Beide hoch")
    print("   Zurück: RC1=995, RC2=995    → Beide niedrig")
    print("   → MIXED CHANNELS! Direkte Motor-Werte!")
    print()
    print("💡 LÖSUNG: Direct Mapping:")
    print("   RC1 → ESC1 (Linker Motor)")
    print("   RC2 → ESC3 (Rechter Motor)")
    
    # Connect to Orange Cube
    print("\n🔌 Connecting to Orange Cube...")
    try:
        connection = mavutil.mavlink_connection('COM4', baud=115200)
        connection.wait_heartbeat()
        print("✅ Connected to Orange Cube")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return
    
    # DIRECT RC to ESC Mapping!
    parameters = {
        # Direct RC Passthrough - das ist der Schlüssel!
        'SERVO1_FUNCTION': 1,     # RC1 passthrough → ESC1
        'SERVO2_FUNCTION': 0,     # Disabled (kaputt)
        'SERVO3_FUNCTION': 2,     # RC2 passthrough → ESC3
        'SERVO4_FUNCTION': 0,     # Disabled
        
        # RC Kalibrierung (deine gemessenen Werte)
        'RC1_MIN': 995,           # RC1 minimum
        'RC1_MAX': 2115,          # RC1 maximum
        'RC1_TRIM': 1555,         # RC1 center
        'RC1_DZ': 50,             # RC1 deadzone
        
        'RC2_MIN': 1166,          # RC2 minimum
        'RC2_MAX': 1995,          # RC2 maximum
        'RC2_TRIM': 1580,         # RC2 center
        'RC2_DZ': 50,             # RC2 deadzone
        
        # Servo Konfiguration
        'SERVO1_MIN': 1000,       # ESC1 minimum
        'SERVO1_MAX': 2000,       # ESC1 maximum
        'SERVO1_TRIM': 1500,      # ESC1 neutral
        
        'SERVO3_MIN': 1000,       # ESC3 minimum
        'SERVO3_MAX': 2000,       # ESC3 maximum
        'SERVO3_TRIM': 1500,      # ESC3 neutral
        
        # DroneCAN ESC Konfiguration - ESC1 + ESC3
        'CAN_D1_UC_ESC_BM': 5,    # ESC Bitmask: 5 = ESC1 + ESC3 (binary: 101)
        'SERVO_BLH_MASK': 5,      # BLHeli Mask: 5 = Servo1 + Servo3
        
        # Frame Configuration - Manual/Generic
        'FRAME_TYPE': 0,          # Manual (nicht Skid Steering!)
        'FRAME_CLASS': 2,         # Rover
        
        # RC Mapping - Disable automatic mixing
        'RCMAP_ROLL': 0,          # Disable
        'RCMAP_THROTTLE': 0,      # Disable
        'RCMAP_PITCH': 0,         # Disable
        'RCMAP_YAW': 0,           # Disable
    }
    
    print("\n📝 Setting DIRECT RC to ESC mapping...")
    for param, value in parameters.items():
        connection.mav.param_set_send(
            connection.target_system,
            connection.target_component,
            param.encode('utf-8'),
            value,
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32
        )
        print(f"   {param} = {value}")
        time.sleep(0.1)
    
    print("\n✅ DIRECT RC to ESC mapping set!")
    print("\n🎯 Das sollte ENDLICH funktionieren:")
    print("   - RC1 → SERVO1 → ESC1 (Linker Motor)")
    print("   - RC2 → SERVO3 → ESC3 (Rechter Motor)")
    print("   - Dein Controller macht das Mixing!")
    print("   - Kein automatisches Skid Steering!")
    print("\n📋 Next Steps:")
    print("1. Orange Cube neu starten")
    print("2. PWM Monitor für ESC1 und ESC3 testen")
    print("3. BEIDE Motoren sollten jetzt funktionieren!")
    print("\n💡 Erwartetes Verhalten:")
    print("   - Vorne: ESC1=hoch, ESC3=hoch")
    print("   - Links: ESC1=niedrig, ESC3=hoch")
    print("   - Rechts: ESC1=hoch, ESC3=niedrig")

if __name__ == "__main__":
    direct_rc_mapping()
