#!/bin/bash

# Quassel UGV - Motor Controller MOTD Script (raspberrycan)
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
echo "   🚗  Quassel UGV - Motor Controller (raspberrycan)  🚗"
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
echo -e "${BOLD}${YELLOW}📋 Motor Controller Service:${NC}"
echo ""

# Motor Controller
check_service "motor-controller-v2" "Motor Controller"
echo -e "    ${BLUE}Status:${NC}   sudo systemctl status motor-controller-v2"
echo -e "    ${BLUE}Stop:${NC}     sudo systemctl stop motor-controller-v2"
echo -e "    ${BLUE}Start:${NC}    sudo systemctl start motor-controller-v2"
echo -e "    ${BLUE}Restart:${NC}  sudo systemctl restart motor-controller-v2"
echo -e "    ${BLUE}Logs:${NC}     sudo journalctl -u motor-controller-v2 -f"
echo ""

# Enable/Disable Autostart
echo -e "${BOLD}${YELLOW}🔧 Enable/Disable Autostart:${NC}"
echo -e "  ${BLUE}Enable:${NC}  sudo systemctl enable motor-controller-v2"
echo -e "  ${BLUE}Disable:${NC} sudo systemctl disable motor-controller-v2"
echo ""

# Debugging (ohne Service)
echo -e "${BOLD}${YELLOW}🐛 Debugging (without service):${NC}"
echo -e "  cd /home/nicolay && sudo python3 -m motor_controller.main --config motor_controller/config.yaml"
echo ""

# Web Interface
echo -e "${BOLD}${YELLOW}🌐 Web Interface:${NC}"
echo -e "  ${BLUE}http://raspberrycan.local${NC} ${GREEN}(or IP address)${NC}"
echo ""

# Footer
echo -e "${BOLD}${BLUE}"
echo "👑 ═══════════════════════════════════════════════════════════════ 👑"
echo -e "${NC}"

