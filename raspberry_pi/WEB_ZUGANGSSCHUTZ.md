# Zugangsschutz für die öffentlich erreichbaren Weboberflächen

Stand: 07.08.2026

Steuerungsoberfläche und SensorHub hängen über Portfreigaben direkt am
Internet. Beide verlangen seitdem eine Anmeldung per HTTP-Basic-Auth. Diese
Datei beschreibt, wie die Passwörter gesetzt werden und was der Schutz leistet.

## Erreichbarkeit (gemessen am 07.08.2026)

| Öffentlicher Port | Ziel | Intern |
|---|---|---|
| 8080 | Raspberry Steuerungsoberfläche | `raspberrycan:80` |
| 8081 | SensorHub | `orangeugv:80` |
| 80, 443 | anderes Gerät im Netz (nginx), **nicht** das UGV | — |

Zur Prüfung von außen dient die Kennung im Antwortkopf: Der Raspberry meldet
`WWW-Authenticate: Basic realm="Quassel UGV"`, der SensorHub
`realm="Quassel UGV SensorHub"`. Antwortet ein Port stattdessen mit
`Server: nginx`, ist es nicht das Fahrzeug.

## Was ohne Schutz erreichbar war

| Endpunkt | Wirkung |
|---|---|
| `POST /api/joystick`, WebSocket `joystick_update` | Fahrzeug fahren |
| `POST /api/mower/toggle` | Mähmesser starten |
| `POST /api/mapping/maps/<name>/plan/execute` | autonome Mahd starten |
| `POST /api/safety/reset` | Sicherheitsverriegelung aufheben |
| SensorHub `GET /api/telemetry` | metergenaue Position des Grundstücks |

## Passwörter setzen

### Raspberry (Steuerungsoberfläche)

Das Passwort steht **nicht** in der `config.yaml` und auch nicht in der
Service-Unit — Unit-Dateien sind für alle lokalen Benutzer lesbar. Es liegt in
`/etc/ugv-web.env` mit Modus 600, die die Unit über `EnvironmentFile=` einliest:

