# Sensor Hub Deploy auf Orange Pi Zero 2W (DietPi)

## Produktiver Sollzustand

- **Board:** Orange Pi Zero 2W
- **OS:** DietPi
- **User:** `imperator`
- **App-Verzeichnis:** `/opt/sensor_hub`
- **CAN:** candleLight-compatible USB-CAN adapter via native `gs_usb`/SocketCAN → `can0`
- **CAN protocol:** Classical CAN 2.0 at 250 kbit/s; CAN FD is not used
- **GPS:** Holybro UM982 per USB via `/dev/serial/by-id/...`
- **IMU:** WitMotion USB via `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`
- **Web:** direkte Auslieferung auf **Port 80**
- **Reverse Proxy:** **kein `nginx` erforderlich**
- **RTK/NTRIP:** aktiv via `.env`

## 1. Systempakete installieren

```bash
sudo apt update
sudo apt install -y can-utils python3-can python3-dotenv python3-flask python3-pip python3-serial
sudo python3 -m pip install --break-system-packages pynmea2
```

## 2. Sensor Hub nach `/opt/sensor_hub` deployen

```bash
scp -r sensor_hub imperator@orangeugv:/home/imperator/
ssh imperator@orangeugv
sudo mkdir -p /opt/sensor_hub
sudo cp -a /home/imperator/sensor_hub/. /opt/sensor_hub/
sudo chown -R imperator:imperator /opt/sensor_hub
cd /opt/sensor_hub
python3 -m py_compile config.py can_protocol.py telemetry_payload.py sensor_hub_app.py
```

## 3. Helper-Skripte installieren

```bash
sudo install -D -m 755 /opt/sensor_hub/scripts/wait-can0.sh /usr/local/bin/wait-can0.sh
```

## 4. systemd-Services installieren

```bash
sudo install -m 644 /opt/sensor_hub/can-interface.service /etc/systemd/system/can-interface.service
sudo install -m 644 /opt/sensor_hub/sensor-hub.service /etc/systemd/system/sensor-hub.service
sudo systemctl daemon-reload
sudo systemctl disable --now slcan-can0.service || true
sudo systemctl enable --now can-interface.service
sudo systemctl disable --now nginx || true
sudo systemctl enable --now sensor-hub.service
```

Für reinen WLAN-Betrieb ohne USB-CAN-Adapter:

```bash
sed -i 's/^CAN_ENABLED=.*/CAN_ENABLED=0/' /opt/sensor_hub/.env
sudo systemctl disable --now can-interface.service
sudo systemctl restart sensor-hub.service
```

Der SensorHub-Dienst startet dann unabhängig von `can0`. Der CAN-Code und die
Service-Datei bleiben installiert. Für eine spätere Rückkehr zu CAN zuerst
`CAN_ENABLED=1` setzen, danach `can-interface.service` wieder aktivieren und
zuletzt `sensor-hub.service` neu starten.

## 5. `.env` anlegen

```bash
cd /opt/sensor_hub
cp .env.example .env
nano .env
chmod 600 .env
```

Mindestens diese Werte prüfen/anpassen:

```bash
GPS_PORT=/dev/serial/by-id/usb-FTDI_FT231X_USB_UART_*
GPS_BAUDRATE=230400
IMU_ENABLED=1
IMU_TYPE=witmotion
IMU_PORT=/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
IMU_BAUDRATE=9600
WEB_HOST=0.0.0.0
WEB_PORT=80
CAN_ENABLED=1
CAN_INTERFACE=can0
CAN_BITRATE=250000
NTRIP_ENABLED=1
NTRIP_HOST=openrtk-mv.de
NTRIP_PORT=2101
NTRIP_MOUNTPOINT=openrtk_mv_2G
NTRIP_USERNAME=your-username
NTRIP_PASSWORD=your-password
```

## 6. Laufzeit prüfen

```bash
sudo systemctl status can-interface.service --no-pager
sudo systemctl status sensor-hub.service --no-pager
ip -details link show can0
curl http://127.0.0.1/api/health
curl http://127.0.0.1/api/status
curl http://127.0.0.1/api/ntrip/status
```

## 7. Erwartetes Ergebnis

- `sensor-hub.service` läuft als User `imperator`
- `can0` ist `UP`
- der USB-CAN-Adapter arbeitet nativ mit `gs_usb` und Classical CAN 2.0 bei 250 kbit/s
- `http://orangeugv/` antwortet direkt von Flask/Werkzeug auf Port 80
- `/api/health` meldet `status: ok`
- `/api/status` liefert GPS-Daten
- `/api/ntrip/status` zeigt aktive NTRIP-Verbindung

## 8. Wichtige Hinweise

- Die produktive Port-80-Bindung erfolgt über `AmbientCapabilities=CAP_NET_BIND_SERVICE` in `sensor-hub.service`.
- `nginx` bleibt optional installiert, ist für den Betrieb aber **nicht im Pfad**.
- Die echte `.env` enthält Secrets und gehört **nicht** ins Git.
