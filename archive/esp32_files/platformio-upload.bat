@echo off
echo PlatformIO Upload-Skript
echo =====================

REM Vollständiger Pfad zum PlatformIO-Executable
set PIO_EXE=C:\Users\mausz\.platformio\penv\Scripts\platformio.exe

echo Verwende PlatformIO: %PIO_EXE%
echo.

REM Prüfen, ob die Datei existiert
if not exist "%PIO_EXE%" (
    echo FEHLER: PlatformIO-Executable nicht gefunden!
    echo Bitte stellen Sie sicher, dass PlatformIO korrekt installiert ist.
    exit /b 1
)

echo Starte Upload-Prozess...
echo.

REM Führe PlatformIO mit den angegebenen Parametern aus
"%PIO_EXE%" run --target upload %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo Upload fehlgeschlagen! Fehlercode: %ERRORLEVEL%
    echo.
    echo Tipps zur Fehlerbehebung:
    echo 1. Stellen Sie sicher, dass der ESP32 angeschlossen ist
    echo 2. Drücken Sie die BOOT-Taste während des Uploads
    echo 3. Versuchen Sie ein anderes USB-Kabel
    echo 4. Überprüfen Sie die COM-Port-Einstellungen in platformio.ini
) else (
    echo.
    echo Upload erfolgreich abgeschlossen!
)

echo.
pause
