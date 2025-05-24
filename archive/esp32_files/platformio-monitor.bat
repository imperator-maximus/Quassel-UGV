@echo off
echo PlatformIO Serieller Monitor
echo =========================

REM Vollständiger Pfad zum PlatformIO-Executable
set PIO_EXE=C:\Users\mausz\.platformio\penv\Scripts\platformio.exe

echo Verwende PlatformIO: %PIO_EXE%
echo.

REM Prüfen, ob die Datei existiert
if not exist "%PIO_EXE%" (
    echo FEHLER: PlatformIO-Executable nicht gefunden!
    echo Bitte stellen Sie sicher, dass PlatformIO korrekt installiert ist.
    echo.
    echo Versuche alternative Methode mit Python...
    goto :use_python
)

echo Starte seriellen Monitor mit PlatformIO...
echo Drücken Sie Ctrl+C zum Beenden.
echo.

REM Führe PlatformIO mit den angegebenen Parametern aus
"%PIO_EXE%" device monitor %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo PlatformIO Monitor fehlgeschlagen. Versuche alternative Methode mit Python...
    goto :use_python
) else (
    goto :end
)

:use_python
echo.
echo Starte seriellen Monitor mit Python...
echo Drücken Sie Ctrl+C zum Beenden.
echo.

REM Prüfen, ob das Python-Skript existiert
if not exist "serial_monitor.py" (
    echo FEHLER: serial_monitor.py nicht gefunden!
    echo Erstelle das Skript...

    echo import serial > serial_monitor.py
    echo import time >> serial_monitor.py
    echo. >> serial_monitor.py
    echo def main(): >> serial_monitor.py
    echo     ser = serial.Serial('COM7', 115200, timeout=1) >> serial_monitor.py
    echo     print('Serielle Überwachung gestartet. Drücken Sie Ctrl+C zum Beenden.') >> serial_monitor.py
    echo     try: >> serial_monitor.py
    echo         while True: >> serial_monitor.py
    echo             if ser.in_waiting: >> serial_monitor.py
    echo                 line = ser.readline().decode('utf-8', errors='ignore').strip() >> serial_monitor.py
    echo                 if line: >> serial_monitor.py
    echo                     print(line) >> serial_monitor.py
    echo             time.sleep(0.1) >> serial_monitor.py
    echo     except KeyboardInterrupt: >> serial_monitor.py
    echo         print('Beendet') >> serial_monitor.py
    echo     finally: >> serial_monitor.py
    echo         ser.close() >> serial_monitor.py
    echo. >> serial_monitor.py
    echo if __name__ == "__main__": >> serial_monitor.py
    echo     main() >> serial_monitor.py
)

REM Führe das Python-Skript aus
python serial_monitor.py

:end
echo.
pause
