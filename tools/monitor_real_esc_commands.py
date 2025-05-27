#!/usr/bin/env python3
"""
Beyond Robotics CAN Node Serial Monitor
Monitors COM8 for CAN test output from Beyond Robotics Dev Board
"""

import serial
import time
import sys
from datetime import datetime

# Konfiguration
BEYOND_ROBOTICS_PORT = 'COM8'
BAUD_RATE = 115200
TIMEOUT = 1

def main():
    print("=" * 70)
    print("    🎯 Real ESC Commands Monitor")
    print("=" * 70)
    print("Überwacht ECHTE ESC-Befehle zwischen Orange Cube und Beyond Robotics")
    print("Beyond Robotics Board sollte ESC-Befehle vom Orange Cube empfangen!")
    print("=" * 70)
    print()

    try:
        # Beyond Robotics Board überwachen
        ser = serial.Serial(BEYOND_ROBOTICS_PORT, BAUD_RATE, timeout=TIMEOUT)
        print(f"✅ Verbunden mit Beyond Robotics Board auf {BEYOND_ROBOTICS_PORT}")
        print("🔍 Überwache ESC-Befehle...")
        print("   (Drücken Sie Ctrl+C zum Beenden)")
        print("-" * 70)

        esc_command_count = 0
        battery_count = 0

        while True:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    timestamp = datetime.now().strftime("%H:%M:%S")

                    # ESC-Befehle hervorheben
                    if "ESC" in line.upper() or "MOTOR" in line.upper() or "PWM" in line.upper():
                        esc_command_count += 1
                        print(f"🎯 {timestamp} | ESC #{esc_command_count}: {line}")
                    elif "Battery" in line or "🔋" in line:
                        battery_count += 1
                        print(f"🔋 {timestamp} | Battery #{battery_count}: {line}")
                    else:
                        print(f"📡 {timestamp} | {line}")

            except KeyboardInterrupt:
                print(f"\n🛑 Überwachung beendet")
                print(f"📊 Statistik: {esc_command_count} ESC-Befehle, {battery_count} Battery-Nachrichten")
                break
            except Exception as e:
                print(f"❌ Fehler: {e}")
                time.sleep(1)

    except serial.SerialException as e:
        print(f"❌ Verbindungsfehler: {e}")
        return 1
    except Exception as e:
        print(f"❌ Unerwarteter Fehler: {e}")
        return 1
    finally:
        try:
            ser.close()
            print("🔌 Verbindung geschlossen")
        except:
            pass

    return 0

if __name__ == "__main__":
    sys.exit(main())
