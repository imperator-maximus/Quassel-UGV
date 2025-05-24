#!/usr/bin/env python3
"""
Simple CAN Activity Monitor
Monitors Orange Cube for DroneCAN activity to detect Beyond Robotics Dev Board
"""

import time
import sys
from pymavlink import mavutil
from datetime import datetime

def main():
    print("=" * 60)
    print("Simple CAN Activity Monitor")
    print("=" * 60)
    print("Monitoring Orange Cube for DroneCAN activity...")
    print("Looking for Beyond Robotics Dev Board communication")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    
    try:
        # Connect to Orange Cube
        master = mavutil.mavlink_connection('COM4', baud=57600)
        print("Waiting for Orange Cube heartbeat...")
        master.wait_heartbeat()
        print(f"✅ Connected to Orange Cube (System: {master.target_system})")
        print()
        
        # Message counters
        message_counts = {}
        start_time = time.time()
        last_stats_time = time.time()
        
        print("Monitoring MAVLink messages...")
        print("Looking for DroneCAN/UAVCAN related messages...")
        print("-" * 60)
        
        while True:
            # Read messages
            msg = master.recv_match(blocking=False)
            if msg:
                msg_type = msg.get_type()
                
                # Count messages
                if msg_type not in message_counts:
                    message_counts[msg_type] = 0
                message_counts[msg_type] += 1
                
                # Show interesting messages
                if msg_type in ['UAVCAN_NODE_STATUS', 'CAN_FRAME', 'CANFD_FRAME', 
                               'UAVCAN_NODE_INFO', 'BATTERY_STATUS', 'ESC_STATUS']:
                    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    print(f"[{timestamp}] 🔍 {msg_type}: {msg}")
                
                # Show any message with "CAN" or "UAVCAN" in the name
                if 'CAN' in msg_type or 'UAVCAN' in msg_type:
                    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    print(f"[{timestamp}] 📡 {msg_type}: {msg}")
                
                # Show new message types (potential DroneCAN activity)
                if msg_type not in ['HEARTBEAT', 'SYS_STATUS', 'ATTITUDE', 'GPS_RAW_INT',
                                   'VFR_HUD', 'SERVO_OUTPUT_RAW', 'RC_CHANNELS_RAW',
                                   'SYSTEM_TIME', 'POWER_STATUS', 'MEMINFO', 'AHRS2',
                                   'SIMSTATE', 'AHRS3', 'HWSTATUS', 'WIND', 'VIBRATION',
                                   'EKF_STATUS_REPORT', 'LOCAL_POSITION_NED', 'GLOBAL_POSITION_INT']:
                    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    print(f"[{timestamp}] 🆕 NEW: {msg_type}")
            
            # Print statistics every 10 seconds
            current_time = time.time()
            if current_time - last_stats_time > 10:
                last_stats_time = current_time
                runtime = current_time - start_time
                
                print(f"\n📊 STATS (Runtime: {runtime:.1f}s)")
                print(f"Total message types: {len(message_counts)}")
                
                # Show top 5 most frequent messages
                sorted_msgs = sorted(message_counts.items(), key=lambda x: x[1], reverse=True)
                print("Top messages:")
                for msg_type, count in sorted_msgs[:5]:
                    print(f"  {msg_type}: {count}")
                
                # Look for CAN-related messages
                can_messages = {k: v for k, v in message_counts.items() 
                               if 'CAN' in k or 'UAVCAN' in k}
                if can_messages:
                    print("🔍 CAN-related messages:")
                    for msg_type, count in can_messages.items():
                        print(f"  {msg_type}: {count}")
                else:
                    print("❌ No CAN-related messages detected yet")
                
                print("-" * 60)
            
            time.sleep(0.01)  # Small delay
            
    except KeyboardInterrupt:
        print(f"\n\n📊 Final Statistics:")
        runtime = time.time() - start_time
        print(f"Runtime: {runtime:.1f} seconds")
        print(f"Total message types: {len(message_counts)}")
        
        # Show all message types
        print("\nAll message types received:")
        for msg_type, count in sorted(message_counts.items()):
            print(f"  {msg_type}: {count}")
        
        # Highlight CAN messages
        can_messages = {k: v for k, v in message_counts.items() 
                       if 'CAN' in k or 'UAVCAN' in k}
        if can_messages:
            print(f"\n🎯 CAN-related messages found:")
            for msg_type, count in can_messages.items():
                print(f"  ✅ {msg_type}: {count}")
        else:
            print(f"\n❌ No CAN-related messages detected")
            print("This suggests the Beyond Robotics Dev Board is not communicating")
        
        print("\nMonitoring stopped.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
