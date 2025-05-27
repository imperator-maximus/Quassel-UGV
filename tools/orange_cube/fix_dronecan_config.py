#!/usr/bin/env python3
"""
Orange Cube DroneCAN Configuration Fixer
Fixes Orange Cube parameters to properly send DroneCAN ESC commands
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

def set_parameter(connection, param_name, param_value):
    """Set a parameter on Orange Cube"""
    print(f"🔧 Setze {param_name} = {param_value}")
    
    connection.mav.param_set_send(
        connection.target_system,
        connection.target_component,
        param_name.encode('utf-8'),
        param_value,
        mavutil.mavlink.MAV_PARAM_TYPE_REAL32
    )
    
    # Wait for confirmation
    start_time = time.time()
    while time.time() - start_time < 5:
        msg = connection.recv_match(type='PARAM_VALUE', blocking=False)
        if msg:
            param_name_recv = msg.param_id if isinstance(msg.param_id, str) else msg.param_id.decode('utf-8')
            if param_name_recv.strip('\x00') == param_name:
                print(f"✅ {param_name} gesetzt auf {msg.param_value}")
                return True
    
    print(f"❌ Timeout beim Setzen von {param_name}")
    return False

def arm_orange_cube(connection):
    """Arm the Orange Cube"""
    print("🔫 Orange Cube armieren...")
    
    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,  # confirmation
        1,  # arm (1=arm, 0=disarm)
        0, 0, 0, 0, 0, 0  # unused parameters
    )
    
    time.sleep(3)
    
    # Check if armed
    msg = connection.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
    if msg:
        armed = msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        if armed:
            print("✅ Orange Cube erfolgreich armiert!")
            return True
        else:
            print("❌ Orange Cube konnte nicht armiert werden")
            return False
    
    print("❌ Keine Heartbeat-Antwort")
    return False

def main():
    print("=" * 60)
    print("    🔧 Orange Cube DroneCAN Configuration Fixer")
    print("=" * 60)
    
    connection = connect_orange_cube()
    if not connection:
        return
    
    try:
        print("\n🔧 Repariere DroneCAN Konfiguration...")
        
        # Fix CAN_D1_UC_ESC_BM (ESC Bitmask)
        if not set_parameter(connection, 'CAN_D1_UC_ESC_BM', 15):
            print("❌ Konnte ESC Bitmask nicht setzen!")
            return
        
        print("\n🔫 Armiere Orange Cube...")
        if not arm_orange_cube(connection):
            print("❌ Konnte Orange Cube nicht armieren!")
            return
        
        print("\n" + "=" * 60)
        print("✅ ORANGE CUBE KONFIGURATION REPARIERT!")
        print("✅ CAN_D1_UC_ESC_BM: 15 (alle 4 ESCs)")
        print("✅ Orange Cube: ARMIERT")
        print("🚀 Orange Cube sollte jetzt DroneCAN ESC-Befehle senden!")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n🛑 Unterbrochen")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
