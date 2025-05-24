@echo off
echo PlatformIO Helper
echo ================

REM Vollständiger Pfad zum PlatformIO-Executable
set PIO_EXE=C:\Users\mausz\.platformio\penv\Scripts\platformio.exe

:menu
cls
echo.
echo PlatformIO Helper - Wählen Sie eine Aktion:
echo =========================================
echo.
echo  1. Projekt kompilieren
echo  2. Projekt hochladen
echo  3. Seriellen Monitor öffnen
echo  4. Originalen Auto-Reset-Code hochladen (Reset vor jeder Nachricht)
echo  5. Hardware-Diagnose-Tool hochladen
echo  6. Simple Loopback Test hochladen
echo  7. Advanced Loopback Test hochladen
echo  8. Timeout Investigation hochladen
echo  9. platformio.ini reparieren
echo  10. Beenden
echo.
echo =========================================
echo.

set /p choice="Bitte wählen Sie eine Option (1-10): "

if "%choice%"=="1" goto :compile
if "%choice%"=="2" goto :upload
if "%choice%"=="3" goto :monitor
if "%choice%"=="4" goto :adaptive_reset
if "%choice%"=="5" goto :hardware_diagnostic
if "%choice%"=="6" goto :simple_loopback
if "%choice%"=="7" goto :advanced_loopback
if "%choice%"=="8" goto :timeout_investigation
if "%choice%"=="9" goto :fix_platformio
if "%choice%"=="10" goto :end

echo Ungültige Auswahl. Bitte versuchen Sie es erneut.
timeout /t 2 /nobreak > nul
goto :menu

:compile
cls
echo.
echo Kompiliere Projekt...
echo.
"%PIO_EXE%" run
echo.
echo Kompilierung abgeschlossen.
pause
goto :menu

:upload
cls
echo.
echo Lade Projekt auf ESP32 hoch...
echo.
"%PIO_EXE%" run --target upload
echo.
echo Upload abgeschlossen.
pause
goto :menu

:monitor
cls
echo.
echo Öffne seriellen Monitor...
echo.
"%PIO_EXE%" device monitor
goto :menu

:adaptive_reset
cls
echo.
echo Lade originalen Auto-Reset-Code hoch...
echo.
call run-fixed-original-auto-reset.bat
goto :menu

:hardware_diagnostic
cls
echo.
echo Lade Hardware-Diagnose-Tool hoch...
echo.
call run-diagnostic.bat
goto :menu

:simple_loopback
cls
echo.
echo Lade Simple Loopback Test hoch...
echo.
call run-simple-loopback.bat
goto :menu

:advanced_loopback
cls
echo.
echo Lade Advanced Loopback Test hoch...
echo.
call run-advanced-loopback.bat
goto :menu

:timeout_investigation
cls
echo.
echo Lade Timeout Investigation hoch...
echo.
call run-timeout-investigation.bat
goto :menu

:fix_platformio
cls
echo.
echo Repariere platformio.ini...
echo.
call fix-platformio.bat
goto :menu

:end
cls
echo.
echo Vielen Dank für die Verwendung des PlatformIO Helpers!
echo.
exit /b 0
