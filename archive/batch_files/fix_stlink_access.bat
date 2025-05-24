@echo off
echo ========================================
echo ST-LINK Access Problem Fixer
echo ========================================
echo.
echo Problem: libusb_open() failed with LIBUSB_ERROR_ACCESS
echo Lösung: ST-LINK Zugriff freigeben
echo.
echo SCHRITT 1: ST-LINK Prozesse beenden
echo ========================================
echo.
echo Beende alle ST-LINK Prozesse...
taskkill /F /IM "STM32CubeProgrammer.exe" 2>nul
taskkill /F /IM "STM32_Programmer_CLI.exe" 2>nul
taskkill /F /IM "ST-LINK_gdbserver.exe" 2>nul
taskkill /F /IM "STLinkUSBDriver.exe" 2>nul
echo.
echo SCHRITT 2: USB-Gerät zurücksetzen
echo ========================================
echo.
echo 1. ST-LINK V3 USB-Kabel abziehen
echo 2. 5 Sekunden warten
echo 3. USB-Kabel wieder anstecken
echo 4. Warten bis Windows das Gerät erkennt
echo.
echo Bitte führe diese Schritte jetzt durch...
pause
echo.
echo SCHRITT 3: COM-Ports prüfen
echo ========================================
echo.
python check_com_ports.py
echo.
echo SCHRITT 4: Upload erneut versuchen
echo ========================================
echo.
echo Jetzt sollte der Upload funktionieren.
echo Führe aus: python find_platformio.py
echo.
pause
