#!/usr/bin/env python3
"""
Motor Controller Test
Überwacht Beyond Robotics Board für ESC-Commands vom Orange Cube
"""

import serial
import time

def test_motor_controller():
    """Test motor controller ESC command reception"""
    print("=" * 80)
    print("🚀 Motor Controller Test - ESC Command Monitoring")
    print("=" * 80)
    print("Überwacht Beyond Robotics Board für ESC-Commands vom Orange Cube")
    print()
    print("🎯 Erwartete Nachrichten:")
    print("- 🚀 ESC Command: [pwm1, pwm2, pwm3, pwm4]")
    print("- 🔓 Motors ARMED by ESC command")
    print("- Motors: ARMED PWM:[values]")
    print("- Battery: V=xxx, I=xxx, T=xxx°C")
    print()
    print("⚠️ Orange Cube Konfiguration:")
    print("- SERVO1_FUNCTION = 33 (DroneCAN ESC 1)")
    print("- SERVO2_FUNCTION = 34 (DroneCAN ESC 2)")
    print("- SERVO3_FUNCTION = 35 (DroneCAN ESC 3)")
    print("- SERVO4_FUNCTION = 36 (DroneCAN ESC 4)")
    print("- CAN_D1_UC_ESC_BM = 15 (Binary 1111 = All 4 motors)")
    print()
    print("Drücke Ctrl+C zum Beenden")
    print("-" * 80)
    
    try:
        ser = serial.Serial('COM8', 115200, timeout=1)
        print(f"✅ Verbunden mit {ser.name}")
        print()
        
        start_time = time.time()
        esc_commands_received = 0
        motors_armed = False
        last_motor_status = ""
        
        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    timestamp = time.time() - start_time
                    print(f"[{timestamp:8.2f}s] {line}")
                    
                    # Analyze important messages
                    if "🚀 ESC Command:" in line:
                        esc_commands_received += 1
                        print(f"    🎯 ESC Command #{esc_commands_received} received!")
                        
                    elif "Motors ARMED" in line:
                        motors_armed = True
                        print(f"    🔓 Motors successfully armed!")
                        
                    elif "Motors: ARMED" in line:
                        last_motor_status = line
                        print(f"    ⚡ Motors active!")
                        
                    elif "Motors: DISARMED" in line:
                        if motors_armed:  # Only log if previously armed
                            print(f"    🛑 Motors disarmed (safety timeout)")
                        
                    elif "Battery:" in line and "Transfer ID=" in line:
                        print(f"    🔋 Battery telemetry")
                        
                    elif "GetNodeInfo request from10" in line:
                        print(f"    📡 Orange Cube node discovery")
            
            time.sleep(0.01)
            
    except serial.SerialException as e:
        print(f"❌ Serial connection error: {e}")
        print("Make sure Beyond Robotics Board is connected to COM8")
        
    except KeyboardInterrupt:
        print(f"\n\n📊 TEST RESULTS:")
        print(f"ESC Commands received: {esc_commands_received}")
        print(f"Motors armed: {'YES' if motors_armed else 'NO'}")
        print(f"Test duration: {time.time() - start_time:.1f} seconds")
        print(f"Last motor status: {last_motor_status}")
        
        if esc_commands_received > 0:
            print("\n✅ SUCCESS: Motor Controller working!")
            print("- Orange Cube sends ESC commands via DroneCAN")
            print("- Beyond Robotics Board receives and processes commands")
            print("- Motor PWM outputs are controlled")
        else:
            print("\n⚠️ NO ESC COMMANDS RECEIVED")
            print("Possible issues:")
            print("1. Orange Cube still rebooting (wait longer)")
            print("2. DroneCAN configuration not applied")
            print("3. CAN bus connection issue")
            print("4. Orange Cube not sending motor commands")
            
        print("\n🎯 Next steps:")
        if esc_commands_received > 0:
            print("- Test with actual motor hardware")
            print("- Implement safety features")
            print("- Add more DroneCAN message types")
        else:
            print("- Check Orange Cube parameter configuration")
            print("- Verify CAN bus wiring")
            print("- Test with manual motor commands")
        
    finally:
        try:
            ser.close()
        except:
            pass

if __name__ == "__main__":
    print("Waiting for Orange Cube to complete reboot...")
    print("(~30 seconds after configuration)")
    time.sleep(5)  # Give some time for reboot
    test_motor_controller()
