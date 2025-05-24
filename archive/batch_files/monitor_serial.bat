@echo off
echo ========================================
echo Beyond Robotics Serial Monitor
echo ========================================
echo.
echo Monitoring COM8 at 115200 baud
echo.
echo Expected output:
echo - DroneCAN initialization messages
echo - Parameter values (PARM_1, etc.)
echo - Battery info messages every 100ms
echo - CPU temperature readings
echo.
echo Press Ctrl+C to stop monitoring
echo.
cd beyond_robotics_working
pio device monitor --port COM8 --baud 115200
