#!/usr/bin/env python3

import serial
import time
import sys

def reset_to_bootloader_method1(ser):
    """
    Method 1: Standard ESP32 reset sequence
    """
    print("Trying reset method 1...")

    # Toggle DTR and RTS to reset ESP32 into bootloader mode
    ser.setDTR(False)
    ser.setRTS(False)
    time.sleep(0.1)

    ser.setDTR(True)
    ser.setRTS(True)
    time.sleep(0.1)

    ser.setDTR(False)
    time.sleep(0.1)

    ser.setDTR(True)
    time.sleep(0.1)

def reset_to_bootloader_method2(ser):
    """
    Method 2: Alternative reset sequence
    """
    print("Trying reset method 2...")

    # Alternative sequence
    ser.setDTR(True)
    ser.setRTS(True)
    time.sleep(0.05)
    ser.setDTR(False)
    time.sleep(0.05)
    ser.setDTR(True)
    time.sleep(0.05)
    ser.setRTS(False)
    time.sleep(0.05)
    ser.setDTR(False)
    time.sleep(0.05)
    ser.setRTS(True)
    time.sleep(0.05)
    ser.setDTR(True)
    time.sleep(0.05)
    ser.setRTS(False)
    time.sleep(0.05)

def reset_to_bootloader_method3(ser):
    """
    Method 3: ESP32-S2/S3/C3 style reset
    """
    print("Trying reset method 3...")

    # ESP32-S2/S3/C3 style
    ser.setRTS(True)  # EN->LOW
    ser.setDTR(True)  # GPIO0->LOW
    time.sleep(0.1)
    ser.setRTS(False) # EN->HIGH
    time.sleep(0.1)
    ser.setDTR(False) # GPIO0->HIGH

def reset_to_bootloader(port="COM7"):
    """
    Reset ESP32 to bootloader mode using multiple methods
    """
    print(f"Resetting ESP32 on {port} to bootloader mode...")

    try:
        # Open serial port with a lower baudrate for stability
        ser = serial.Serial(port, 115200, timeout=1)

        # Try different reset methods
        reset_to_bootloader_method1(ser)
        time.sleep(0.5)

        reset_to_bootloader_method2(ser)
        time.sleep(0.5)

        reset_to_bootloader_method3(ser)
        time.sleep(0.5)

        # Send break condition
        print("Sending break condition...")
        ser.send_break(0.5)
        time.sleep(0.5)

        # Close and reopen the port
        ser.close()
        time.sleep(0.5)

        # Reopen with different baudrate
        ser = serial.Serial(port, 115200, timeout=1)
        ser.setDTR(False)
        ser.setRTS(False)
        time.sleep(0.5)

        # Close the port
        ser.close()

        print("ESP32 should now be in bootloader mode")
        print("You can now run the upload command")
        print("If upload fails, please manually press and hold the BOOT button on the ESP32")
        print("while starting the upload process.")

    except Exception as e:
        print(f"Error: {e}")
        return False

    return True

if __name__ == "__main__":
    port = "COM7"
    if len(sys.argv) > 1:
        port = sys.argv[1]

    reset_to_bootloader(port)
