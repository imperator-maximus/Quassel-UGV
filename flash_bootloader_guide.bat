@echo off
echo ========================================
echo Beyond Robotics AP Bootloader Flash
echo ========================================
echo.
echo This script helps you flash the AP bootloader using STM32CubeProgrammer
echo.
echo PREREQUISITES:
echo 1. STM32CubeProgrammer installed
echo 2. ST-LINK V3 connected to dev board
echo 3. SW1 in position "1" (STLINK enabled)
echo 4. Use provided cable between ST-LINK and dev board
echo.
echo BOOTLOADER FILE:
echo beyond_robotics_working/AP_Bootloader.bin
echo.
echo FLASH ADDRESS:
echo 0x8000000
echo.
echo INSTRUCTIONS:
echo 1. Open STM32CubeProgrammer
echo 2. Select "ST-LINK" connection
echo 3. Click "Connect"
echo 4. Go to "Erasing & Programming" tab
echo 5. Browse to: beyond_robotics_working/AP_Bootloader.bin
echo 6. Set start address: 0x8000000
echo 7. Click "Start Programming"
echo.
echo After successful flash:
echo - Node will boot in maintenance mode
echo - Ready for firmware upload via PlatformIO
echo.
pause
