#!/usr/bin/env bash
#
# usb_gadget_setup.sh – USB-Gadget (CDC-ECM, g_ether via configfs/libcomposite)
# auf dem Orange Pi Zero 2W einrichten.
#
# Ergebnis: Punkt-zu-Punkt-Ethernet-Link "usb0" zum Raspberry Pi (USB-Host),
# Geraete-Seite statisch 10.66.0.1/24. Der SensorHub-Telemetrie-Endpunkt ist
# darueber als http://10.66.0.1/api/telemetry erreichbar (siehe
# raspberry_pi/USB_GADGET_LINK.md).
#
# Aufruf: usb_gadget_setup.sh [start|stop|status]   (Default: start)
#
# Ueberschreibbar per Env:
#   UDC        Name des USB Device Controllers (Default: erster Eintrag aus
#              /sys/class/udc, z.B. "musb-hdrc.1.auto" oder "5200000.usb")
#   IFACE      Erwarteter Interface-Name (Default: usb0; wird sonst anhand der
#              Device-MAC automatisch gesucht)
#   DEV_ADDR   MAC der Geraete-Seite   (Default: 02:11:22:33:44:01)
#   HOST_ADDR  MAC der Host-Seite      (Default: 02:11:22:33:44:02)
#   GADGET_IP  Statische IP            (Default: 10.66.0.1/24)
#
# Voraussetzung: Der OTG-USB-Controller muss im Device-Tree auf
# dr_mode = "peripheral" (oder "otg") stehen und /sys/class/udc darf nicht
# leer sein. Auf Armbian/DietPi ggf. das Overlay "usb-otg" aktivieren
# (armbian-config bzw. /boot/armbianEnv.txt bzw. dietpi-config) und neu starten.
# Schnellcheck:  ls /sys/class/udc   -> muss mindestens einen Eintrag liefern.
#
set -euo pipefail

GADGET_NAME="sensorhub"
GADGET_DIR="/sys/kernel/config/usb_gadget/${GADGET_NAME}"

# Unverfaengliche, oeffentlich dokumentierte IDs:
# 0x1d6b = Linux Foundation, 0x0104 = Multifunction Composite Gadget (g_ether).
ID_VENDOR="0x1d6b"
ID_PRODUCT="0x0104"

UDC="${UDC:-}"
IFACE="${IFACE:-usb0}"
DEV_ADDR="${DEV_ADDR:-02:11:22:33:44:01}"   # lokal administriert (Bit 1 im 1. Oktett)
HOST_ADDR="${HOST_ADDR:-02:11:22:33:44:02}" # erscheint als usb0-MAC am Raspberry Pi
GADGET_IP="${GADGET_IP:-10.66.0.1/24}"

