#!/usr/bin/env python3
"""
Try SERVO3 instead of SERVO2
SERVO2 ist komplett tot! Versuche SERVO3 für den zweiten Motor!
"""

import time
from pymavlink import mavutil

def try_servo3():
    print("🔧 Try SERVO3 instead of SERVO2...")
    print("❌ Problem: SERVO2 ist komplett tot (immer 0 μs)")
    print("💡 Lösung: SERVO3 für den zweiten Motor verwenden!")
    
    # Connect to Orange Cube
    print("🔌 Connecting to Orange Cube...")
    try:
        connection = mavutil.mavlink_connection('COM4', baud=115200)
        connection.wait_heartbeat()
        print("✅ Connected to Orange Cube")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return
    
    # SERVO3 statt SERVO2 verwenden!
    parameters = {
        # Servo Functions - SERVO3 statt SERVO2!
        'SERVO1_FUNCTION': 26,    # Throttle Left (Motor 1)
        'SERVO2_FUNCTION': 0,     # DEAKTIVIERT (ist sowieso kaputt)
        'SERVO3_FUNCTION': 27,    # Throttle Right (Motor 2) - SERVO3 statt SERVO2!
        'SERVO4_FUNCTION': 0,     # Disabled
        
        # Servo3 Konfiguration (statt Servo2)
        'SERVO3_MIN': 1000,       # Servo3 minimum PWM
        'SERVO3_MAX': 2000,       # Servo3 maximum PWM
        'SERVO3_TRIM': 1500,      # Servo3 neutral PWM
        'SERVO3_REVERSED': 0,     # Servo3 normal direction
        
        # Servo1 Konfiguration (bleibt gleich)
        'SERVO1_MIN': 1000,       # Servo1 minimum PWM
        'SERVO1_MAX': 2000,       # Servo1 maximum PWM
        'SERVO1_TRIM': 1500,      # Servo1 neutral PWM
        'SERVO1_REVERSED': 0,     # Servo1 normal direction
        
        # DroneCAN ESC Konfiguration - ESC1 + ESC3 (statt ESC2!)
        'CAN_D1_UC_ESC_BM': 5,    # ESC Bitmask: 5 = ESC1 + ESC3 (binary: 101)
        'SERVO_BLH_MASK': 5,      # BLHeli Mask: 5 = Servo1 + Servo3
        
        # Frame Konfiguration
        'FRAME_TYPE': 1,          # Skid Steering
        'FRAME_CLASS': 2,         # Rover
        
        # RC Mapping
        'RCMAP_ROLL': 1,          # RC1 für Steering
        'RCMAP_THROTTLE': 2,      # RC2 für Throttle
        'RCMAP_PITCH': 0,         # Disable
        'RCMAP_YAW': 0,           # Disable
    }
    
    print("\n📝 Setting SERVO3 instead of SERVO2...")
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
    
    print("\n✅ SERVO3 configuration set!")
    print("\n🎯 Das sollte das Problem lösen:")
    print("   - SERVO1 = ESC1 (Motor 1)")
    print("   - SERVO3 = ESC3 (Motor 2) - statt SERVO2!")
    print("   - SERVO2 ist deaktiviert (war sowieso kaputt)")
    print("   - CAN_D1_UC_ESC_BM = 5 (ESC1 + ESC3)")
    print("\n📋 Next Steps:")
    print("1. Orange Cube neu starten")
    print("2. PWM Monitor anpassen für ESC1 und ESC3")
    print("3. Testen ob SERVO3 funktioniert!")

if __name__ == "__main__":
    try_servo3()
