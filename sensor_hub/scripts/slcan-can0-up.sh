#!/bin/sh
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  /usr/sbin/ip link set up dev can0 txqueuelen 1000 && exit 0
  sleep 1
done
exit 1
