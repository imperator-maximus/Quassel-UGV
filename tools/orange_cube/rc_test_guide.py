#!/usr/bin/env python3
"""
RC Test Guide - Schritt-für-Schritt Anleitung

Führt Sie durch einen einfachen RC-Test mit klaren Anweisungen
was Sie machen sollen und was Sie sehen sollten.

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

class RCTestGuide:
    def __init__(self, connection):
        self.connection = connection
        self.rc_channels = [1500] * 8
        self.servo_outputs = [0, 0]
        
    def process_messages(self):
        """Verarbeite MAVLink-Nachrichten"""
        msg = self.connection.recv_match(blocking=False)
        if msg is None:
            return
            
        msg_type = msg.get_type()
        
        if msg_type in ['RC_CHANNELS', 'RC_CHANNELS_RAW']:
            if hasattr(msg, 'chan1_raw'):
                self.rc_channels[0] = msg.chan1_raw
                self.rc_channels[1] = msg.chan2_raw
                self.rc_channels[2] = msg.chan3_raw
                self.rc_channels[3] = msg.chan4_raw
                
        elif msg_type == 'SERVO_OUTPUT_RAW':
            self.servo_outputs[0] = msg.servo1_raw
            self.servo_outputs[1] = msg.servo2_raw
    
    def wait_for_rc_change(self, channel, direction, timeout=10):
        """Warte auf RC-Änderung in bestimmte Richtung"""
        start_time = time.time()
        initial_value = self.rc_channels[channel]
        
        print(f"   Aktueller Wert: {initial_value}")
        print(f"   Erwarte Änderung in Richtung: {direction}")
        print("   Bewegen Sie den Stick jetzt...")
        
        while time.time() - start_time < timeout:
            self.process_messages()
            current_value = self.rc_channels[channel]
            
            # Prüfe Änderung
            if direction == "hoch" and current_value > initial_value + 50:
                print(f"   ✅ ERKANNT! Neuer Wert: {current_value}")
                return True
            elif direction == "runter" and current_value < initial_value - 50:
                print(f"   ✅ ERKANNT! Neuer Wert: {current_value}")
                return True
            elif direction == "neutral" and abs(current_value - 1500) < 30:
                print(f"   ✅ NEUTRAL! Wert: {current_value}")
                return True
            
            time.sleep(0.1)
        
        print(f"   ❌ TIMEOUT! Keine Änderung erkannt.")
        return False
    
    def test_steering_channel(self):
        """Teste Steering-Kanal (Kanal 1)"""
        print("\n🎮 TEST 1: STEERING (Kanal 1)")
        print("=" * 40)
        
        input("Drücken Sie Enter um zu beginnen...")
        
        # Links testen
        print("\n1️⃣ Bewegen Sie den STEERING-Stick nach LINKS")
        if self.wait_for_rc_change(0, "runter"):
            print("   🎯 STEERING LINKS funktioniert!")
        else:
            print("   ⚠️ STEERING LINKS nicht erkannt")
        
        # Neutral
        print("\n2️⃣ Lassen Sie den STEERING-Stick in NEUTRAL-Position")
        if self.wait_for_rc_change(0, "neutral"):
            print("   🎯 STEERING NEUTRAL funktioniert!")
        else:
            print("   ⚠️ STEERING NEUTRAL nicht erkannt")
        
        # Rechts testen
        print("\n3️⃣ Bewegen Sie den STEERING-Stick nach RECHTS")
        if self.wait_for_rc_change(0, "hoch"):
            print("   🎯 STEERING RECHTS funktioniert!")
        else:
            print("   ⚠️ STEERING RECHTS nicht erkannt")
        
        # Zurück zu Neutral
        print("\n4️⃣ Lassen Sie den STEERING-Stick wieder in NEUTRAL")
        self.wait_for_rc_change(0, "neutral")
    
    def test_throttle_channel(self):
        """Teste Throttle-Kanal (Kanal 3)"""
        print("\n🚗 TEST 2: THROTTLE (Kanal 3)")
        print("=" * 40)
        
        input("Drücken Sie Enter um zu beginnen...")
        
        # Vorwärts testen
        print("\n1️⃣ Bewegen Sie den THROTTLE-Stick nach VORWÄRTS")
        if self.wait_for_rc_change(2, "hoch"):
            print("   🎯 THROTTLE VORWÄRTS funktioniert!")
        else:
            print("   ⚠️ THROTTLE VORWÄRTS nicht erkannt")
        
        # Neutral
        print("\n2️⃣ Lassen Sie den THROTTLE-Stick in NEUTRAL-Position")
        if self.wait_for_rc_change(2, "neutral"):
            print("   🎯 THROTTLE NEUTRAL funktioniert!")
        else:
            print("   ⚠️ THROTTLE NEUTRAL nicht erkannt")
        
        # Rückwärts testen
        print("\n3️⃣ Bewegen Sie den THROTTLE-Stick nach RÜCKWÄRTS")
        if self.wait_for_rc_change(2, "runter"):
            print("   🎯 THROTTLE RÜCKWÄRTS funktioniert!")
        else:
            print("   ⚠️ THROTTLE RÜCKWÄRTS nicht erkannt")
        
        # Zurück zu Neutral
        print("\n4️⃣ Lassen Sie den THROTTLE-Stick wieder in NEUTRAL")
        self.wait_for_rc_change(2, "neutral")
    
    def test_combined_movements(self):
        """Teste kombinierte Bewegungen"""
        print("\n🔄 TEST 3: KOMBINIERTE BEWEGUNGEN")
        print("=" * 40)
        
        movements = [
            ("VORWÄRTS + LINKS", "Throttle vorwärts, Steering links"),
            ("VORWÄRTS + RECHTS", "Throttle vorwärts, Steering rechts"),
            ("RÜCKWÄRTS + LINKS", "Throttle rückwärts, Steering links"),
            ("RÜCKWÄRTS + RECHTS", "Throttle rückwärts, Steering rechts"),
        ]
        
        for movement_name, instruction in movements:
            print(f"\n🎯 {movement_name}")
            print(f"   Anweisung: {instruction}")
            input("   Drücken Sie Enter wenn bereit, dann bewegen Sie die Sticks...")
            
            # 3 Sekunden Daten sammeln
            start_time = time.time()
            values = []
            
            while time.time() - start_time < 3:
                self.process_messages()
                values.append((self.rc_channels[0], self.rc_channels[2], 
                             self.servo_outputs[0], self.servo_outputs[1]))
                time.sleep(0.1)
            
            # Durchschnittswerte berechnen
            if values:
                avg_steering = sum(v[0] for v in values) / len(values)
                avg_throttle = sum(v[1] for v in values) / len(values)
                avg_servo1 = sum(v[2] for v in values) / len(values)
                avg_servo2 = sum(v[3] for v in values) / len(values)
                
                print(f"   📊 Durchschnittswerte:")
                print(f"      Steering: {avg_steering:.0f} μs")
                print(f"      Throttle: {avg_throttle:.0f} μs")
                print(f"      Servo1 (Links): {avg_servo1:.0f} μs")
                print(f"      Servo2 (Rechts): {avg_servo2:.0f} μs")
                
                # Bewertung
                if avg_servo1 > 0 and avg_servo2 > 0:
                    print(f"   ✅ Servo-Ausgänge aktiv!")
                else:
                    print(f"   ⚠️ Keine Servo-Ausgänge erkannt")
    
    def show_final_summary(self):
        """Zeige finale Zusammenfassung"""
        print("\n🎉 RC-TEST ABGESCHLOSSEN!")
        print("=" * 50)
        
        # Aktuelle Werte anzeigen
        self.process_messages()
        
        print("📊 Aktuelle Werte:")
        print(f"   Ch1 (Steering): {self.rc_channels[0]} μs")
        print(f"   Ch3 (Throttle): {self.rc_channels[2]} μs")
        print(f"   Servo1 (Links): {self.servo_outputs[0]} μs")
        print(f"   Servo2 (Rechts): {self.servo_outputs[1]} μs")
        
        print("\n✅ Was funktioniert haben sollte:")
        print("   - RC-Werte ändern sich beim Stick-Bewegen")
        print("   - Servo-Ausgänge folgen den RC-Eingängen")
        print("   - Skid Steering funktioniert korrekt")
        
        print("\n🔧 Falls etwas nicht funktioniert:")
        print("   1. Prüfen Sie die RC-Empfänger Verkabelung")
        print("   2. Prüfen Sie die Orange Cube RC-Parameter")
        print("   3. Verwenden Sie 'python configure_rc_skid_steering.py'")

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
    parser = argparse.ArgumentParser(description='RC Test Guide - Schritt-für-Schritt')
    parser.add_argument('--connection', default=DEFAULT_CONNECTION,
                        help=f'Verbindungsstring (Standard: {DEFAULT_CONNECTION})')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help=f'Baudrate (Standard: {DEFAULT_BAUDRATE})')
    
    args = parser.parse_args()
    
    print("🎮 RC TEST GUIDE")
    print("=" * 50)
    print("Dieser Test führt Sie Schritt-für-Schritt durch die RC-Konfiguration.")
    print("Sie erhalten klare Anweisungen was zu tun ist und was Sie sehen sollten.")
    print()
    
    # Verbindung herstellen
    connection = connect_to_orange_cube(args.connection, args.baudrate)
    if not connection:
        sys.exit(1)
    
    # Test Guide erstellen
    guide = RCTestGuide(connection)
    
    try:
        # Tests durchführen
        guide.test_steering_channel()
        guide.test_throttle_channel()
        guide.test_combined_movements()
        guide.show_final_summary()
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Test abgebrochen")
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
