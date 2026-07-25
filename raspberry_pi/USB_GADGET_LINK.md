# USB-Gadget-Link zwischen Orange Pi (SensorHub) und Raspberry Pi

Alternative zum WLAN für die SensorHub-Telemetrie: Der Orange Pi Zero 2W stellt
über seinen freien OTG-USB-C-Port ein CDC-ECM-Gadget (`g_ether` via
configfs/libcomposite) bereit, der Raspberry Pi ist USB-Host. Ergebnis ist ein
Punkt-zu-Punkt-Ethernet-Link mit statischen IPs:

| Seite | Rolle | Interface | IP |
|---|---|---|---|
| Orange Pi Zero 2W | USB-Gadget (Device) | `usb0` | `10.66.0.1/24` |
| Raspberry Pi 3 | USB-Host (`cdc_ether`) | `usb0` | `10.66.0.2/24` |

Der HTTP-Pfad im Code bleibt unverändert – es wandert nur die URL in
`config.yaml`. Es gibt **bewusst keinen Auto-Fallback** zwischen WLAN und
USB-Link; die Umstellung ist explizit manuell. Wer zurück will, stellt die
alte `wifi_url` wieder ein.

Die Stromversorgung des Orange Pi läuft weiter über den eigenen Power-Port,
nicht über den OTG-Port. Das Verbindungskabel muss Datenleitungen haben
(kein reines Ladekabel).

## 1. Orange Pi (Gadget-Seite)

Skript und Unit liegen unter `sensor_hub/scripts/` und werden wie die übrigen
SensorHub-Artefakte nach `/opt/sensor_hub` deployt (siehe
`sensor_hub/DEPLOY_ORANGE_PI.md`):

```bash
sudo install -m 755 /opt/sensor_hub/scripts/usb_gadget_setup.sh /usr/local/bin/usb_gadget_setup.sh
sudo install -m 644 /opt/sensor_hub/scripts/usb-gadget.service /etc/systemd/system/usb-gadget.service
sudo systemctl daemon-reload
sudo systemctl enable --now usb-gadget.service
```

Das Skript lädt `libcomposite`, legt das Gadget `ecm.usb0` mit festen MACs an
(Device `02:11:22:33:44:01`, Host `02:11:22:33:44:02`) und setzt
`10.66.0.1/24` auf `usb0`. USB-IDs: `0x1d6b:0x0104` (Linux Foundation
Multifunction Composite Gadget) – eine unverfängliche, öffentlich
dokumentierte Kombination.

Voraussetzung: Der OTG-Controller muss im Device-Tree auf
`dr_mode = "peripheral"` (oder `"otg"`) stehen. Schnellcheck:

```bash
ls /sys/class/udc        # muss mindestens einen Eintrag liefern
```

Ist das Verzeichnis leer, auf Armbian/DietPi das Overlay `usb-otg` aktivieren
(`armbian-config` bzw. `/boot/armbianEnv.txt` bzw. `dietpi-config`) und neu
starten. Das Setup-Skript bricht in dem Fall mit einem entsprechenden Hinweis
ab. Bei mehreren UDCs kann der gewünschte per Env-Var `UDC` gewählt werden.

## 2. Raspberry Pi (Host-Seite)

Nach dem Anstecken meldet sich das Gadget als CDC-ECM-Gerät (`cdc_ether`),
das Interface heißt typischerweise `usb0`:

```bash
lsusb                  # ... ID 1d6b:0104 Linux Foundation Multifunction Composite Gadget
ip addr show usb0
```

### Statische IP per dhcpcd (Raspberry Pi OS Standard)

In `/etc/dhcpcd.conf` ergänzen:

```
interface usb0
static ip_address=10.66.0.2/24
nogateway
```

Danach `sudo systemctl restart dhcpcd` (oder neu starten). `nogateway`
verhindert, dass der Link die Default-Route vom WLAN/Ethernet wegzieht.

### Alternative: systemd-networkd

Falls das System `systemd-networkd` statt `dhcpcd` nutzt,
`/etc/systemd/network/20-ugv-usb0.network`:

```ini
[Match]
Name=usb0

[Network]
Address=10.66.0.2/24
```

Dann `sudo systemctl enable --now systemd-networkd` und `sudo networkctl reload`.

### udev-Regel, falls das Interface anders heißt

Vergibt das System einen persistierten Namen (z. B. `enx021122334402`), kann
das Interface anhand der Host-MAC `02:11:22:33:44:02` auf `usb0` festgepinnt
werden – `/etc/udev/rules.d/70-ugv-ecm.rules`:

```
SUBSYSTEM=="net", ACTION=="add", ATTR{address}=="02:11:22:33:44:02", NAME="usb0"
```

Danach neu starten (udev benennt nur beim Anlegen des Interfaces um).
Alternativ den tatsächlichen Namen in den Snippets oben verwenden.

## 3. Telemetrie auf den USB-Link umstellen

In `config.yaml` (Block `sensor_hub`, siehe `motor_controller/config.py`) nur
die URL ändern – `transport: wifi` bleibt stehen, es ist derselbe
HTTP-Transport, nur über ein anderes Netz:

```yaml
sensor_hub:
  transport: wifi
  wifi_url: http://10.66.0.1/api/telemetry
```

Der Default in `config.py` (`http://192.168.178.20/api/telemetry`) bleibt
unverändert, damit WLAN weiterhin als Rückfall per Konfiguration verfügbar
ist. Danach den Motor-Controller-Dienst neu starten.

## 4. Verifikation

Auf dem Raspberry Pi:

```bash
lsusb                                   # Gadget mit ID 1d6b:0104 sichtbar
ip addr show usb0                       # inet 10.66.0.2/24
ping -c 3 10.66.0.1                     # Orange Pi antwortet
curl http://10.66.0.1/api/telemetry     # Telemetrie-JSON
```

Auf dem Orange Pi:

```bash
sudo /usr/local/bin/usb_gadget_setup.sh status
ip addr show usb0                       # inet 10.66.0.1/24
journalctl -u usb-gadget.service --no-pager
```

## 5. Troubleshooting

- **`/sys/class/udc` auf dem Orange Pi ist leer:** OTG-Controller steht nicht
  im Peripheral-Modus → Device-Tree/Overlay `usb-otg` aktivieren
  (`armbian-config` / `armbianEnv.txt` / `dietpi-config`), neu starten.
  Das ist der bekannte Knackpunkt auf dem H618.
- **Interface heißt anders (`enx...`):** udev-Regel aus Abschnitt 2 setzen
  oder den Namen im dhcpcd/networkd-Snippet anpassen. Am Orange Pi sucht das
  Setup-Skript das Interface notfalls anhand der Device-MAC selbst.
- **Kein `usb0` am Raspberry, nichts in `lsusb`:** Kabel ohne Datenleitungen
  (reines Ladekabel) oder falscher USB-C-Port am Orange Pi – es muss der
  OTG-fähige Port sein.
- **Link da, aber keine Route ins restliche Netz:** Absicht – der Link ist
  Punkt-zu-Punkt. Am Raspberry `nogateway` (dhcpcd) bzw. kein `Gateway=` in
  networkd gesetzt lassen.
- **Zurück zu WLAN:** `wifi_url` in `config.yaml` auf die alte Adresse
  setzen, Dienst neu starten. `usb-gadget.service` kann parallel aktiv
  bleiben, er stört das WLAN nicht.
