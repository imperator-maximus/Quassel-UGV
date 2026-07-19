#!/bin/bash
# Quassel UGV Motor Controller v2.0 - Installation Script

set -e

echo "============================================================"
echo "Quassel UGV Motor Controller v2.0 - Installation"
echo "============================================================"

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Funktionen
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ️  $1${NC}"
}

# Root-Check
if [ "$EUID" -eq 0 ]; then
    print_error "Bitte NICHT als root ausführen!"
    exit 1
fi

# 1. System-Update
print_info "System-Update..."
sudo apt-get update

# 2. Python-Dependencies installieren
print_info "Installiere Python-Dependencies..."
pip3 install --upgrade pip
pip3 install -r motor_controller/requirements.txt
print_success "Python-Dependencies installiert"

# 3. pigpiod installieren und aktivieren
print_info "Installiere pigpiod..."
sudo apt-get install -y pigpio python3-pigpio
sudo systemctl enable pigpiod
sudo systemctl start pigpiod
print_success "pigpiod installiert und gestartet"

# 4. CAN-Tools installieren
print_info "Installiere CAN-Tools..."
sudo apt-get install -y can-utils
print_success "CAN-Tools installiert"

# 5. Verzeichnis erstellen
print_info "Erstelle Verzeichnisstruktur..."
mkdir -p /home/$USER/motor_controller
cp -r motor_controller/* /home/$USER/motor_controller/
print_success "Dateien kopiert nach /home/$USER/motor_controller/"

# 6. Konfiguration erstellen
print_info "Erstelle Konfigurationsdatei..."
if [ ! -f /home/$USER/motor_controller/config.yaml ]; then
    cp /home/$USER/motor_controller/config.yaml.example \
       /home/$USER/motor_controller/config.yaml
    print_success "config.yaml erstellt"
else
    print_info "config.yaml existiert bereits (nicht überschrieben)"
fi

# 7. Berechtigungen setzen
print_info "Setze Berechtigungen..."
chmod +x /home/$USER/motor_controller/main.py
print_success "Berechtigungen gesetzt"

# 8. Systemd-Services installieren
print_info "Installiere Systemd-Services..."
sudo cp motor_controller_v2.service /etc/systemd/system/motor-controller-v2.service
sudo cp can-interface.service /etc/systemd/system/can-interface.service

# Service-Datei anpassen (User ersetzen)
sudo sed -i "s/User=nicolay/User=$USER/g" /etc/systemd/system/motor-controller-v2.service
sudo sed -i "s/Group=nicolay/Group=$USER/g" /etc/systemd/system/motor-controller-v2.service
sudo sed -i "s|WorkingDirectory=/home/nicolay|WorkingDirectory=/home/$USER|g" /etc/systemd/system/motor-controller-v2.service
sudo sed -i "s|/home/nicolay/motor_controller|/home/$USER/motor_controller|g" /etc/systemd/system/motor-controller-v2.service

sudo systemctl daemon-reload
sudo systemctl enable can-interface.service
print_success "Systemd-Services installiert"

# 9. Altes InnoMaker/MCP2515-Overlay deaktivieren
print_info "Deaktiviere alte MCP2515 Device-Tree-Einträge..."
for boot_config in /boot/firmware/config.txt /boot/config.txt; do
    if [ -f "$boot_config" ]; then
        sudo sed -i -E 's|^([[:space:]]*dtoverlay=mcp2515-can.*)|# \1|' "$boot_config"
    fi
done
print_success "USB-CAN benötigt kein MCP2515 Device-Tree-Overlay"

# 10. USB-CAN-Interface aktivieren
if ip link show can0 &> /dev/null; then
    print_info "Aktiviere USB-CAN-Interface..."
    sudo systemctl restart can-interface.service
    print_success "USB-CAN als can0 aktiviert (250 kbit/s)"
else
    print_error "USB-CAN-Interface can0 nicht verfügbar"
    print_info "USB-Adapter und gs_usb-Treiber mit lsusb und dmesg prüfen"
fi

# 11. Test-Ausführung
print_info "Teste Installation..."
cd /home/$USER/motor_controller
if python3 -c "import motor_controller; print('Import OK')"; then
    print_success "Import-Test erfolgreich"
else
    print_error "Import-Test fehlgeschlagen"
fi

# 12. Zusammenfassung
echo ""
echo "============================================================"
echo "Installation abgeschlossen!"
echo "============================================================"
echo ""
echo "Nächste Schritte:"
echo ""
echo "1. Konfiguration anpassen:"
echo "   nano /home/$USER/motor_controller/config.yaml"
echo ""
echo "2. Manueller Test:"
echo "   cd /home/$USER/motor_controller"
echo "   python3 -m motor_controller.main --config config.yaml"
echo ""
echo "3. Service aktivieren:"
echo "   sudo systemctl enable motor-controller-v2.service"
echo "   sudo systemctl start motor-controller-v2.service"
echo ""
echo "4. Status prüfen:"
echo "   sudo systemctl status motor-controller-v2.service"
echo ""
echo "5. Logs anzeigen:"
echo "   sudo journalctl -u motor-controller-v2.service -f"
echo ""
echo "6. Web-Interface:"
echo "   http://$(hostname)/api/status"
echo ""
echo "============================================================"

# USB-CAN-Check
if ! ip link show can0 &> /dev/null; then
    echo ""
    print_info "⚠️  USB-CAN-Adapter wurde nicht als can0 erkannt"
fi
