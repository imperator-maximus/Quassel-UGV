#!/usr/bin/env python3
"""
Fix Orange Cube DroneCAN ESC Configuration
Konfiguriert Orange Cube korrekt für DroneCAN ESC-Output
"""

import serial
import time

def send_mavlink_command(ser, command):
    """Send MAVLink command to Orange Cube"""
    print(f"📤 {command}")
    ser.write((command + '\n').encode())
    time.sleep(1)
    
    # Read response briefly
    start_time = time.time()
    while time.time() - start_time < 1.0:
        if ser.in_waiting > 0:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line and not line.startswith('MAV') and len(line) < 100:
                print(f"📥 {line}")
        time.sleep(0.1)

def fix_orange_cube_dronecan():
    """Fix Orange Cube DroneCAN ESC configuration"""
    print("=" * 80)
    print("🔧 Orange Cube DroneCAN ESC Fix")
    print("=" * 80)
    print("Problem: Orange Cube sendet keine ESC-Commands über DroneCAN")
    print("Lösung: Korrekte Parameter-Konfiguration")
    print()
    
    try:
        # Connect to Orange Cube
        ser = serial.Serial('COM4', 115200, timeout=1)
        print(f"✅ Connected to Orange Cube on {ser.name}")
        time.sleep(2)
        
        print("\n🎯 Step 1: Disable Safety Checks (for testing)")
        safety_commands = [
            "param set ARMING_CHECK 0",        # Disable all arming checks
            "param set BRD_SAFETYENABLE 0",    # Disable safety switch
            "param set BRD_SAFETY_DEFLT 0",    # Safety switch default off
        ]
        
        for command in safety_commands:
            send_mavlink_command(ser, command)
        
        print("\n🎯 Step 2: Configure Frame Type for Rover")
        frame_commands = [
            "param set FRAME_CLASS 2",         # Rover frame
            "param set FRAME_TYPE 1",          # Skid steering
        ]
        
        for command in frame_commands:
            send_mavlink_command(ser, command)
        
        print("\n🎯 Step 3: Configure DroneCAN ESC Parameters")
        dronecan_commands = [
            "param set CAN_D1_PROTOCOL 1",     # DroneCAN enabled
            "param set CAN_D1_UC_NODE 10",     # Orange Cube Node ID
            "param set CAN_D1_UC_ESC_BM 15",   # ESC bitmask (motors 1-4)
            "param set CAN_D1_UC_SRV_BM 0",    # Disable servo bitmask
            "param set CAN_D1_UC_OPTION 0",    # Standard options
        ]
        
        for command in dronecan_commands:
            send_mavlink_command(ser, command)
        
        print("\n🎯 Step 4: Configure Motor Outputs")
        motor_commands = [
            "param set SERVO1_FUNCTION 73",    # Throttle Left (DroneCAN)
            "param set SERVO2_FUNCTION 73",    # Throttle Left (DroneCAN)
            "param set SERVO3_FUNCTION 74",    # Throttle Right (DroneCAN)
            "param set SERVO4_FUNCTION 74",    # Throttle Right (DroneCAN)
            "param set SERVO_BLH_MASK 0",      # Disable BLHeli
        ]
        
        for command in motor_commands:
            send_mavlink_command(ser, command)
        
        print("\n🎯 Step 5: Configure RC Input (for testing)")
        rc_commands = [
            "param set RC1_MIN 1000",
            "param set RC1_MAX 2000", 
            "param set RC2_MIN 1000",
            "param set RC2_MAX 2000",
            "param set RC3_MIN 1000",
            "param set RC3_MAX 2000",
            "param set RC4_MIN 1000", 
            "param set RC4_MAX 2000",
        ]
        
        for command in rc_commands:
            send_mavlink_command(ser, command)
        
        print("\n💾 Step 6: Save Parameters")
        send_mavlink_command(ser, "param save")
        time.sleep(3)
        
        print("\n🔄 Step 7: Reboot Orange Cube")
        send_mavlink_command(ser, "reboot")
        time.sleep(2)
        
        print("\n✅ Orange Cube DroneCAN ESC Configuration Complete!")
        print("\n🎯 Expected Results after reboot:")
        print("- Orange Cube will send ESC commands via DroneCAN when armed")
        print("- Beyond Robotics Board will receive ESC commands")
        print("- Motor PWM outputs will be controlled")
        
        print("\n🚀 Next Steps:")
        print("1. Wait for Orange Cube reboot (~30 seconds)")
        print("2. Arm the Orange Cube: 'arm throttle'")
        print("3. Send RC commands: 'rc 3 1600' (throttle)")
        print("4. Monitor Beyond Robotics for ESC commands")
        
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        
    finally:
        try:
            ser.close()
        except:
            pass

def test_esc_after_reboot():
    """Test ESC commands after Orange Cube reboot"""
    print("\n" + "=" * 80)
    print("🧪 Testing ESC Commands After Reboot")
    print("=" * 80)
    
    print("Waiting for Orange Cube reboot...")
    time.sleep(30)  # Wait for reboot
    
    try:
        ser = serial.Serial('COM4', 115200, timeout=1)
        print(f"✅ Reconnected to Orange Cube")
        time.sleep(2)
        
        print("\n🔓 Step 1: Arm the system")
        send_mavlink_command(ser, "arm throttle")
        time.sleep(2)
        
        print("\n🚀 Step 2: Send throttle commands")
        throttle_commands = [
            "rc 3 1200",  # Low throttle
            "rc 3 1400",  # Medium throttle  
            "rc 3 1600",  # High throttle
            "rc 3 1000",  # Stop
        ]
        
        for command in throttle_commands:
            print(f"\n📤 Sending: {command}")
            send_mavlink_command(ser, command)
            time.sleep(3)  # Wait to see effect
        
        print("\n🛑 Step 3: Disarm system")
        send_mavlink_command(ser, "disarm")
        
        print("\n✅ ESC Test Complete!")
        print("Check Beyond Robotics Board for ESC command messages")
        
    except Exception as e:
        print(f"❌ Test error: {e}")
        
    finally:
        try:
            ser.close()
        except:
            pass

if __name__ == "__main__":
    fix_orange_cube_dronecan()
    
    print("\n" + "="*50)
    response = input("Continue with ESC test after reboot? (y/n): ")
    if response.lower() == 'y':
        test_esc_after_reboot()
