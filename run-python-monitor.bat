@echo off
echo ===================================================
echo Beyond Robotics Python Serial Monitor
echo ===================================================
echo.

REM Check if Python is available
python --version >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found!
    echo Please install Python or add it to your PATH
    pause
    exit /b 1
)

REM Check if pyserial is installed
python -c "import serial" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Installing pyserial...
    pip install pyserial
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: Failed to install pyserial
        pause
        exit /b 1
    )
)

echo Starting Python serial monitor for COM8...
echo.
python monitor_beyond_robotics.py

pause
