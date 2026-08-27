# Systemd-Einheiten des SensorHub

Diese Dateien liegen auf dem Orange Pi unter `/usr/local/sbin/` (Skripte) und
`/etc/systemd/system/` (Einheiten). Sie stehen hier, damit sie nicht nur auf
dem Geraet existieren.

## `hub-netwatch` — aktiv

Prueft alle 30 s, ob das eigene Standard-Gateway antwortet, und fordert eine
neue Adresse an, wenn nicht.

Der SensorHub bringt sein WLAN ueber `ifupdown` mit `wpa-conf` hoch. Faellt das
aktuelle Netz weg, wechselt `wpa_supplicant` in das naechste - aber niemand
fordert eine neue Adresse an. Am 27.08.2026 behielt er dadurch eine Adresse aus
dem Netz des Mobilfunkrouters, waehrend er im alten WLAN hing: fuer alle
unerreichbar, bis jemand hinfuhr und ihn stromlos machte. Der Raspberry hat das
Problem nicht, weil NetworkManager beim Netzwechsel selbst neu anfragt.

## `hub-netlog` — aktiv

Schreibt nach jedem Start den Netzzustand nach `/home/imperator/hub-netz.log`.
Das Journal liegt hier im Arbeitsspeicher (`Storage=auto`, keine Dateilogs);
nach einem Neustart war deshalb nicht mehr nachvollziehbar, woran ein
Umschaltversuch gescheitert war.

## `hub-failsafe` — installiert, nicht aktiv

Rueckfallschalter fuer Netzumstellungen: Ist das Huawei-Profil zehn Minuten
nach dem Start noch freigegeben und hat sich niemand gemeldet, setzt er es
still und startet neu. Wird vor einer Umstellung mit
`systemctl enable --now hub-failsafe.timer` scharfgeschaltet und danach wieder
abgeschaltet. Die Pruefung am Skriptanfang verhindert eine Neustartschleife.
