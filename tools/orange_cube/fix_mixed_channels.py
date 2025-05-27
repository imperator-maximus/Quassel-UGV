#!/usr/bin/env python3
"""
Fix Mixed Channel RC System for Orange Cube
Based on your REAL measured RC values that show mixed channels, not standard skid steering

Your RC Values:
- Links: RC1=995, RC2=1995    → RC1 low, RC2 high
- Rechts: RC1=2115, RC2=1166  → RC1 high, RC2 low
- Vorne: RC1=1995, RC2=1995   → Both high
- Zurück: RC1=995, RC2=995    → Both low

This is MIXED CHANNELS, not separate throttle/steering!
"""

import time
from pymavlink import mavutil

def fix_mixed_channels():
    print("🔧 Fixing Mixed Channel RC System...")
    print("📊 Your RC Values Analysis:")
    print("   Links: RC1=995, RC2=1995    → RC1 low, RC2 high")
    print("   Rechts: RC1=2115, RC2=1166  → RC1 high, RC2 low")
    print("   Vorne: RC1=1995, RC2=1995   → Both high")
    print("   Zurück: RC1=995, RC2=995    → Both low")
    print("   → MIXED CHANNELS! Need custom mixing!")

    # Connect to Orange Cube
    print("🔌 Connecting to Orange Cube...")
    try:
        connection = mavutil.mavlink_connection('COM4', baud=115200)
        connection.wait_heartbeat()
        print("✅ Connected to Orange Cube")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return

    # Configure for MIXED CHANNELS instead of standard skid steering
    parameters = {
        # Use RC1 and RC2 as direct motor inputs (mixed channels)
        'RC_MAP_ROLL': 0,         # Disable roll
        'RC_MAP_PITCH': 0,        # Disable pitch
        'RC_MAP_THROTTLE': 0,     # Disable throttle
        'RC_MAP_YAW': 0,          # Disable yaw

        # Use manual servo functions for direct RC mapping
        'SERVO1_FUNCTION': 1,     # RC1 passthrough to Servo1 (left motor)
        'SERVO3_FUNCTION': 2,     # RC2 passthrough to Servo3 (right motor)

        # RC1 calibration (your measured values)
        'RC1_MIN': 995,           # RC1 minimum
        'RC1_MAX': 2115,          # RC1 maximum
        'RC1_TRIM': 1555,         # RC1 center
        'RC1_DZ': 50,             # RC1 deadzone
        'RC1_REVERSED': 0,        # Normal direction

        # RC2 calibration (your measured values)
        'RC2_MIN': 1166,          # RC2 minimum
        'RC2_MAX': 1995,          # RC2 maximum
        'RC2_TRIM': 1580,         # RC2 center
        'RC2_DZ': 50,             # RC2 deadzone
        'RC2_REVERSED': 0,        # Normal direction

        # Frame configuration - try manual mode
        'FRAME_TYPE': 0,          # Manual/Generic
        'FRAME_CLASS': 2,         # Rover

        # Servo output configuration
        'SERVO1_MIN': 1000,       # Left motor minimum
        'SERVO1_MAX': 2000,       # Left motor maximum
        'SERVO1_TRIM': 1500,      # Left motor neutral

        'SERVO3_MIN': 1000,       # Right motor minimum
        'SERVO3_MAX': 2000,       # Right motor maximum
        'SERVO3_TRIM': 1500,      # Right motor neutral
    }

    print("\n📝 Setting mixed channel parameters...")
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

    print("\n✅ Mixed channel parameters set!")
    print("\n🎯 Test Instructions:")
    print("1. Reboot Orange Cube")
    print("2. Test with Beyond Robotics Board:")
    print("   python ../monitor_real_esc_commands.py")
    print("3. Your mixed channels should now work directly!")
    print("\n💡 Expected behavior:")
    print("   - RC1 controls left motor directly")
    print("   - RC2 controls right motor directly")
    print("   - Your controller's mixing creates the movement patterns")

if __name__ == "__main__":
    fix_mixed_channels()
