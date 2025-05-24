@echo off
echo ESP32 Reset und Upload-Skript
echo ===========================

REM Vollständiger Pfad zum PlatformIO-Executable
set PIO_EXE=C:\Users\mausz\.platformio\penv\Scripts\platformio.exe

echo.
echo WICHTIG: Wenn der automatische Upload nicht funktioniert, bitte:
echo 1. Halten Sie die BOOT-Taste auf dem ESP32 gedrückt
echo 2. Drücken Sie kurz die RESET-Taste
echo 3. Lassen Sie die RESET-Taste los
echo 4. Lassen Sie die BOOT-Taste los, wenn der Upload beginnt
echo.

REM Fragen, ob der Benutzer den Reset-Prozess überspringen möchte
set /p SKIP_RESET="Möchten Sie den automatischen Reset überspringen und manuell die BOOT-Taste drücken? (j/n): "
if /i "%SKIP_RESET%"=="j" goto :skip_reset

REM Python-Skript ausführen, um den ESP32 in den Bootloader-Modus zu versetzen
echo Versetze ESP32 in den Bootloader-Modus...
python reset-esp32.py

REM Kurz warten
echo Warte 3 Sekunden...
timeout /t 3 /nobreak > nul

:skip_reset
REM PlatformIO-Upload starten
echo.
echo Starte Upload-Prozess...
echo JETZT die BOOT-Taste drücken und halten, falls der automatische Reset nicht funktioniert hat!
echo.

REM Verzögerung für manuelles Drücken der BOOT-Taste
timeout /t 2 /nobreak > nul

REM Upload mit verschiedenen Optionen
echo Versuche Upload mit Standard-Einstellungen...
"%PIO_EXE%" run --target upload

if %ERRORLEVEL% neq 0 (
    echo.
    echo Erster Upload-Versuch fehlgeschlagen. Versuche alternative Methode...
    echo.

    REM Versuche mit alternativen Flags
    echo Versuche Upload mit alternativen Einstellungen...
    "%PIO_EXE%" run --target upload --upload-port COM7

    if %ERRORLEVEL% neq 0 (
        echo.
        echo Zweiter Upload-Versuch fehlgeschlagen. Versuche direkt mit esptool.py...
        echo.

        REM Pfad zur Firmware-Datei
        set FIRMWARE=.pio\build\esp32dev\firmware.bin

        REM Absoluter Pfad, falls der relative Pfad nicht funktioniert
        if not exist "%FIRMWARE%" (
            set FIRMWARE=%CD%\.pio\build\esp32dev\firmware.bin
        )

        REM Prüfen, ob die Firmware existiert
        if not exist "%FIRMWARE%" (
            echo FEHLER: Firmware-Datei nicht gefunden!
            echo Bitte stellen Sie sicher, dass der Build-Prozess erfolgreich war.
            goto :upload_failed
        )

        REM Versuche mit esptool.py direkt
        echo Versuche Upload mit esptool.py direkt...
        python -m esptool --chip esp32 --port COM7 --baud 115200 --before default_reset --after hard_reset write_flash -z --flash_mode dio --flash_freq 40m --flash_size detect 0x10000 %FIRMWARE%

        if %ERRORLEVEL% neq 0 (
            :upload_failed
            echo.
            echo Alle Upload-Versuche fehlgeschlagen! Fehlercode: %ERRORLEVEL%
            echo.
            echo Tipps zur Fehlerbehebung:
            echo 1. Stellen Sie sicher, dass der ESP32 angeschlossen ist
            echo 2. Versuchen Sie ein anderes USB-Kabel
            echo 3. Überprüfen Sie die COM-Port-Einstellungen in platformio.ini
            echo 4. Drücken Sie manuell die BOOT-Taste während des Uploads
            echo 5. Versuchen Sie, den ESP32 an einen anderen USB-Port anzuschließen
            echo 6. Überprüfen Sie, ob die CH340-Treiber korrekt installiert sind
            exit /b 1
        ) else (
            echo.
            echo Upload erfolgreich abgeschlossen!
            exit /b 0
        )
    ) else (
        echo.
        echo Upload erfolgreich abgeschlossen!
        exit /b 0
    )
) else (
    echo.
    echo Upload erfolgreich abgeschlossen!
    exit /b 0
)

echo.
pause
