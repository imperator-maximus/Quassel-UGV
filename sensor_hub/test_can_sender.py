#!/usr/bin/env python3
"""
Einfacher CAN-Test Sender für Sensor Hub
Sendet Test-JSON-Nachrichten über CAN
"""

import can
import json
import time

def send_can_json(bus, json_str):
    """Sendet JSON-String über CAN (Multi-Frame)"""
    data_bytes = json_str.encode('utf-8')

    # Multi-Frame Übertragung (6 Bytes Nutzdaten pro Frame, 2 Bytes Header)
    chunk_size = 6
    total_frames = (len(data_bytes) + chunk_size - 1) // chunk_size

    for frame_idx in range(total_frames):
        start = frame_idx * chunk_size
        end = min(start + chunk_size, len(data_bytes))
        chunk = data_bytes[start:end]

        # Frame-Header: [frame_idx, total_frames, ...data (max 6 bytes)]
        frame_data = bytes([frame_idx, total_frames]) + chunk
        # Auf 8 Bytes auffüllen
        frame_data = frame_data + b'\x00' * (8 - len(frame_data))

        msg = can.Message(
            arbitration_id=0x100,
            data=frame_data,
            is_extended_id=False
        )

        bus.send(msg)
        time.sleep(0.001)  # 1ms zwischen Frames

def main():
    print("🚀 CAN Test Sender gestartet")
    
    # CAN-Bus initialisieren (bitrate nicht angeben, da bereits konfiguriert)
    bus = can.interface.Bus(channel='can0', interface='socketcan')
    print("✅ CAN-Bus initialisiert (can0)")
    
    try:
        counter = 0
        while True:
            # Test-Daten erstellen
            sensor_data = {
                'gps': {'lat': 53.8234 + counter * 0.0001, 'lon': 10.4567, 'altitude': 45.2},
                'heading': 45.2 + counter,
                'rtk_status': 'FIXED',
                'imu': {'roll': 2.3, 'pitch': -1.8},
                'timestamp': time.time(),
                'counter': counter
            }
            
            json_str = json.dumps(sensor_data)
            print(f"📤 Sende: {json_str[:80]}...")
            
            send_can_json(bus, json_str)
            
            counter += 1
            time.sleep(0.02)  # 50Hz
    
    except KeyboardInterrupt:
        print("\n⏹️  Beende...")
    finally:
        bus.shutdown()
        print("✅ CAN-Bus geschlossen")

if __name__ == '__main__':
    main()

