#!/usr/bin/env python3
"""
Orange Cube RC Input Monitor

Überwacht RC-Eingänge vom Orange Cube und zeigt Skid Steering Ausgaben an.
Hilfreich zum Testen und Kalibrieren der RC-Fernbedienung.

Author: Beyond Robotics Integration
Date: 2024
"""

import time
import sys
import argparse
from pymavlink import mavutil

# Standard-Verbindungseinstellungen
DEFAULT_CONNECTION = 'COM4'
DEFAULT_BAUDRATE = 115200

class RCMonitor:
    def __init__(self, connection):
        self.connection = connection
        self.rc_channels = [0] * 18  # ArduPilot unterstützt bis zu 18 RC-Kanäle
        self.servo_outputs = [0] * 16  # Servo-Ausgänge
        self.last_rc_update = 0
        self.last_servo_update = 0
        self.last_display_time = 0
        self.display_interval = 0.5  # Update Display nur alle 500ms
        self.last_rc_values = [0] * 4  # Für Änderungserkennung
        self.last_servo_values = [0, 0]  # Für Änderungserkennung

    def process_messages(self):
        """Verarbeite eingehende MAVLink-Nachrichten"""
        msg = self.connection.recv_match(blocking=False)
        if msg is None:
            return

        msg_type = msg.get_type()

        if msg_type == 'RC_CHANNELS':
            self.handle_rc_channels(msg)
        elif msg_type == 'SERVO_OUTPUT_RAW':
            self.handle_servo_output(msg)
        elif msg_type == 'RC_CHANNELS_RAW':
            self.handle_rc_channels_raw(msg)

    def handle_rc_channels(self, msg):
        """Verarbeite RC_CHANNELS Nachricht"""
        self.rc_channels[0] = msg.chan1_raw
        self.rc_channels[1] = msg.chan2_raw
        self.rc_channels[2] = msg.chan3_raw
        self.rc_channels[3] = msg.chan4_raw
        self.rc_channels[4] = msg.chan5_raw
        self.rc_channels[5] = msg.chan6_raw
        self.rc_channels[6] = msg.chan7_raw
        self.rc_channels[7] = msg.chan8_raw
        self.rc_channels[8] = msg.chan9_raw
        self.rc_channels[9] = msg.chan10_raw
        self.rc_channels[10] = msg.chan11_raw
        self.rc_channels[11] = msg.chan12_raw
        self.rc_channels[12] = msg.chan13_raw
        self.rc_channels[13] = msg.chan14_raw
        self.rc_channels[14] = msg.chan15_raw
        self.rc_channels[15] = msg.chan16_raw
        self.rc_channels[16] = msg.chan17_raw
        self.rc_channels[17] = msg.chan18_raw

        self.last_rc_update = time.time()

    def handle_rc_channels_raw(self, msg):
        """Verarbeite RC_CHANNELS_RAW Nachricht (Fallback)"""
        self.rc_channels[0] = msg.chan1_raw
        self.rc_channels[1] = msg.chan2_raw
        self.rc_channels[2] = msg.chan3_raw
        self.rc_channels[3] = msg.chan4_raw
        self.rc_channels[4] = msg.chan5_raw
        self.rc_channels[5] = msg.chan6_raw
        self.rc_channels[6] = msg.chan7_raw
        self.rc_channels[7] = msg.chan8_raw

        self.last_rc_update = time.time()

    def handle_servo_output(self, msg):
        """Verarbeite SERVO_OUTPUT_RAW Nachricht"""
        self.servo_outputs[0] = msg.servo1_raw
        self.servo_outputs[1] = msg.servo2_raw
        self.servo_outputs[2] = msg.servo3_raw
        self.servo_outputs[3] = msg.servo4_raw
        self.servo_outputs[4] = msg.servo5_raw
        self.servo_outputs[5] = msg.servo6_raw
        self.servo_outputs[6] = msg.servo7_raw
        self.servo_outputs[7] = msg.servo8_raw
        self.servo_outputs[8] = msg.servo9_raw
        self.servo_outputs[9] = msg.servo10_raw
        self.servo_outputs[10] = msg.servo11_raw
        self.servo_outputs[11] = msg.servo12_raw
        self.servo_outputs[12] = msg.servo13_raw
        self.servo_outputs[13] = msg.servo14_raw
        self.servo_outputs[14] = msg.servo15_raw
        self.servo_outputs[15] = msg.servo16_raw

        self.last_servo_update = time.time()

    def calculate_skid_steering(self):
        """Berechne Skid Steering Werte aus RC-Eingängen"""
        steering = self.rc_channels[0]  # Kanal 1 (Roll)
        throttle = self.rc_channels[2]  # Kanal 3 (Throttle)

        # Normalisiere auf -1.0 bis +1.0
        steering_norm = (steering - 1500) / 500.0
        throttle_norm = (throttle - 1500) / 500.0

        # Begrenze Werte
        steering_norm = max(-1.0, min(1.0, steering_norm))
        throttle_norm = max(-1.0, min(1.0, throttle_norm))

        # Berechne linken und rechten Motor
        left_motor = throttle_norm + steering_norm
        right_motor = throttle_norm - steering_norm

        # Begrenze auf -1.0 bis +1.0
        left_motor = max(-1.0, min(1.0, left_motor))
        right_motor = max(-1.0, min(1.0, right_motor))

        # Konvertiere zurück zu PWM (1000-2000)
        left_pwm = int(1500 + left_motor * 500)
        right_pwm = int(1500 + right_motor * 500)

        return left_pwm, right_pwm

    def should_update_display(self):
        """Prüfe ob Display aktualisiert werden soll"""
        current_time = time.time()

        # Zeitbasierte Aktualisierung (alle 500ms)
        if current_time - self.last_display_time < self.display_interval:
            return False

        # Oder bei Änderung der wichtigen Werte
        current_rc = [self.rc_channels[0], self.rc_channels[1],
                     self.rc_channels[2], self.rc_channels[3]]
        current_servo = [self.servo_outputs[0], self.servo_outputs[1]]

        rc_changed = current_rc != self.last_rc_values
        servo_changed = current_servo != self.last_servo_values

        if rc_changed or servo_changed:
            self.last_rc_values = current_rc[:]
            self.last_servo_values = current_servo[:]
            self.last_display_time = current_time
            return True

        # Regelmäßige Aktualisierung auch ohne Änderung
        if current_time - self.last_display_time >= self.display_interval:
            self.last_display_time = current_time
            return True

        return False

    def display_status(self):
        """Zeige aktuellen Status an"""
        # Clear screen
        print("\033[2J\033[H", end="")

        print("🎮 Orange Cube RC Input Monitor")
        print("=" * 60)

        # RC Status
        rc_age = time.time() - self.last_rc_update if self.last_rc_update > 0 else 999
        rc_status = "🟢 AKTIV" if rc_age < 1.0 else "🔴 INAKTIV"

        print(f"📡 RC Status: {rc_status} (vor {rc_age:.1f}s)")

        # RC Channels (nur die wichtigen)
        print("\n📊 RC Kanäle:")
        print(f"  Kanal 1 (Steering): {self.rc_channels[0]:4d} μs")
        print(f"  Kanal 2 (Pitch):    {self.rc_channels[1]:4d} μs")
        print(f"  Kanal 3 (Throttle): {self.rc_channels[2]:4d} μs")
        print(f"  Kanal 4 (Yaw):      {self.rc_channels[3]:4d} μs")

        # Skid Steering Berechnung
        left_pwm, right_pwm = self.calculate_skid_steering()
        print(f"\n🚗 Skid Steering Berechnung:")
        print(f"  Linker Motor:  {left_pwm:4d} μs")
        print(f"  Rechter Motor: {right_pwm:4d} μs")

        # Servo Outputs
        servo_age = time.time() - self.last_servo_update if self.last_servo_update > 0 else 999
        servo_status = "🟢 AKTIV" if servo_age < 1.0 else "🔴 INAKTIV"

        print(f"\n⚙️ Servo Ausgänge: {servo_status} (vor {servo_age:.1f}s)")
        print(f"  Servo 1 (Links):  {self.servo_outputs[0]:4d} μs")
        print(f"  Servo 2 (Rechts): {self.servo_outputs[1]:4d} μs")

        # DroneCAN Status (basierend auf Servo-Ausgängen)
        dronecan_active = (self.servo_outputs[0] != 0 or self.servo_outputs[1] != 0)
        dronecan_status = "🟢 AKTIV" if dronecan_active else "🔴 INAKTIV"
        print(f"\n🔗 DroneCAN ESC: {dronecan_status}")

        # Anweisungen
        print(f"\n💡 Anweisungen:")
        print(f"  - Bewegen Sie die RC-Sticks um Eingänge zu testen")
        print(f"  - Steering (Kanal 1): Links/Rechts bewegen")
        print(f"  - Throttle (Kanal 3): Vor/Zurück bewegen")
        print(f"  - Drücken Sie Ctrl+C zum Beenden")

        print(f"\n⏰ Letzte Aktualisierung: {time.strftime('%H:%M:%S')}")

