#!/usr/bin/env python3
"""
Quick Orange Cube Monitor - Startet direkt die Nachrichten-Überwachung
"""

import time
import sys
from pymavlink import mavutil

def main():
    """Hauptfunktion - startet direkt die Überwachung"""
    connection_string = 'COM4'
    baud_rate = 57600
    
    print("=" * 60)
    print("Quick Orange Cube Monitor - CAN Activity Detection")
    print("=" * 60)
    print(f"Verbinde mit Orange Cube auf {connection_string}...")
    
    try:
        # Verbindung herstellen
        master = mavutil.mavlink_connection(connection_string, baud=baud_rate)
        
        # Warten auf Heartbeat
        print("Warte auf Heartbeat...")
        master.wait_heartbeat()
        print(f"✅ Verbunden mit System: {master.target_system}, Komponente: {master.target_component}")
        
    except Exception as e:
        print(f"❌ Fehler beim Verbinden: {e}")
        sys.exit(1)
    
    print("\n🔍 Überwache MAVLink-Nachrichten für 30 Sekunden...")
    print("Suche nach DroneCAN-Aktivität vom Beyond Robotics Board...")
    print("-" * 60)
    
    # Nachrichtenzähler
    message_counts = {}
    dronecan_activity = False
    start_time = time.time()
    
    # Hauptüberwachungsschleife
    while time.time() - start_time < 30:
        # Auf neue Nachrichten prüfen
        msg = master.recv_match(blocking=True, timeout=1.0)
        if msg is None:
            continue
        
        # Nachrichtentyp zählen
        msg_type = msg.get_type()
        if msg_type in message_counts:
            message_counts[msg_type] += 1
        else:
            message_counts[msg_type] = 1
        
        # DroneCAN-spezifische Nachrichten
        if msg_type == 'UAVCAN_NODE_STATUS':
            dronecan_activity = True
            print(f"🟢 DroneCAN Node Status: ID={msg.node_id}, Health={msg.health}, Mode={msg.mode}")
        
        # Servo-Ausgänge anzeigen (zeigt CAN-Aktivität)
        if msg_type == 'SERVO_OUTPUT_RAW':
            if message_counts[msg_type] % 10 == 1:  # Nur jede 10. Nachricht anzeigen
                print(f"📊 Servo-Ausgänge: 1={msg.servo1_raw}, 2={msg.servo2_raw}, 3={msg.servo3_raw}, 4={msg.servo4_raw}")
        
        # Statusmeldungen
        if msg_type == 'STATUSTEXT':
            text = msg.text.decode('utf-8') if hasattr(msg.text, 'decode') else msg.text
            if 'CAN' in text or 'DroneCAN' in text or 'UAVCAN' in text:
                print(f"🔵 CAN Status: {text}")
            elif 'error' in text.lower() or 'fail' in text.lower():
                print(f"🔴 Error: {text}")
        
        # Heartbeat vom Orange Cube
        if msg_type == 'HEARTBEAT' and message_counts[msg_type] % 20 == 1:
            print(f"💓 Orange Cube Heartbeat #{message_counts[msg_type]}")
    
    # Zusammenfassung anzeigen
    print("\n" + "=" * 60)
    print("ÜBERWACHUNG ABGESCHLOSSEN")
    print("=" * 60)
    
    print(f"\n📊 Empfangene Nachrichtentypen ({len(message_counts)} verschiedene):")
    for msg_type, count in sorted(message_counts.items()):
        if count > 5:  # Nur häufige Nachrichten anzeigen
            print(f"  {msg_type}: {count}")
    
    if dronecan_activity:
        print("\n🎉 DroneCAN-Aktivität erkannt!")
        print("✅ Beyond Robotics Board kommuniziert erfolgreich über DroneCAN")
    else:
        print("\n⚠️  Keine DroneCAN-Aktivität erkannt")
        print("❌ Beyond Robotics Board sendet möglicherweise keine DroneCAN-Nachrichten")
    
    print(f"\n📈 Gesamte Nachrichten: {sum(message_counts.values())}")
    print("=" * 60)

if __name__ == "__main__":
    main()
