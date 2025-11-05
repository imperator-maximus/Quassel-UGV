#!/bin/bash

# Quassel UGV - System Health Check Script
# Prüft Autostart, Logs und System-Status

echo "👑 ═══════════════════════════════════════════════════════════════ 👑"
echo "   🔍  Quassel UGV - System Health Check  🔍"
echo "👑 ═══════════════════════════════════════════════════════════════ 👑"
echo ""

# Farben
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Hostname prüfen
HOSTNAME=$(hostname)
echo -e "${BOLD}${BLUE}System: ${HOSTNAME}${NC}"
echo ""

# Funktion: Service-Status und Autostart prüfen
check_service_full() {
    local service_name=$1
    local display_name=$2
    
    echo -e "${BOLD}${YELLOW}📋 ${display_name}:${NC}"
    
    # Status prüfen
    if systemctl is-active --quiet "$service_name"; then
        echo -e "  Status:    ${GREEN}● Running${NC}"
    else
        echo -e "  Status:    ${RED}● Stopped${NC}"
    fi
    
    # Autostart prüfen
    if systemctl is-enabled --quiet "$service_name" 2>/dev/null; then
        echo -e "  Autostart: ${GREEN}✓ Enabled${NC}"
    else
        echo -e "  Autostart: ${RED}✗ Disabled${NC}"
    fi
    
    # Letzte 5 Log-Zeilen
    echo -e "  ${BLUE}Last 5 log entries:${NC}"
    sudo journalctl -u "$service_name" -n 5 --no-pager | sed 's/^/    /'
    echo ""
}

# Prüfe welches System wir sind
if [ "$HOSTNAME" = "raspberrycan" ]; then
    echo -e "${BOLD}${GREEN}Motor Controller System${NC}"
    echo ""
    check_service_full "motor-controller-v2" "Motor Controller"
    
elif [ "$HOSTNAME" = "raspberryzero" ]; then
    echo -e "${BOLD}${GREEN}Sensor Hub System${NC}"
    echo ""
    check_service_full "sensor-hub" "Sensor Hub"
    
else
    echo -e "${RED}Unknown system: $HOSTNAME${NC}"
fi

# System-Uptime
echo -e "${BOLD}${YELLOW}⏱️  System Uptime:${NC}"
uptime -p
echo ""

# Letzte Reboots
echo -e "${BOLD}${YELLOW}🔄 Last 3 Reboots:${NC}"
last reboot -n 3 | head -3
echo ""

# Filesystem-Fehler prüfen
echo -e "${BOLD}${YELLOW}💾 Filesystem Errors:${NC}"
if sudo dmesg | grep -i "ext4.*error" > /dev/null; then
    echo -e "  ${RED}⚠️  EXT4 errors found!${NC}"
    sudo dmesg | grep -i "ext4.*error" | tail -5 | sed 's/^/    /'
else
    echo -e "  ${GREEN}✓ No filesystem errors${NC}"
fi
echo ""

# WiFi-Status
echo -e "${BOLD}${YELLOW}📡 WiFi Status:${NC}"
if iwconfig wlan0 2>/dev/null | grep -q "ESSID"; then
    ESSID=$(iwconfig wlan0 2>/dev/null | grep ESSID | awk -F'"' '{print $2}')
    SIGNAL=$(iwconfig wlan0 2>/dev/null | grep "Signal level" | awk -F'=' '{print $3}' | awk '{print $1}')
    echo -e "  SSID:   ${GREEN}${ESSID}${NC}"
    echo -e "  Signal: ${GREEN}${SIGNAL}${NC}"
else
    echo -e "  ${RED}✗ WiFi not connected${NC}"
fi
echo ""

# Speicherplatz
echo -e "${BOLD}${YELLOW}💿 Disk Usage:${NC}"
df -h / | tail -1 | awk '{print "  Root: " $3 " / " $2 " (" $5 " used)"}'
echo ""

# Temperatur
echo -e "${BOLD}${YELLOW}🌡️  CPU Temperature:${NC}"
if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
    TEMP=$(cat /sys/class/thermal/thermal_zone0/temp)
    TEMP_C=$((TEMP/1000))
    if [ $TEMP_C -gt 70 ]; then
        echo -e "  ${RED}${TEMP_C}°C (HOT!)${NC}"
    elif [ $TEMP_C -gt 60 ]; then
        echo -e "  ${YELLOW}${TEMP_C}°C (Warm)${NC}"
    else
        echo -e "  ${GREEN}${TEMP_C}°C (OK)${NC}"
    fi
else
    echo -e "  ${YELLOW}Temperature sensor not available${NC}"
fi
echo ""

echo "👑 ═══════════════════════════════════════════════════════════════ 👑"

