@echo off
echo ========================================
echo Beyond Robotics Firmware Upload
echo ========================================
echo.
echo Bootloader erfolgreich geflasht! ✅
echo Jetzt uploaden wir die offizielle Firmware...
echo.
echo METHODE 1: VSCode mit PlatformIO
echo ========================================
echo.
echo 1. VSCode öffnen mit diesem Projekt
echo 2. PlatformIO Extension sollte automatisch laden
echo 3. Unten in der Statusleiste "Upload" klicken
echo.
echo Öffne VSCode mit dem Projekt...
echo.

REM Versuche VSCode zu öffnen
if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe" (
    echo VSCode gefunden, öffne Projekt...
    "C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe" .
) else (
    echo VSCode nicht im Standard-Pfad gefunden.
    echo Bitte öffne VSCode manuell und lade diesen Ordner:
    echo %CD%
)

echo.
echo ========================================
echo ALTERNATIVE: Manueller Upload
echo ========================================
echo.
echo Falls VSCode nicht funktioniert:
echo 1. Öffne VSCode
echo 2. Öffne Ordner: %CD%
echo 3. PlatformIO Extension installieren (falls nicht vorhanden)
echo 4. Warte bis PlatformIO das Projekt erkennt
echo 5. Klicke unten auf "Upload" (Pfeil-Symbol)
echo.
echo ERWARTETES ERGEBNIS:
echo - Upload successful
echo - Serial communication auf COM8
echo - DroneCAN messages sichtbar
echo.
pause
