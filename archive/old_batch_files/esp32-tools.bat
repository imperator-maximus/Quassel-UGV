@echo off
title ESP32 Entwicklungstools
color 0A

:menu
cls
echo ===================================
echo    ESP32 Entwicklungstools v1.0
echo ===================================
echo.
echo  1. Treiber überprüfen
echo  2. ESP32 in Bootloader-Modus versetzen
echo  3. Code hochladen (mit automatischem Reset)
echo  4. Code hochladen (mit manuellem Reset)
echo  5. Seriellen Monitor starten
echo  6. Alle Prozesse beenden
echo  7. Beenden
echo.
echo ===================================
echo.

set /p choice="Bitte wählen Sie eine Option (1-7): "

if "%choice%"=="1" goto :check_drivers
if "%choice%"=="2" goto :reset_esp32
if "%choice%"=="3" goto :upload_auto
if "%choice%"=="4" goto :upload_manual
if "%choice%"=="5" goto :monitor
if "%choice%"=="6" goto :kill_processes
if "%choice%"=="7" goto :end

echo Ungültige Auswahl. Bitte versuchen Sie es erneut.
timeout /t 2 /nobreak > nul
goto :menu

:check_drivers
cls
echo Überprüfe Treiber...
call check-drivers.bat
pause
goto :menu

:reset_esp32
cls
echo Versetze ESP32 in Bootloader-Modus...
python reset-esp32.py
pause
goto :menu

:upload_auto
cls
echo Starte Upload mit automatischem Reset...
call upload-with-reset.bat
goto :menu

:upload_manual
cls
echo Starte Upload mit manuellem Reset...
echo.
echo WICHTIG: Bitte halten Sie die BOOT-Taste gedrückt und drücken Sie dann ENTER.
echo Lassen Sie die BOOT-Taste erst los, wenn der Upload-Prozess beginnt.
echo.
pause
C:\Users\mausz\.platformio\penv\Scripts\platformio.exe run --target upload
pause
goto :menu

:monitor
cls
echo Starte seriellen Monitor...
call platformio-monitor.bat
goto :menu

:kill_processes
cls
echo Beende alle laufenden Prozesse...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM platformio.exe /T 2>nul
echo Alle Prozesse wurden beendet.
timeout /t 2 /nobreak > nul
goto :menu

:end
cls
echo Vielen Dank für die Verwendung der ESP32 Entwicklungstools!
echo.
echo Auf Wiedersehen!
timeout /t 2 /nobreak > nul
exit
