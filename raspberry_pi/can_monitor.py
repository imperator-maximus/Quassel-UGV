#!/usr/bin/env python3
"""
DroneCAN Monitor for Raspberry Pi with Innomaker RS485 CAN HAT
Monitors CAN traffic and communicates with Orange Cube flight controller

Hardware Setup:
- Raspberry Pi 3 with Innomaker RS485 CAN HAT
- Connected to Orange Cube CAN port
- CAN bitrate: 1000000 (1 Mbps)
- DroneCAN 1.0 protocol

Purpose: Replace Beyond Robotics Dev Board with reliable solution

Usage:
    sudo python3 can_monitor.py

Author: Generated for Beyond Robotics → Raspberry Pi migration
"""

import can
import struct
import time
import sys
from datetime import datetime
from typing import Dict, Any, Optional

# DroneCAN Message IDs (from libcanard examples)
DRONECAN_MSG_TYPES = {
    # ESC Messages
    1030: "uavcan.equipment.esc.RawCommand",
    1031: "uavcan.equipment.esc.Status",
    
    # Battery Messages  
    1092: "uavcan.equipment.power.BatteryInfo",
    
    # Node Status
    341: "uavcan.protocol.NodeStatus",
    
    # Parameter Messages
    12: "uavcan.protocol.param.GetSet",
    13: "uavcan.protocol.param.ExecuteOpcode",
    
    # Magnetic Field
    1025: "uavcan.equipment.ahrs.MagneticFieldStrength",
}

