# 🚀 CAN-Bus Integration Guide
## Beyond Robotics Board ↔ Orange Cube DroneCAN

### ✅ AKTUELLER STATUS
- ✅ Beyond Robotics Board: DroneCAN läuft, Node ID 127
- ✅ Orange Cube: DroneCAN konfiguriert, Node ID 10
- ✅ Beide Geräte: 1 Mbps Bitrate
- ✅ Serial-Kommunikation funktioniert

---

## 🔌 HARDWARE-VERBINDUNG

### Beyond Robotics Dev Board CAN-Pins
**Laut Beyond Robotics Dokumentation:**
- **CAN_TX**: Pin wird automatisch konfiguriert
- **CAN_RX**: Pin wird automatisch konfiguriert
- **CAN-Transceiver**: Integriert im Board

### Orange Cube CAN-Port
**Orange Cube Carrier Board:**
- **CAN1 Port**: 4-Pin JST-GH Connector
- **Pin 1**: VCC (5V)
- **Pin 2**: CAN_H
- **Pin 3**: CAN_L  
- **Pin 4**: GND

### Verbindungsschema
```
Beyond Robotics Board    Orange Cube CAN1
├─ CAN_H        ←────→   Pin 2 (CAN_H)
├─ CAN_L        ←────→   Pin 3 (CAN_L)
└─ GND          ←────→   Pin 4 (GND)
```

**WICHTIG:** 
- 120Ω Terminierung an beiden Enden
- Orange Cube hat bereits interne Terminierung
- Beyond Robotics Board sollte auch Terminierung haben

---

## ⚙️ SOFTWARE-KONFIGURATION

### Orange Cube Parameter (bereits gesetzt)
```
CAN_P1_DRIVER = 1         # CAN-Treiber aktiviert
CAN_P1_BITRATE = 1000000  # 1 Mbps
CAN_D1_PROTOCOL = 1       # DroneCAN aktiviert
CAN_D1_UC_NODE = 10       # Orange Cube Node ID
CAN_D1_UC_ESC_BM = 5      # ESC Bitmask
CAN_D1_UC_SRV_BM = 5      # Servo Bitmask
```

### Beyond Robotics Node ID anpassen
**Aktuell:** Node ID 127 (default)
**Empfohlen:** Node ID 20-50 (vermeidet Konflikte)

---

## 🔧 INTEGRATION SCHRITTE

### Schritt 1: Node ID anpassen
1. Beyond Robotics Node ID von 127 auf 25 ändern
2. Firmware neu kompilieren und uploaden
3. Eindeutige Node IDs sicherstellen

### Schritt 2: Hardware verbinden
1. CAN-Kabel zwischen beiden Geräten
2. Terminierung prüfen
3. Stromversorgung sicherstellen

### Schritt 3: Kommunikation testen
1. CAN-Traffic mit Cangaroo überwachen
2. Node-Discovery prüfen
3. Message-Austausch verifizieren

### Schritt 4: Funktionalität implementieren
1. Battery-Messages vom Beyond Robotics Board
2. Actuator-Commands vom Orange Cube
3. Status-Messages bidirektional

---

## 📊 ERWARTETE ERGEBNISSE

### Nach erfolgreicher Integration:
- ✅ Beide Nodes sichtbar im CAN-Netzwerk
- ✅ GetNodeInfo Requests/Responses
- ✅ Parameter-Austausch möglich
- ✅ Battery-Info vom Beyond Robotics Board
- ✅ Actuator-Commands vom Orange Cube

### CAN-Messages die zu sehen sein sollten:
```
Node 10 (Orange Cube):
- NodeStatus broadcasts
- GetNodeInfo responses
- Actuator commands

Node 25 (Beyond Robotics):
- NodeStatus broadcasts  
- GetNodeInfo responses
- Battery info broadcasts
- Parameter responses
```

---

## 🛠️ TROUBLESHOOTING

### Keine CAN-Kommunikation:
1. **Hardware prüfen**: Verkabelung, Terminierung
2. **Bitrate prüfen**: Beide auf 1 Mbps
3. **Node IDs prüfen**: Keine Duplikate
4. **Power prüfen**: Stabile Versorgung

### Partial Communication:
1. **Timing prüfen**: Message-Raten anpassen
2. **Buffer prüfen**: CAN-Buffer-Größen
3. **Interference prüfen**: Kabel-Qualität

---

## 🎯 NÄCHSTE SCHRITTE

1. **Node ID anpassen** (127 → 25)
2. **Hardware verbinden**
3. **CAN-Traffic überwachen**
4. **Integration testen**
5. **Anwendung entwickeln**

Bereit für die Implementierung! 🚀
