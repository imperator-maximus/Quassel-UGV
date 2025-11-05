# 🔧 IMU Sensor Fusion Refactoring

## Problembeschreibung

Die ursprüngliche `imu_handler.py` war ein "Gott-Objekt" mit zu vielen Verantwortlichkeiten:
- Hardware-Treiber (I2C-Kommunikation)
- Kalibrierung
- Sensor-Fusion (Komplementärfilter)
- GPS-Heading-Fusion

**Kritische Logik-Fehler:**

### 1. Winkel-Wrap-Around Problem (359° + 1° = 251°)

**Alter Code:**
```python
self.yaw = (1.0 - self.gps_heading_weight) * self.yaw + \
           self.gps_heading_weight * self.gps_heading
```

**Problem:**
- IMU Yaw: 359° (fast Nord)
- GPS Heading: 1° (auch fast Nord)
- Ergebnis: (0.7 * 359) + (0.3 * 1) = 251.6° (Süd-West) ❌
- Korrekt wäre: 0° (Nord) ✅

**Lösung:**
```python
# Finde kürzesten Weg
diff = gps_heading - self.yaw
if diff > 180.0:
    diff -= 360.0
elif diff < -180.0:
    diff += 360.0

# Wende Korrektur an
self.yaw += self.gps_heading_weight * diff
```

### 2. Fehlende Tilt-Kompensation für Yaw

**Alter Code:**
```python
gyro_yaw = self.yaw + self.gyro['z'] * dt
```

**Problem:**
- Funktioniert nur, wenn UGV perfekt flach steht
- Bei 10° Pitch misst Gyro-Z nicht mehr reine Yaw-Rate
- Gyro-Z misst Mischung aus Yaw + Roll

**Lösung:**
```python
# Projiziere 3D-Gyro-Raten auf Welt-Hochachse
roll_rad = math.radians(self.roll)
pitch_rad = math.radians(self.pitch)

yaw_rate = gyro['y'] * math.sin(roll_rad) + \
           gyro['z'] * math.cos(roll_rad) * math.cos(pitch_rad)

self.yaw = self.yaw + yaw_rate * dt
```

---

## Neue Architektur

### 📁 Datei-Struktur

```
sensor_hub/
├── imu_handler_refactored.py  # Reiner Hardware-Treiber
├── sensor_fusion.py            # Sensor Fusion Engine
└── sensor_hub_app.py           # Hauptanwendung
```

### 1. `imu_handler_refactored.py` - Hardware-Treiber

**Verantwortlichkeiten:**
- ✅ I2C-Kommunikation mit ICM-42688-P
- ✅ Sensor-Konfiguration (ODR, Range, etc.)
- ✅ Lesen von Rohdaten (Accel, Gyro, Temp)
- ✅ Kalibrierung (Gyro Bias, Accel Offset)
- ❌ KEINE Sensor-Fusion
- ❌ KEINE GPS-Integration

**API:**
```python
imu = ICM42688P(bus=1, address=0x69, sample_rate=200)
imu.connect()
imu.calibrate(samples=1000)

data = imu.get_data()
# Returns: {'accel': {...}, 'gyro': {...}, 'temperature': ..., 'is_calibrated': ...}
```

### 2. `sensor_fusion.py` - Sensor Fusion Engine

**Verantwortlichkeiten:**
- ✅ Komplementärfilter (Roll/Pitch aus Accel + Gyro)
- ✅ Yaw-Integration mit Tilt-Kompensation
- ✅ GPS-Heading-Fusion (mit korrekter Winkel-Arithmetik)
- ✅ Orientierungs-Berechnung (Roll/Pitch/Yaw)

**API:**
```python
fusion = SensorFusion(sample_rate=200)

# In Loop (200Hz):
fusion.update(
    accel={'x': ..., 'y': ..., 'z': ...},
    gyro={'x': ..., 'y': ..., 'z': ...},
    gps_heading=45.0  # Optional
)

orientation = fusion.get_orientation()
# Returns: {'roll': ..., 'pitch': ..., 'yaw': ..., 'heading': ...}
```

### 3. `sensor_hub_app.py` - Hauptanwendung

**Verantwortlichkeiten:**
- ✅ Initialisierung von IMU + Fusion Engine
- ✅ Fusion Loop (200Hz)
- ✅ GPS-Heading-Integration
- ✅ Flask API-Endpunkte
- ✅ CAN-Bus-Kommunikation

**Fusion Loop:**
```python
def _sensor_fusion_loop(self):
    while self.running:
        # IMU-Rohdaten holen
        imu_data = self.imu.get_data()
        
        # GPS Heading holen (falls verfügbar)
        gps_heading = self.gps.get_status().get('heading')
        
        # Fusion durchführen
        self.fusion.update(
            accel=imu_data['accel'],
            gyro=imu_data['gyro'],
            gps_heading=gps_heading
        )
        
        time.sleep(1.0 / 200)  # 200Hz
```

---

## Vorteile der neuen Architektur

### 1. **Separation of Concerns**
- Jede Klasse hat eine klare Verantwortlichkeit
- Treiber kennt keine Fusion-Logik
- Fusion kennt keine Hardware-Details

### 2. **Testbarkeit**
- Treiber kann isoliert getestet werden
- Fusion kann mit simulierten Daten getestet werden
- Keine Hardware für Fusion-Tests nötig

### 3. **Wartbarkeit**
- Änderungen an Fusion-Algorithmus berühren nicht den Treiber
- Hardware-Änderungen berühren nicht die Fusion
- Klare Schnittstellen zwischen Modulen