```
UGV_WEB_USERNAME=smart
UGV_WEB_PASSWORD=hier-ein-langes-passwort
UGV_WEB_SECRET_KEY=hier-ein-zufaelliger-wert
SENSOR_HUB_TELEMETRY_USER=smart
SENSOR_HUB_TELEMETRY_PASSWORD=passwort-des-sensorhubs
Rechte setzen und übernehmen:

```bash
sudo chown root:root /etc/ugv-web.env && sudo chmod 600 /etc/ugv-web.env && sudo systemctl restart motor-controller-v2
```

Weil die Datei nur root gehört, kommt auch das Deploy-Skript nur über `sudo`
an sie heran — die Abschlussprüfung dort liest sie entsprechend.

Besser als das Passwort im Klartext ist ein Hash. Er wird auf dem Raspberry
erzeugt und in dieselbe Variable eingetragen:

```bash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash(input('Passwort: ')))"
```

Ein zufälliges Passwort und einen Sitzungsschlüssel erzeugst du mit:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

Danach:

```bash
sudo systemctl daemon-reload && sudo systemctl restart motor-controller-v2
```

### SensorHub (Orange Pi)

Der SensorHub liest seine Konfiguration aus `/opt/sensor_hub/.env`:

```
WEB_AUTH_USERNAME=ugv
WEB_AUTH_PASSWORD=hier-ein-langes-passwort
```

Rechte einschränken und neu starten:

```bash
sudo chmod 600 /opt/sensor_hub/.env && sudo systemctl restart sensor-hub.service
```

### Wichtig: der Raspberry ist selbst ein Client des SensorHub

Der Raspberry holt seine Pose über `sensor_hub.wifi_url` vom SensorHub. Diese
Zugangsdaten müssen zusammenpassen:

| SensorHub (`.env`) | Raspberry |
|---|---|
| `WEB_AUTH_USERNAME` | `sensor_hub.auth_username` in der `config.yaml` |
| `WEB_AUTH_PASSWORD` | `SENSOR_HUB_TELEMETRY_PASSWORD` in der Dienst-Umgebung |

Passen sie nicht zusammen, bleibt die Pose aus und der Watchdog pausiert nach
etwa einer Sekunde Fahrantrieb und Route. Im Journal steht dann:

```
SensorHub weist die Anmeldung ab ...
```

### Reihenfolge beim Ausrollen: Raspberry zuerst

Ein SensorHub, der bereits Anmeldung verlangt, während der Raspberry noch alten
Code fährt, antwortet diesem mit 401 — Pose weg, Fahrantrieb pausiert.
Andersherum ist es unkritisch: Ein Raspberry, der Zugangsdaten mitschickt,
kommt an einem SensorHub, der noch keine verlangt, problemlos durch. Der
zusätzliche Header wird schlicht ignoriert.

1. Zugangsdaten auf **beiden** Geräten hinterlegen (die alte SensorHub-Version
   ignoriert `WEB_AUTH_*`, das ist gefahrlos)
2. **Raspberry** ausrollen und neu starten
3. **SensorHub** ausrollen und neu starten
4. `journalctl -u motor-controller-v2 -f` kontrollieren

Nach Schritt 3 erscheint einmalig `SensorHub-Telemetriestrom beendet` — das ist
der Abriss durch den Dienstneustart, kein Fehler. Bleibt es dabei und meldet
der Status `motion_allowed: true`, ist die Kette intakt.

## Was der Schutz leistet

- **Anmeldung für jede Route.** Ohne gültige Zugangsdaten antworten beide
  Server mit 401, auch auf Statusabfragen.
- **WebSocket abgesichert.** Der Socket.IO-Handshake läuft am HTTP-Hook vorbei
  und wird separat über das Sitzungscookie geprüft. Ohne diese Prüfung wäre
  `joystick_update` ein unauthentifizierter Steuerkanal geblieben.
- **Kein Wildcard-CORS mehr.** Vorher stand auf jeder Antwort
  `Access-Control-Allow-Origin: *`; jede beliebige Webseite konnte damit
  Antworten dieses Servers lesen.
- **Schutz vor fremden Webseiten.** Ein Browser hängt einmal eingegebene
  Basic-Auth-Zugangsdaten auch an Requests an, die eine fremde Seite auslöst.
  Schreibende Requests mit fremder Herkunft (`Origin` / `Sec-Fetch-Site`)
  werden deshalb mit 403 abgewiesen. Skripte ohne Browser-Header bleiben
  erlaubt, weil das Basic-Auth sie bereits abfängt.
- **Bremse gegen Rateversuche.** Nach `auth_max_failures` Fehlversuchen ist die
  Quell-IP für `auth_lockout_s` Sekunden gesperrt.
- **Fail closed.** Ist der Schutz aktiv, aber kein Passwort gesetzt, antwortet
  der Server mit 503 statt ungeschützt zu laufen.
- **Keine Geheimnisse in der YAML.** `to_yaml()` schreibt weder Passwörter noch
  den `secret_key`.

## Was der Schutz nicht leistet

Basic-Auth ohne TLS überträgt das Passwort bei **jedem** Request mitlesbar.
Jeder Netzknoten zwischen deinem Handy und dem Grundstück sieht es: fremdes
WLAN, Mobilfunknetz, jeder Hop dazwischen. Der Schutz hält Gelegenheitsfunde
und Portscanner ab, nicht jemanden, der deinen Datenverkehr beobachtet.

### Nachrüsten von TLS

Hier gibt es zwei Hindernisse, die man kennen sollte, bevor man anfängt.

**Die Ports 80 und 443 sind belegt.** Sie zeigen auf ein anderes Gerät im Netz,
nicht auf das UGV. Let's Encrypt braucht aber genau einen von beiden für den
Besitznachweis (HTTP-01 auf 80, TLS-ALPN-01 auf 443). Ein Caddy auf dem
Raspberry käme also gar nicht an ein Zertifikat, solange die Freigaben so
stehen.

**Die Uhr.** Weder Raspberry noch Orange Pi haben ein RTC-Modul, und beide sind
über den Winter aus. Nach Monaten ohne Strom booten sie mit falschem Datum; bis
NTP durchgelaufen ist, scheitert jede Zertifikatsausstellung. Ein Dienst, der
darauf angewiesen ist, bräuchte eine Startbedingung auf `time-sync.target`.

Beides zusammen spricht dafür, TLS **nicht** auf dem Fahrzeug zu betreiben,
sondern auf dem Gerät, das ohnehin schon 80 und 443 hält, durchgehend läuft und
eine korrekte Uhr hat. Es würde als Reverse Proxy vor die UGV-Oberfläche
gesetzt und das Zertifikat verwalten; auf dem Fahrzeug bliebe alles wie es ist.
Die Origin-Prüfung akzeptiert `https` auf demselben Host bereits, es wäre also
keine Codeänderung nötig.

**Wichtig dabei:** Der Telemetriepfad Raspberry → SensorHub darf nicht über
einen TLS-Proxy laufen. Python bricht bei abgelaufenem Zertifikat hart ab, es
gibt kein Wegklicken — ein abgelaufenes Zertifikat würde damit den Fahrantrieb
stilllegen. Diese Verbindung bleibt auf reinem HTTP.
