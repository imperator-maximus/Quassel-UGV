#!/usr/bin/env python3
"""
Beyond Robotics CAN Node Serial Monitor
Monitors COM8 for CAN test output from Beyond Robotics Dev Board
"""

import serial
import time
import sys
from datetime import datetime

def main():
    print("=" * 60)
    print("Beyond Robotics CAN Node Serial Monitor")
    print("=" * 60)
    print(f"Monitoring COM8 at 115200 baud")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    try:
        # Open serial connection
        # Open serial connection at 115200 baud
        ser = serial.Serial(
            port='COM8',
            baudrate=115200,
            timeout=1,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE
        )

        print(f"Serial connection opened: {ser.name}")
        print("Waiting for data...")
        print("-" * 60)

        line_count = 0

        while True:
            try:
                # Read line from serial
                if ser.in_waiting > 0:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        line_count += 1
                        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]

                        # Color coding for different message types
                        if "[RX]" in line:
                            print(f"[{timestamp}] 🟢 {line}")
                        elif "Sent heartbeat" in line:
                            print(f"[{timestamp}] 🔵 {line}")
                        elif "STATS" in line:
                            print(f"[{timestamp}] 📊 {line}")
                        elif "ERROR" in line or "Failed" in line:
                            print(f"[{timestamp}] 🔴 {line}")
                        elif "Initializing" in line or "successful" in line:
                            print(f"[{timestamp}] ✅ {line}")
                        else:
                            print(f"[{timestamp}] ℹ️  {line}")

                time.sleep(0.01)  # Small delay to prevent CPU overload

            except UnicodeDecodeError:
                # Skip lines that can't be decoded
                continue

    except serial.SerialException as e:
        print(f"❌ Serial connection error: {e}")
        print("\nTroubleshooting:")
        print("- Check if COM8 is available")
        print("- Ensure STM-LINK V3 is connected")
        print("- Verify Beyond Robotics Dev Board is programmed")
        return 1

    except KeyboardInterrupt:
        print(f"\n\n📊 Session Summary:")
        print(f"Total lines received: {line_count}")
        print(f"Session duration: {datetime.now().strftime('%H:%M:%S')}")
        print("Monitor stopped by user")
        return 0

    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return 1

    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Serial connection closed")

if __name__ == "__main__":
    sys.exit(main())
