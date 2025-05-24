#!/usr/bin/env python3
"""
STM32 Chip Detection Script
Detects the actual STM32 chip on the Beyond Robotics Dev Board
"""

import subprocess
import sys
import os

def run_openocd_detect():
    """Run OpenOCD to detect the STM32 chip"""
    print("=" * 60)
    print("STM32 Chip Detection for Beyond Robotics Dev Board")
    print("=" * 60)
    
    # Find OpenOCD path
    platformio_core = os.path.expanduser("~/.platformio")
    openocd_path = os.path.join(platformio_core, "packages", "tool-openocd", "bin", "openocd.exe")
    
    if not os.path.exists(openocd_path):
        print(f"❌ OpenOCD not found at: {openocd_path}")
        print("Please install PlatformIO first")
        return False
    
    print(f"✅ Found OpenOCD at: {openocd_path}")
    print()
    
    # OpenOCD command to detect chip
    cmd = [
        openocd_path,
        "-f", "interface/stlink.cfg",
        "-c", "transport select hla_swd",
        "-c", "adapter speed 1000",
        "-f", "target/stm32f1x.cfg",
        "-c", "init",
        "-c", "targets",
        "-c", "shutdown"
    ]
    
    print("Running chip detection...")
    print("Command:", " ".join(cmd))
    print("-" * 60)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        print("STDOUT:")
        print(result.stdout)
        print()
        print("STDERR:")
        print(result.stderr)
        print()
        print(f"Return code: {result.returncode}")
        
        # Parse output for chip information
        output = result.stdout + result.stderr
        
        if "idcode" in output.lower():
            print("\n🔍 Chip ID Information Found:")
            for line in output.split('\n'):
                if 'idcode' in line.lower() or 'unexpected' in line.lower():
                    print(f"  {line.strip()}")
        
        if "stm32" in output.lower():
            print("\n🔍 STM32 Information Found:")
            for line in output.split('\n'):
                if 'stm32' in line.lower():
                    print(f"  {line.strip()}")
                    
        return True
        
    except subprocess.TimeoutExpired:
        print("❌ Command timed out after 30 seconds")
        return False
    except Exception as e:
        print(f"❌ Error running OpenOCD: {e}")
        return False

def suggest_board_config():
    """Suggest board configurations based on detected chip"""
    print("\n" + "=" * 60)
    print("SUGGESTED BOARD CONFIGURATIONS")
    print("=" * 60)
    
    print("Based on the chip ID 0x2ba01477, try these board configurations:")
    print()
    print("1. STM32F103C8 (Blue Pill):")
    print("   board = bluepill_f103c8")
    print()
    print("2. Generic STM32F103C8:")
    print("   board = genericSTM32F103C8")
    print()
    print("3. STM32F103CB:")
    print("   board = genericSTM32F103CB")
    print()
    print("4. Custom board definition:")
    print("   board = genericSTM32F103RB")
    print("   board_build.mcu = stm32f103c8t6")
    print()
    print("Try updating platformio.ini with one of these configurations.")

def main():
    print("Detecting STM32 chip on Beyond Robotics Dev Board...")
    print("Make sure:")
    print("- STM-LINK V3 is connected")
    print("- SW1 is on position '1'")
    print("- Beyond Robotics Dev Board is connected")
    print()
    
    if run_openocd_detect():
        suggest_board_config()
    else:
        print("\n❌ Detection failed. Check hardware connections.")
        
    print("\n" + "=" * 60)
    print("Next steps:")
    print("1. Update platformio.ini with suggested board configuration")
    print("2. Try uploading again")
    print("3. If still failing, the Beyond Robotics board may need custom config")

if __name__ == "__main__":
    main()
