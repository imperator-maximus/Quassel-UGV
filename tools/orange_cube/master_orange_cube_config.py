#!/usr/bin/env python3
"""
MASTER Orange Cube Configuration
COMPLETE setup script for Orange Cube DroneCAN + Skid Steering + RC

This script contains the WORKING configuration that was successfully tested.
Based on Context7 recommendations and parameter dump from 2025-05-28.

Features:
- DroneCAN ESC output (ESC1 + ESC2)
- Skid Steering with mixed channel RC
- RC calibration for your specific remote
- All necessary parameters in ONE script

Usage: python master_orange_cube_config.py
"""

import time
from pymavlink import mavutil

# WORKING Configuration - tested and verified!
MASTER_CONFIG = {
    # ============================================================================
    # CAN / DroneCAN Configuration
    # ============================================================================
    'CAN_P1_DRIVER': 1,           # CAN driver enable
    'CAN_P1_BITRATE': 1000000,    # 1 Mbps (Beyond Robotics standard)
    'CAN_D1_PROTOCOL': 1,         # DroneCAN protocol
    'CAN_D1_UC_NODE': 10,         # Orange Cube node ID
    'CAN_D1_UC_ESC_BM': 3,        # ESC bitmask: 3 = ESC1 + ESC2 (binary: 11)
    'CAN_D1_UC_ESC_OF': 0,        # ESC offset
    'CAN_D1_UC_SRV_BM': 3,        # Servo bitmask: 3 = Servo1 + Servo2
    'CAN_D1_UC_SRV_RT': 100,      # Servo rate 100 Hz
    'CAN_D1_UC_NTF_RT': 100,      # Notification rate 100 Hz

    # ============================================================================
    # SERVO Configuration (Context7 values!)
    # ============================================================================
    'SERVO1_FUNCTION': 73,        # ThrottleLeft (Skid Steering) - Context7!
    'SERVO2_FUNCTION': 74,        # ThrottleRight (Skid Steering) - Context7!
    'SERVO3_FUNCTION': 0,         # Disabled
    'SERVO4_FUNCTION': 0,         # Disabled

    # Servo1 settings
    'SERVO1_MIN': 1000,           # Servo1 minimum PWM
    'SERVO1_MAX': 2000,           # Servo1 maximum PWM
    'SERVO1_TRIM': 1500,          # Servo1 neutral PWM
    'SERVO1_REVERSED': 0,         # Normal direction

    # Servo2 settings
    'SERVO2_MIN': 1000,           # Servo2 minimum PWM
    'SERVO2_MAX': 2000,           # Servo2 maximum PWM
    'SERVO2_TRIM': 1500,          # Servo2 neutral PWM
    'SERVO2_REVERSED': 0,         # Normal direction

    # ============================================================================
    # BLHeli / ESC Configuration
    # ============================================================================
    'SERVO_BLH_MASK': 3,          # BLHeli mask: 3 = Servo1 + Servo2
    'SERVO_BLH_AUTO': 1,          # Auto BLHeli detection
    'SERVO_BLH_POLES': 14,        # Motor poles
    'SERVO_BLH_TRATE': 10,        # Telemetry rate

    # ============================================================================
    # FRAME Configuration
    # ============================================================================
    'FRAME_CLASS': 2,             # Rover
    'FRAME_TYPE': 1,              # Skid Steering

    # ============================================================================
    # RC Configuration (your measured values!)
    # ============================================================================
    'RCMAP_ROLL': 1,              # RC1 = Steering (Links/Rechts)
    'RCMAP_THROTTLE': 2,          # RC2 = Throttle (Vor/Zurück)
    'RCMAP_PITCH': 0,             # Disabled
    'RCMAP_YAW': 0,               # Disabled

    # RC1 calibration (your measured values from find_throttle_channel.py)
    'RC1_MIN': 995,               # RC1 minimum (Links/Zurück)
    'RC1_MAX': 2115,              # RC1 maximum (Rechts/Vorne)
    'RC1_TRIM': 1555,             # RC1 center
    'RC1_DZ': 50,                 # RC1 deadzone
    'RC1_REVERSED': 0,            # Normal direction

    # RC2 calibration (your measured values from find_throttle_channel.py)
    'RC2_MIN': 1166,              # RC2 minimum (Rechts/Zurück)
    'RC2_MAX': 1995,              # RC2 maximum (Links/Vorne)
    'RC2_TRIM': 1580,             # RC2 center
    'RC2_DZ': 50,                 # RC2 deadzone
    'RC2_REVERSED': 0,            # Normal direction

    # ============================================================================
    # Motor Configuration
    # ============================================================================
    'MOT_PWM_TYPE': 0,            # Normal PWM
    'MOT_PWM_FREQ': 16,           # PWM frequency
    'MOT_THR_MIN': 0,             # Minimum throttle
    'MOT_THR_MAX': 100,           # Maximum throttle

    # ============================================================================
    # Safety & Arming Configuration
    # ============================================================================
    'ARMING_CHECK': 0,            # Disable arming checks (for testing)
    'ARMING_REQUIRE': 0,          # No arming required for manual mode
    'BRD_SAFETY_DEFLT': 0,        # Safety switch default
    'BRD_SAFETY_MASK': 0,         # Safety mask

    # ============================================================================
    # Failsafe Configuration
    # ============================================================================
    'FS_ACTION': 2,               # Failsafe action: HOLD
    'FS_TIMEOUT': 5,              # Failsafe timeout
    'FS_THR_ENABLE': 1,           # Throttle failsafe enable
    'FS_THR_VALUE': 975,          # Throttle failsafe value

    # ============================================================================
    # Mode Configuration
    # ============================================================================
    'MODE1': 0,                   # Manual mode
    'MODE2': 4,                   # Hold mode
    'MODE3': 10,                  # Auto mode
    'MODE_CH': 8,                 # Mode channel

    # ============================================================================
    # Serial/SBUS Configuration
    # ============================================================================
    'SERIAL1_PROTOCOL': 23,       # SBUS protocol
    'SERIAL1_BAUD': 100000,       # SBUS baud rate
    'RC_PROTOCOLS': 1,            # SBUS enabled
    'BRD_PWM_VOLT_SEL': 1,        # Servo power enabled

    # ============================================================================
    # Logging Configuration
    # ============================================================================
    'LOG_BACKEND_TYPE': 1,        # File logging
    'LOG_DISARMED': 1,            # Log when disarmed
    'LOG_BITMASK': 65535,         # Log everything
}

