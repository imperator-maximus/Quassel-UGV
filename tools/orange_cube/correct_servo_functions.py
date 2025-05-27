#!/usr/bin/env python3
"""
CORRECT Servo Functions from Context7!
Das Problem: Wir haben falsche SERVO_FUNCTION Werte verwendet!

RICHTIG (Context7):
- SERVO1_FUNCTION = 73 (ThrottleLeft Skid Steering)
- SERVO2_FUNCTION = 74 (ThrottleRight Skid Steering)

FALSCH (was wir verwendet haben):
- SERVO1_FUNCTION = 26 
- SERVO2_FUNCTION = 27
"""

import time
from pymavlink import mavutil

def correct_servo_functions():
    print("🎯 CORRECT Servo Functions from Context7!")
    print("❌ Problem: Falsche SERVO_FUNCTION Werte!")
    print("✅ Lösung: Context7 Konfiguration verwenden!")
    print()
    print("📋 RICHTIGE Werte (Context7):")
    print("   SERVO1_FUNCTION = 73 (ThrottleLeft Skid Steering)")
    print("   SERVO2_FUNCTION = 74 (ThrottleRight Skid Steering)")
    
    # Connect to Orange Cube
    print("\n🔌 Connecting to Orange Cube...")
    try:
        connection = mavutil.mavlink_connection('COM4', baud=115200)
        connection.wait_heartbeat()
        print("✅ Connected to Orange Cube")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return
    
    # RICHTIGE Context7 Konfiguration!
    parameters = {
        # RICHTIGE Servo Functions (Context7)
        'SERVO1_FUNCTION': 73,    # ThrottleLeft (Skid Steering)
        'SERVO2_FUNCTION': 74,    # ThrottleRight (Skid Steering)
        'SERVO3_FUNCTION': 0,     # Disabled
        'SERVO4_FUNCTION': 0,     # Disabled
        
        # Servo Konfiguration
        'SERVO1_MIN': 1000,       # Servo1 minimum
        'SERVO1_MAX': 2000,       # Servo1 maximum
        'SERVO1_TRIM': 1500,      # Servo1 neutral
        
        'SERVO2_MIN': 1000,       # Servo2 minimum
        'SERVO2_MAX': 2000,       # Servo2 maximum
        'SERVO2_TRIM': 1500,      # Servo2 neutral
        
        # DroneCAN ESC Konfiguration (Context7)
        'CAN_D1_UC_ESC_BM': 3,    # ESC Bitmask: 3 = ESC1 + ESC2
        'SERVO_BLH_MASK': 3,      # BLHeli Mask: 3 = Servo1 + Servo2
        'SERVO_BLH_AUTO': 1,      # Auto BLHeli detection
        
        # Frame Configuration (Context7)
        'FRAME_TYPE': 1,          # Skid Steering
        'FRAME_CLASS': 2,         # Rover
        
        # Skid Steering aktivieren (Context7)
        'SKID_STEER_OUT': 1,      # Skid Steering Output aktivieren
        'SKID_STEER_IN': 1,       # Skid Steering Input aktivieren
        
        # RC Mapping für deine Mixed Channels
        'RCMAP_ROLL': 1,          # RC1 = Steering
        'RCMAP_THROTTLE': 2,      # RC2 = Throttle
        'RCMAP_PITCH': 0,         # Disable
        'RCMAP_YAW': 0,           # Disable
        
        # RC Kalibrierung (deine Werte)
        'RC1_MIN': 995,           # RC1 minimum
        'RC1_MAX': 2115,          # RC1 maximum
        'RC1_TRIM': 1555,         # RC1 center
        'RC1_DZ': 50,             # RC1 deadzone
        
        'RC2_MIN': 1166,          # RC2 minimum
        'RC2_MAX': 1995,          # RC2 maximum
        'RC2_TRIM': 1580,         # RC2 center
        'RC2_DZ': 50,             # RC2 deadzone
    }
    
    print("\n📝 Setting CORRECT Context7 parameters...")
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
    
    print("\n✅ CORRECT Context7 configuration set!")
    print("\n🎯 Das sollte ENDLICH funktionieren:")
    print("   - SERVO1_FUNCTION = 73 (ThrottleLeft)")
    print("   - SERVO2_FUNCTION = 74 (ThrottleRight)")
    print("   - Skid Steering aktiviert")
    print("   - ESC1 und ESC2 sollten beide funktionieren!")
    print("\n📋 Next Steps:")
    print("1. Orange Cube neu starten")
    print("2. PWM Monitor für ESC1 und ESC2 testen")
    print("3. BEIDE Motoren sollten jetzt funktionieren!")

if __name__ == "__main__":
    correct_servo_functions()
