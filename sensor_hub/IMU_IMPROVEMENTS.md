# 🧭 IMU-Integration Verbesserungen

## ✅ Implementierte Features

### 1. IMU-Kalibrierung 🔧

**Gyro-Bias-Kalibrierung:**
- Automatische Kalibrierung beim Start (1000 Samples)
- Entfernt Gyro-Drift für präzise Drehratenmessung
- Bias wird für X, Y, Z-Achse separat berechnet

**Accelerometer-Offset-Kalibrierung:**
- Kalibriert Beschleunigungssensor-Offsets
- Z-Achse wird auf 9.81 m/s² (Erdanziehung) normalisiert
- X/Y-Achsen werden auf 0 m/s² kalibriert

**Verwendung:**
```python
imu = ICM42688P(bus=1, address=0x69, sample_rate=200)
imu.connect()
imu.calibrate(samples=1000)  # 10 Sekunden Kalibrierung
```

**WICHTIG:** IMU muss während der Kalibrierung STILL liegen!

---

### 2. Roll/Pitch/Yaw Berechnung 📐

**Komplementärfilter:**
- Fusioniert Accelerometer und Gyroscope Daten
- 98% Gyro (schnelle Reaktion) + 2% Accel (Drift-Korrektur)
- Berechnet Roll/Pitch/Yaw in Grad (0-360°)

**Roll (Rotation um X-Achse):**
- Berechnet aus Accelerometer: `atan2(accel_y, accel_z)`
- Fusioniert mit Gyro-Integration
- Positiv = Rechts geneigt, Negativ = Links geneigt

**Pitch (Rotation um Y-Achse):**
- Berechnet aus Accelerometer: `atan2(-accel_x, sqrt(accel_y² + accel_z²))`
- Fusioniert mit Gyro-Integration
- Positiv = Nase oben, Negativ = Nase unten

**Yaw (Rotation um Z-Achse / Heading):**
- Nur Gyro-Integration (kein Magnetometer)
- Wird mit GPS-Heading fusioniert für Drift-Korrektur
- 0° = Norden, 90° = Osten, 180° = Süden, 270° = Westen

---

### 3. Heading-Fusion mit GPS-Kurs 🛰️

**GPS-IMU Fusion:**
- Fusioniert IMU Yaw mit GPS Heading (HDT)
- GPS Heading hat 30% Gewicht (konfigurierbar)
- Verhindert Yaw-Drift über lange Zeit

**Automatische Fusion:**
- Läuft in separatem Thread mit 10Hz
- Holt GPS Heading vom UM982 (Dual-Antenna)
- Übergibt Heading an IMU für Fusion

**Vorteile:**
- IMU liefert schnelle, hochfrequente Heading-Updates (200Hz)
- GPS korrigiert langsame Drift
- Beste Kombination aus beiden Sensoren

---

### 4. Web-Interface Visualisierung 🌐

**Kompass-Anzeige 🧭:**
- Zeigt aktuelles Heading (0-360°)
- Goldener Pfeil zeigt Fahrtrichtung
- Himmelsrichtungen (N, E, S, W) markiert
- Echtzeit-Update mit Canvas-Animation

**Orientierungs-Anzeige 📐:**
- Zeigt Roll und Pitch visuell
- Künstlicher Horizont (Himmel blau, Boden braun)
- Rotes Fadenkreuz zeigt UGV-Position
- Horizont rotiert entsprechend Roll/Pitch

**IMU Status-Karte:**
- Kalibrierungs-Status (JA/NEIN)
- Roll, Pitch, Yaw in Grad
- Temperatur
- Verbindungsstatus

**IMU Rohdaten-Karte:**
- Beschleunigung X/Y/Z (m/s²)
- Drehrate X/Y/Z (°/s)
- Für Debugging und Analyse

---

## 📊 API Endpoints

### GET `/api/imu/data`
Gibt vollständige IMU-Daten zurück:
```json
{
  "accel": {"x": 0.12, "y": -0.05, "z": 9.81},
  "gyro": {"x": 0.01, "y": -0.02, "z": 0.15},
  "temperature": 24.5,
  "roll": 2.3,
  "pitch": -1.5,
  "yaw": 45.2,
  "heading": 45.2,
  "is_calibrated": true,
  "timestamp": 1699876543.123
}
```

