@echo off
echo ===================================================
echo Beyond Robotics CAN Node Test
echo ===================================================
echo.
echo Hardware Setup Check:
echo - STM-LINK V3 connected to STLINK header
echo - SW1 on position "1" (STLINK enabled)
echo - CAN connection: CANH/CANL between Dev Board and Orange Cube
echo - Serial output on COM8
echo.
echo Starting test...
echo.

REM Set PlatformIO path
set "PIO_PATH=%USERPROFILE%\.platformio\penv\Scripts\pio.exe"

REM Check if PlatformIO is available
if not exist "%PIO_PATH%" (
    echo ERROR: PlatformIO not found at %PIO_PATH%
    echo Please install PlatformIO Core
    pause
    exit /b 1
)

echo Found PlatformIO at: %PIO_PATH%

REM Change to project directory
cd beyond_robotics_project

REM Upload the test program
echo Uploading test program to Beyond Robotics Dev Board...
"%PIO_PATH%" run -e beyond_robotics_dev_board --target upload

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Upload failed!
    echo Check:
    echo - STM-LINK V3 is properly connected
    echo - SW1 is on position "1"
    echo - Beyond Robotics Dev Board is connected to STLINK header
    pause
    exit /b 1
)

echo.
echo Upload successful! Starting serial monitor...
echo.
echo Expected output:
echo - Initialization messages
echo - Heartbeat messages every 1 second
echo - Received CAN messages from Orange Cube
echo - Statistics every 5 seconds
echo.
echo Press Ctrl+C to stop monitoring
echo.

REM Start serial monitor
"%PIO_PATH%" device monitor --port COM8 --baud 115200

pause