log()  { echo "[usb-gadget] $*"; }
warn() { echo "[usb-gadget] WARNUNG: $*" >&2; }
die()  { echo "[usb-gadget] FEHLER: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "muss als root laufen (systemd-Unit oder sudo)."

mount_configfs() {
  if ! mountpoint -q /sys/kernel/config; then
    log "mounte configfs auf /sys/kernel/config"
    mount -t configfs none /sys/kernel/config \
      || die "configfs nicht mountbar (Kernel ohne CONFIG_CONFIGFS_FS?)"
  fi
}

load_libcomposite() {
  if [ ! -d /sys/kernel/config/usb_gadget ]; then
    log "lade Modul libcomposite"
    modprobe libcomposite \
      || die "libcomposite nicht ladbar (Kernel ohne USB-Gadget-Support?)"
  fi
  # Damit das Modul nach jedem Boot da ist, einmalig dokumentieren:
  #   echo libcomposite | sudo tee /etc/modules-load.d/libcomposite.conf
}

select_udc() {
  if [ -n "${UDC}" ]; then
    [ -e "/sys/class/udc/${UDC}" ] \
      || die "UDC '${UDC}' existiert nicht (siehe: ls /sys/class/udc)"
    return
  fi
  local entries
  entries=$(ls /sys/class/udc 2>/dev/null || true)
  if [ -z "${entries}" ]; then
    warn "/sys/class/udc ist leer – kein USB-Device-Controller im Peripheral-Modus."
    warn "Device-Tree pruefen: OTG-Controller braucht dr_mode = \"peripheral\"/\"otg\"."
    warn "Auf Armbian/DietPi das Overlay 'usb-otg' aktivieren (armbian-config /"
    warn "/boot/armbianEnv.txt / dietpi-config), dann neu starten."
    die "kein UDC verfuegbar"
  fi
  UDC=$(echo "${entries}" | head -n1)
  log "verwende UDC: ${UDC} (per Env UDC=... ueberschreibbar)"
}

teardown_gadget() {
  [ -d "${GADGET_DIR}" ] || return 0
  log "entferne vorhandenes Gadget ${GADGET_NAME}"
  echo "" > "${GADGET_DIR}/UDC" 2>/dev/null || true
  rm -f "${GADGET_DIR}/configs/c.1/ecm.usb0"
  rmdir "${GADGET_DIR}/configs/c.1/strings/0x409" 2>/dev/null || true
  rmdir "${GADGET_DIR}/configs/c.1"
  rmdir "${GADGET_DIR}/functions/ecm.usb0"
  rmdir "${GADGET_DIR}/strings/0x409"
  rmdir "${GADGET_DIR}"
}

create_gadget() {
  log "lege Gadget ${GADGET_NAME} an (CDC-ECM, ${ID_VENDOR}:${ID_PRODUCT})"
  mkdir -p "${GADGET_DIR}"
  cd "${GADGET_DIR}"

  echo "${ID_VENDOR}"  > idVendor
  echo "${ID_PRODUCT}" > idProduct
  echo "0x0200" > bcdUSB

  mkdir -p strings/0x409
  echo "Quassel UGV"            > strings/0x409/manufacturer
  echo "UGV SensorHub ECM Link" > strings/0x409/product
  echo "ugv-sensorhub-usb0"     > strings/0x409/serialnumber

  mkdir -p configs/c.1/strings/0x409
  echo "ECM"   > configs/c.1/strings/0x409/configuration
  echo 120     > configs/c.1/MaxPower

  # Feste MACs, damit Host und Geraet nach jedem Boot identisch aussehen
  # (udev-Regel am Raspberry Pi matcht auf HOST_ADDR).
  mkdir -p functions/ecm.usb0
  echo "${DEV_ADDR}"  > functions/ecm.usb0/dev_addr
  echo "${HOST_ADDR}" > functions/ecm.usb0/host_addr

  ln -s functions/ecm.usb0 configs/c.1/

  echo "${UDC}" > UDC
  log "Gadget an UDC '${UDC}' gebunden"
}

find_iface() {
  # Der ECM-Treiber legt das Netz-Interface erst nach dem Bind an.
  local i name addr
  for i in $(seq 1 10); do
    if [ -d "/sys/class/net/${IFACE}" ]; then
      return 0
    fi
    for name in /sys/class/net/*/; do
      name="${name%/}"; name="${name##*/}"
      addr=$(cat "/sys/class/net/${name}/address" 2>/dev/null || true)
      if [ "${addr}" = "${DEV_ADDR}" ]; then
        IFACE="${name}"
        return 0
      fi
    done
    sleep 1
  done
  return 1
}

configure_iface() {
  find_iface || die "Netz-Interface des Gadgets nicht gefunden (erwartet ${IFACE} oder MAC ${DEV_ADDR})"
  log "konfiguriere ${IFACE} mit ${GADGET_IP}"
  ip link set "${IFACE}" up
  if ip addr show dev "${IFACE}" | grep -qF "inet ${GADGET_IP%/*}/"; then
    log "IP ${GADGET_IP} bereits gesetzt – nichts zu tun"
  else
    ip addr flush dev "${IFACE}"
    ip addr add "${GADGET_IP}" dev "${IFACE}"
  fi
}

cmd_start() {
  mount_configfs
  load_libcomposite
  select_udc
  teardown_gadget   # idempotent: sauber neu aufbauen statt halben Zustand zu duplizieren
  create_gadget
  configure_iface
  log "fertig: ${IFACE} = ${GADGET_IP}, Host-Seite 10.66.0.2 (siehe raspberry_pi/USB_GADGET_LINK.md)"
}

cmd_stop() {
  [ -d "${GADGET_DIR}" ] || { log "Gadget nicht angelegt – nichts zu tun"; return 0; }
  echo "" > "${GADGET_DIR}/UDC" 2>/dev/null || true
  log "Gadget vom UDC geloest (Konfiguration bleibt in configfs)"
}

case "${1:-start}" in
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  status)
    ls -l "${GADGET_DIR}/UDC" 2>/dev/null && cat "${GADGET_DIR}/UDC" \
      || die "Gadget nicht angelegt"
    ip addr show dev "${IFACE}" 2>/dev/null || true
    ;;
  *) die "Usage: $0 [start|stop|status]" ;;
esac
