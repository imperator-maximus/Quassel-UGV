@echo off
echo Orange Cube Monitor - Direktes Überwachungstool
echo =============================================
echo.
echo Dieses Tool verbindet sich direkt mit dem Orange Cube und
echo überwacht die MAVLink-Kommunikation, einschließlich DroneCAN-Aktivität.
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

python monitor_orange_cube.py

pause
