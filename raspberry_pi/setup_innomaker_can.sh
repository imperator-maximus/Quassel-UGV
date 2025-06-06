#!/bin/bash
#
# Innomaker RS485 CAN HAT Complete Setup Script
# Configures hardware and software for DroneCAN communication with Orange Cube
#
# Usage: sudo ./setup_innomaker_can.sh
#
# Hardware: Innomaker RS485 CAN HAT on Raspberry Pi
# Target: Orange Cube flight controller communication
#

set -e

echo "🔧 Innomaker RS485 CAN HAT Complete Setup"
echo "   Hardware + Software configuration for DroneCAN"
echo "   Target: Orange Cube flight controller"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run as root"
    echo "   Please run: sudo ./setup_innomaker_can.sh"
    exit 1
fi

echo "🔍 SYSTEM INFORMATION:"
echo

# System info
echo "📋 Raspberry Pi Model:"
cat /proc/device-tree/model 2>/dev/null || echo "Unknown"

echo "📋 OS Version:"
cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2

echo "📋 Kernel Version:"
uname -r

echo
echo "📦 INSTALLING REQUIRED PACKAGES:"

# Update package list
echo "📦 Updating package list..."
apt update

# Install CAN utilities
echo "📦 Installing CAN utilities..."
apt install -y can-utils

# Install Python packages
echo "📦 Installing Python CAN support..."
apt install -y python3-can python3-pip

# Install DroneCAN/MAVLink support
echo "📦 Installing DroneCAN/MAVLink packages..."
pip3 install pymavlink dronecan

echo "✅ All packages installed successfully"

echo
echo "🔧 HARDWARE CONFIGURATION:"

# Determine config file location
if [ -f "/boot/firmware/config.txt" ]; then
    CONFIG_FILE="/boot/firmware/config.txt"
elif [ -f "/boot/config.txt" ]; then
    CONFIG_FILE="/boot/config.txt"
else
    echo "❌ Boot configuration file not found"
    exit 1
fi

echo "📋 Using configuration file: $CONFIG_FILE"

# Check current configuration
if grep -q "InnoMaker.*CAN HAT" "$CONFIG_FILE"; then
    echo "✅ Innomaker CAN HAT configuration already present"
else
    echo "🔧 Configuring Innomaker RS485 CAN HAT..."
    
    # Create backup
    BACKUP_FILE="$CONFIG_FILE.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$CONFIG_FILE" "$BACKUP_FILE"
    echo "📄 Backup created: $BACKUP_FILE"
    
    # Remove any conflicting CAN configuration
    sed -i '/dtoverlay=mcp2515/d' "$CONFIG_FILE"
    sed -i '/dtoverlay=spi/d' "$CONFIG_FILE"
    sed -i '/dtparam=spi/d' "$CONFIG_FILE"
    sed -i '/dtoverlay=sc16is752/d' "$CONFIG_FILE"
    
    # Add Innomaker configuration
    cat >> "$CONFIG_FILE" << 'EOF'

# --- Innomaker RS485 CAN HAT Configuration ---
# Dual-chip HAT: RS485 (SC16IS752) + CAN (MCP2515)
# RS485 on spi0.0 (CS0/GPIO8), CAN on spi0.1 (CS1/GPIO7)

# Enable SPI
dtparam=spi=on

# RS485 chip on SPI0.0 (CS0)
dtoverlay=sc16is752-spi0,int_pin=24

# CAN chip on SPI0.1 (CS1) - uses mcp2515-can1 to avoid CS conflict
dtoverlay=mcp2515-can1,oscillator=16000000,interrupt=25
EOF
    
    echo "✅ Innomaker CAN HAT configuration applied"
    
    # Show what was added
    echo "📋 Configuration added:"
    grep -A10 "InnoMaker.*CAN HAT" "$CONFIG_FILE"
fi

echo
echo "🔄 REBOOT CHECK:"

# Check if reboot is needed
if dmesg | grep -q "mcp251x.*successfully initialized"; then
    echo "✅ CAN hardware already initialized"
    REBOOT_NEEDED=false
else
    echo "⚠️  Reboot required for hardware configuration to take effect"
    REBOOT_NEEDED=true
fi

if [ "$REBOOT_NEEDED" = true ]; then
    echo
    read -p "🔄 Reboot now to activate CAN hardware? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🔄 Rebooting in 3 seconds..."
        sleep 3
        reboot
    else
        echo "⚠️  Please reboot manually: sudo reboot"
        echo "   Then run this script again to complete setup"
        exit 0
    fi
fi

echo
echo "🔧 CAN INTERFACE SETUP:"

# Configure CAN interface
CAN_INTERFACE="can0"
CAN_BITRATE="1000000"  # 1 Mbps for DroneCAN

echo "📋 Configuring CAN interface: $CAN_INTERFACE"

# Check if CAN interface exists
if ip link show "$CAN_INTERFACE" &> /dev/null; then
    echo "✅ CAN interface $CAN_INTERFACE found"

    # Configure interface
    echo "🔧 Configuring CAN interface..."
    ip link set "$CAN_INTERFACE" down 2>/dev/null || true
    ip link set "$CAN_INTERFACE" type can bitrate "$CAN_BITRATE"
    ip link set "$CAN_INTERFACE" up

    echo "✅ CAN interface configured:"
    echo "   Interface: $CAN_INTERFACE"
    echo "   Bitrate: $CAN_BITRATE bps (1 Mbps)"
    echo "   Status: UP"

    # Show interface details
    echo "📋 Interface Status:"
    ip link show "$CAN_INTERFACE"

else
    echo "❌ CAN interface $CAN_INTERFACE not found"
    echo "   Hardware may not be properly configured"
    echo "   Check kernel messages: dmesg | grep -i mcp"
    exit 1
fi

echo
echo "🎉 SETUP COMPLETE!"
echo
echo "📋 Summary:"
echo "   ✅ Innomaker RS485 CAN HAT configured"
echo "   ✅ CAN interface $CAN_INTERFACE ready at $CAN_BITRATE bps"
echo "   ✅ Python CAN and DroneCAN packages installed"
echo
echo "🔗 HARDWARE CONNECTION:"
echo "   Connect Orange Cube CAN port to Innomaker HAT CAN0:"
echo "   • CAN_H ↔ CAN_H"
echo "   • CAN_L ↔ CAN_L"
echo "   • GND ↔ GND (optional)"
echo
echo "📝 TESTING:"
echo "   Monitor CAN traffic:     candump $CAN_INTERFACE"
echo "   Send test message:       cansend $CAN_INTERFACE 123#DEADBEEF"
echo "   Start DroneCAN monitor:  sudo python3 can_monitor.py"
echo
echo "🚀 Ready for DroneCAN communication with Orange Cube!"
