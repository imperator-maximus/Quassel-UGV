@echo off
echo ===================================================
echo Beyond Robotics CAN Node Test - VS Code Method
echo ===================================================
echo.
echo This will open VS Code with the Beyond Robotics project
echo.
echo Hardware Setup Check:
echo - STM-LINK V3 connected to STLINK header
echo - SW1 on position "1" (STLINK enabled)  
echo - CAN connection: CANH/CANL between Dev Board and Orange Cube
echo - Serial output on COM8
echo.

REM Create a temporary PlatformIO project structure
if not exist "beyond_robotics_project" (
    mkdir beyond_robotics_project
    mkdir beyond_robotics_project\src
    mkdir beyond_robotics_project\include
    mkdir beyond_robotics_project\lib
)

REM Copy files to project structure
copy beyond_robotics_can_test.cpp beyond_robotics_project\src\main.cpp >nul
copy platformio_beyond_robotics.ini beyond_robotics_project\platformio.ini >nul

echo Project structure created in: beyond_robotics_project\
echo.
echo Opening VS Code...
echo.
echo In VS Code:
echo 1. Install PlatformIO extension if not already installed
echo 2. Click "Upload" button in PlatformIO toolbar
echo 3. Click "Serial Monitor" button after upload
echo.

REM Open VS Code with the project
code beyond_robotics_project

echo VS Code opened. Follow the instructions above to upload and monitor.
pause
