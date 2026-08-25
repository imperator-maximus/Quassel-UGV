# Quassel UGV – verbindlicher Produktionsstand

Stand: 24.07.2026

Diese Datei ist die maßgebliche Transport- und Hardwareübersicht für neue
Arbeiten am UGV. Ältere CAN-Anleitungen im Repository gelten ausschließlich
für den ehemaligen Offline-Teststand.

## Produktive Verbindungen

| Verbindung | Aktiver Transport |
|---|---|
| Orange Pi SensorHub → Raspberry-Hauptrechner | zwei parallele persistente HTTP/WiFi-NDJSON-Streams |
| Raspberry → ODrive Board A | direkte USB/Fibre-Verbindung, Serial `386132523135`, Axis 0/1 = Node 0/1 |
| Raspberry → ODrive Board B | direkte USB/Fibre-Verbindung, Serial `387132523135`, Axis 0 = Node 2 |
| Raspberry → Fahrmotorcontroller | Hardware-PWM über GPIO 19/18 |

Der SensorHub-Basisendpunkt ist
`http://schloss.fdog.de:8081/api/telemetry`; der Client verwendet daraus
`/api/telemetry/stream`. Zwei unabhängige TCP-Verbindungen verhindern, dass
das Stocken eines einzelnen Streams die Navigation pausiert.

## Zugangsschutz der Weboberflächen

Steuerungsoberfläche und SensorHub sind über Portfreigaben aus dem Internet
erreichbar: extern `8080` → `raspberrycan:80`, extern `8081` → `orangeugv:80`.
Die Ports 80 und 443 zeigen auf ein anderes Gerät im Netz, nicht auf das UGV.

Beide UGV-Endpunkte verlangen eine Anmeldung per HTTP-Basic-Auth; die
Passwörter stehen in `/etc/ugv-web.env` (Modus 600) bzw. `/opt/sensor_hub/.env`,
nie in der Konfigurationsdatei. Ohne gesetztes Passwort antworten sie mit 503
statt ungeschützt zu laufen.

Beim Ausrollen gilt: **Raspberry zuerst, dann SensorHub.** Umgekehrt entsteht
ein Fenster, in dem der SensorHub den Raspberry mit 401 abweist und der
Fahrantrieb pausiert.

Der Raspberry ist selbst Client des SensorHub: `sensor_hub.auth_username` und
`SENSOR_HUB_TELEMETRY_PASSWORD` müssen zu den Zugangsdaten des SensorHub
passen, sonst bleibt die Pose aus und der Watchdog pausiert den Fahrantrieb.

Die Verbindung ist unverschlüsselt; das Passwort ist unterwegs mitlesbar.
Einzelheiten und die Nachrüstung von TLS: `raspberry_pi/WEB_ZUGANGSSCHUTZ.md`.

## Fernzugriff über den Rückwärtstunnel

Die SIM-Karte des Fahrzeugs hat keine öffentliche IP – Mobilfunk liegt hinter
Carrier-Grade-NAT, eingehende Verbindungen sind damit unmöglich. Der Weg dreht
sich deshalb um: Das Fahrzeug baut die Verbindung **hinaus** zur Synology im
Schloss auf und hält sie offen (`raspberry_pi/ugv-reverse-tunnel.service`,
Ziel in `/etc/ugv-tunnel.env`, Vorlage `raspberry_pi/ugv-tunnel.env.example`).

| Auf der Synology | führt zu |
|---|---|
| `127.0.0.1:18080` | Weboberfläche des Fahrzeugs, Port 80 |
| `127.0.0.1:12222` | SSH des Fahrzeugs, Port 22 |

Beide Enden binden auf `127.0.0.1`; was nach außen soll, veröffentlicht dort
der DSM-Reverse-Proxy gezielt per HTTPS. Der SSH-Kanal ist kein Beiwerk: Sobald
das Fahrzeug am Mobilfunkrouter hängt, ist die SSH-Portfreigabe der FRITZ!Box
auf das Fahrzeug tot, und ohne diesen zweiten Kanal bliebe für die Wartung nur
die Weboberfläche. Wartungszugang von außen:

    ssh -J ugvtunnel@schloss.fdog.de:2224 -p 12222 nicolay@127.0.0.1

