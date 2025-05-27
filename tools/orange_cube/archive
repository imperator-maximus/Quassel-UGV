#!/usr/bin/env python3
"""
Bypass PreArm and send ESC commands directly
Forces Orange Cube to output ESC commands without armming
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

def disable_prearm_checks(connection):
    """Disable PreArm safety checks"""
    print("\n🔓 Deaktiviere PreArm Checks...")
    
    # Disable various safety checks
    safety_params = [
        ('ARMING_CHECK', 0),        # Disable all arming checks
        ('BRD_SAFETYENABLE', 0),    # Disable safety switch
        ('BRD_SAFETY_DEFLT', 0),    # Safety switch default off
        ('COMPASS_USE', 0),         # Disable compass
        ('COMPASS_USE2', 0),        # Disable compass 2
        ('COMPASS_USE3', 0),        # Disable compass 3
        ('GPS_TYPE', 0),            # Disable GPS
        ('BATT_MONITOR', 0),        # Disable battery monitor
        ('FS_BATT_ENABLE', 0),      # Disable battery failsafe
        ('FS_GCS_ENABLE', 0),       # Disable GCS failsafe
    ]
    
    for param_name, param_value in safety_params:
        print(f"🔧 Setze {param_name} = {param_value}")
        connection.mav.param_set_send(
            connection.target_system,
            connection.target_component,
            param_name.encode('utf-8'),
            param_value,
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32
        )
        time.sleep(0.5)

def force_esc_output(connection):
    """Force ESC output using multiple methods"""
    print("\n🚀 Erzwinge ESC-Ausgabe...")
    
    # Method 1: Direct servo output
    print("📡 Methode 1: Direkte Servo-Ausgabe...")
    for i in range(5):
        for servo in range(1, 5):  # Servos 1-4
            connection.mav.command_long_send(
                connection.target_system,
                connection.target_component,
                mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
                0, servo, 1600, 0, 0, 0, 0, 0
            )
        time.sleep(0.5)
    
    # Method 2: RC Override (even without arming)
    print("📡 Methode 2: RC Override...")
    for i in range(10):
        connection.mav.rc_channels_override_send(
            connection.target_system,
            connection.target_component,
            1500, 1500, 1600, 1500,
            65535, 65535, 65535, 65535
        )
        time.sleep(0.2)
    
    # Method 3: Manual control
    print("📡 Methode 3: Manual Control...")
    for i in range(10):
        connection.mav.manual_control_send(
            connection.target_system,
            0, 0, 600, 0, 0  # x, y, z(throttle), r, buttons
        )
        time.sleep(0.2)
    
    # Method 4: Set mode to GUIDED and send velocity
    print("📡 Methode 4: GUIDED Mode Velocity...")
    connection.mav.set_mode_send(
        connection.target_system,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        4  # GUIDED mode
    )
    time.sleep(1)
    
    for i in range(5):
        connection.mav.set_position_target_local_ned_send(
            0, connection.target_system, connection.target_component,
            mavutil.mavlink.MAV_FRAME_LOCAL_NED,
            0b110111000111,  # velocity control
            0, 0, 0,  # position (ignored)
            1, 0, 0,  # velocity (1 m/s forward)
            0, 0, 0,  # acceleration (ignored)
            0, 0      # yaw, yaw_rate (ignored)
        )
        time.sleep(0.5)

def main():
    print("=" * 70)
    print("    🚀 Bypass PreArm and Force ESC Output")
    print("=" * 70)
    
    connection = connect_orange_cube()
    if not connection:
        return
    
    try:
        disable_prearm_checks(connection)
        
        print("\n⏳ Warte 5 Sekunden für Parameter-Update...")
        time.sleep(5)
        
        force_esc_output(connection)
        
        print("\n" + "=" * 70)
        print("✅ ALLE ESC-AUSGABE-METHODEN VERSUCHT!")
        print("🔍 PRÜFE BEYOND ROBOTICS BOARD AUF ESC-NACHRICHTEN!")
        print("Wenn immer noch nichts ankommt, sendet Orange Cube")
        print("definitiv keine DroneCAN ESC-Befehle!")
        print("=" * 70)
        
    except KeyboardInterrupt:
        print("\n🛑 Unterbrochen")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
