@echo off
echo Orange Cube CAN Parameter Setter
echo ===============================
echo.
echo Dieses Skript setzt CAN-bezogene Parameter auf dem Orange Cube,
echo um die DroneCAN-Kommunikation zu optimieren.
echo.
echo Bitte stellen Sie sicher, dass:
echo 1. Der Orange Cube über USB angeschlossen ist
echo 2. Mission Planner NICHT gleichzeitig geöffnet ist
echo 3. Python und die pymavlink-Bibliothek installiert sind
echo.
echo Wenn Sie die pymavlink-Bibliothek noch nicht installiert haben,
echo führen Sie bitte zuerst den folgenden Befehl aus:
echo pip install pymavlink
echo.
pause

REM Nur Parameter überprüfen
echo.
echo Überprüfe aktuelle Parameter...
python set_can_parameters.py --check-only
echo.
echo Möchten Sie die empfohlenen Parameter setzen? (J/N)
choice /c JN /m "Parameter setzen"

if errorlevel 2 goto :end
if errorlevel 1 goto :set_params

:set_params
echo.
echo Setze Parameter...
python set_can_parameters.py

echo.
echo Möchten Sie den Orange Cube neu starten, um die Änderungen zu aktivieren? (J/N)
choice /c JN /m "Orange Cube neustarten"

if errorlevel 2 goto :end
if errorlevel 1 goto :reboot

:reboot
echo.
echo Starte Orange Cube neu...
python set_can_parameters.py --reboot

:end
echo.
echo Fertig.
pause
