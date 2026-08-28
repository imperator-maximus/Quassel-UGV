#!/bin/bash

# Installation der Web-Interface Dependencies für DroneCAN ESC Controller
# Raspberry Pi 3 - UGV DroneCAN Controller

echo "🌐 Installation der Web-Interface Dependencies..."
echo "=================================================="

# System-Update (optional)
read -p "System-Update durchführen? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "📦 System-Update..."
    sudo apt update && sudo apt upgrade -y
fi

# Python3 und pip sicherstellen
echo "🐍 Python3 und pip prüfen..."
sudo apt install -y python3 python3-pip

# Flask und SocketIO installieren
echo "🌐 Flask und SocketIO installieren..."
pip3 install flask flask-socketio

# Eventlet für bessere Performance (optional aber empfohlen)
echo "⚡ Eventlet für bessere WebSocket-Performance..."
pip3 install eventlet

# Prüfung der Installation
echo ""
echo "✅ Installation abgeschlossen!"
echo ""
echo "Installierte Pakete:"
pip3 list | grep -E "(Flask|flask-socketio|eventlet)"

echo ""
echo "🚀 Web-Interface kann jetzt gestartet werden mit:"
echo "   python3 -m motor_controller.main --config config.yaml"
echo ""
echo "📱 Zugriff über Browser:"
echo "   http://raspberrycan:5000"
echo "   http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "🔧 Weitere Optionen:"
echo "   --web-port 8080    # Anderen Port verwenden"
echo "   --quiet            # Weniger Ausgaben"
echo ""
