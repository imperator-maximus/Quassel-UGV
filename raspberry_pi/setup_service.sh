#!/bin/bash
# Setup-Script für DroneCAN ESC Service

echo "🚀 DroneCAN ESC Service Setup"
echo "=============================="

# 1. pigpiod Service aktivieren
echo "📡 pigpiod Service aktivieren..."
sudo systemctl enable pigpiod
sudo systemctl start pigpiod

# Status prüfen
if sudo systemctl is-active --quiet pigpiod; then
    echo "✅ pigpiod läuft"
else
    echo "❌ pigpiod Fehler"
    sudo systemctl status pigpiod
    exit 1
fi

# 2. Service-Datei kopieren
echo "📋 Service-Datei installieren..."
sudo cp dronecan-esc.service /etc/systemd/system/

# 3. Service aktivieren
echo "⚙️ DroneCAN ESC Service aktivieren..."
sudo systemctl daemon-reload
sudo systemctl enable dronecan-esc.service
sudo systemctl start dronecan-esc.service

# 4. Status prüfen
echo "🔍 Service-Status:"
sudo systemctl status dronecan-esc.service --no-pager

# 5. Aliases hinzufügen
echo "🔧 Praktische Aliases hinzufügen..."
if ! grep -q "alias esc-stop" ~/.bashrc; then
    echo "" >> ~/.bashrc
    echo "# DroneCAN ESC Service Aliases" >> ~/.bashrc
    echo 'alias esc-stop="sudo systemctl stop dronecan-esc.service"' >> ~/.bashrc
    echo 'alias esc-start="sudo systemctl start dronecan-esc.service"' >> ~/.bashrc
    echo 'alias esc-restart="sudo systemctl restart dronecan-esc.service"' >> ~/.bashrc
    echo 'alias esc-status="sudo systemctl status dronecan-esc.service"' >> ~/.bashrc
    echo 'alias esc-logs="sudo journalctl -u dronecan-esc.service -f"' >> ~/.bashrc
    echo 'alias esc-logs-tail="sudo journalctl -u dronecan-esc.service -n 50"' >> ~/.bashrc
    echo "✅ Aliases hinzugefügt"
else
    echo "ℹ️ Aliases bereits vorhanden"
fi

echo ""
echo "🎯 Setup abgeschlossen!"
echo ""
echo "📋 Verfügbare Befehle (nach 'source ~/.bashrc'):"
echo "   esc-stop      - Service stoppen"
echo "   esc-start     - Service starten"
echo "   esc-restart   - Service neu starten"
echo "   esc-status    - Service-Status anzeigen"
echo "   esc-logs      - Live-Logs anzeigen"
echo "   esc-logs-tail - Letzte 50 Log-Zeilen"
echo ""
echo "🔄 Aliases aktivieren:"
echo "   source ~/.bashrc"
echo ""
echo "🧪 Für Tests:"
echo "   esc-stop"
echo "   sudo python3 dronecan_esc_controller.py --pwm"
echo "   esc-start"
