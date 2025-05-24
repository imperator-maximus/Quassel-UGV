#!/usr/bin/env python3
"""
Manual Orange Cube ESC Test
Sendet manuelle Befehle an Orange Cube um ESC-Output zu testen
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
            if line and not line.startswith('MAV'):  # Filter out MAVLink noise
                response_lines.append(line)
                print(f"📥 {line}")
        time.sleep(0.1)
    
    return response_lines

def test_orange_cube_esc():
    """Test Orange Cube ESC output manually"""
    print("=" * 80)
    print("🧪 Manual Orange Cube ESC Test")
    print("=" * 80)
    print("Testet ESC-Output vom Orange Cube durch manuelle Befehle")
    print()
    
    try:
        # Connect to Orange Cube
        ser = serial.Serial('COM4', 115200, timeout=1)
        print(f"✅ Connected to Orange Cube on {ser.name}")
        time.sleep(2)
        
        print("\n🔧 Current System Status:")
        
        # Check system status
        status_commands = [
            "status",
            "param show ARMING_CHECK",
            "param show SERVO1_FUNCTION",
            "param show SERVO2_FUNCTION", 
            "param show SERVO3_FUNCTION",
            "param show SERVO4_FUNCTION",
            "param show CAN_D1_UC_ESC_BM",
            "param show FRAME_CLASS",
            "param show FRAME_TYPE"
        ]
        
        for command in status_commands:
            send_mavlink_command(ser, command)
        
        print("\n🚀 Testing Manual ESC Commands:")
        
        # Try to arm the system (if possible)
        print("\n1. Attempting to arm system...")
        send_mavlink_command(ser, "arm throttle")
        time.sleep(2)
        
        # Set manual servo outputs
        print("\n2. Setting manual servo outputs...")
        manual_commands = [
            "servo set 1 1600",  # Motor 1 - slight throttle
            "servo set 2 1600",  # Motor 2 - slight throttle
            "servo set 3 1600",  # Motor 3 - slight throttle
            "servo set 4 1600",  # Motor 4 - slight throttle
        ]
        
        for command in manual_commands:
            send_mavlink_command(ser, command)
            time.sleep(1)
        
        print("\n3. Checking servo outputs...")
        send_mavlink_command(ser, "servo list")
        
        print("\n4. Testing RC override (simulates RC input)...")
        rc_commands = [
            "rc 1 1600",  # Roll
            "rc 2 1600",  # Pitch  
            "rc 3 1600",  # Throttle
            "rc 4 1500",  # Yaw
        ]
        
        for command in rc_commands:
            send_mavlink_command(ser, command)
            time.sleep(0.5)
        
        print("\n5. Resetting to neutral...")
        neutral_commands = [
            "servo set 1 1500",
            "servo set 2 1500", 
            "servo set 3 1500",
            "servo set 4 1500",
            "rc 1 1500",
            "rc 2 1500",
            "rc 3 1000",  # Throttle to minimum
            "rc 4 1500"
        ]
        
        for command in neutral_commands:
            send_mavlink_command(ser, command)
            time.sleep(0.5)
        
        print("\n6. Disarming system...")
        send_mavlink_command(ser, "disarm")
        
        print("\n✅ Manual ESC Test Complete!")
        print("\n🎯 Expected Results:")
        print("- Beyond Robotics Board should show ESC commands")
        print("- Motor PWM values should change from 1500 to 1600")
        print("- Motors should arm/disarm accordingly")
        
    except serial.SerialException as e:
        print(f"❌ Serial connection error: {e}")
        print("Make sure Orange Cube is connected to COM4")
        
    except Exception as e:
        print(f"❌ Test error: {e}")
        
    finally:
        try:
            ser.close()
        except:
            pass

def monitor_both_devices():
    """Monitor both Orange Cube and Beyond Robotics simultaneously"""
    print("\n" + "=" * 80)
    print("🔄 Dual Device Monitoring")
    print("=" * 80)
    print("Überwacht beide Geräte gleichzeitig während ESC-Test")
    print("Drücke Ctrl+C zum Beenden")
    print("-" * 80)
    
    import threading
    
    def monitor_orange_cube():
        try:
            ser = serial.Serial('COM4', 115200, timeout=1)
            while True:
                if ser.in_waiting > 0:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line and not line.startswith('MAV'):
                        print(f"🟠 Orange: {line}")
                time.sleep(0.1)
        except:
            pass
    
    def monitor_beyond_robotics():
        try:
            ser = serial.Serial('COM8', 115200, timeout=1)
            while True:
                if ser.in_waiting > 0:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        print(f"🔵 Beyond: {line}")
                time.sleep(0.1)
        except:
            pass
    
    # Start monitoring threads
    orange_thread = threading.Thread(target=monitor_orange_cube, daemon=True)
    beyond_thread = threading.Thread(target=monitor_beyond_robotics, daemon=True)
    
    orange_thread.start()
    beyond_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n📊 Monitoring stopped")

if __name__ == "__main__":
    test_orange_cube_esc()
    
    print("\n" + "="*50)
    input("Press Enter to start dual monitoring...")
    monitor_both_devices()
