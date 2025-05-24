@echo off
echo ESP32 TWAI Timeout Investigation
echo ============================

REM Vollständiger Pfad zum PlatformIO-Executable
set PIO_EXE=C:\Users\mausz\.platformio\penv\Scripts\platformio.exe

echo.
echo Dieser Skript kompiliert und lädt einen speziellen Test zur Untersuchung des Timeout-Problems auf den ESP32.
echo.

REM Temporäre platformio.ini erstellen
echo Erstelle temporäre Konfiguration für Timeout-Investigation...
copy platformio.ini platformio.ini.bak

REM Erstelle eine neue platformio.ini mit der geänderten build_src_filter-Zeile
powershell -Command "(Get-Content platformio.ini) -replace 'build_src_filter = .*', 'build_src_filter = +<timeout_investigation.cpp> -<advanced_loopback_test.cpp> -<simple_loopback_test.cpp> -<auto_reset_dronecan.cpp> -<can_hardware_diagnostic.cpp> -<main.cpp> -<can_reset_test.cpp> -<esp32can_test.cpp> -<sn65hvd230_test.cpp> -<dronecan_orange_cube_test.cpp> -<can_transceiver_test.cpp> -<twai_listen_only_test.cpp> -<twai_loopback_test.cpp> -<twai_test.cpp> -<can_diagnostic_test.cpp> -<pin_direct_test.cpp> -<blink_test.cpp> -<simple_can_test.cpp> -<improved_dronecan_test.cpp> -<serial_test.cpp> -<can_test.cpp> -<dronecan_test.cpp> -<pin_test.cpp>' | Set-Content platformio.ini.new"
move /y platformio.ini.new platformio.ini

REM Kompilieren und Hochladen
echo.
echo Kompiliere und lade Timeout Investigation...
"%PIO_EXE%" run --target upload

REM Konfiguration wiederherstellen
echo.
echo Stelle ursprüngliche Konfiguration wieder her...
copy platformio.ini.bak platformio.ini
del platformio.ini.bak

echo.
echo Timeout Investigation wurde hochgeladen. Öffne den seriellen Monitor, um die Ergebnisse zu sehen.
echo.
echo Drücke eine Taste, um den seriellen Monitor zu starten...
pause > nul

REM Starte den seriellen Monitor
"%PIO_EXE%" device monitor

echo.
pause
