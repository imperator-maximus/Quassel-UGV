@echo off
echo ESP32 Treiber-Check
echo =================
echo.

echo Überprüfe installierte USB-Treiber...
echo.

REM Überprüfen der installierten Treiber
echo Installierte USB-Geräte:
echo ------------------------
powershell -Command "Get-PnpDevice -Class USB | Where-Object { $_.FriendlyName -like '*CH340*' -or $_.FriendlyName -like '*CP210*' -or $_.FriendlyName -like '*FTDI*' -or $_.FriendlyName -like '*Serial*' } | Format-Table -AutoSize"
echo.

echo Installierte COM-Ports:
echo ---------------------
powershell -Command "Get-PnpDevice -Class Ports | Format-Table -AutoSize"
echo.

echo Überprüfe Treiberstatus...
echo ------------------------
powershell -Command "Get-PnpDevice | Where-Object { $_.FriendlyName -like '*CH340*' -or $_.FriendlyName -like '*CP210*' -or $_.FriendlyName -like '*FTDI*' -or $_.FriendlyName -like '*Serial*' } | Select-Object Status, Class, FriendlyName, InstanceId | Format-Table -AutoSize"
echo.

echo Überprüfung abgeschlossen.
echo.

echo Tipps zur Fehlerbehebung:
echo ------------------------
echo 1. Wenn kein CH340-Gerät angezeigt wird, ist der ESP32 möglicherweise nicht angeschlossen oder wird nicht erkannt.
echo 2. Wenn der Status nicht "OK" ist, könnte ein Treiberproblem vorliegen.
echo 3. CH340-Treiber können hier heruntergeladen werden: https://www.wch.cn/download/CH341SER_EXE.html
echo.

pause
