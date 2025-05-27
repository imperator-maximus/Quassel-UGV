#!/usr/bin/env python3
"""
Force Orange Cube to send DroneCAN ESC commands
Uses MAVLink commands to force ESC output
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

def force_esc_commands(connection):
    """Force Orange Cube to send DroneCAN ESC commands"""
    print("\n🚀 Erzwinge DroneCAN ESC-Befehle...")

    # Set mode to MANUAL (mode 0)
    print("🎮 Setze Modus auf MANUAL...")
    connection.mav.set_mode_send(
        connection.target_system,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        0  # MANUAL mode
    )
    time.sleep(1)

    # Try to arm (may fail due to PreArm checks)
    print("🔫 Versuche zu armieren...")
    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 1, 0, 0, 0, 0, 0, 0
    )
    time.sleep(2)

    # Send RC override commands (this should trigger DroneCAN ESC)
    print("📡 Sende RC Override Befehle...")
    for i in range(20):
        print(f"  RC Override #{i+1}: Throttle=1600")

        connection.mav.rc_channels_override_send(
            connection.target_system,
            connection.target_component,
            1500,  # channel 1 (roll)
            1500,  # channel 2 (pitch)
            1600,  # channel 3 (throttle - WICHTIG!)
            1500,  # channel 4 (yaw)
            65535, 65535, 65535, 65535  # channels 5-8 (unused)
        )

        # Also try direct servo commands
        connection.mav.command_long_send(
            connection.target_system,
            connection.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
            0,  # confirmation
            1,  # servo 1
            1600,  # PWM value
            0, 0, 0, 0, 0
        )

        time.sleep(0.2)  # 5 Hz

    print("✅ RC Override und Servo-Befehle gesendet!")
    print("🔍 Prüfe Beyond Robotics Board auf ESC-Debug-Nachrichten!")

def main():
    print("=" * 70)
    print("    🚀 Force Orange Cube DroneCAN ESC Commands")
    print("=" * 70)

    connection = connect_orange_cube()
    if not connection:
        return

    try:
        force_esc_commands(connection)

        print("\n" + "=" * 70)
        print("✅ BEFEHLE GESENDET!")
        print("🔍 SCHAUE JETZT IM BEYOND ROBOTICS MONITOR:")
        print("   Erwarte: '🎮 ESC Command received! Motors: ...'")
        print("=" * 70)

    except KeyboardInterrupt:
        print("\n🛑 Unterbrochen")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
