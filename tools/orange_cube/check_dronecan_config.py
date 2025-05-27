#!/usr/bin/env python3
"""
Orange Cube DroneCAN Configuration Checker
Checks if Orange Cube is properly configured to send DroneCAN ESC commands
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

def check_dronecan_parameters(connection):
    """Check DroneCAN related parameters"""
    print("\n🔍 Prüfe DroneCAN Parameter...")

    # Parameters to check
    params_to_check = [
        'CAN_P1_BITRATE',
        'CAN_D1_PROTOCOL',
        'CAN_D1_UC_NODE',
        'CAN_D1_UC_ESC_BM',
        'SERVO_BLH_MASK',
        'SERVO_BLH_AUTO',
        'SERVO1_FUNCTION',
        'SERVO3_FUNCTION'
    ]

    for param in params_to_check:
        # Request parameter
        connection.mav.param_request_read_send(
            connection.target_system,
            connection.target_component,
            param.encode('utf-8'),
            -1
        )

        # Wait for response
        start_time = time.time()
        while time.time() - start_time < 2:
            msg = connection.recv_match(type='PARAM_VALUE', blocking=False)
            if msg:
                param_name = msg.param_id if isinstance(msg.param_id, str) else msg.param_id.decode('utf-8')
                if param_name.strip('\x00') == param:
                    print(f"  {param}: {msg.param_value}")
                    break
        else:
            print(f"  {param}: TIMEOUT")

def check_system_status(connection):
    """Check system status and mode"""
    print("\n📊 Prüfe System Status...")

    # Request system status
    msg = connection.recv_match(type='SYS_STATUS', blocking=True, timeout=5)
    if msg:
        print(f"  Voltage: {msg.voltage_battery/1000.0:.2f}V")
        print(f"  Current: {msg.current_battery/100.0:.2f}A")

    # Request heartbeat for mode
    msg = connection.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
    if msg:
        armed = msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        print(f"  Armed: {'YES' if armed else 'NO'}")
        print(f"  Mode: {msg.custom_mode}")

def main():
    print("=" * 60)
    print("    🔍 Orange Cube DroneCAN Configuration Checker")
    print("=" * 60)

    connection = connect_orange_cube()
    if not connection:
        return

    try:
        check_dronecan_parameters(connection)
        check_system_status(connection)

        print("\n" + "=" * 60)
        print("ERWARTETE WERTE:")
        print("  CAN_P1_BITRATE: 1000000")
        print("  CAN_D1_PROTOCOL: 1")
        print("  CAN_D1_UC_NODE: 10")
        print("  CAN_D1_UC_ESC_BM: 15")
        print("  SERVO_BLH_MASK: 5")
        print("  Armed: YES (für ESC-Befehle)")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n🛑 Unterbrochen")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
