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
import argparse
from datetime import datetime
from typing import Dict, Any, Optional

# DroneCAN library for proper message decoding
try:
    import dronecan
    DRONECAN_AVAILABLE = True
except ImportError:
    print("⚠️  DroneCAN library not available. Install with: pip3 install dronecan")
    DRONECAN_AVAILABLE = False

# DroneCAN Message IDs (DroneCAN 1.0 Standard + Vendor-specific)
DRONECAN_MSG_TYPES = {
    # ESC Messages
    1030: "uavcan.equipment.esc.RawCommand",
    1031: "uavcan.equipment.esc.Status",

    # Battery Messages
    1092: "uavcan.equipment.power.BatteryInfo",

    # Node Status & Protocol
    341: "uavcan.protocol.NodeStatus",
    7509: "uavcan.protocol.GetNodeInfo",

    # Parameter Messages
    12: "uavcan.protocol.param.GetSet",
    13: "uavcan.protocol.param.ExecuteOpcode",

    # Magnetic Field & AHRS
    1025: "uavcan.equipment.ahrs.MagneticFieldStrength",
    1000: "uavcan.equipment.ahrs.Solution",
    1001: "uavcan.equipment.ahrs.MagneticFieldStrength2",

    # Navigation & GPS
    1010: "uavcan.equipment.gnss.Fix",
    1011: "uavcan.equipment.gnss.Fix2",
    1060: "uavcan.equipment.indication.BeepCommand",
    1061: "uavcan.equipment.indication.LightsCommand",

    # Air Data
    1027: "uavcan.equipment.air_data.StaticPressure",
    1028: "uavcan.equipment.air_data.StaticTemperature",
    1029: "uavcan.equipment.air_data.Sideslip",

    # Actuator Messages
    1010: "uavcan.equipment.actuator.ArrayCommand",
    1011: "uavcan.equipment.actuator.Command",
    1012: "uavcan.equipment.actuator.Status",

    # Camera & Gimbal
    1044: "uavcan.equipment.camera_gimbal.AngularCommand",
    1045: "uavcan.equipment.camera_gimbal.GEOPOICommand",

    # Safety & Hardpoint
    1100: "uavcan.equipment.safety.ArmingStatus",
    1101: "uavcan.equipment.hardpoint.Command",
    1102: "uavcan.equipment.hardpoint.Status",

    # Vendor-specific Messages (ArduPilot/Orange Cube)
    20000: "ardupilot.indication.NotifyState",
    20001: "ardupilot.indication.Button",
    20002: "ardupilot.equipment.trafficmonitor.TrafficReport",
    20003: "ardupilot.equipment.power.BatteryInfoAux",
    20004: "ardupilot.gnss.Status",
    20005: "ardupilot.gnss.MovingBaselineData",
    20006: "ardupilot.gnss.RelPosHeading",
    20007: "ardupilot.equipment.esp32.WiFiConfigCommand",
    20008: "ardupilot.equipment.esp32.WiFiConfigResponse",
}

