#!/usr/bin/env python3

import dronecan
import time
import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description='Send DroneCAN actuator commands')
    parser.add_argument('--port', '-p', type=str, default='COM5', help='Serial port (default: COM5)')
    parser.add_argument('--bitrate', '-b', type=int, default=1000000, help='CAN bitrate (default: 1000000)')
    args = parser.parse_args()

    # Initialize DroneCAN node
    node = dronecan.make_node(args.port, bitrate=args.bitrate)
    node_monitor = dronecan.app.node_monitor.NodeMonitor(node)
    
    # Wait for the node to become ready
    print(f"Initializing DroneCAN node on {args.port} at {args.bitrate} bps...")
    time.sleep(1)
    
    # Create an actuator command message
    actuator_cmd = dronecan.uavcan.equipment.actuator.Command()
    
    try:
        # Main loop
        print("Sending actuator commands. Press Ctrl+C to stop.")
        motor_value = 0.0
        direction = 0.01  # Increment value
        
        while True:
            # Update motor value (oscillate between 0.0 and 1.0)
            motor_value += direction
            if motor_value >= 1.0 or motor_value <= 0.0:
                direction = -direction
                
            # Set command values
            actuator_cmd.command_type = 0  # Command type (0 = position)
            actuator_cmd.actuator_id = 0   # Actuator ID
            actuator_cmd.command_value = float(motor_value)  # Command value (0.0 to 1.0)
            
            # Broadcast the message
            node.broadcast(actuator_cmd)
            print(f"Sent actuator command: value={motor_value:.2f}")
            
            # Wait a bit
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("Stopped by user")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Close the node
        node.close()

if __name__ == "__main__":
    main()
