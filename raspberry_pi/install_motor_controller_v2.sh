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

# 8. Systemd-Service installieren
print_info "Installiere Systemd-Service..."
sudo cp motor_controller_v2.service /etc/systemd/system/motor-controller-v2.service

# Service-Datei anpassen (User ersetzen)
sudo sed -i "s/User=nicolay/User=$USER/g" /etc/systemd/system/motor-controller-v2.service
sudo sed -i "s/Group=nicolay/Group=$USER/g" /etc/systemd/system/motor-controller-v2.service
sudo sed -i "s|WorkingDirectory=/home/nicolay|WorkingDirectory=/home/$USER|g" /etc/systemd/system/motor-controller-v2.service
sudo sed -i "s|/home/nicolay/motor_controller|/home/$USER/motor_controller|g" /etc/systemd/system/motor-controller-v2.service

sudo systemctl daemon-reload
print_success "Systemd-Service installiert"

# 9. CAN-Interface konfigurieren
print_info "Konfiguriere CAN-Interface..."
if ! grep -q "dtoverlay=mcp2515-can1" /boot/config.txt; then
    echo "dtoverlay=mcp2515-can1,oscillator=16000000,interrupt=25" | sudo tee -a /boot/config.txt
    print_success "CAN-Interface in /boot/config.txt konfiguriert"
else
    print_info "CAN-Interface bereits konfiguriert"
fi

# 10. CAN-Interface aktivieren (falls bereits verfügbar)
if ip link show can0 &> /dev/null; then
    print_info "Aktiviere CAN-Interface..."
    sudo ip link set can0 down 2>/dev/null || true
    sudo ip link set can0 type can bitrate 1000000
    sudo ip link set can0 up
    print_success "CAN-Interface aktiviert (1 Mbps)"
else
    print_info "CAN-Interface nicht verfügbar (Reboot erforderlich)"
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

# Reboot-Check
if ! ip link show can0 &> /dev/null; then
    echo ""
    print_info "⚠️  CAN-Interface benötigt Reboot zur Aktivierung"
    echo ""
    read -p "Jetzt neu starten? (j/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Jj]$ ]]; then
        sudo reboot
    fi
fi

