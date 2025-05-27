#!/usr/bin/env python3
"""
Check Orange Cube PreArm Errors
Shows why Orange Cube cannot be armed
"""

from pymavlink import mavutil
import time

def connect_orange_cube():
    """Connect to Orange Cube"""
    try:
        print("🔌 Verbinde mit Orange Cube auf COM4...")
        connection = mavutil.mavlink_connection('COM4', baud=115200)
        connection.wait_heartbeat()
        print(f"✅ Verbunden mit System {connection.target_system}")
        return connection
    except Exception as e:
        print(f"❌ Verbindungsfehler: {e}")
        return None

def check_prearm_status(connection):
    """Check PreArm status and errors"""
    print("\n🔍 Prüfe PreArm Status...")
    
    # Request PreArm check
    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_CMD_RUN_PREARM_CHECKS,
        0, 0, 0, 0, 0, 0, 0, 0
    )
    
    # Listen for status messages
    print("📡 Höre auf Status-Nachrichten...")
    start_time = time.time()
    
    while time.time() - start_time < 10:
        msg = connection.recv_match(blocking=False)
        if msg:
            msg_type = msg.get_type()
            
            if msg_type == 'STATUSTEXT':
                severity = msg.severity
                text = msg.text
                
                if severity <= 3:  # Error or Critical
                    print(f"❌ ERROR: {text}")
                elif severity <= 5:  # Warning
                    print(f"⚠️  WARNING: {text}")
                else:
                    print(f"ℹ️  INFO: {text}")
            
            elif msg_type == 'HEARTBEAT':
                armed = msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                print(f"💓 Heartbeat: Armed={armed}, Mode={msg.custom_mode}")
            
            elif msg_type == 'SYS_STATUS':
                print(f"📊 System: Voltage={msg.voltage_battery/1000.0:.2f}V")
        
        time.sleep(0.1)

def try_force_arm(connection):
    """Try to force arm ignoring PreArm checks"""
    print("\n🔫 Versuche FORCE ARM...")
    
    # Force arm command
    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,  # confirmation
        1,  # arm
        21196,  # force arm magic number
        0, 0, 0, 0, 0
    )
    
    time.sleep(3)
    
    # Check if armed
    msg = connection.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
    if msg:
        armed = msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        if armed:
            print("✅ FORCE ARM erfolgreich!")
            return True
        else:
            print("❌ FORCE ARM fehlgeschlagen")
            return False
    
    return False

def main():
    print("=" * 60)
    print("    🔍 Orange Cube PreArm Error Checker")
    print("=" * 60)
    
    connection = connect_orange_cube()
    if not connection:
        return
    
    try:
        check_prearm_status(connection)
        
        if try_force_arm(connection):
            print("\n🎮 Orange Cube ist armiert - teste ESC-Ausgabe...")
            
            # Send throttle commands
            for i in range(5):
                print(f"📡 Throttle #{i+1}")
                connection.mav.rc_channels_override_send(
                    connection.target_system,
                    connection.target_component,
                    1500, 1500, 1600, 1500,
                    65535, 65535, 65535, 65535
                )
                time.sleep(1)
            
            print("✅ Throttle-Befehle gesendet!")
            print("🔍 PRÜFE BEYOND ROBOTICS BOARD AUF ESC-NACHRICHTEN!")
        
    except KeyboardInterrupt:
        print("\n🛑 Unterbrochen")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
