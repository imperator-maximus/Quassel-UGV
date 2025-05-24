@echo off
echo ESP32 Direkter Upload mit esptool.py
echo ================================

echo.
echo WICHTIG: Dieser Upload-Modus verwendet esptool.py direkt.
echo.

REM Firmware-Datei finden
set FIRMWARE=.pio\build\esp32dev\firmware.bin
if not exist "%FIRMWARE%" (
    echo Firmware-Datei nicht gefunden: %FIRMWARE%
    echo Bitte zuerst das Projekt kompilieren.
    exit /b 1
)

echo Firmware gefunden: %FIRMWARE%
echo.

REM Direkter Upload mit esptool.py
echo Starte Upload mit esptool.py...
echo.

python -m esptool --chip esp32 --port COM7 --baud 115200 --before default_reset --after hard_reset write_flash -z --flash_mode dio --flash_freq 40m --flash_size detect 0x10000 %FIRMWARE%

if %ERRORLEVEL% neq 0 (
    echo.
    echo Upload fehlgeschlagen! Fehlercode: %ERRORLEVEL%
    echo.
    echo Tipps zur Fehlerbehebung:
    echo 1. Stellen Sie sicher, dass der ESP32 angeschlossen ist
    echo 2. Versuchen Sie ein anderes USB-Kabel
    echo 3. Überprüfen Sie die COM-Port-Einstellungen
    echo 4. Versuchen Sie, den ESP32 an einen anderen USB-Port anzuschließen
    echo 5. Überprüfen Sie, ob die CH340-Treiber korrekt installiert sind
    echo 6. Drücken Sie die BOOT-Taste während des Uploads
) else (
    echo.
    echo Upload erfolgreich abgeschlossen!
)

echo.
pause
