#!/bin/sh
# Schreibt nach jedem Start den Netzzustand in eine Datei, die den Neustart
# ueberlebt. Das Journal liegt hier im Arbeitsspeicher - beim ersten
# Umschaltversuch war deshalb hinterher nicht mehr nachvollziehbar, woran es
# gescheitert war.
L=/home/imperator/hub-netz.log
{
  echo "=== Start $(date '+%F %T')"
  wpa_cli -i wlan0 status 2>/dev/null | grep -E '^ssid=|^wpa_state='
  ip -4 addr show wlan0 | grep inet
  ip -4 route | head -2
  wpa_cli -i wlan0 list_networks 2>/dev/null
  echo
} >> "$L" 2>&1