def connect_to_orange_cube(connection_string, baudrate):
    """Verbindung zum Orange Cube herstellen"""
    print(f"🔌 Verbinde mit Orange Cube auf {connection_string}...")

    try:
        master = mavutil.mavlink_connection(connection_string, baud=baudrate)
        master.wait_heartbeat()
        print(f"✅ Verbindung hergestellt! System ID: {master.target_system}")
        return master
    except Exception as e:
        print(f"❌ Verbindung fehlgeschlagen: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description='Orange Cube RC Input Monitor')
    parser.add_argument('--connection', default=DEFAULT_CONNECTION,
                        help=f'Verbindungsstring (Standard: {DEFAULT_CONNECTION})')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help=f'Baudrate (Standard: {DEFAULT_BAUDRATE})')

    args = parser.parse_args()

    # Verbindung herstellen
    connection = connect_to_orange_cube(args.connection, args.baudrate)
    if not connection:
        sys.exit(1)

    # RC Monitor erstellen
    monitor = RCMonitor(connection)

    print("\n🎮 RC Monitor gestartet...")
    print("Drücken Sie Ctrl+C zum Beenden\n")

    try:
        while True:
            # Nachrichten verarbeiten
            monitor.process_messages()

            # Status nur anzeigen wenn nötig (reduziert Flackern)
            if monitor.should_update_display():
                monitor.display_status()

            time.sleep(0.05)  # Schnellere Nachrichtenverarbeitung, langsamere Anzeige

    except KeyboardInterrupt:
        print("\n\n⚠️ RC Monitor beendet")
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
