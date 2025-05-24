@echo off
echo ESP32 Upload für Breakout Board
echo =============================

REM Vollständiger Pfad zum PlatformIO-Executable
set PIO_EXE=C:\Users\mausz\.platformio\penv\Scripts\platformio.exe

echo.
echo WICHTIG: Dieser Upload-Modus ist speziell für den ESP32 im Breakout Board optimiert.
echo.

REM PlatformIO-Upload mit speziellen Flags starten
echo Starte Upload-Prozess mit speziellen Einstellungen...
echo.

REM Führe PlatformIO mit den angegebenen Parametern aus
"%PIO_EXE%" run --target upload --upload-port COM7

if %ERRORLEVEL% neq 0 (
    echo.
    echo Upload fehlgeschlagen! Fehlercode: %ERRORLEVEL%
    echo.
    echo Tipps zur Fehlerbehebung:
    echo 1. Stellen Sie sicher, dass der ESP32 angeschlossen ist
    echo 2. Versuchen Sie ein anderes USB-Kabel
    echo 3. Überprüfen Sie die COM-Port-Einstellungen in platformio.ini
    echo 4. Versuchen Sie, den ESP32 an einen anderen USB-Port anzuschließen
    echo 5. Überprüfen Sie, ob die CH340-Treiber korrekt installiert sind
) else (
    echo.
    echo Upload erfolgreich abgeschlossen!
)

echo.
pause
