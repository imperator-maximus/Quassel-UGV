#!/usr/bin/env python3
"""
Beyond Robotics Serial Monitor
Überwacht COM8 für DroneCAN-Nachrichten
"""

import serial
import time
import sys

def monitor_serial():
    """Monitor COM8 for Beyond Robotics messages"""
    print("=" * 60)
    print("🚀 Beyond Robotics Serial Monitor")
    print("=" * 60)
    print("Port: COM8")
    print("Baud: 115200")
    print("Erwartete Nachrichten:")
    print("- PARM_1 value: 69")
    print("- DroneCAN initialization")
    print("- Battery info messages (alle 100ms)")
    print("- CPU temperature readings")
    print()
    print("Drücke Ctrl+C zum Beenden")
    print("-" * 60)
    
    try:
        # Open serial connection
        ser = serial.Serial('COM8', 115200, timeout=1)
        print(f"✅ Verbunden mit {ser.name}")
        print()
        
        message_count = 0
        start_time = time.time()
        
        while True:
            try:
                # Read line
                if ser.in_waiting > 0:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        message_count += 1
                        timestamp = time.time() - start_time
                        print(f"[{timestamp:8.2f}s] {line}")
                        
                        # Highlight important messages
                        if "PARM_1" in line:
                            print("    🎯 Parameter-Nachricht erkannt!")
                        elif "battery" in line.lower():
                            print("    🔋 Battery-Info erkannt!")
                        elif "temperature" in line.lower():
                            print("    🌡️ Temperatur-Reading erkannt!")
                        elif "dronecan" in line.lower():
                            print("    📡 DroneCAN-Nachricht erkannt!")
                
                time.sleep(0.01)  # Small delay
                
            except UnicodeDecodeError:
                # Skip binary data
                pass
                
    except serial.SerialException as e:
        print(f"❌ Serial-Fehler: {e}")
        print("\nTROUBLESHOOTING:")
        print("1. Prüfe, ob COM8 verfügbar ist")
        print("2. Stelle sicher, dass kein anderes Programm COM8 verwendet")
        print("3. Board reset versuchen")
        
    except KeyboardInterrupt:
        print(f"\n\n📊 STATISTIK:")
        print(f"Nachrichten empfangen: {message_count}")
        print(f"Laufzeit: {time.time() - start_time:.1f} Sekunden")
        print("✅ Monitoring beendet")
        
    finally:
        try:
            ser.close()
        except:
            pass

if __name__ == "__main__":
    monitor_serial()
