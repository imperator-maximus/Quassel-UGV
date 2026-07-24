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

## Vorgabe für weitere Entwicklung

Navigation, Pfadplanung, Weboberfläche und Mählogik müssen auf dieser
USB/WiFi-Architektur weiterentwickelt werden. CAN darf dabei nicht wieder als
Produktionsabhängigkeit eingeführt werden.