class DroneCAN_Monitor:
    def __init__(self, interface: str = 'can0', bitrate: int = 1000000,
                 filter_mode: str = 'all', verbose: bool = True):
        """
        Initialize DroneCAN Monitor

        Args:
            interface: CAN interface name (default: can0)
            bitrate: CAN bitrate in bps (default: 1000000)
            filter_mode: Message filter ('all', 'esc', 'important') (default: all)
            verbose: Show detailed output (default: True)
        """
        self.interface = interface
        self.bitrate = bitrate
        self.filter_mode = filter_mode
        self.verbose = verbose
        self.bus: Optional[can.Bus] = None
        self.message_count = 0
        self.start_time = time.time()

        # Statistics
        self.stats: Dict[str, int] = {}

        # Last ESC command for change detection
        self.last_esc_command = None
        
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
    
    def decode_esc_command(self, data: bytes, can_id: int = 0) -> Dict[str, Any]:
        """
        Decode DroneCAN ESC RawCommand message according to DroneCAN 1.0 specification

        DroneCAN format (from DSDL specification):
        int14[<=20] cmd

        Bit-packed format:
        - Bits 0-4: Array length (5 bits, max 20)
        - Following bits: 14-bit signed integers for each motor command
        - Value range: -8192 to +8191 (14-bit signed)
        - Conversion: throttle = cmd.data[i]/8192.0 (Beyond Robotics: line 375)

        Reference: uavcan.equipment.esc.RawCommand.h lines 117-142
        """
        try:
            if len(data) < 1:
                return {"error": "Data too short"}

            # Convert bytes to bit array for bit-level operations
            bit_data = 0
            for i, byte in enumerate(data):
                bit_data |= (byte << (i * 8))

            # Extract array length from first 5 bits
            array_len = bit_data & 0x1F  # 0x1F = 0b11111 (5 bits)

            # Sanity check for array length
            if array_len > 20:
                return {"error": f"Invalid array length: {array_len} (max 20)"}

            # Calculate expected bit length: 5 bits for length + 14 bits per motor
            expected_bits = 5 + (array_len * 14)
            expected_bytes = (expected_bits + 7) // 8  # Round up to nearest byte

            if len(data) < expected_bytes:
                return {"error": f"Data too short: expected {expected_bytes} bytes, got {len(data)}"}

            # Extract motor commands (14-bit signed values)
            commands = []
            bit_offset = 5  # Start after the 5-bit length field

            for i in range(array_len):
                # Extract 14 bits starting at bit_offset
                mask = 0x3FFF  # 0x3FFF = 0b11111111111111 (14 bits)
                raw_value = (bit_data >> bit_offset) & mask

                # Convert from 14-bit unsigned to signed (-8192 to +8191)
                if raw_value >= 8192:  # If MSB is set (negative number)
                    signed_value = raw_value - 16384  # Convert to signed
                else:
                    signed_value = raw_value

                commands.append(signed_value)
                bit_offset += 14

            # Convert to various useful formats (following Beyond Robotics approach)
            throttle_values = []  # -1.0 to +1.0 range
            throttle_percent = []  # -100% to +100%
            pwm_equivalent = []   # 1000-2000 μs range

            for cmd in commands:
                # Beyond Robotics conversion: throttle = cmd/8192.0
                throttle = cmd / 8192.0
                throttle_values.append(round(throttle, 4))

                # Convert to percentage
                percent = round(throttle * 100, 1)
                throttle_percent.append(percent)

                # Convert to PWM equivalent (1000-2000 μs range)
                # 0 = 1500μs (neutral), -8192 = 1000μs, +8191 = 2000μs
                pwm_us = int(1500 + throttle * 500)
                pwm_equivalent.append(pwm_us)

            # Analyze motor status for skid steering
            motor_status = self._analyze_motor_commands(commands, array_len)

            return {
                "format": "DroneCAN_BitPacked",
                "array_length": array_len,
                "raw_commands": commands,
                "throttle_values": throttle_values,  # -1.0 to +1.0 (Beyond Robotics format)
                "throttle_percent": throttle_percent,
                "pwm_equivalent_us": pwm_equivalent,
                "motor_status": motor_status,
                "data_hex": data.hex()
            }

        except Exception as e:
            return {"error": f"Decode error: {e}", "raw_hex": data.hex()}

    def _analyze_motor_commands(self, commands: list, array_len: int) -> str:
        """Analyze motor commands and return human-readable status"""
        if not commands or array_len == 0:
            return "NO_MOTORS"

        if array_len == 1:
            # Single motor
            cmd = commands[0]
            if cmd == 0:
                return "STOPPED"
            elif cmd > 0:
                return f"FORWARD ({cmd})"
            else:
                return f"BACKWARD ({cmd})"

        elif array_len == 2:
            # Skid steering (2 motors) - Beyond Robotics configuration
            left, right = commands[0], commands[1]

            if left == 0 and right == 0:
                return "STOPPED"
            elif left > 0 and right > 0:
                if abs(left - right) < 100:  # Similar values
                    return f"FORWARD (L:{left}, R:{right})"
                elif left > right:
                    return f"FORWARD_RIGHT (L:{left}, R:{right})"
                else:
                    return f"FORWARD_LEFT (L:{left}, R:{right})"
            elif left < 0 and right < 0:
                if abs(left - right) < 100:  # Similar values
                    return f"BACKWARD (L:{left}, R:{right})"
                elif left < right:  # left more negative
                    return f"BACKWARD_RIGHT (L:{left}, R:{right})"
                else:
                    return f"BACKWARD_LEFT (L:{left}, R:{right})"
            elif left > 0 and right < 0:
                return f"TURN_RIGHT (L:{left}, R:{right})"
            elif left < 0 and right > 0:
                return f"TURN_LEFT (L:{left}, R:{right})"
            else:
                return f"CUSTOM (L:{left}, R:{right})"

        else:
            # Multi-motor configuration
            active_motors = sum(1 for cmd in commands if cmd != 0)
            return f"{active_motors}/{array_len} motors active"
    
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
    
    def extract_dronecan_info(self, can_id: int) -> Dict[str, int]:
        """
        Extract DroneCAN information from CAN ID
        DroneCAN 1.0 CAN ID format (29-bit extended):
        - Bits 28-24: Priority (5 bits)
        - Bits 23-16: Data Type ID high byte (8 bits)
        - Bits 15-8:  Data Type ID low byte (8 bits)
        - Bits 7-1:   Source Node ID (7 bits)
        - Bit 0:      Transfer Type (0=message, 1=service)
        """
        priority = (can_id >> 24) & 0x1F
        data_type_id = (can_id >> 8) & 0xFFFF
        source_node_id = (can_id >> 1) & 0x7F
        transfer_type = can_id & 0x01

        return {
            "priority": priority,
            "data_type_id": data_type_id,
            "source_node_id": source_node_id,
            "transfer_type": transfer_type
        }

    def should_display_message(self, msg_type: str, decoded_data: Dict[str, Any] = None) -> bool:
        """Determine if message should be displayed based on filter mode"""
        if self.filter_mode == 'all':
            return True
        elif self.filter_mode == 'esc':
            return "esc.RawCommand" in msg_type
        elif self.filter_mode == 'important':
            important_types = [
                "esc.RawCommand",
                "BatteryInfo",
                "NodeStatus",
                "ArmingStatus"
            ]
            return any(important in msg_type for important in important_types)
        return True

    def format_esc_output(self, decoded_data: Dict[str, Any], timestamp: str) -> str:
        """Format ESC command output in compact form"""
        if not decoded_data or "error" in decoded_data:
            error_msg = decoded_data.get("error", "Unknown error") if decoded_data else "No data"
            return f"[{timestamp}] ❌ ESC: {error_msg}"

        # DroneCAN Standard format
        if "raw_commands" in decoded_data and "motor_status" in decoded_data:
            commands = decoded_data["raw_commands"]
            throttles = decoded_data.get("throttle_percent", [])
            status = decoded_data["motor_status"]
            array_len = decoded_data.get("array_length", len(commands))

            if array_len == 2 and len(commands) >= 2:
                # Skid steering format
                return (f"[{timestamp}] 🚗 ESC: L={commands[0]:5d} ({throttles[0]:+6.1f}%) "
                       f"R={commands[1]:5d} ({throttles[1]:+6.1f}%) → {status}")
            elif array_len == 1 and len(commands) >= 1:
                # Single motor format
                return (f"[{timestamp}] 🚗 ESC: M={commands[0]:5d} ({throttles[0]:+6.1f}%) → {status}")
            else:
                # Multi-motor format
                cmd_str = ", ".join(f"{cmd}" for cmd in commands[:4])  # Show first 4
                return f"[{timestamp}] 🚗 ESC: [{cmd_str}] → {status}"

        return f"[{timestamp}] 🚗 ESC: {decoded_data}"

    def process_message(self, msg: can.Message) -> None:
        """Process received CAN message"""
        self.message_count += 1

        # Extract DroneCAN info from CAN ID
        dronecan_info = self.extract_dronecan_info(msg.arbitration_id)
        data_type_id = dronecan_info["data_type_id"]
        source_node_id = dronecan_info["source_node_id"]

        # Get message type name
        msg_type = DRONECAN_MSG_TYPES.get(data_type_id, f"Unknown_{data_type_id}")

        # Update statistics
        self.stats[msg_type] = self.stats.get(msg_type, 0) + 1

        # Decode specific message types
        decoded_data = None
        if "esc.RawCommand" in msg_type:
            decoded_data = self.decode_esc_command(msg.data, msg.arbitration_id)
        elif "BatteryInfo" in msg_type:
            decoded_data = self.decode_battery_info(msg.data)

        # Check if message should be displayed
        if not self.should_display_message(msg_type, decoded_data):
            return

        # Timestamp
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Special compact format for ESC commands
        if "esc.RawCommand" in msg_type and self.filter_mode == 'esc':
            # Only show ESC commands that changed significantly
            if decoded_data and "raw_commands" in decoded_data:
                current_cmd = decoded_data["raw_commands"]
                if (self.last_esc_command is None or
                    self._esc_command_changed(current_cmd, self.last_esc_command)):
                    print(self.format_esc_output(decoded_data, timestamp))
                    self.last_esc_command = current_cmd.copy() if current_cmd else None
            else:
                # Show decode errors
                print(self.format_esc_output(decoded_data, timestamp))
            return

        # Verbose output for other modes
        if self.verbose:
            print(f"[{timestamp}] 🎯 {msg_type}")
            print(f"  Node ID: {source_node_id}")
            print(f"  Data Type ID: {data_type_id}")
            print(f"  Priority: {dronecan_info['priority']}")
            print(f"  Transfer Type: {'Service' if dronecan_info['transfer_type'] else 'Message'}")
            print(f"  Data Length: {len(msg.data)}")
            print(f"  Raw Data: {msg.data.hex()}")

            if decoded_data:
                if "esc.RawCommand" in msg_type:
                    print(f"  🚗 {self.format_esc_output(decoded_data, timestamp).split('🚗 ')[1]}")
                else:
                    print(f"  Decoded: {decoded_data}")

            print("-" * 60)
        else:
            # Compact output
            if "esc.RawCommand" in msg_type:
                print(self.format_esc_output(decoded_data, timestamp))
            else:
                print(f"[{timestamp}] 📡 {msg_type}")

    def _esc_command_changed(self, current: list, last: list) -> bool:
        """Check if ESC command changed significantly"""
        if not current or not last or len(current) != len(last):
            return True

        # Check if motor values changed by more than threshold
        threshold = 50  # Raw value threshold

        for i in range(len(current)):
            if abs(current[i] - last[i]) > threshold:
                return True

        return False
    
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
    parser = argparse.ArgumentParser(description='DroneCAN Message Monitor for Raspberry Pi')
    parser.add_argument('--filter', '-f', choices=['all', 'esc', 'important'],
                       default='all', help='Message filter mode (default: all)')
    parser.add_argument('--quiet', '-q', action='store_true',
                       help='Compact output mode')
    parser.add_argument('--interface', '-i', default='can0',
                       help='CAN interface (default: can0)')
    parser.add_argument('--bitrate', '-b', type=int, default=1000000,
                       help='CAN bitrate (default: 1000000)')

    args = parser.parse_args()

    print("🤖 DroneCAN Message Monitor")
    print("   Beyond Robotics → Raspberry Pi Migration")
    print("   Orange Cube CAN Message Decoder")
    print(f"   Filter: {args.filter} | Verbose: {not args.quiet}")
    print()

    # Check if running as root
    if os.geteuid() != 0:
        print("⚠️  This script needs root privileges for CAN interface setup")
        print("   Please run: sudo python3 can_monitor.py")
        sys.exit(1)

    monitor = DroneCAN_Monitor(
        interface=args.interface,
        bitrate=args.bitrate,
        filter_mode=args.filter,
        verbose=not args.quiet
    )
    monitor.monitor()

if __name__ == "__main__":
    import os
    main()
