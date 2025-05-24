@echo off
echo ESP32 Pin-Test
echo =============

REM Vollständiger Pfad zum PlatformIO-Executable
set PIO_EXE=C:\Users\mausz\.platformio\penv\Scripts\platformio.exe

echo.
echo Dieser Skript kompiliert und lädt den Pin-Test auf den ESP32.
echo.

REM Temporäre platformio.ini erstellen
echo Erstelle temporäre Konfiguration für Pin-Test...
copy platformio.ini platformio.ini.bak
echo ; Nur pin_test.cpp kompilieren > platformio.tmp
echo build_src_filter = +^<pin_test.cpp^> -^<main.cpp^> >> platformio.tmp

REM Füge die Zeile zur platformio.ini hinzu
type platformio.tmp >> platformio.ini

REM Kompilieren und Hochladen
echo.
echo Kompiliere und lade Pin-Test...
"%PIO_EXE%" run --target upload

REM Konfiguration wiederherstellen
echo.
echo Stelle ursprüngliche Konfiguration wieder her...
copy platformio.ini.bak platformio.ini
del platformio.tmp
del platformio.ini.bak

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
) else (
    echo.
    echo Pin-Test erfolgreich hochgeladen!
    echo.
    echo Der ESP32 sollte jetzt die LEDs an den Pins blinken lassen.
    echo Beobachten Sie die Pins, um ihre Position zu identifizieren.
)

echo.
pause
