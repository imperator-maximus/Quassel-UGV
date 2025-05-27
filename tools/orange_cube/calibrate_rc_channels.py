#!/usr/bin/env python3
"""
Orange Cube RC Channel Calibration Script

Misst die ECHTEN RC-Werte deiner Fernbedienung und kalibriert automatisch.
Löst das Problem mit verkehrten Throttle-Werten und fehlendem Steering.

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

class RCCalibrator:
    def __init__(self, connection):
        self.connection = connection
        self.rc_values = {}
        self.calibration_data = {
            'RC1': {'min': 9999, 'max': 0, 'center': 1500},  # Steering
            'RC3': {'min': 9999, 'max': 0, 'center': 1500},  # Throttle
        }

    def read_rc_channels(self, duration=5):
        """Lese RC-Kanäle für eine bestimmte Zeit"""
        print(f"📡 Lese RC-Kanäle für {duration} Sekunden...")

        start_time = time.time()
        sample_count = 0

        while time.time() - start_time < duration:
            msg = self.connection.recv_match(type=['RC_CHANNELS_RAW', 'RC_CHANNELS'], blocking=True, timeout=1)
            if msg:
                # Alle RC-Kanäle lesen (beide Message-Typen unterstützen)
                channels = {
                    'RC1': getattr(msg, 'chan1_raw', 1500),
                    'RC2': getattr(msg, 'chan2_raw', 1500),
                    'RC3': getattr(msg, 'chan3_raw', 1500),
                    'RC4': getattr(msg, 'chan4_raw', 1500),
                    'RC5': getattr(msg, 'chan5_raw', 1500),
                    'RC6': getattr(msg, 'chan6_raw', 1500),
                    'RC7': getattr(msg, 'chan7_raw', 1500),
                    'RC8': getattr(msg, 'chan8_raw', 1500),
                }

                # Aktualisiere Min/Max für Steering und Throttle
                for channel in ['RC1', 'RC3']:
                    value = channels[channel]
                    if value > 0:  # Gültiger Wert
                        if value < self.calibration_data[channel]['min']:
                            self.calibration_data[channel]['min'] = value
                        if value > self.calibration_data[channel]['max']:
                            self.calibration_data[channel]['max'] = value

                sample_count += 1

                # Live-Anzeige
                print(f"\r🎮 RC1(Steering): {channels['RC1']:4d} | RC3(Throttle): {channels['RC3']:4d} | Samples: {sample_count}", end='')

        print()  # Neue Zeile
        return sample_count > 0

    def calibrate_center_position(self):
        """Kalibriere Center-Position (Sticks in Neutral)"""
        print("\n🎯 SCHRITT 1: Center-Position kalibrieren")
        print("📋 Anweisungen:")
        print("   - Lassen Sie BEIDE Sticks in NEUTRAL-Position")
        print("   - Steering-Stick: MITTE")
        print("   - Throttle-Stick: MITTE")
        input("   Drücken Sie ENTER wenn bereit...")

        # Lese Center-Werte (versuche beide Message-Typen)
        msg = self.connection.recv_match(type=['RC_CHANNELS_RAW', 'RC_CHANNELS'], blocking=True, timeout=5)
        if msg:
            if hasattr(msg, 'chan1_raw'):
                # RC_CHANNELS_RAW
                rc1_val = msg.chan1_raw
                rc3_val = msg.chan3_raw
            else:
                # RC_CHANNELS
                rc1_val = msg.chan1_raw if hasattr(msg, 'chan1_raw') else 1500
                rc3_val = msg.chan3_raw if hasattr(msg, 'chan3_raw') else 1500

            self.calibration_data['RC1']['center'] = rc1_val
            self.calibration_data['RC3']['center'] = rc3_val
            print(f"✅ Center-Werte: RC1={rc1_val}, RC3={rc3_val}")
        else:
            print("❌ Keine RC-Daten empfangen!")
            return False

        return True

    def calibrate_extremes(self):
        """Kalibriere Min/Max-Werte"""
        print("\n🎯 SCHRITT 2: Min/Max-Werte kalibrieren")
        print("📋 Anweisungen:")
        print("   - Bewegen Sie BEIDE Sticks in ALLE Richtungen")
        print("   - Steering: Ganz LINKS und ganz RECHTS")
        print("   - Throttle: Ganz VORWÄRTS und ganz RÜCKWÄRTS")
        print("   - Halten Sie jeden Extremwert 2 Sekunden")
        input("   Drücken Sie ENTER um zu starten...")

        return self.read_rc_channels(15)  # 15 Sekunden für alle Extremwerte

    def analyze_calibration(self):
        """Analysiere Kalibrierungsdaten"""
        print("\n🔍 KALIBRIERUNGS-ANALYSE:")
        print("=" * 50)

        for channel in ['RC1', 'RC3']:
            data = self.calibration_data[channel]
            channel_name = "Steering" if channel == 'RC1' else "Throttle"

            print(f"\n📊 {channel} ({channel_name}):")
            print(f"   Min:    {data['min']:4d}")
            print(f"   Center: {data['center']:4d}")
            print(f"   Max:    {data['max']:4d}")
            print(f"   Range:  {data['max'] - data['min']:4d}")

            # Probleme erkennen
            if data['min'] >= data['max']:
                print(f"   ❌ PROBLEM: Min >= Max!")
            elif data['max'] - data['min'] < 500:
                print(f"   ⚠️  WARNUNG: Kleiner Range ({data['max'] - data['min']})")
            else:
                print(f"   ✅ OK: Guter Range")

    def apply_calibration(self):
        """Wende Kalibrierung auf Orange Cube an"""
        print("\n🔧 WENDE KALIBRIERUNG AN:")
        print("=" * 50)

        # Parameter für beide Kanäle setzen
        for channel in ['RC1', 'RC3']:
            data = self.calibration_data[channel]
            channel_num = channel[2:]  # '1' oder '3'

            # Parameter setzen
            params = {
                f'RC{channel_num}_MIN': data['min'],
                f'RC{channel_num}_MAX': data['max'],
                f'RC{channel_num}_TRIM': data['center'],
                f'RC{channel_num}_DZ': 50,  # Deadzone
            }

            for param_name, param_value in params.items():
                print(f"📝 Setze {param_name} = {param_value}")
                self.connection.mav.param_set_send(
                    self.connection.target_system,
                    self.connection.target_component,
                    param_name.encode('utf-8'),
                    param_value,
                    mavutil.mavlink.MAV_PARAM_TYPE_REAL32
                )
                time.sleep(0.1)

        print("✅ Kalibrierung angewendet!")

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
    parser = argparse.ArgumentParser(description='Orange Cube RC Channel Calibration')
    parser.add_argument('--connection', default=DEFAULT_CONNECTION,
                        help=f'Verbindungsstring (Standard: {DEFAULT_CONNECTION})')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help=f'Baudrate (Standard: {DEFAULT_BAUDRATE})')

    args = parser.parse_args()

    print("🎯 Orange Cube RC Channel Calibration")
    print("=" * 50)
    print("Dieses Skript misst DEINE echten RC-Werte und kalibriert automatisch!")
    print()

    # Verbindung herstellen
    connection = connect_to_orange_cube(args.connection, args.baudrate)
    if not connection:
        sys.exit(1)

    try:
        calibrator = RCCalibrator(connection)

        # Schritt 1: Center-Position
        if not calibrator.calibrate_center_position():
            print("❌ Center-Kalibrierung fehlgeschlagen!")
            return

        # Schritt 2: Min/Max-Werte
        if not calibrator.calibrate_extremes():
            print("❌ Extrem-Kalibrierung fehlgeschlagen!")
            return

        # Schritt 3: Analyse
        calibrator.analyze_calibration()

        # Schritt 4: Anwenden
        print("\n🎯 Kalibrierung anwenden?")
        response = input("Drücken Sie 'y' um fortzufahren: ")
        if response.lower() == 'y':
            calibrator.apply_calibration()
            print("\n🎉 RC-Kalibrierung abgeschlossen!")
            print("\n📋 Nächste Schritte:")
            print("1. Orange Cube neu starten")
            print("2. RC-Test mit MAVProxy oder Beyond Robotics Board")
            print("3. Beide Kanäle sollten jetzt funktionieren!")
        else:
            print("⚠️ Kalibrierung nicht angewendet")

    except KeyboardInterrupt:
        print("\n⚠️ Kalibrierung abgebrochen")
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
