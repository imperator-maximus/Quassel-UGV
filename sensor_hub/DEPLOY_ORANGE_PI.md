# Sensor Hub Deploy auf Orange Pi Zero 2W (DietPi)

## Aktueller Stand

- **Board:** Orange Pi Zero 2W
- **OS:** DietPi
- **CAN:** CANable2 per USB via `slcan-can0.service` → `can0`
- **GPS:** Holybro UM982 per USB, stabil über `/dev/serial/by-id/...`
- **IMU:** aktuell deaktiviert
- **NTRIP/RTK:** im Service derzeit bewusst deaktiviert für stabilen Erstbetrieb

## 1. Systempakete installieren

```bash
sudo apt update
sudo apt install -y can-utils python3-can python3-dotenv python3-flask python3-pip
sudo python3 -m pip install --break-system-packages pynmea2
```

## 2. Sensor Hub deployen

```bash
scp -r sensor_hub nicolay@orangeugv:/home/nicolay/
ssh nicolay@orangeugv
cd /home/nicolay/sensor_hub
python3 -m py_compile config.py can_protocol.py telemetry_payload.py sensor_hub_app.py
```

## 3. CAN-Service bereitstellen

Voraussetzung: `slcan-can0.service` ist bereits eingerichtet und erzeugt `can0`.

Prüfen:

```bash
sudo systemctl status slcan-can0.service
ip -details link show can0
```

## 4. Sensor-Hub-Service installieren

```bash
sudo install -m 644 /home/nicolay/sensor_hub/sensor-hub.service /etc/systemd/system/sensor-hub.service
sudo systemctl daemon-reload
sudo systemctl enable --now sensor-hub.service
```

## 5. Laufzeit prüfen

```bash
sudo systemctl status sensor-hub.service
sudo journalctl -u sensor-hub.service -f
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1:8080/api/status
```

## 6. Aktuelle Default-Annahmen

Der Service startet derzeit absichtlich mit:

```ini
Environment=IMU_ENABLED=0
Environment=NTRIP_ENABLED=0
```

Das bedeutet:

- **GPS ist aktiv**
- **CAN ist aktiv**
- **IMU ist aus**
- **RTK/NTRIP ist aus**

## 7. RTK/NTRIP wieder aktivieren

### `.env` anlegen

```bash
cd /home/nicolay/sensor_hub
cp .env.example .env
nano .env
chmod 600 .env
```

Pflege dort deine echten Werte ein:

```bash
NTRIP_HOST=your-host
NTRIP_PORT=2101
NTRIP_MOUNTPOINT=your-mountpoint
NTRIP_USERNAME=your-username
NTRIP_PASSWORD=your-password
```

### Service wieder mit NTRIP starten

Datei anpassen:

```bash
sudo nano /etc/systemd/system/sensor-hub.service
```

Diese Zeile ändern:

```ini
Environment=NTRIP_ENABLED=0
```

zu:

```ini
Environment=NTRIP_ENABLED=1
```

Dann neu laden:

```bash
sudo systemctl daemon-reload
sudo systemctl restart sensor-hub.service
sudo journalctl -u sensor-hub.service -n 50 --no-pager
```

## 8. Nützliche Checks

```bash
# CAN-Daten sehen
candump can0

# Health API
curl http://127.0.0.1:8080/api/health

# GPS-Daten
curl http://127.0.0.1:8080/api/status

# NTRIP-Status (wenn aktiviert)
curl http://127.0.0.1:8080/api/ntrip/status
```

## 9. Erwartetes Ergebnis

- `gps_connected: true` in `/api/health`
- Live-GPS-Daten in `/api/status`
- CAN-Telemetrie auf `can0`
- nach NTRIP-Aktivierung: `ntrip_connected: true` und RTK-Status im GPS-Status