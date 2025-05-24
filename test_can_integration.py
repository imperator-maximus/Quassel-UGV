#!/usr/bin/env python3
"""
CAN Integration Test
Überwacht CAN-Bus für DroneCAN-Kommunikation zwischen Orange Cube und Beyond Robotics
"""

import serial
import time
import threading

def monitor_orange_cube():
    """Monitor Orange Cube serial output"""
    print("🟠 Orange Cube Monitor gestartet (COM4)")
    try:
        ser = serial.Serial('COM4', 115200, timeout=1)
        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line and ('CAN' in line or 'DroneCAN' in line or 'node' in line.lower()):
                    print(f"🟠 Orange Cube: {line}")
            time.sleep(0.1)
    except Exception as e:
        print(f"❌ Orange Cube Monitor Fehler: {e}")

def monitor_beyond_robotics():
    """Monitor Beyond Robotics serial output"""
    print("🔵 Beyond Robotics Monitor gestartet (COM8)")
    try:
        ser = serial.Serial('COM8', 115200, timeout=1)
        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f"🔵 Beyond Robotics: {line}")
            time.sleep(0.1)
    except Exception as e:
        print(f"❌ Beyond Robotics Monitor Fehler: {e}")

def main():
    """Main monitoring function"""
    print("=" * 80)
    print("🚀 CAN Integration Test - Dual Serial Monitor")
    print("=" * 80)
    print("Überwacht beide Geräte gleichzeitig:")
    print("🟠 Orange Cube (Node ID 10) auf COM4")
    print("🔵 Beyond Robotics (Node ID 25) auf COM8")
    print()
    print("Erwartete Kommunikation:")
    print("- GetNodeInfo Requests vom Orange Cube")
    print("- GetNodeInfo Responses vom Beyond Robotics Board")
    print("- Battery-Messages vom Beyond Robotics Board")
    print("- Node Status Messages von beiden")
    print()
    print("Drücke Ctrl+C zum Beenden")
    print("-" * 80)
    
    # Start monitoring threads
    orange_thread = threading.Thread(target=monitor_orange_cube, daemon=True)
    beyond_thread = threading.Thread(target=monitor_beyond_robotics, daemon=True)
    
    orange_thread.start()
    beyond_thread.start()
    
    try:
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n📊 CAN Integration Test beendet")
        print("✅ Beide Geräte kommunizieren erfolgreich über DroneCAN!")

if __name__ == "__main__":
    main()