### 4. **Erweiterbarkeit**
- Einfach andere Fusion-Algorithmen austauschen (z.B. Kalman-Filter)
- Einfach andere IMU-Sensoren unterstützen
- Einfach weitere Sensoren hinzufügen (z.B. Magnetometer)

### 5. **Korrektheit**
- ✅ Winkel-Wrap-Around korrekt behandelt
- ✅ Tilt-Kompensation für Yaw implementiert
- ✅ Keine Sprünge bei 0°/360°-Übergang

---

## Migration

### Alte Dateien (nicht mehr verwenden):
- ❌ `imu_handler.py` (Gott-Objekt)

### Neue Dateien (verwenden):
- ✅ `imu_handler_refactored.py` (Treiber)
- ✅ `sensor_fusion.py` (Fusion Engine)
- ✅ `sensor_hub_app.py` (aktualisiert)

### Änderungen in `sensor_hub_app.py`:

**Imports:**
```python
from imu_handler_refactored import ICM42688P
from sensor_fusion import SensorFusion
```

**Initialisierung:**
```python
self.imu = ICM42688P(...)
self.fusion = SensorFusion(sample_rate=200)
```

**Fusion Loop:**
```python
self.fusion_thread = threading.Thread(target=self._sensor_fusion_loop, daemon=True)
```

**API-Endpunkte:**
```python
# Rohdaten vom IMU
imu_data = self.imu.get_data()

# Orientierung von Fusion Engine
orientation = self.fusion.get_orientation()
```

---

## Testing

### 1. Treiber-Test (ohne Hardware):
```python
# Mock I2C-Bus für Unit-Tests
# Test Kalibrierung, Daten-Parsing, etc.
```

### 2. Fusion-Test (ohne Hardware):
```python
fusion = SensorFusion(sample_rate=200)

# Simuliere Rotation um Z-Achse (Yaw)
for i in range(100):
    fusion.update(
        accel={'x': 0, 'y': 0, 'z': 9.81},
        gyro={'x': 0, 'y': 0, 'z': 10.0},  # 10°/s
        gps_heading=None
    )

orientation = fusion.get_orientation()
assert abs(orientation['yaw'] - 50.0) < 1.0  # Nach 0.5s: 50°
```

### 3. Winkel-Wrap-Around-Test:
```python
fusion = SensorFusion(sample_rate=200)
fusion.yaw = 359.0

# GPS sagt 1° (fast Nord)
fusion.update(
    accel={'x': 0, 'y': 0, 'z': 9.81},
    gyro={'x': 0, 'y': 0, 'z': 0},
    gps_heading=1.0
)

# Sollte ~359.9° oder ~0.1° sein, NICHT 251°
orientation = fusion.get_orientation()
assert orientation['yaw'] < 10.0 or orientation['yaw'] > 350.0
```

---

## Performance

### Alte Architektur:
- IMU Read Loop: 200Hz ✅
- Fusion in IMU-Klasse: 200Hz ✅
- GPS-Fusion: 10Hz ✅
- **Problem:** Alles in einer Klasse, schwer zu debuggen

### Neue Architektur:
- IMU Read Loop: 200Hz ✅
- Fusion Loop: 200Hz ✅
- GPS-Fusion: 200Hz (aber nur wenn GPS-Daten verfügbar) ✅
- **Vorteil:** Klare Trennung, einfach zu debuggen

---

## Nächste Schritte

### Mögliche Erweiterungen:

1. **Kalman-Filter** statt Komplementärfilter
   - Bessere Sensor-Fusion
   - Adaptive Gewichtung
   - Fehlerkovarianz-Schätzung

2. **Magnetometer-Integration**
   - Absolutes Heading ohne GPS
   - Drift-freies Yaw
   - Magnetische Störungen kompensieren

3. **Bewegungserkennung**
   - Stillstand vs. Bewegung
   - Adaptive Fusion-Parameter
   - Bessere Accel-Nutzung bei Stillstand

4. **Vibrations-Filterung**
   - FFT auf Accel-Daten
   - Hochpass-Filter für Vibrationen
   - Bessere Roll/Pitch-Schätzung

---

## Deployment

### 1. Alte Dateien sichern:
```bash
ssh nicolay@raspberryzero
cd /home/nicolay/sensor_hub
cp imu_handler.py imu_handler.py.backup
```

### 2. Neue Dateien hochladen:
```bash
scp sensor_hub/imu_handler_refactored.py nicolay@raspberryzero:/home/nicolay/sensor_hub/
scp sensor_hub/sensor_fusion.py nicolay@raspberryzero:/home/nicolay/sensor_hub/
scp sensor_hub/sensor_hub_app.py nicolay@raspberryzero:/home/nicolay/sensor_hub/
```

### 3. Service neu starten:
```bash
ssh nicolay@raspberryzero "sudo systemctl restart sensor-hub"
```

### 4. Logs prüfen:
```bash
ssh nicolay@raspberryzero "sudo journalctl -u sensor-hub -f"
```

---

## Zusammenfassung

✅ **Architektur:** Saubere Trennung (Treiber / Fusion / App)  
✅ **Fehler behoben:** Winkel-Wrap-Around + Tilt-Kompensation  
✅ **Testbarkeit:** Jedes Modul isoliert testbar  
✅ **Wartbarkeit:** Klare Schnittstellen, einfache Erweiterung  
✅ **Performance:** Gleiche Performance, bessere Struktur  

**Bereit für Deployment!** 🚀

