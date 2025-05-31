#!/usr/bin/env python3
"""
Orange Cube Connection Demo
Zeigt die neue globale Verbindungskonfiguration in Aktion

Demonstriert:
- Automatische COM/WiFi Erkennung
- Manuelle Verbindungstyp-Auswahl
- Konfiguration zur Laufzeit
- Integration in bestehende Scripts
"""

import sys
from connection_config import (
    get_connection, get_connection_info, 
    set_connection_type, set_com_config, set_wifi_config
)

def demo_auto_connection():
    """Demo: Automatische Verbindungserkennung"""
    print("🔍 Demo: Automatische Verbindungserkennung")
    print("-" * 50)
    
    set_connection_type('auto')
    
    try:
        connection = get_connection()
        print("🎯 Auto-Connection erfolgreich!")
        
        # Kurzer Test
        connection.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0, 0, 0
        )
        
        connection.close()
        return True
    except Exception as e:
        print(f"❌ Auto-Connection fehlgeschlagen: {e}")
        return False

def demo_manual_wifi():
    """Demo: Manuelle WiFi Verbindung"""
    print("\n📶 Demo: Manuelle WiFi Verbindung")
    print("-" * 50)
    
    set_connection_type('wifi')
    set_wifi_config('192.168.178.101', 14550)
    
    try:
        connection = get_connection()
        print("🎯 WiFi Connection erfolgreich!")
        connection.close()
        return True
    except Exception as e:
        print(f"❌ WiFi Connection fehlgeschlagen: {e}")
        return False

def demo_manual_com():
    """Demo: Manuelle COM Verbindung"""
    print("\n🔌 Demo: Manuelle COM Verbindung")
    print("-" * 50)
    
    set_connection_type('com')
    set_com_config('COM4', 115200)
    
    try:
        connection = get_connection()
        print("🎯 COM Connection erfolgreich!")
        connection.close()
        return True
    except Exception as e:
        print(f"❌ COM Connection fehlgeschlagen: {e}")
        return False

def show_config():
    """Zeigt aktuelle Konfiguration"""
    print("\n📋 Aktuelle Konfiguration:")
    print("-" * 30)
    config = get_connection_info()
    for key, value in config.items():
        print(f"   {key}: {value}")

def interactive_demo():
    """Interaktive Demo mit Benutzerauswahl"""
    print("🎮 Interaktive Connection Demo")
    print("=" * 50)
    
    while True:
        print("\nWähle Verbindungstyp:")
        print("1. Auto-Detection (empfohlen)")
        print("2. WiFi Bridge")
        print("3. COM Port")
        print("4. Konfiguration anzeigen")
        print("5. Beenden")
        
        choice = input("\nEingabe (1-5): ").strip()
        
        if choice == '1':
            demo_auto_connection()
        elif choice == '2':
            demo_manual_wifi()
        elif choice == '3':
            demo_manual_com()
        elif choice == '4':
            show_config()
        elif choice == '5':
            print("👋 Demo beendet")
            break
        else:
            print("❌ Ungültige Eingabe")

def migration_example():
    """Zeigt wie bestehende Scripts migriert werden"""
    print("\n🔄 Migration Beispiel")
    print("=" * 50)
    print("VORHER (hardcoded COM4):")
    print("   connection = mavutil.mavlink_connection('COM4', baud=115200)")
    print("")
    print("NACHHER (flexible Verbindung):")
    print("   from connection_config import get_connection")
    print("   connection = get_connection()")
    print("")
    print("✅ Vorteile:")
    print("   • Automatische COM/WiFi Erkennung")
    print("   • Zentrale Konfiguration")
    print("   • Einfache Umschaltung zwischen Verbindungstypen")
    print("   • Keine Code-Änderungen in Scripts nötig")

def main():
    print("🔧 Orange Cube Connection Configuration Demo")
    print("=" * 60)
    print("Neue globale Verbindungskonfiguration für alle Orange Cube Scripts")
    print("=" * 60)
    
    # Zeige Migration Beispiel
    migration_example()
    
    # Zeige aktuelle Konfiguration
    show_config()
    
    # Frage ob interaktive Demo gewünscht
    print("\n❓ Möchtest du die interaktive Demo starten? (j/n)")
    response = input().strip().lower()
    
    if response in ['j', 'ja', 'y', 'yes']:
        interactive_demo()
    else:
        print("\n🚀 Quick Test mit Auto-Detection:")
        success = demo_auto_connection()
        
        if success:
            print("\n✅ Connection Config funktioniert!")
            print("🎯 Nächste Schritte:")
            print("   1. Teste: python monitor_pwm_before_can.py")
            print("   2. Migriere andere Scripts nach Bedarf")
        else:
            print("\n⚠️ Verbindung fehlgeschlagen")
            print("💡 Prüfe:")
            print("   • Orange Cube eingeschaltet?")
            print("   • WiFi Bridge erreichbar?")
            print("   • COM4 verfügbar?")

if __name__ == "__main__":
    # Import hier um Circular Import zu vermeiden
    from pymavlink import mavutil
    main()
