# 🔌 Externe SBUS-Stromversorgung Guide

## 🎯 Problem
Orange Cube SBUS-Port liefert keinen Strom trotz korrekter Parameter-Konfiguration.

## ✅ Lösung: Externe 5V-Versorgung

### 📋 Benötigte Komponenten:
- **5V BEC** (Battery Eliminator Circuit)
- **Oder 5V-Ausgang vom Power Module**
- **Oder separate 5V-Stromquelle**

### 🔌 Verkabelung:

```
SBUS-Empfänger:
├── Signal (weiß/gelb) → Orange Cube SBUS Pin 1 (Signal)
├── + (rot)            → Externe 5V-Quelle (+)
└── GND (schwarz)      → Orange Cube SBUS Pin 5 (GND) + Externe 5V-Quelle (GND)
```

### 🎯 Wichtige Punkte:

1. **Signal-Pin** bleibt am Orange Cube angeschlossen
2. **Strom** kommt von externer Quelle
3. **GND** muss gemeinsam sein (Orange Cube + externe Quelle)

### 🔧 Mögliche 5V-Quellen:

#### **Option 1: BEC (Empfohlen)**
```
Batterie → BEC (5V/3A) → SBUS-Empfänger
```

#### **Option 2: Power Module**
```
Power Module 5V-Ausgang → SBUS-Empfänger
```

#### **Option 3: USB-Adapter**
```
USB 5V-Adapter → SBUS-Empfänger (nur für Tests)
```

### ⚡ Stromverbrauch:
- **SBUS-Empfänger**: ~50-100mA
- **BEC-Empfehlung**: Mindestens 500mA (für Sicherheit)

### 🎮 Nach der externen Stromversorgung:

1. **SBUS-Empfänger sollte LED zeigen**
2. **RC-Test durchführen:**
   ```bash
   python rc_test_guide.py
   ```
3. **RC-Werte sollten sich ändern**

### 🔍 Troubleshooting:

#### **SBUS-Empfänger LED blinkt nicht:**
- Externe 5V-Spannung prüfen
- Verkabelung überprüfen
- SBUS-Empfänger defekt?

#### **LED leuchtet, aber keine RC-Werte:**
- SBUS-Signal-Pin überprüfen
- Fernbedienung eingeschaltet?
- Binding zwischen Sender und Empfänger OK?

#### **RC-Werte ändern sich, aber falsche Richtung:**
- Parameter-Konfiguration überprüfen
- RC-Kalibrierung durchführen

### 📋 Test-Checkliste:

- [ ] Externe 5V-Versorgung angeschlossen
- [ ] SBUS-Empfänger LED leuchtet/blinkt
- [ ] Fernbedienung eingeschaltet
- [ ] Orange Cube Parameter korrekt gesetzt
- [ ] RC-Test zeigt sich ändernde Werte
- [ ] Skid Steering funktioniert

### 🎯 Erfolg-Kriterien:

**RC-Test sollte zeigen:**
```
🎮 TEST 1: STEERING (Kanal 1)
1️⃣ Bewegen Sie den STEERING-Stick nach LINKS
   ✅ ERKANNT! Neuer Wert: 1200
```

**Beyond Robotics Board sollte zeigen:**
```
Motors: 8100, 0  →  ESC Command: [1994, 1500]  (Linkskurve)
Motors: 0, 8100  →  ESC Command: [1500, 1994]  (Rechtskurve)
```

---

## 💡 Hinweis:
Externe SBUS-Stromversorgung ist bei vielen professionellen Systemen Standard-Praxis. Viele Autopiloten haben schwache Servo-Stromversorgung oder diese ist standardmäßig deaktiviert.
