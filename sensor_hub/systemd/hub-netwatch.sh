#!/bin/sh
# Repariert eine Adresse, die nicht mehr zum Netz passt.
#
# Der SensorHub bringt sein WLAN ueber ifupdown mit wpa-conf hoch. Verschwindet
# das aktuelle Netz, wechselt wpa_supplicant brav in das naechste - aber
# niemand fordert eine neue Adresse an. Am 27.08.2026 behielt er dadurch eine
# Adresse aus dem Netz des Mobilfunkrouters, waehrend er im alten WLAN hing:
# fuer alle unerreichbar, bis jemand hinfuhr und ihn stromlos machte.
#
# Geprueft wird deshalb nicht die Verbindung, sondern ob das eigene Gateway
# ueberhaupt antwortet. Das ist genau die Frage, die eine falsche Adresse
# verneint.
GW=$(ip -4 route 2>/dev/null | awk '/^default/ {print $3; exit}')
STATE=/run/hub-netwatch.fails
LOG=/home/imperator/hub-netz.log
FAILS=$(cat "$STATE" 2>/dev/null || echo 0)

if [ -n "$GW" ] && ping -4 -c 1 -W 2 "$GW" >/dev/null 2>&1; then
  [ "$FAILS" = 0 ] || echo "$(date '+%F %T') netwatch: Gateway $GW wieder da" >> "$LOG"
  echo 0 > "$STATE"
  exit 0
fi

FAILS=$((FAILS + 1))
echo "$FAILS" > "$STATE"

# Erst nach anderthalb Minuten eingreifen - ein Routerneustart dauert laenger
# als ein Messintervall, und eine Adressanforderung mittendrin bringt nichts.
if [ "$FAILS" -ge 20 ]; then
  echo "$(date '+%F %T') netwatch: seit $((FAILS * 30))s ohne Gateway - Neustart" >> "$LOG"
  /sbin/reboot
elif [ $((FAILS % 3)) -eq 0 ]; then
  echo "$(date '+%F %T') netwatch: Gateway ${GW:-keins} stumm ($FAILS) - neue Adresse anfordern" >> "$LOG"
  dhclient -r wlan0 >/dev/null 2>&1
  dhclient -4 wlan0 >/dev/null 2>&1
  echo "$(date '+%F %T') netwatch: danach $(ip -4 addr show wlan0 | grep -o 'inet [0-9.]*')" >> "$LOG"
fi