**DSM erlaubt Portweiterleitung nicht von sich aus.** Der ausgelieferte
`sshd_config` setzt `AllowTcpForwarding no` und macht nur für `root` und
`admin` eine Ausnahme; ohne einen eigenen `Match User`-Block scheitert der
Tunnel mit `remote port forwarding failed`. Der Block wird über eine Aufgabe im
DSM-Aufgabenplaner nach jedem Neustart wiederhergestellt, weil ein DSM-Update
die Datei ersetzen kann. Nach größeren DSM-Updates gehört deshalb geprüft, ob
der Tunnel noch steht.

## Datenverbrauch der Weboberfläche

Das Fahrzeug hängt an einer SIM-Karte, deshalb ist der Statusstrom zur
Oberfläche auf Sparsamkeit ausgelegt:

- Der Server schiebt nur die **Änderung** gegenüber der letzten Sendung
  (`status_delta`); den vollen Stand (`status_update`) bekommt nur, wer sich
  gerade verbunden hat oder eine Differenz verpasst hat. Statt gut 5,5 kB
  gehen im Mittel rund 0,7 kB über die Leitung.
- Gesendet wird nur, solange mindestens eine Oberfläche offen ist. Steht das
  Fahrzeug, einmal je Sekunde; sobald es fährt, mäht, aufzeichnet oder
  gestört ist, viermal (`web.status_interval_idle_s`/`_active_s`).
- Zahlen werden vorher auf die angezeigte Genauigkeit gerundet, Alterswerte
  auf ganze Sekunden. Sonst bestünde die Differenz nur aus Rauschen.
- Der Browser hält keinen zweiten Abrufkanal mehr offen; `/api/status` bleibt
  für Diagnose per curl und liefert dort die ungerundeten Werte.
- Der Joystick sendet nur bei geänderter Auslenkung, dazu alle 200 ms ein
  Lebenszeichen für den Fahr-Wachhund.
- Socket.IO verbindet direkt per WebSocket; die HTTP-Polling-Phase entfällt.
  Lässt ein Netz keinen WebSocket durch, fällt der Browser von selbst zurück.
- Textantworten gehen gzip-komprimiert raus, die Oberfläche trägt ein ETag –
  ein erneuter Aufruf kostet dann nichts mehr statt 90 kB.

## CAN-Status

- Haupt-UGV: `can.enabled: false`
- SensorHub: `CAN_ENABLED=0`
- Kein InnoMaker CAN HAT und kein CAN Device-Tree-Overlay
- Kein USB-CAN-Adapter im produktiven SensorHub- oder Hauptrechner-Pfad
- ODrive-Steuerung produktiv ausschließlich mit `odrive_mower.transport: usb`
- CAN-Code bleibt nur für Legacy-/Testzwecke im Repository und ist kein
  automatischer Rückfallpfad
- Ehemaliger Teststand: offline, USB-CAN, Classical CAN 2.0 bei 250 kbit/s

## Safety

- Nach etwa 1 s ohne aktuelle SensorHub-Pose pausieren Fahrantrieb und Route.
- Kehrt die Pose zurück, wird eine aktive Route aus der Speicherpause exakt
  fortgesetzt.
- Nach längerem Ausfall verriegelt der Gesamtsystem-Stopp einschließlich
  Mähdeck.
- Alle drei Mähachsen besitzen einen lokalen ODrive-Watchdog und werden über
  USB auf Zustand, Strom, Drehzahl und Fehler überwacht.
- Diese Überwachung läuft im zentralen Safety-Watchdog, nicht im Mähdeck-Thread.
  Ein libfibre-Aufruf blockiert seinen Thread ohne Timeout; eine Prüfung, die
  im selben Thread lebt, fällt mit ihm aus. Läuft das Deck, führen hängender
  Transport, veralteter Status, ODrive-Fehler, verlassener Closed-Loop und ein
  stehendes Messer zum Gesamtstopp. Ein hängender USB-Aufruf beendet danach den
  Prozess (Exit 70), weil er prozessintern nicht abbrechbar ist; systemd startet
  neu, die Messer sind zu diesem Zeitpunkt bereits vom ODrive-Watchdog entwaffnet.

## Vorgabe für weitere Entwicklung

Navigation, Pfadplanung, Weboberfläche und Mählogik müssen auf dieser
USB/WiFi-Architektur weiterentwickelt werden. CAN darf dabei nicht wieder als
Produktionsabhängigkeit eingeführt werden.
