#!/usr/bin/env python3
"""
Check Current Servo Parameters
Überprüfe warum SERVO2 immer noch 0 μs ist!
"""

import time
from pymavlink import mavutil

def check_servo_params():
    print("🔍 Checking Current Servo Parameters...")
    print("Warum ist SERVO2 immer noch 0 μs?")

    # Connect to Orange Cube
    print("🔌 Connecting to Orange Cube...")
    try:
        connection = mavutil.mavlink_connection('COM4', baud=115200)
        connection.wait_heartbeat()
        print("✅ Connected to Orange Cube")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return

    # Parameters to check
    params_to_check = [
        'SERVO1_FUNCTION',
        'SERVO2_FUNCTION',
        'SERVO3_FUNCTION',
        'SERVO1_MIN',
        'SERVO1_MAX',
        'SERVO2_MIN',
        'SERVO2_MAX',
        'SERVO3_MIN',
        'SERVO3_MAX',
        'CAN_D1_UC_ESC_BM',
        'SERVO_BLH_MASK',
        'FRAME_TYPE',
        'FRAME_CLASS',
        'RCMAP_ROLL',
        'RCMAP_THROTTLE',
        'RCMAP_PITCH',
        'RCMAP_YAW',
        'RC1_MIN',
        'RC1_MAX',
        'RC2_MIN',
        'RC2_MAX',
    ]

    print("\n📋 Current Parameter Values:")
    print("=" * 50)

    for param in params_to_check:
        # Request parameter
        connection.mav.param_request_read_send(
            connection.target_system,
            connection.target_component,
            param.encode('utf-8'),
            -1
        )

        # Wait for response
        msg = connection.recv_match(type='PARAM_VALUE', blocking=True, timeout=2)
        if msg:
            param_name = msg.param_id if isinstance(msg.param_id, str) else msg.param_id.decode('utf-8')
            param_name = param_name.strip('\x00')
            if param_name == param:
                print(f"   {param:<20} = {msg.param_value}")
            else:
                print(f"   {param:<20} = NOT FOUND (got {param_name})")
        else:
            print(f"   {param:<20} = TIMEOUT")

        time.sleep(0.1)

    print("=" * 50)
    print("\n🎯 Analysis:")
    print("   - SERVO2_FUNCTION sollte 27 sein (Throttle Right)")
    print("   - SERVO2_MIN/MAX sollten 1000/2000 sein")
    print("   - CAN_D1_UC_ESC_BM sollte 3 sein (ESC1+ESC2)")
    print("   - SERVO_BLH_MASK sollte 3 sein (Servo1+Servo2)")

if __name__ == "__main__":
    check_servo_params()
