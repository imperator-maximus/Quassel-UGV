# 🚀 NTRIP/RTK Setup - Schnellstart

## Schritt 1: SSH auf Orange Pi verbinden

```bash
ssh nicolay@orangeugv
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
NTRIP_MOUNTPOINT=openrtk_mv
NTRIP_USERNAME=your_username
NTRIP_PASSWORD=your_password
```

**Mountpoint:** `openrtk_mv` verwenden — MSM4 mit GPS, GLONASS, Galileo und BeiDou.
Der ältere `openrtk_mv_2G` liefert nur Legacy-RTCM3 mit GPS und GLONASS und ist
für stabile Fixes deutlich schwächer. Details unter [RTK-Mountpoints](#rtk-mountpoints).

**Speichern:** `Ctrl+O`, `Enter`, `Ctrl+X`

## Schritt 5: NTRIP im Service aktivieren

Bearbeite die Service-Datei und setze:

```bash
sudo nano /etc/systemd/system/sensor-hub.service
```

von:

```ini
Environment=NTRIP_ENABLED=0
```

auf:

```ini
Environment=NTRIP_ENABLED=1
```

Danach:

```bash
sudo systemctl daemon-reload
sudo systemctl restart sensor-hub.service
```

## Schritt 6: Anwendung prüfen

```bash
python3 sensor_hub_app.py
```

Du solltest folgende Ausgabe sehen:

```
✅ GPS verbunden: /dev/serial/by-id/... @ 230400 baud
✅ GPS initialisiert
🌉 Starte GPS-NTRIP Bridge
🔗 Verbinde mit NTRIP-Server: openrtk-mv.de:2101/openrtk_mv
✅ NTRIP verbunden - RTK-Daten werden empfangen
✅ GPS-NTRIP Bridge gestartet
✅ NTRIP/RTK aktiviert
🌐 Starte Web-Interface auf 0.0.0.0:8080
```

## Schritt 7: Web-Interface öffnen

Öffne im Browser:
```
http://orangeugv:8080
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
   - Username: dein eigener NTRIP-Benutzername
   - Password: dein eigenes NTRIP-Passwort
   - Host: `openrtk-mv.de`
   - Port: `2101`
   - Mountpoint: `openrtk_mv`

3. Teste Verbindung manuell:
   ```bash
   telnet openrtk-mv.de 2101
   ```

4. **„Too many concurrent connections"**: Der Account erlaubt nur *eine*
   gleichzeitige Verbindung. Der Caster meldet den Grund als RTCM-Textnachricht
   MT1029 — im Klartext sichtbar nur im Mitschnitt, nicht im HTTP-Status
   (der ist `ICY 200 OK`). Erst den laufenden Dienst stoppen, dann testen.

### RTK bleibt dauerhaft FLOAT

Wenn NTRIP verbunden ist, Daten fließen und trotzdem kein Fix zustande kommt:
Prüfe, **welche Konstellationen** überhaupt Korrekturen bekommen — nicht nur, ob
die Verbindung steht. Ein GGA-Satz mit niedrigem Wert in Feld 13 (Alter der
Differentialkorrekturen, z. B. `1.0`) beweist, dass die Daten ankommen *und*
verarbeitet werden; das Problem liegt dann nicht in der Übertragungskette.

Am 06.08.2026 hing das Fahrzeug so über 25 Minuten in FLOAT, weil `openrtk_mv_2G`
nur GPS und GLONASS lieferte. Nach Wechsel auf `openrtk_mv` war der Fix nach
14 Sekunden zurück.

## RTK-Mountpoints

Sourcetable von `openrtk-mv.de:2101` (Stand 06.08.2026):

| Mountpoint | Format | Konstellationen | Zugang |
|---|---|---|---|
| **`openrtk_mv`** | RTCM 3 / MSM4 | GPS + GLONASS + Galileo + BeiDou | frei (LAiV MV) |
| `openrtk_mv_2G` | RTCM 3 legacy | GPS + GLONASS | frei (LAiV MV) |
| `VRS_3_4G_MV` | RTCM 3 / MSM4 | GPS + GLONASS + Galileo + BeiDou | SAPOS MV (kostenpflichtig) |
| `VRS_3_3G_MV` | RTCM 3 / MSM4 | GPS + GLONASS + Galileo | SAPOS MV |
| `VRS_3_GE_MV` | RTCM 3 / MSM4 | GPS + Galileo | SAPOS MV |
| `VRS_3_2G_MV` | RTCM 3 legacy | GPS + GLONASS | SAPOS MV |

Achtung: Bei `openrtk_mv` lässt die Sourcetable das Feld für die Konstellationen
**leer** — dort steht nur `MSM4`. Der tatsächliche Inhalt (MT1074/1084/1094/1124,
je 1 Hz, ~1073 B/s) wurde per RTCM-Mitschnitt verifiziert. `openrtk_mv_2G`
liefert MT1004/1012 bei ~320 B/s.

Sourcetable selbst abrufen (ohne Zugangsdaten möglich, zählt nicht als Verbindung):

```bash
printf 'GET / HTTP/1.0\r\n\r\n' | nc openrtk-mv.de 2101 | grep '^STR;'
```

### GPS zeigt "NO GPS"

1. Überprüfe GPS-Verbindung:
   ```bash
   curl http://127.0.0.1:8080/api/status
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
curl http://orangeugv:8080/api/status

# NTRIP Status
curl http://orangeugv:8080/api/ntrip/status

# Bridge Status (GPS + NTRIP)
curl http://orangeugv:8080/api/bridge/status

# Koordinaten
curl http://orangeugv:8080/api/coordinates
```

## Nächste Schritte

- [x] WitMotion USB-IMU integriert
- [ ] CAN-Bus Integration
- [ ] Systemd Service für Auto-Start
- [ ] Produktions-WSGI Server (Gunicorn)

---

**Viel Erfolg! 🚀**

