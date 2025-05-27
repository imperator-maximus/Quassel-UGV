#!/usr/bin/env python3
"""
Orange Cube RC Skid Steering Test Script

Testet die RC-Konfiguration durch Simulation von RC-Eingängen
und Überwachung der resultierenden DroneCAN ESC-Befehle.

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

def set_manual_mode(connection):
    """Setze Orange Cube in Manual Mode"""
    print("🎮 Setze Manual Mode...")
    
    connection.mav.set_mode_send(
        connection.target_system,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        0  # MANUAL mode
    )
    time.sleep(1)
    print("✅ Manual Mode gesetzt")

def send_rc_override(connection, steering, throttle):
    """Sende RC Override Befehle"""
    connection.mav.rc_channels_override_send(
        connection.target_system,
        connection.target_component,
        steering,    # Channel 1 (Steering)
        1500,        # Channel 2 (Pitch) - neutral
        throttle,    # Channel 3 (Throttle)
        1500,        # Channel 4 (Yaw) - neutral
        65535, 65535, 65535, 65535  # Channels 5-8 (unused)
    )

def test_skid_steering_patterns(connection):
    """Teste verschiedene Skid Steering Muster"""
    print("\n🚗 Teste Skid Steering Muster...")
    
    # Test-Muster: (Beschreibung, Steering, Throttle, Dauer)
    test_patterns = [
        ("Neutral (Stop)", 1500, 1500, 2),
        ("Vorwärts", 1500, 1600, 3),
        ("Rückwärts", 1500, 1400, 3),
        ("Links drehen (auf der Stelle)", 1400, 1500, 3),
        ("Rechts drehen (auf der Stelle)", 1600, 1500, 3),
        ("Vorwärts + Links", 1400, 1600, 3),
        ("Vorwärts + Rechts", 1600, 1600, 3),
        ("Rückwärts + Links", 1400, 1400, 3),
        ("Rückwärts + Rechts", 1600, 1400, 3),
        ("Zurück zu Neutral", 1500, 1500, 2),
    ]
    
    for i, (description, steering, throttle, duration) in enumerate(test_patterns):
        print(f"\n[{i+1}/{len(test_patterns)}] {description}")
        print(f"  Steering: {steering} μs, Throttle: {throttle} μs")
        
        # Berechne erwartete Skid Steering Ausgabe
        steering_norm = (steering - 1500) / 500.0
        throttle_norm = (throttle - 1500) / 500.0
        
        left_motor = throttle_norm + steering_norm
        right_motor = throttle_norm - steering_norm
        
        # Begrenze auf -1.0 bis +1.0
        left_motor = max(-1.0, min(1.0, left_motor))
        right_motor = max(-1.0, min(1.0, right_motor))
        
        # Konvertiere zu PWM
        left_pwm = int(1500 + left_motor * 500)
        right_pwm = int(1500 + right_motor * 500)
        
        print(f"  Erwartete Ausgabe: Links={left_pwm} μs, Rechts={right_pwm} μs")
        
        # Sende RC Override für die angegebene Dauer
        start_time = time.time()
        while time.time() - start_time < duration:
            send_rc_override(connection, steering, throttle)
            time.sleep(0.1)  # 10 Hz
        
        print(f"  ✅ Test abgeschlossen ({duration}s)")

def monitor_servo_outputs(connection, duration=10):
    """Überwache Servo-Ausgänge für eine bestimmte Zeit"""
    print(f"\n📊 Überwache Servo-Ausgänge für {duration} Sekunden...")
    
    start_time = time.time()
    last_servo1 = 0
    last_servo2 = 0
    
    while time.time() - start_time < duration:
        msg = connection.recv_match(type='SERVO_OUTPUT_RAW', blocking=False)
        if msg:
            servo1 = msg.servo1_raw
            servo2 = msg.servo2_raw
            
            # Nur anzeigen wenn sich Werte geändert haben
            if servo1 != last_servo1 or servo2 != last_servo2:
                print(f"  Servo 1 (Links): {servo1} μs, Servo 2 (Rechts): {servo2} μs")
                last_servo1 = servo1
                last_servo2 = servo2
        
        time.sleep(0.1)
    
    print("✅ Servo-Überwachung abgeschlossen")

def test_rc_calibration(connection):
    """Teste RC-Kalibrierung mit Extremwerten"""
    print("\n🎯 Teste RC-Kalibrierung...")
    
    # Test-Werte für Kalibrierung
    calibration_tests = [
        ("RC Min-Werte", 1000, 1000),
        ("RC Max-Werte", 2000, 2000),
        ("RC Neutral", 1500, 1500),
        ("Steering Min, Throttle Neutral", 1000, 1500),
        ("Steering Max, Throttle Neutral", 2000, 1500),
        ("Steering Neutral, Throttle Min", 1500, 1000),
        ("Steering Neutral, Throttle Max", 1500, 2000),
    ]
    
    for description, steering, throttle in calibration_tests:
        print(f"\n📡 {description}: Steering={steering}, Throttle={throttle}")
        
        # Sende 5 Befehle
        for i in range(5):
            send_rc_override(connection, steering, throttle)
            time.sleep(0.2)
        
        print("  ✅ Kalibrierungstest gesendet")

def main():
    parser = argparse.ArgumentParser(description='Orange Cube RC Skid Steering Test')
    parser.add_argument('--connection', default=DEFAULT_CONNECTION,
                        help=f'Verbindungsstring (Standard: {DEFAULT_CONNECTION})')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help=f'Baudrate (Standard: {DEFAULT_BAUDRATE})')
    parser.add_argument('--test', choices=['patterns', 'calibration', 'monitor', 'all'],
                        default='all', help='Test-Typ auswählen')
    
    args = parser.parse_args()
    
    print("🚀 Orange Cube RC Skid Steering Test")
    print("=" * 50)
    
    # Verbindung herstellen
    connection = connect_to_orange_cube(args.connection, args.baudrate)
    if not connection:
        sys.exit(1)
    
    try:
        # Manual Mode setzen
        set_manual_mode(connection)
        
        if args.test in ['patterns', 'all']:
            # Skid Steering Muster testen
            test_skid_steering_patterns(connection)
        
        if args.test in ['calibration', 'all']:
            # RC-Kalibrierung testen
            test_rc_calibration(connection)
        
        if args.test in ['monitor', 'all']:
            # Servo-Ausgänge überwachen
            monitor_servo_outputs(connection, duration=15)
        
        # Zurück zu Neutral
        print("\n🛑 Setze alle Ausgänge auf Neutral...")
        for i in range(10):
            send_rc_override(connection, 1500, 1500)
            time.sleep(0.1)
        
        print("\n🎉 RC Skid Steering Test abgeschlossen!")
        print("\n📋 Nächste Schritte:")
        print("1. Überprüfen Sie die Beyond Robotics Board Ausgaben")
        print("2. Testen Sie mit echter RC-Fernbedienung")
        print("3. Verwenden Sie monitor_rc_input.py für Live-Überwachung")
        
    except KeyboardInterrupt:
        print("\n⚠️ Test abgebrochen")
        # Sicherheits-Neutral
        for i in range(5):
            send_rc_override(connection, 1500, 1500)
            time.sleep(0.1)
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
