# 🚀 NTRIP/RTK Setup - Schnellstart

## Schritt 1: SSH auf Raspberry Pi Zero verbinden

```bash
ssh nicolay@raspberryzero
cd /home/nicolay/sensor_hub
```

## Schritt 2: Dependencies installieren

```bash
pip3 install python-dotenv
```

## Schritt 3: .env Datei erstellen

```bash
cp .env.example .env
```

## Schritt 4: .env mit deinen Credentials füllen

```bash
nano .env
```

Ersetze die Platzhalter mit deinen NTRIP-Daten:

```bash
NTRIP_HOST=openrtk-mv.de
NTRIP_PORT=2101
NTRIP_MOUNTPOINT=openrtk_mv_2G
NTRIP_USERNAME=odmv-3569452
NTRIP_PASSWORD=hSahH6jy9e
```

**Speichern:** `Ctrl+O`, `Enter`, `Ctrl+X`

## Schritt 5: Anwendung starten

```bash
python3 sensor_hub_app.py
```

Du solltest folgende Ausgabe sehen:

```
✅ GPS verbunden: /dev/serial0 @ 230400 baud
✅ GPS initialisiert
🌉 Starte GPS-NTRIP Bridge
🔗 Verbinde mit NTRIP-Server: openrtk-mv.de:2101/openrtk_mv_2G
✅ NTRIP verbunden - RTK-Daten werden empfangen
✅ GPS-NTRIP Bridge gestartet
✅ NTRIP/RTK aktiviert
🌐 Starte Web-Interface auf 0.0.0.0:8080
```

## Schritt 6: Web-Interface öffnen

Öffne im Browser:
```
http://raspberryzero:8080
```

Du solltest sehen:
- GPS Status (Satelliten, Höhe, Heading)
- NTRIP Status (ONLINE)
- RTK Uptime (wenn RTK FIXED)
- Koordinaten mit Bing Maps Link

## Troubleshooting

### NTRIP zeigt OFFLINE

1. Überprüfe `.env` Datei:
   ```bash
   cat .env
   ```

2. Überprüfe Credentials:
   - Username: `odmv-3569452`
   - Password: `hSahH6jy9e`
   - Host: `openrtk-mv.de`
   - Port: `2101`
   - Mountpoint: `openrtk_mv_2G`

3. Teste Verbindung manuell:
   ```bash
   telnet openrtk-mv.de 2101
   ```

### GPS zeigt "NO GPS"

1. Überprüfe GPS-Verbindung:
   ```bash
   cat /dev/serial0
   ```

2. Sollte NMEA-Sätze anzeigen (z.B. `$GPRMC...`)

3. Warte 30-60 Sekunden für GPS-Lock

### Anwendung startet nicht

1. Überprüfe Python-Version:
   ```bash
   python3 --version
   ```

2. Überprüfe Dependencies:
   ```bash
   pip3 list | grep -E "flask|python-dotenv"
   ```

3. Überprüfe Logs:
   ```bash
   python3 sensor_hub_app.py
   ```

## Sicherheit

⚠️ **WICHTIG:**
- `.env` Datei enthält Passwörter
- Niemals in Git committen
- Nur auf dem Raspberry Pi speichern
- Datei-Permissions: `chmod 600 .env`

Siehe `SECURITY.md` für mehr Informationen.

## API Endpoints

```bash
# GPS Status
curl http://raspberryzero:8080/api/status

# NTRIP Status
curl http://raspberryzero:8080/api/ntrip/status

# Bridge Status (GPS + NTRIP)
curl http://raspberryzero:8080/api/bridge/status

# Koordinaten
curl http://raspberryzero:8080/api/coordinates
```

## Nächste Schritte

- [ ] IMU-Integration (wenn ICM-42688-P ankommt)
- [ ] CAN-Bus Integration
- [ ] Systemd Service für Auto-Start
- [ ] Produktions-WSGI Server (Gunicorn)

---

**Viel Erfolg! 🚀**

