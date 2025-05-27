#!/usr/bin/env python3
"""
Simple Orange Cube RC Monitor

Einfache, ruhige Anzeige der RC-Werte ohne Flackern.
Zeigt nur die wichtigsten Werte an und aktualisiert nur bei Änderungen.

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

class SimpleRCMonitor:
    def __init__(self, connection):
        self.connection = connection
        self.rc_channels = [1500] * 8  # Nur die ersten 8 Kanäle
        self.servo_outputs = [0, 0]   # Nur Servo 1 und 2
        self.last_update = 0
        self.update_interval = 1.0    # Nur alle 1 Sekunde aktualisieren
        
        # Für Änderungserkennung (nur bei größeren Änderungen anzeigen)
        self.last_displayed_rc = [1500] * 4
        self.last_displayed_servo = [0, 0]
        self.change_threshold = 10    # Mindestens 10μs Änderung
        
    def process_messages(self):
        """Verarbeite eingehende MAVLink-Nachrichten"""
        msg = self.connection.recv_match(blocking=False)
        if msg is None:
            return
            
        msg_type = msg.get_type()
        
        if msg_type == 'RC_CHANNELS':
            self.rc_channels[0] = msg.chan1_raw
            self.rc_channels[1] = msg.chan2_raw
            self.rc_channels[2] = msg.chan3_raw
            self.rc_channels[3] = msg.chan4_raw
            self.rc_channels[4] = msg.chan5_raw
            self.rc_channels[5] = msg.chan6_raw
            self.rc_channels[6] = msg.chan7_raw
            self.rc_channels[7] = msg.chan8_raw
            
        elif msg_type == 'RC_CHANNELS_RAW':
            self.rc_channels[0] = msg.chan1_raw
            self.rc_channels[1] = msg.chan2_raw
            self.rc_channels[2] = msg.chan3_raw
            self.rc_channels[3] = msg.chan4_raw
            self.rc_channels[4] = msg.chan5_raw
            self.rc_channels[5] = msg.chan6_raw
            self.rc_channels[6] = msg.chan7_raw
            self.rc_channels[7] = msg.chan8_raw
            
        elif msg_type == 'SERVO_OUTPUT_RAW':
            self.servo_outputs[0] = msg.servo1_raw
            self.servo_outputs[1] = msg.servo2_raw
    
    def has_significant_change(self):
        """Prüfe ob es eine signifikante Änderung gibt"""
        # RC-Änderungen prüfen
        for i in range(4):
            if abs(self.rc_channels[i] - self.last_displayed_rc[i]) > self.change_threshold:
                return True
        
        # Servo-Änderungen prüfen
        for i in range(2):
            if abs(self.servo_outputs[i] - self.last_displayed_servo[i]) > self.change_threshold:
                return True
        
        return False
    
    def should_update(self):
        """Prüfe ob Update nötig ist"""
        current_time = time.time()
        
        # Bei signifikanter Änderung sofort aktualisieren
        if self.has_significant_change():
            return True
        
        # Oder alle X Sekunden
        if current_time - self.last_update >= self.update_interval:
            return True
        
        return False
    
    def calculate_skid_steering(self):
        """Berechne Skid Steering Werte"""
        steering = self.rc_channels[0]  # Kanal 1
        throttle = self.rc_channels[2]  # Kanal 3
        
        # Normalisiere
        steering_norm = (steering - 1500) / 500.0
        throttle_norm = (throttle - 1500) / 500.0
        
        # Begrenze
        steering_norm = max(-1.0, min(1.0, steering_norm))
        throttle_norm = max(-1.0, min(1.0, throttle_norm))
        
        # Berechne Motoren
        left_motor = throttle_norm + steering_norm
        right_motor = throttle_norm - steering_norm
        
        # Begrenze
        left_motor = max(-1.0, min(1.0, left_motor))
        right_motor = max(-1.0, min(1.0, right_motor))
        
        # Zu PWM
        left_pwm = int(1500 + left_motor * 500)
        right_pwm = int(1500 + right_motor * 500)
        
        return left_pwm, right_pwm
    
    def display_status(self):
        """Zeige Status an (ohne Screen-Clear für weniger Flackern)"""
        print("\n" + "="*50)
        print(f"🎮 RC Monitor - {time.strftime('%H:%M:%S')}")
        print("="*50)
        
        # RC-Eingänge (nur die wichtigen)
        print("📡 RC Eingänge:")
        print(f"  Ch1 (Steering): {self.rc_channels[0]:4d} μs")
        print(f"  Ch3 (Throttle): {self.rc_channels[2]:4d} μs")
        
        # Skid Steering Berechnung
        left_calc, right_calc = self.calculate_skid_steering()
        print(f"\n🧮 Skid Steering Berechnung:")
        print(f"  Links:  {left_calc:4d} μs")
        print(f"  Rechts: {right_calc:4d} μs")
        
        # Tatsächliche Servo-Ausgänge
        print(f"\n⚙️ Servo Ausgänge:")
        print(f"  Servo1: {self.servo_outputs[0]:4d} μs")
        print(f"  Servo2: {self.servo_outputs[1]:4d} μs")
        
        # Status-Indikatoren
        rc_active = any(ch != 0 for ch in self.rc_channels[:4])
        servo_active = any(servo != 0 for servo in self.servo_outputs)
        
        print(f"\n🔍 Status:")
        print(f"  RC Input:     {'🟢 AKTIV' if rc_active else '🔴 INAKTIV'}")
        print(f"  Servo Output: {'🟢 AKTIV' if servo_active else '🔴 INAKTIV'}")
        
        # Bewegungsrichtung anzeigen
        steering_dir = "NEUTRAL"
        if self.rc_channels[0] < 1450:
            steering_dir = "LINKS"
        elif self.rc_channels[0] > 1550:
            steering_dir = "RECHTS"
        
        throttle_dir = "NEUTRAL"
        if self.rc_channels[2] < 1450:
            throttle_dir = "RÜCKWÄRTS"
        elif self.rc_channels[2] > 1550:
            throttle_dir = "VORWÄRTS"
        
        print(f"\n🚗 Bewegung:")
        print(f"  Steering: {steering_dir}")
        print(f"  Throttle: {throttle_dir}")
        
        # Werte für nächsten Vergleich speichern
        self.last_displayed_rc = self.rc_channels[:4][:]
        self.last_displayed_servo = self.servo_outputs[:]
        self.last_update = time.time()

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
    parser = argparse.ArgumentParser(description='Simple Orange Cube RC Monitor')
    parser.add_argument('--connection', default=DEFAULT_CONNECTION,
                        help=f'Verbindungsstring (Standard: {DEFAULT_CONNECTION})')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help=f'Baudrate (Standard: {DEFAULT_BAUDRATE})')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='Update-Intervall in Sekunden (Standard: 1.0)')
    
    args = parser.parse_args()
    
    # Verbindung herstellen
    connection = connect_to_orange_cube(args.connection, args.baudrate)
    if not connection:
        sys.exit(1)
    
    # Monitor erstellen
    monitor = SimpleRCMonitor(connection)
    monitor.update_interval = args.interval
    
    print(f"\n🎮 Simple RC Monitor gestartet (Update alle {args.interval}s)")
    print("Bewegen Sie die RC-Sticks um Änderungen zu sehen")
    print("Drücken Sie Ctrl+C zum Beenden\n")
    
    try:
        while True:
            # Nachrichten verarbeiten
            monitor.process_messages()
            
            # Status anzeigen wenn nötig
            if monitor.should_update():
                monitor.display_status()
            
            time.sleep(0.1)  # Kurze Pause
            
    except KeyboardInterrupt:
        print("\n\n⚠️ Simple RC Monitor beendet")
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
