#!/usr/bin/env python3
"""
Orange Cube ESC Configuration
Konfiguriert Orange Cube um ESC-Commands über DroneCAN zu senden
"""

import serial
import time

def send_mavlink_command(ser, command):
    """Send MAVLink command to Orange Cube"""
    print(f"📤 Sending: {command}")
    ser.write((command + '\n').encode())
    time.sleep(0.5)
    
    # Read response
    response_lines = []
    start_time = time.time()
    while time.time() - start_time < 2.0:
        if ser.in_waiting > 0:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                response_lines.append(line)
                print(f"📥 {line}")
        time.sleep(0.1)
    
    return response_lines

def configure_orange_cube_esc():
    """Configure Orange Cube for DroneCAN ESC control"""
    print("=" * 70)
    print("🚀 Orange Cube ESC Configuration for Beyond Robotics Motor Control")
    print("=" * 70)
    
    try:
        # Connect to Orange Cube
        ser = serial.Serial('COM4', 115200, timeout=1)
        print(f"✅ Connected to Orange Cube on {ser.name}")
        time.sleep(2)
        
        print("\n🔧 Current DroneCAN Configuration:")
        
        # Check current DroneCAN parameters
        current_params = [
            "CAN_D1_PROTOCOL",
            "CAN_D1_UC_NODE", 
            "CAN_D1_UC_ESC_BM",
            "CAN_D1_UC_SRV_BM",
            "SERVO_BLH_MASK",
            "SERVO1_FUNCTION",
            "SERVO2_FUNCTION", 
            "SERVO3_FUNCTION",
            "SERVO4_FUNCTION"
        ]
        
        for param in current_params:
            send_mavlink_command(ser, f"param show {param}")
        
        print("\n🎯 Configuring ESC Output via DroneCAN:")
        
        # Configure DroneCAN ESC parameters
        esc_config_commands = [
            # Ensure DroneCAN is enabled
            "param set CAN_D1_PROTOCOL 1",      # DroneCAN enabled
            "param set CAN_D1_UC_NODE 10",      # Orange Cube Node ID
            
            # Configure ESC bitmask for 4 motors
            "param set CAN_D1_UC_ESC_BM 15",    # Binary 1111 = Motors 1,2,3,4
            
            # Configure servo functions for motor control
            "param set SERVO1_FUNCTION 33",     # Motor1 (DroneCAN ESC 1)
            "param set SERVO2_FUNCTION 34",     # Motor2 (DroneCAN ESC 2) 
            "param set SERVO3_FUNCTION 35",     # Motor3 (DroneCAN ESC 3)
            "param set SERVO4_FUNCTION 36",     # Motor4 (DroneCAN ESC 4)
            
            # Disable BLHeli for these channels (use DroneCAN instead)
            "param set SERVO_BLH_MASK 0",       # Disable BLHeli on all channels
        ]
        
        for command in esc_config_commands:
            send_mavlink_command(ser, command)
            time.sleep(1)
        
        print("\n💾 Saving parameters...")
        send_mavlink_command(ser, "param save")
        time.sleep(3)
        
        print("\n🔄 Restarting Orange Cube...")
        send_mavlink_command(ser, "reboot")
        time.sleep(2)
        
        print("\n✅ Orange Cube ESC Configuration Complete!")
        print("\n🎯 Expected Behavior:")
        print("- Orange Cube will send ESC commands via DroneCAN")
        print("- Beyond Robotics Board will receive and execute commands")
        print("- Motor outputs on pins PA8, PA9, PA10, PA11")
        print("- PWM range: 1000-2000 microseconds")
        
        print("\n🚀 Next Steps:")
        print("1. Wait for Orange Cube to reboot (~30 seconds)")
        print("2. Monitor Beyond Robotics serial for ESC commands")
        print("3. Test motor control via Orange Cube")
        
    except serial.SerialException as e:
        print(f"❌ Serial connection error: {e}")
        print("Make sure Orange Cube is connected to COM4")
        
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        
    finally:
        try:
            ser.close()
        except:
            pass

def test_esc_commands():
    """Test ESC command reception"""
    print("\n" + "=" * 70)
    print("🧪 Testing ESC Command Reception")
    print("=" * 70)
    
    print("Monitoring Beyond Robotics Board for ESC commands...")
    print("Expected messages:")
    print("- 🚀 ESC Command: [pwm1, pwm2, pwm3, pwm4]")
    print("- 🔓 Motors ARMED by ESC command")
    print("- Motors: ARMED PWM:[values]")
    
    try:
        ser = serial.Serial('COM8', 115200, timeout=1)
        print(f"✅ Monitoring {ser.name} for ESC commands...")
        
        start_time = time.time()
        esc_commands_received = 0
        
        while time.time() - start_time < 60:  # Monitor for 1 minute
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f"[{time.time() - start_time:6.1f}s] {line}")
                    
                    if "ESC Command" in line:
                        esc_commands_received += 1
                        print(f"    🎯 ESC Command #{esc_commands_received} received!")
                    elif "Motors ARMED" in line:
                        print(f"    🔓 Motors armed successfully!")
                    elif "Motors: ARMED" in line:
                        print(f"    ⚡ Motors active with PWM values!")
        
        print(f"\n📊 Test Results:")
        print(f"ESC Commands received: {esc_commands_received}")
        print(f"Test duration: {time.time() - start_time:.1f} seconds")
        
        if esc_commands_received > 0:
            print("✅ ESC communication working!")
        else:
            print("⚠️ No ESC commands received - check Orange Cube configuration")
            
    except Exception as e:
        print(f"❌ Monitoring error: {e}")
    finally:
        try:
            ser.close()
        except:
            pass

if __name__ == "__main__":
    configure_orange_cube_esc()
    
    print("\n" + "="*50)
    input("Press Enter to start ESC command monitoring...")
    test_esc_commands()
