@echo off
echo Repariere platformio.ini
echo ===================

echo.
echo Dieser Skript stellt die Standard-Konfiguration der platformio.ini wieder her.
echo.

echo ; PlatformIO Project Configuration File > platformio.ini
echo ; >> platformio.ini
echo ;   Build options: build flags, source filter >> platformio.ini
echo ;   Upload options: custom upload port, speed and extra flags >> platformio.ini
echo ;   Library options: dependencies, extra library storages >> platformio.ini
echo ;   Advanced options: extra scripting >> platformio.ini
echo ; >> platformio.ini
echo ; Please visit documentation for the other options and examples >> platformio.ini
echo ; https://docs.platformio.org/page/projectconf.html >> platformio.ini
echo. >> platformio.ini
echo [env:esp32dev] >> platformio.ini
echo platform = espressif32 >> platformio.ini
echo board = esp32dev >> platformio.ini
echo framework = arduino >> platformio.ini
echo upload_port = COM7 >> platformio.ini
echo monitor_port = COM7 >> platformio.ini
echo monitor_speed = 115200 >> platformio.ini
echo upload_speed = 115200 >> platformio.ini
echo ; Bibliotheken >> platformio.ini
echo lib_deps = >> platformio.ini
echo     ESP32CAN=https://github.com/miwagner/ESP32-Arduino-CAN/archive/refs/heads/master.zip >> platformio.ini
echo ; Auto-Reset DroneCAN Test kompilieren >> platformio.ini
echo build_src_filter = +^<auto_reset_dronecan.cpp^> -^<can_hardware_diagnostic.cpp^> -^<can_reset_test.cpp^> -^<esp32can_test.cpp^> -^<sn65hvd230_test.cpp^> -^<dronecan_orange_cube_test.cpp^> -^<can_transceiver_test.cpp^> -^<twai_listen_only_test.cpp^> -^<twai_loopback_test.cpp^> -^<twai_test.cpp^> -^<can_diagnostic_test.cpp^> -^<pin_direct_test.cpp^> -^<blink_test.cpp^> -^<simple_can_test.cpp^> -^<improved_dronecan_test.cpp^> -^<serial_test.cpp^> -^<can_test.cpp^> -^<dronecan_test.cpp^> -^<pin_test.cpp^> -^<main.cpp^> >> platformio.ini
echo ; Alternativer Upload-Modus für problematische Verbindungen >> platformio.ini
echo upload_protocol = esptool >> platformio.ini
echo upload_flags = >> platformio.ini
echo     --before=default_reset >> platformio.ini
echo     --after=hard_reset >> platformio.ini
echo     --chip=esp32 >> platformio.ini
echo     --baud=115200 >> platformio.ini

echo.
echo platformio.ini wurde erfolgreich repariert.
echo.
echo Drücken Sie eine beliebige Taste, um fortzufahren...
pause > nul
