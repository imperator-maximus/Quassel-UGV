#!/usr/bin/env python3
"""
Dump ALL Orange Cube Parameters
Liest ALLE aktuellen Parameter aus und speichert sie für Master-Config-Script

UPDATED: Now supports both COM and WiFi connections via connection_config.py
"""

import time
from pymavlink import mavutil
import json
from connection_config import get_connection

def dump_all_parameters():
    print("🔍 Dumping ALL Orange Cube Parameters...")
    print("Das kann ein paar Minuten dauern...")
    
    # Connect to Orange Cube (COM or WiFi)
    try:
        connection = get_connection()
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return
    
    # Request all parameters
    print("\n📥 Requesting all parameters...")
    connection.mav.param_request_list_send(
        connection.target_system,
        connection.target_component
    )
    
    parameters = {}
    param_count = 0
    expected_count = None
    
    print("⏳ Receiving parameters...")
    start_time = time.time()
    
    while True:
        msg = connection.recv_match(type='PARAM_VALUE', blocking=True, timeout=5)
        if msg:
            param_name = msg.param_id if isinstance(msg.param_id, str) else msg.param_id.decode('utf-8')
            param_name = param_name.strip('\x00')
            param_value = msg.param_value
            
            parameters[param_name] = param_value
            param_count += 1
            
            if expected_count is None:
                expected_count = msg.param_count
            
            # Progress indicator
            if param_count % 50 == 0:
                progress = (param_count / expected_count * 100) if expected_count else 0
                print(f"   📊 {param_count}/{expected_count} parameters ({progress:.1f}%)")
            
            # Check if we got all parameters
            if expected_count and param_count >= expected_count:
                break
                
        else:
            # Timeout - check if we got enough parameters
            if param_count > 100:  # Reasonable minimum
                print(f"⚠️ Timeout after {param_count} parameters - continuing...")
                break
            else:
                print("❌ Timeout waiting for parameters")
                return
    
    elapsed = time.time() - start_time
    print(f"\n✅ Received {param_count} parameters in {elapsed:.1f} seconds")
    
    # Filter relevant parameters for our use case
    relevant_categories = [
        'CAN_', 'SERVO', 'RC', 'FRAME', 'SKID', 'MOT_', 'ARMING', 'LOG_',
        'BRD_', 'SERIAL', 'RCMAP', 'FS_', 'MODE'
    ]
    
    relevant_params = {}
    all_params = {}
    
    for param_name, param_value in parameters.items():
        all_params[param_name] = param_value
        
        # Check if parameter is relevant
        for category in relevant_categories:
            if param_name.startswith(category):
                relevant_params[param_name] = param_value
                break
    
    # Save to files
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    
    # Save all parameters
    all_filename = f"orange_cube_all_params_{timestamp}.json"
    with open(all_filename, 'w') as f:
        json.dump(all_params, f, indent=2, sort_keys=True)
    print(f"💾 All parameters saved to: {all_filename}")
    
    # Save relevant parameters
    relevant_filename = f"orange_cube_relevant_params_{timestamp}.json"
    with open(relevant_filename, 'w') as f:
        json.dump(relevant_params, f, indent=2, sort_keys=True)
    print(f"💾 Relevant parameters saved to: {relevant_filename}")
    
    # Create Python config file
    config_filename = f"orange_cube_config_{timestamp}.py"
    with open(config_filename, 'w') as f:
        f.write("#!/usr/bin/env python3\n")
        f.write('"""\n')
        f.write(f"Orange Cube Configuration - Exported {timestamp}\n")
        f.write("WORKING CONFIGURATION - alle Parameter die aktuell funktionieren!\n")
        f.write('"""\n\n')
        f.write("# Orange Cube Parameters (funktionierend)\n")
        f.write("ORANGE_CUBE_PARAMETERS = {\n")
        
        for param_name in sorted(relevant_params.keys()):
            param_value = relevant_params[param_name]
            f.write(f"    '{param_name}': {param_value},\n")
        
        f.write("}\n")
    
    print(f"🐍 Python config saved to: {config_filename}")
    
    # Summary
    print(f"\n📊 Parameter Summary:")
    print(f"   Total parameters: {len(all_params)}")
    print(f"   Relevant parameters: {len(relevant_params)}")
    
    # Show key parameters
    key_params = [
        'CAN_D1_PROTOCOL', 'CAN_D1_UC_ESC_BM', 'SERVO1_FUNCTION', 'SERVO2_FUNCTION',
        'SERVO_BLH_MASK', 'FRAME_TYPE', 'FRAME_CLASS', 'RCMAP_ROLL', 'RCMAP_THROTTLE'
    ]
    
    print(f"\n🔑 Key Parameters (current values):")
    for param in key_params:
        if param in relevant_params:
            print(f"   {param:<20} = {relevant_params[param]}")
    
    print(f"\n✅ Parameter dump complete!")
    print(f"📁 Files created:")
    print(f"   - {all_filename} (all parameters)")
    print(f"   - {relevant_filename} (relevant only)")  
    print(f"   - {config_filename} (Python config)")

if __name__ == "__main__":
    dump_all_parameters()
