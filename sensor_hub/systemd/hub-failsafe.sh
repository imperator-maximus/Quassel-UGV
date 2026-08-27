#!/bin/sh
# Rueckfallschalter, der den Neustart ueberlebt: Ist der Huawei-Block noch
# freigegeben, wenn dieser Dienst zehn Minuten nach dem Start anlaeuft, hat
# sich offenbar niemand gemeldet - dann zurueck ins alte WLAN.
#
# Die Pruefung am Anfang ist wichtig: Ohne sie wuerde der Dienst nach dem
# Rueckfall beim naechsten Start erneut neu starten, und das endlos.
C=/etc/wpa_supplicant/wpa_supplicant.conf
if sed -n '/HUAWEI-E5180-E406/,/}/p' "$C" | grep -q 'disabled=1'; then
  exit 0
fi
python3 - <<'PY'
p = '/etc/wpa_supplicant/wpa_supplicant.conf'
key = 'HUAWEI-E5180-E406'
s = open(p, encoding='utf-8').read()
head, rest = s.split(key, 1)
block, tail = rest.split('}', 1)
open(p, 'w', encoding='utf-8').write(head + key + block + '\tdisabled=1\n}' + tail)
PY
echo "=== Rueckfall ausgeloest $(date '+%F %T')" >> /home/imperator/hub-netz.log
/sbin/reboot
