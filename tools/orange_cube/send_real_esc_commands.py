#!/usr/bin/env python3
"""
Orange Cube ESC Command Sender
Sends real ESC commands to Beyond Robotics Board via Orange Cube
"""

import time
from pymavlink import mavutil

def connect_orange_cube():
    """Connect to Orange Cube on COM4"""
    try:
        print("🔌 Verbinde mit Orange Cube auf COM4...")
        connection = mavutil.mavlink_connection('COM4', baud=115200)

        # Wait for heartbeat
        print("⏳ Warte auf Heartbeat...")
        connection.wait_heartbeat()
        print(f"✅ Verbunden mit System {connection.target_system}, Component {connection.target_component}")
        return connection
    except Exception as e:
        print(f"❌ Verbindungsfehler: {e}")
        return None

def arm_orange_cube(connection):
    """Arm the Orange Cube"""
    print("\n🔫 Orange Cube armieren...")

    # Send arm command
    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,  # confirmation
        1,  # arm (1=arm, 0=disarm)
        0, 0, 0, 0, 0, 0  # unused parameters
    )

    # Wait for response
    time.sleep(2)
    print("✅ Arm-Befehl gesendet")

def send_pwm_commands(connection):
    """Send RC Override commands that trigger DroneCAN ESC commands"""
    print("\n🎮 Sende RC Override Befehle (triggert DroneCAN ESC)...")

    # RC values (1500 = neutral, 1600 = slight forward)
    throttle = 1600
    steering = 1500

    for i in range(20):  # Send 20 commands
        print(f"📡 RC Override #{i+1}: Throttle={throttle}, Steering={steering}")

        # Send RC override (this triggers DroneCAN ESC commands)
        connection.mav.rc_channels_override_send(
            connection.target_system,
            connection.target_component,
            steering,    # channel 1 (steering)
            1500,        # channel 2 (unused)
            throttle,    # channel 3 (throttle)
            1500,        # channel 4 (unused)
            65535, 65535, 65535, 65535  # channels 5-8 (unused)
        )

        time.sleep(0.2)  # 5 Hz

    print("✅ RC Override Befehle gesendet - Orange Cube sollte DroneCAN ESC-Befehle senden!")

def main():
    print("=" * 70)
    print("    🎯 Orange Cube ESC Command Sender")
    print("=" * 70)
    print("Sendet ESC-Befehle vom Orange Cube an Beyond Robotics Board")
    print("=" * 70)

    # Connect to Orange Cube
    connection = connect_orange_cube()
    if not connection:
        return

    try:
        while True:
            print("\n📋 Menü:")
            print("1. Orange Cube armieren")
            print("2. PWM-Befehle senden")
            print("3. Beenden")

            choice = input("\nWähle Option (1-3): ").strip()

            if choice == "1":
                arm_orange_cube(connection)
            elif choice == "2":
                send_pwm_commands(connection)
            elif choice == "3":
                print("👋 Beende...")
                break
            else:
                print("❌ Ungültige Option")

    except KeyboardInterrupt:
        print("\n🛑 Unterbrochen durch Benutzer")
    except Exception as e:
        print(f"❌ Fehler: {e}")
    finally:
        connection.close()
        print("🔌 Verbindung geschlossen")

if __name__ == "__main__":
    main()
