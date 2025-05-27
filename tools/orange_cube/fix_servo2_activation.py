#!/usr/bin/env python3
"""
Fix Servo2 Activation - ESC2 ist komplett deaktiviert!
Das ist der Grund warum nur ein Motor funktioniert!

Problem: Servo2 (ESC2) = 0 μs (immer AUS)
Lösung: Servo2 aktivieren und konfigurieren
"""

import time
from pymavlink import mavutil

def fix_servo2():
    print("🔧 Fixing Servo2 Activation...")
    print("❌ Problem: ESC2 ist komplett deaktiviert (immer 0 μs)")
    print("✅ Lösung: Servo2 aktivieren für zweiten Motor")
    
    # Connect to Orange Cube
    print("🔌 Connecting to Orange Cube...")
    try:
        connection = mavutil.mavlink_connection('COM4', baud=115200)
        connection.wait_heartbeat()
        print("✅ Connected to Orange Cube")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return
    
    # Servo2 Aktivierung - das ist der Schlüssel!
    parameters = {
        # Servo Functions - BEIDE Servos aktivieren!
        'SERVO1_FUNCTION': 26,    # Throttle Left (Motor 1)
        'SERVO2_FUNCTION': 27,    # Throttle Right (Motor 2) - DAS WAR DEAKTIVIERT!
        
        # Servo2 Konfiguration (war komplett missing!)
        'SERVO2_MIN': 1000,       # Servo2 minimum PWM
        'SERVO2_MAX': 2000,       # Servo2 maximum PWM
        'SERVO2_TRIM': 1500,      # Servo2 neutral PWM
        'SERVO2_REVERSED': 0,     # Servo2 normal direction
        
        # Servo1 Konfiguration (zur Sicherheit)
        'SERVO1_MIN': 1000,       # Servo1 minimum PWM
        'SERVO1_MAX': 2000,       # Servo1 maximum PWM
        'SERVO1_TRIM': 1500,      # Servo1 neutral PWM
        'SERVO1_REVERSED': 0,     # Servo1 normal direction
        
        # DroneCAN ESC Konfiguration - BEIDE ESCs aktivieren!
        'CAN_D1_UC_ESC_BM': 3,    # ESC Bitmask: 3 = ESC1 + ESC2 (binary: 11)
        'SERVO_BLH_MASK': 3,      # BLHeli Mask: 3 = Servo1 + Servo2
        
        # Frame Konfiguration
        'FRAME_TYPE': 1,          # Skid Steering
        'FRAME_CLASS': 2,         # Rover
        
        # RC Mapping (zurück zu Standard)
        'RC_MAP_ROLL': 1,         # RC1 für Steering
        'RC_MAP_THROTTLE': 2,     # RC2 für Throttle
        'RC_MAP_PITCH': 0,        # Disable pitch
        'RC_MAP_YAW': 0,          # Disable yaw
    }
    
    print("\n📝 Setting Servo2 activation parameters...")
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
    
    print("\n✅ Servo2 activation parameters set!")
    print("\n🎯 Das sollte das Problem lösen:")
    print("   - Servo2 ist jetzt aktiviert (SERVO2_FUNCTION = 27)")
    print("   - ESC2 sollte jetzt PWM-Werte bekommen!")
    print("   - Beide Motoren sollten funktionieren!")
    print("\n📋 Next Steps:")
    print("1. Orange Cube neu starten")
    print("2. PWM Monitor testen: python monitor_pwm_before_can.py")
    print("3. Beide ESC1 und ESC2 sollten jetzt Werte zeigen!")

if __name__ == "__main__":
    fix_servo2()
