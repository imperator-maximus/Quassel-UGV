@echo off
echo ========================================
echo Beyond Robotics Official Download Tool
echo ========================================
echo.
echo This script downloads the official Arduino-DroneCAN v1.2 release
echo as recommended by Beyond Robotics support team.
echo.
echo Files to download:
echo - ArduinoDroneCAN.V1.2.zip (Official project)
echo - AP_Bootloader.bin (Bootloader for STM32L431)
echo.
pause

python download_beyond_robotics_official.py

echo.
echo ========================================
echo Download Complete!
echo ========================================
echo.
echo Next steps:
echo 1. Download STM32CubeProgrammer from ST website
echo 2. Flash AP_Bootloader.bin to address 0x8000000
echo 3. Open extracted project in VSCode/PlatformIO
echo 4. Upload firmware and test serial communication
echo.
pause