### GET `/api/imu/status`
Gibt IMU-Status zurück:
```json
{
  "connected": true,
  "running": true,
  "address": "0x69",
  "bus": 1,
  "sample_rate": 200
}
```

---

## 🔧 Konfiguration

**config.py:**
```python
# IMU KONFIGURATION
IMU_ENABLED = True
IMU_ADDRESS = 0x69  # 0x68 wenn AD0=GND, 0x69 wenn AD0=VCC
IMU_BUS = 1
IMU_SAMPLE_RATE = 200  # Hz
```

**Komplementärfilter-Parameter (imu_handler.py):**
```python
self.alpha = 0.98  # 98% Gyro, 2% Accel
```

**GPS-Fusion-Gewichtung (imu_handler.py):**
```python
self.gps_heading_weight = 0.3  # 30% GPS, 70% IMU
```

---

## 🚀 Verwendung

### Automatischer Start
Der Sensor Hub startet automatisch mit:
1. IMU-Verbindung
2. 5 Sekunden Stabilisierung
3. Automatische Kalibrierung (1000 Samples)
4. GPS-IMU Fusion Thread

### Manueller Start
```bash
cd /home/nicolay/sensor_hub
python3 sensor_hub_app.py
```

### Web-Interface
```
http://raspberryzero:8080
```

---

## 📈 Performance

- **IMU Sample Rate:** 200 Hz (5ms pro Sample)
- **Orientierungs-Update:** 200 Hz (Echtzeit)
- **GPS-Fusion-Update:** 10 Hz (100ms)
- **Web-Interface-Update:** 0.5 Hz (2 Sekunden)

---

## 🎯 Nächste Schritte

### Mögliche Erweiterungen:
1. **Magnetometer-Integration** - Für absolutes Heading ohne GPS
2. **Kalman-Filter** - Noch bessere Sensor-Fusion
3. **Bewegungserkennung** - Erkennung von Stillstand/Bewegung
4. **Vibrations-Analyse** - FFT auf Accelerometer für Diagnose
5. **Datenlogging** - Aufzeichnung für Offline-Analyse

---

## 🐛 Troubleshooting

### IMU nicht verbunden
```bash
# I2C-Geräte scannen
sudo i2cdetect -y 1

# Sollte 0x69 (oder 0x68) zeigen
```

### Kalibrierung schlägt fehl
- UGV muss STILL stehen
- Keine Vibrationen während Kalibrierung
- 10 Sekunden warten

### Yaw driftet
- GPS Heading Fusion aktivieren
- GPS muss gültiges Heading liefern (Dual-Antenna)
- GPS-Fusion-Gewichtung erhöhen

### Roll/Pitch ungenau
- Kalibrierung wiederholen
- Alpha-Parameter anpassen (höher = mehr Gyro)
- Accelerometer-Offsets prüfen

---

## 📝 Änderungen

**Geänderte Dateien:**
- `sensor_hub/imu_handler.py` - Kalibrierung, Orientierung, Fusion
- `sensor_hub/sensor_hub_app.py` - GPS-IMU Fusion Loop, API Updates
- `sensor_hub/templates/sensor_hub.html` - Kompass & Orientierungs-Visualisierung

**Neue Features:**
- Gyro-Bias-Kalibrierung
- Accelerometer-Offset-Kalibrierung
- Roll/Pitch/Yaw mit Komplementärfilter
- GPS-IMU Heading-Fusion
- Kompass-Anzeige (Canvas)
- Orientierungs-Anzeige (Canvas)

---

## ✅ Status

Alle 4 Aufgaben erfolgreich implementiert:
- ✅ IMU-Kalibrierung implementieren
- ✅ Roll/Pitch/Yaw korrekt berechnen
- ✅ Heading-Fusion mit GPS-Kurs
- ✅ IMU-Daten in Web-Interface visualisieren

**Bereit für Testing auf Raspberry Pi Zero 2W!** 🎉