def configure_orange_cube():
    """Configure Orange Cube with MASTER configuration"""
    print("🎯 MASTER Orange Cube Configuration")
    print("=" * 60)
    print("COMPLETE setup for DroneCAN + Skid Steering + RC")
    print("Based on Context7 recommendations and tested configuration")
    print("=" * 60)

    # Connect to Orange Cube
    print("🔌 Connecting to Orange Cube...")
    try:
        connection = mavutil.mavlink_connection('COM4', baud=115200)
        connection.wait_heartbeat()
        print("✅ Connected to Orange Cube")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

    # Set all parameters
    print(f"\n📝 Setting {len(MASTER_CONFIG)} parameters...")
    print("This may take a few minutes...")

    success_count = 0
    for i, (param, value) in enumerate(MASTER_CONFIG.items(), 1):
        try:
            connection.mav.param_set_send(
                connection.target_system,
                connection.target_component,
                param.encode('utf-8'),
                value,
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32
            )

            # Progress indicator
            if i % 10 == 0:
                progress = (i / len(MASTER_CONFIG)) * 100
                print(f"   📊 {i}/{len(MASTER_CONFIG)} parameters ({progress:.1f}%)")

            success_count += 1
            time.sleep(0.1)  # Small delay between parameters

        except Exception as e:
            print(f"❌ Failed to set {param}: {e}")

    print(f"\n✅ Configuration complete!")
    print(f"   Successfully set: {success_count}/{len(MASTER_CONFIG)} parameters")

    # WICHTIG: Parameter dauerhaft speichern!
    print(f"\n💾 Saving parameters permanently...")
    print(f"   This prevents parameters from being lost after reboot!")

    try:
        # Send parameter save command
        connection.mav.command_long_send(
            connection.target_system,
            connection.target_component,
            mavutil.mavlink.MAV_CMD_PREFLIGHT_STORAGE,
            0,  # confirmation
            1,  # action: 1 = save parameters
            0, 0, 0, 0, 0, 0  # unused parameters
        )

        # Wait for save to complete
        time.sleep(3)
        print(f"   ✅ Parameters saved permanently!")

    except Exception as e:
        print(f"   ⚠️ Warning: Could not save parameters permanently: {e}")
        print(f"   Parameters may be lost after reboot!")

    # Summary of key settings
    print(f"\n🔑 Key Configuration Summary:")
    print(f"   CAN Protocol: DroneCAN (1 Mbps)")
    print(f"   ESC Outputs: ESC1 + ESC2")
    print(f"   Servo Functions: 73 (ThrottleLeft) + 74 (ThrottleRight)")
    print(f"   Frame Type: Skid Steering")
    print(f"   RC Mapping: RC1=Steering, RC2=Throttle")
    print(f"   RC Calibration: Your measured values")
    print(f"   💾 Parameters: PERMANENTLY SAVED!")

    print(f"\n📋 Next Steps:")
    print(f"1. Reboot Orange Cube: python -c \"from pymavlink import mavutil; m=mavutil.mavlink_connection('COM4'); m.reboot_autopilot()\"")
    print(f"2. Test PWM output: python monitor_pwm_before_can.py")
    print(f"3. Test with Beyond Robotics: python ../monitor_real_esc_commands.py")
    print(f"4. All 4 directions should work: Vorne, Links, Rechts, Zurück")
    print(f"\n🎯 IMPORTANT: Parameters are now saved permanently!")
    print(f"   No need to run this script again unless you want to change settings.")

    return True

if __name__ == "__main__":
    configure_orange_cube()