class DroneCAN_Monitor:
    def __init__(self, interface: str = 'can0', bitrate: int = 1000000):
        """
        Initialize DroneCAN Monitor
        
        Args:
            interface: CAN interface name (default: can0)
            bitrate: CAN bitrate in bps (default: 1000000)
        """
        self.interface = interface
        self.bitrate = bitrate
        self.bus: Optional[can.Bus] = None
        self.message_count = 0
        self.start_time = time.time()
        
        # Statistics
        self.stats: Dict[str, int] = {}
        
    def setup_can_interface(self) -> bool:
        """Setup CAN interface with correct bitrate"""
        try:
            # Configure CAN interface
            import subprocess

            print(f"🔧 Setting up CAN interface {self.interface}...")

            # Check if interface exists
            result = subprocess.run(['ip', 'link', 'show', self.interface],
                                  capture_output=True, text=True)
            if result.returncode != 0:
                print(f"❌ CAN interface {self.interface} does not exist")
                print("   Make sure CAN HAT is properly configured and reboot was done")
                return False

            # Bring interface down
            subprocess.run(['sudo', 'ip', 'link', 'set', self.interface, 'down'],
                         check=False, capture_output=True)

            # Set bitrate
            result = subprocess.run(['sudo', 'ip', 'link', 'set', self.interface,
                                   'type', 'can', 'bitrate', str(self.bitrate)],
                                  check=True, capture_output=True, text=True)

            # Bring interface up
            subprocess.run(['sudo', 'ip', 'link', 'set', self.interface, 'up'],
                         check=True, capture_output=True)

            print(f"✅ CAN interface {self.interface} configured at {self.bitrate} bps")

            # Verify interface is UP
            result = subprocess.run(['ip', 'link', 'show', self.interface],
                                  capture_output=True, text=True)
            if 'UP' in result.stdout:
                print(f"✅ CAN interface {self.interface} is UP and ready")
                return True
            else:
                print(f"⚠️  CAN interface {self.interface} configured but not UP")
                return False

        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to setup CAN interface: {e}")
            if e.stderr:
                print(f"   Command output: {e.stderr}")
            return False
        except Exception as e:
            print(f"❌ Error setting up CAN interface: {e}")
            return False
    
    def connect(self) -> bool:
        """Connect to CAN bus"""
        try:
            # Setup interface first
            if not self.setup_can_interface():
                return False
                
            # Create CAN bus connection
            self.bus = can.Bus(interface='socketcan', 
                             channel=self.interface, 
                             bitrate=self.bitrate)
            
            print(f"🔗 Connected to CAN bus on {self.interface}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to connect to CAN bus: {e}")
            return False
    
    def decode_esc_command(self, data: bytes) -> Dict[str, Any]:
        """
        Decode ESC RawCommand message
        Format: Array of int16 values (-8192 to +8191)
        """
        try:
            # First byte is array length
            if len(data) < 1:
                return {"error": "Data too short"}
                
            array_len = data[0]
            if array_len > 20:  # Sanity check
                return {"error": f"Invalid array length: {array_len}"}
            
            # Extract motor commands (int16 values)
            commands = []
            for i in range(min(array_len, (len(data) - 1) // 2)):
                offset = 1 + i * 2
                if offset + 1 < len(data):
                    # Little-endian int16
                    value = struct.unpack('<h', data[offset:offset+2])[0]
                    commands.append(value)
            
            return {
                "array_length": array_len,
                "commands": commands,
                "throttle_percent": [round(cmd/8192.0*100, 1) for cmd in commands]
            }
            
        except Exception as e:
            return {"error": f"Decode error: {e}"}
    
    def decode_battery_info(self, data: bytes) -> Dict[str, Any]:
        """Decode Battery Info message"""
        try:
            if len(data) < 8:
                return {"error": "Data too short for battery info"}
            
            # Basic battery info (simplified)
            voltage = struct.unpack('<f', data[0:4])[0]
            current = struct.unpack('<f', data[4:8])[0] if len(data) >= 8 else 0.0
            
            return {
                "voltage": round(voltage, 2),
                "current": round(current, 2)
            }
            
        except Exception as e:
            return {"error": f"Decode error: {e}"}
    
    def process_message(self, msg: can.Message) -> None:
        """Process received CAN message"""
        self.message_count += 1
        
        # Extract DroneCAN info from CAN ID
        # DroneCAN uses extended CAN frames with specific ID format
        can_id = msg.arbitration_id
        
        # Basic DroneCAN ID extraction (simplified)
        data_type_id = (can_id >> 8) & 0xFFFF
        source_node_id = can_id & 0x7F
        
        # Get message type name
        msg_type = DRONECAN_MSG_TYPES.get(data_type_id, f"Unknown_{data_type_id}")
        
        # Update statistics
        self.stats[msg_type] = self.stats.get(msg_type, 0) + 1
        
        # Timestamp
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # Decode specific message types
        decoded_data = None
        if "esc.RawCommand" in msg_type:
            decoded_data = self.decode_esc_command(msg.data)
        elif "BatteryInfo" in msg_type:
            decoded_data = self.decode_battery_info(msg.data)
        
        # Print message info
        print(f"[{timestamp}] 🎯 {msg_type}")
        print(f"  Node ID: {source_node_id}")
        print(f"  Data Type ID: {data_type_id}")
        print(f"  Data Length: {len(msg.data)}")
        print(f"  Raw Data: {msg.data.hex()}")
        
        if decoded_data:
            print(f"  Decoded: {decoded_data}")
        
        print("-" * 60)
    
    def print_statistics(self) -> None:
        """Print message statistics"""
        runtime = time.time() - self.start_time
        print(f"\n📊 STATISTICS (Runtime: {runtime:.1f}s)")
        print(f"Total Messages: {self.message_count}")
        print(f"Messages/sec: {self.message_count/runtime:.1f}")
        print("\nMessage Types:")
        for msg_type, count in sorted(self.stats.items()):
            print(f"  {msg_type}: {count}")
        print("-" * 60)
    
    def monitor(self) -> None:
        """Main monitoring loop"""
        if not self.connect():
            return
        
        print("🚀 DroneCAN Monitor started")
        print("📡 Listening for Orange Cube messages...")
        print("   Press Ctrl+C to stop")
        print("=" * 60)
        
        try:
            last_stats = time.time()
            
            while True:
                # Receive message with timeout
                msg = self.bus.recv(timeout=1.0)
                
                if msg is not None:
                    self.process_message(msg)
                
                # Print statistics every 10 seconds
                if time.time() - last_stats > 10:
                    self.print_statistics()
                    last_stats = time.time()
                    
        except KeyboardInterrupt:
            print("\n🛑 Monitoring stopped by user")
        except Exception as e:
            print(f"❌ Error during monitoring: {e}")
        finally:
            if self.bus:
                self.bus.shutdown()
            self.print_statistics()

def main():
    """Main function"""
    print("🤖 DroneCAN Message Monitor")
    print("   Beyond Robotics → Raspberry Pi Migration")
    print("   Orange Cube CAN Message Decoder")
    print()
    
    # Check if running as root
    if os.geteuid() != 0:
        print("⚠️  This script needs root privileges for CAN interface setup")
        print("   Please run: sudo python3 can_monitor.py")
        sys.exit(1)
    
    monitor = DroneCAN_Monitor()
    monitor.monitor()

if __name__ == "__main__":
    import os
    main()
