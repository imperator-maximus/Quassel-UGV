@echo off
echo ========================================
echo Manueller Firmware Upload
echo ========================================
echo.
echo Da PlatformIO Probleme mit ST-LINK hat, flashen wir die
echo kompilierte Firmware manuell über STM32CubeProgrammer.
echo.
echo FIRMWARE-DATEI:
echo beyond_robotics_working\.pio\build\stm32L431\firmware.elf
echo.
echo ANLEITUNG:
echo ========================================
echo.
echo 1. STM32CubeProgrammer öffnen
echo 2. ST-LINK verbinden
echo 3. "Erasing & Programming" Tab
echo 4. Browse zu: beyond_robotics_working\.pio\build\stm32L431\firmware.elf
echo 5. Start address: 0x800A000 (NICHT 0x8000000!)
echo 6. "Start Programming" klicken
echo.
echo WICHTIG: Start Address = 0x800A000
echo (Das ist für Firmware mit Bootloader!)
echo.
echo ERWARTETES ERGEBNIS:
echo - Programming completed successfully
echo - Board reset automatisch
echo - Serial communication auf COM8
echo.
echo Firmware-Datei existiert?
if exist "beyond_robotics_working\.pio\build\stm32L431\firmware.elf" (
    echo ✅ Firmware-Datei gefunden!
    echo Pfad: %CD%\beyond_robotics_working\.pio\build\stm32L431\firmware.elf
) else (
    echo ❌ Firmware-Datei nicht gefunden!
    echo Bitte erst PlatformIO kompilieren lassen:
    echo python find_platformio.py
)
echo.
echo Öffne STM32CubeProgrammer...
if exist "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32CubeProgrammer.exe" (
    start "" "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32CubeProgrammer.exe"
) else (
    echo STM32CubeProgrammer nicht im Standard-Pfad gefunden.
    echo Bitte manuell öffnen.
)
echo.
pause
