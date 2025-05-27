#!/usr/bin/env python3
"""
Configure Orange Cube for DroneCAN ESC Output
Sets all required parameters for DroneCAN ESC command transmission
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
    """Set a parameter"""
    print(f"🔧 Setze {param_name} = {param_value}")

    connection.mav.param_set_send(
        connection.target_system,
        connection.target_component,
        param_name.encode('utf-8'),
        param_value,
        mavutil.mavlink.MAV_PARAM_TYPE_REAL32
    )

    time.sleep(1)
    return True

def configure_dronecan_esc(connection):
    """Configure Orange Cube for DroneCAN ESC output"""
    print("\n🔧 Konfiguriere DroneCAN ESC-Ausgabe...")

    # Essential DroneCAN ESC parameters
    params = [
        ('CAN_D1_UC_ESC_BM', 15),      # ESC Bitmask (all 4 ESCs)
        ('CAN_D1_UC_ESC_OF', 0),       # ESC Offset
        ('SERVO_BLH_MASK', 15),        # BLHeli mask (all 4)
        ('SERVO_BLH_AUTO', 1),         # BLHeli auto
        ('SERVO1_FUNCTION', 33),       # Motor1 (DroneCAN)
        ('SERVO2_FUNCTION', 34),       # Motor2 (DroneCAN)
        ('SERVO3_FUNCTION', 35),       # Motor3 (DroneCAN)
        ('SERVO4_FUNCTION', 36),       # Motor4 (DroneCAN)
        ('MOT_PWM_TYPE', 6),           # DShot600 (for DroneCAN)
        ('CAN_D1_PROTOCOL', 1),        # DroneCAN protocol
        ('CAN_P1_BITRATE', 1000000),   # 1 Mbps
    ]

    for param_name, param_value in params:
        set_parameter(connection, param_name, param_value)

    print("✅ DroneCAN ESC Parameter gesetzt!")

def test_esc_output(connection):
    """Test ESC output by sending throttle commands"""
    print("\n🎮 Teste ESC-Ausgabe...")

    # Set MANUAL mode
    connection.mav.set_mode_send(
        connection.target_system,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        0  # MANUAL
    )
    time.sleep(1)

    # Send throttle via RC override
    for i in range(10):
        print(f"📡 Throttle Test #{i+1}")

        connection.mav.rc_channels_override_send(
            connection.target_system,
            connection.target_component,
            1500, 1500, 1600, 1500,  # roll, pitch, throttle, yaw
            65535, 65535, 65535, 65535  # channels 5-8 (unused)
        )

        time.sleep(0.5)

    print("✅ Throttle-Befehle gesendet!")

def main():
    print("=" * 70)
    print("    🔧 Orange Cube DroneCAN ESC Configuration")
    print("=" * 70)

    connection = connect_orange_cube()
    if not connection:
        return

    try:
        configure_dronecan_esc(connection)

        print("\n🔄 ORANGE CUBE NEUSTART ERFORDERLICH!")
        print("Bitte Orange Cube neu starten damit Parameter aktiv werden.")

        input("\nDrücke ENTER wenn Orange Cube neu gestartet wurde...")

        test_esc_output(connection)

        print("\n" + "=" * 70)
        print("✅ KONFIGURATION ABGESCHLOSSEN!")
        print("🔍 PRÜFE BEYOND ROBOTICS BOARD AUF ESC-NACHRICHTEN!")
        print("=" * 70)

    except KeyboardInterrupt:
        print("\n🛑 Unterbrochen")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
