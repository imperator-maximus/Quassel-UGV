#!/bin/bash

# Quassel UGV - Sensor Hub MOTD Script (raspberryzero)
# Zeigt Service-Status und Autostart-Konfiguration beim SSH-Login

# Farben
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Header
echo -e "${BOLD}${BLUE}"
echo "👑 ═══════════════════════════════════════════════════════════════ 👑"
echo "   📡  Quassel UGV - Sensor Hub (raspberryzero)  📡"
echo "👑 ═══════════════════════════════════════════════════════════════ 👑"
echo -e "${NC}"

# Funktion: Service-Status prüfen
check_service() {
    local service_name=$1
    local display_name=$2
    
    # Status prüfen
    if systemctl is-active --quiet "$service_name"; then
        status="${GREEN}● Running${NC}"
    else
        status="${RED}● Stopped${NC}"
    fi
    
    # Autostart prüfen
    if systemctl is-enabled --quiet "$service_name" 2>/dev/null; then
        autostart="${GREEN}✓ Enabled${NC}"
    else
        autostart="${RED}✗ Disabled${NC}"
    fi
    
    echo -e "  ${BOLD}${display_name}:${NC}"
    echo -e "    Status:    $status"
    echo -e "    Autostart: $autostart"
}

# Service Management Commands
echo -e "${BOLD}${YELLOW}📋 Sensor Hub Service:${NC}"
echo ""

# Sensor Hub
check_service "sensor-hub" "Sensor Hub"
echo -e "    ${BLUE}Status:${NC}   sudo systemctl status sensor-hub"
echo -e "    ${BLUE}Stop:${NC}     sudo systemctl stop sensor-hub"
echo -e "    ${BLUE}Start:${NC}    sudo systemctl start sensor-hub"
echo -e "    ${BLUE}Restart:${NC}  sudo systemctl restart sensor-hub"
echo -e "    ${BLUE}Logs:${NC}     sudo journalctl -u sensor-hub -f"
echo ""

# Enable/Disable Autostart
echo -e "${BOLD}${YELLOW}🔧 Enable/Disable Autostart:${NC}"
echo -e "  ${BLUE}Enable:${NC}  sudo systemctl enable sensor-hub"
echo -e "  ${BLUE}Disable:${NC} sudo systemctl disable sensor-hub"
echo ""

# Debugging (ohne Service)
echo -e "${BOLD}${YELLOW}🐛 Debugging (without service):${NC}"
echo -e "  cd /home/nicolay && sudo python3 -m sensor_hub.main --config sensor_hub/config.yaml"
echo ""

# Footer
echo -e "${BOLD}${BLUE}"
echo "👑 ═══════════════════════════════════════════════════════════════ 👑"
echo -e "${NC}"

