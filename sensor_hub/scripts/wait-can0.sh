#!/bin/sh
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  /usr/sbin/ip link show can0 >/dev/null 2>&1 && exit 0
  sleep 1
done
echo can0 not ready >&2
exit 1
