# 🔧 Bootloader Flash Anleitung
## Beyond Robotics AP Bootloader Installation

### ✅ HARDWARE-STATUS BESTÄTIGT
- ✅ COM8 verfügbar (ST-LINK V3)
- ✅ Orange Cube auf COM4 aktiv
- ✅ Bootloader-Datei bereit: `beyond_robotics_working/AP_Bootloader.bin`

---

## 📋 SCHRITT-FÜR-SCHRITT ANLEITUNG

### 1. Hardware-Verbindung prüfen
**Vor dem Flashen sicherstellen:**
- ✅ ST-LINK V3 mit PC verbunden (USB)
- ✅ **Originalkabel** zwischen ST-LINK und Dev Board verwenden (wichtig!)
- ✅ SW1 in Position "1" (STLINK enabled)
- ✅ Dev Board mit Strom versorgt
- ✅ LED am Board sichtbar

### 2. STM32CubeProgrammer starten
1. STM32CubeProgrammer öffnen
2. **Connection Type**: "ST-LINK" auswählen
3. **Connect** klicken
4. **Erwartung**: STM32L431 wird erkannt

### 3. Bootloader flashen
**Datei-Pfad:**
```
C:\Users\mausz\Documents\PlatformIO\Projects\UGV ESP32CAN\beyond_robotics_working\AP_Bootloader.bin
```

**Flash-Einstellungen:**
- **File Path**: Zu obiger Datei navigieren
- **Start Address**: `0x8000000` (genau so eingeben!)
- **Verify**: Aktiviert lassen

**Flash-Prozess:**
1. "Erasing & Programming" Tab öffnen
2. File Path setzen
3. Start Address eingeben: `0x8000000`
4. **"Start Programming"** klicken

### 4. Erfolg verifizieren
**Erwartete Ausgabe:**
```
Connecting to target...
Connection established
Erasing memory...
Programming...
Verifying...
Programming completed successfully
```

**Nach dem Flash:**
- Board reset (Reset-Button drücken)
- LED-Verhalten beobachten
- Node sollte in "Maintenance Mode" booten

---

## 🎯 NÄCHSTER SCHRITT: FIRMWARE UPLOAD

Nach erfolgreichem Bootloader-Flash:

### Firmware via PlatformIO uploaden
```bash
cd beyond_robotics_working
pio run --target upload
```

**Oder mit unserem Script:**
```bash
upload_firmware.bat
```

### Serial Monitor testen
```bash
pio device monitor --port COM8 --baud 115200
```

**Oder mit unserem Script:**
```bash
monitor_serial.bat
```

---

## 🔍 ERWARTETE ERGEBNISSE

### Nach Bootloader-Flash:
- ✅ STM32CubeProgrammer meldet Erfolg
- ✅ Board bootet in Maintenance Mode
- ✅ Bereit für Firmware-Upload

### Nach Firmware-Upload:
- ✅ Serial-Kommunikation auf COM8
- ✅ DroneCAN-Nachrichten sichtbar
- ✅ Parameter-Ausgaben (PARM_1 = 69)
- ✅ Battery-Info alle 100ms
- ✅ CPU-Temperatur-Readings

### Beispiel Serial-Output:
```
PARM_1 value: 69
[DroneCAN initialization messages]
[Battery info messages every 100ms]
[CPU temperature readings]
```

---

## 🚨 TROUBLESHOOTING

### Problem: Kann nicht verbinden
**Lösungen:**
- ST-LINK Treiber neu installieren
- Anderer USB-Port versuchen
- SW1 Position prüfen
- Originalkabel verwenden

### Problem: Programming failed
**Lösungen:**
- Start Address nochmal prüfen: `0x8000000`
- Chip erst löschen, dann programmieren
- Board power-cycle

### Problem: Node bootet nicht
**Lösungen:**
- Reset-Button drücken
- Power-Cycle durchführen
- CAN-Bus Verbindung prüfen

---

## 📞 SUPPORT

Bei Problemen:
- **Beyond Robotics**: admin@beyondrobotix.com
- **Dokumentation**: https://beyond-robotix.gitbook.io/docs/

---

## ✨ BEREIT FÜR NÄCHSTEN SCHRITT

Sobald der Bootloader erfolgreich geflasht ist, können wir mit dem Firmware-Upload fortfahren und endlich die Serial-Kommunikation testen!
