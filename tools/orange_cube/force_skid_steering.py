#!/usr/bin/env python3
"""
Force REAL Skid Steering Configuration
Das Problem: Orange Cube verwendet nur einen RC-Kanal für beide Motoren!
Lösung: Echtes Skid Steering mit separaten Throttle/Steering Kanälen
"""

import time
from pymavlink import mavutil

def force_skid_steering():
    print("🔧 Force REAL Skid Steering Configuration...")
    print("❌ Problem: Orange Cube verwendet nur einen RC-Kanal!")
    print("✅ Lösung: Echtes Skid Steering mit Throttle + Steering")
    
    # Connect to Orange Cube
    print("🔌 Connecting to Orange Cube...")
    try:
        connection = mavutil.mavlink_connection('COM4', baud=115200)
        connection.wait_heartbeat()
        print("✅ Connected to Orange Cube")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return
    
    # ECHTES Skid Steering - das ist der Schlüssel!
    parameters = {
        # Frame Configuration - WICHTIG!
        'FRAME_CLASS': 2,         # Rover
        'FRAME_TYPE': 1,          # Skid Steering (nicht Manual!)
        
        # RC Channel Mapping - KORREKT für Skid Steering
        'RCMAP_ROLL': 1,          # RC1 = Steering (Links/Rechts)
        'RCMAP_THROTTLE': 2,      # RC2 = Throttle (Vor/Zurück)
        'RCMAP_PITCH': 0,         # Disable
        'RCMAP_YAW': 0,           # Disable
        
        # Servo Functions - BEIDE für Skid Steering
        'SERVO1_FUNCTION': 26,    # Throttle Left
        'SERVO2_FUNCTION': 27,    # Throttle Right
        'SERVO3_FUNCTION': 0,     # Disabled
        'SERVO4_FUNCTION': 0,     # Disabled
        
        # Motor Configuration
        'MOT_PWM_TYPE': 0,        # Normal PWM
        'MOT_SKID_FRIC': 0.3,     # Skid friction
        
        # RC Calibration (deine gemessenen Werte)
        'RC1_MIN': 995,           # RC1 minimum
        'RC1_MAX': 2115,          # RC1 maximum
        'RC1_TRIM': 1555,         # RC1 center
        'RC1_DZ': 50,             # RC1 deadzone
        
        'RC2_MIN': 1166,          # RC2 minimum
        'RC2_MAX': 1995,          # RC2 maximum
        'RC2_TRIM': 1580,         # RC2 center
        'RC2_DZ': 50,             # RC2 deadzone
        
        # Servo Configuration
        'SERVO1_MIN': 1000,       # Servo1 minimum
        'SERVO1_MAX': 2000,       # Servo1 maximum
        'SERVO1_TRIM': 1500,      # Servo1 neutral
        
        'SERVO2_MIN': 1000,       # Servo2 minimum
        'SERVO2_MAX': 2000,       # Servo2 maximum
        'SERVO2_TRIM': 1500,      # Servo2 neutral
        
        # DroneCAN Configuration
        'CAN_D1_UC_ESC_BM': 3,    # ESC Bitmask: ESC1 + ESC2
        'SERVO_BLH_MASK': 3,      # BLHeli Mask: Servo1 + Servo2
        
        # Safety
        'ARMING_CHECK': 0,        # Disable arming checks for testing
    }
    
    print("\n📝 Setting REAL Skid Steering parameters...")
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
    
    print("\n✅ REAL Skid Steering configuration set!")
    print("\n🎯 Das sollte das Problem lösen:")
    print("   - FRAME_TYPE = 1 (Skid Steering)")
    print("   - RC1 = Steering, RC2 = Throttle")
    print("   - Servo1 = Left Motor, Servo2 = Right Motor")
    print("   - Orange Cube macht automatisches Mixing!")
    print("\n📋 Next Steps:")
    print("1. Orange Cube neu starten")
    print("2. PWM Monitor testen")
    print("3. BEIDE ESC1 und ESC2 sollten jetzt funktionieren!")
    print("\n💡 Erwartetes Verhalten:")
    print("   - Throttle vor: ESC1=hoch, ESC2=hoch")
    print("   - Steering links: ESC1=niedrig, ESC2=hoch")
    print("   - Steering rechts: ESC1=hoch, ESC2=niedrig")

if __name__ == "__main__":
    force_skid_steering()
