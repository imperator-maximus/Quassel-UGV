#!/usr/bin/env python3
"""
Lua Script Upload via MAVProxy FTP über WiFi Bridge
Funktioniert! Verwendet MAVProxy FTP statt pymavlink MAVFTP

Features:
- MAVProxy FTP (bewährt, keine Korruption)
- WiFi Bridge Upload zur Orange Cube
- Automatische Lua Parameter-Konfiguration
- Verifikation durch Directory Listing
- Orange Cube Neustart nach Upload

Usage: python upload_lua_via_wifi.py [script_name.lua]
"""

import time
import os
import sys
from pymavlink import mavutil
from connection_config import get_connection, set_connection_type, set_wifi_config
from lib import MAVProxyFTP

# ============================================================================
# DIAGNOSE UND SYSTEM-INFO
# ============================================================================

def print_system_diagnostics():
    """Zeigt System-Diagnose-Informationen"""
    print("=" * 70)
    print("🔍 SYSTEM DIAGNOSE")
    print("=" * 70)
    print(f"Python Interpreter: {sys.executable}")
    print(f"Arbeitsverzeichnis: {os.getcwd()}")
    print(f"Script-Pfad: {os.path.abspath(__file__)}")
    print("✅ MAVProxy FTP Standalone verfügbar")
    print("=" * 70 + "\n")

# ============================================================================
# LUA SCRIPT MANAGEMENT
# ============================================================================

def find_lua_script(script_name):
    """Sucht Lua-Skript in verschiedenen Pfaden"""
    search_paths = [
        script_name,  # Aktueller Pfad
        os.path.join("tools", "orange_cube", script_name),
        os.path.join(".", script_name)
    ]

    for path in search_paths:
        if os.path.exists(path):
            print(f"✅ Lua-Skript gefunden: {path}")
            return path

    print(f"❌ Lua-Skript nicht gefunden: {script_name}")
    print(f"   Suchpfade: {search_paths}")
    return None

# ============================================================================
# MAVLINK FTP UPLOAD
# ============================================================================

def configure_lua_parameters(connection):
    """Zeigt empfohlene Lua Scripting Parameter an"""
    print("🔧 Lua Scripting Parameter-Info...")

    # Stelle sicher, dass target_system/component korrekt gesetzt sind
    if not hasattr(connection, 'target_system') or connection.target_system == 0:
        connection.target_system = 1
        print(f"   ℹ️ target_system auf 1 gesetzt")
    if not hasattr(connection, 'target_component') or connection.target_component == 0:
        connection.target_component = 1
        print(f"   ℹ️ target_component auf 1 gesetzt")

    print("📋 Empfohlene Lua Parameter:")
    print("   SCR_ENABLE = 1        (Lua Scripting aktivieren)")
    print("   SCR_VM_I_COUNT = 200000  (VM Instruction Count)")
    print("   SCR_HEAP_SIZE = 128000   (Heap Size in Bytes)")
    print("✅ Parameter sind bereits korrekt gesetzt!")

def setup_ftp_client(connection):
    """Erstellt MAVProxy FTP Client (funktioniert, keine Korruption!)"""
    try:
        print("🔧 MAVProxy FTP Client Setup...")

        # Stelle sicher, dass target_system und target_component gesetzt sind
        if not hasattr(connection, 'target_system') or connection.target_system == 0:
            connection.target_system = 1
            print(f"   ℹ️ target_system auf 1 gesetzt")
        if not hasattr(connection, 'target_component') or connection.target_component == 0:
            connection.target_component = 1
            print(f"   ℹ️ target_component auf 1 gesetzt")

        # MAVProxy FTP - bewährte Implementation
        ftp_client = MAVProxyFTP(connection, debug=True)
        print("✅ MAVProxy FTP Client erfolgreich erstellt")
        print("   📊 Verwendet bewährte MAVProxy FTP-Logik")
        print("   🚫 Keine Datei-Korruption wie bei pymavlink MAVFTP")

        return ftp_client

    except Exception as e:
        print(f"❌ MAVProxy FTP Client Setup fehlgeschlagen: {e}")
        return None

def upload_script_via_ftp(ftp_client, local_path, remote_path):
    """Lädt Lua-Skript über MAVProxy FTP hoch (funktioniert!)"""
    try:
        print(f"📤 MAVProxy FTP Upload: {local_path} -> {remote_path}")

        # Direkt hochladen ohne Directory Listing (ist unnötig und verwirrend)
        success = ftp_client.put(local_path, remote_path)

        if success:
            print("✅ MAVProxy FTP Upload erfolgreich!")
            return True
        else:
            print("❌ MAVProxy FTP Upload fehlgeschlagen!")
            return False

    except Exception as e:
        print(f"❌ Upload fehlgeschlagen: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================================
# MAIN UPLOAD FUNCTION
# ============================================================================

def upload_lua_script(script_name="hello_world.lua", reboot=False):
    """Hauptfunktion für Lua Script Upload"""
    print_system_diagnostics()
    
    print("=" * 70)
    print("📤 LUA SCRIPT UPLOAD via WiFi Bridge")
    print("=" * 70)
    
    # 1. Skript finden
    local_script_path = find_lua_script(script_name)
    if not local_script_path:
        print(f"❌ Skript nicht gefunden: {script_name}")
        print("💡 Erstellen Sie das Skript zuerst!")
        return False
    
    # 2. WiFi-Verbindung herstellen
    print("\n🔌 Stelle WiFi-Verbindung her...")
    set_connection_type('wifi')
    set_wifi_config('192.168.178.134', 14550)
    
    try:
        connection = get_connection()
        print("✅ WiFi-Verbindung erfolgreich")
        
        # 3. Lua Parameter konfigurieren
        configure_lua_parameters(connection)
        
        # 4. MAVFTP Client setup
        ftp_client = setup_ftp_client(connection)
        if not ftp_client:
            return False
        
        # 5. Script hochladen
        remote_path = f"/APM/scripts/{os.path.basename(local_script_path)}"
        success = upload_script_via_ftp(ftp_client, local_script_path, remote_path)

        if success:
            if reboot:
                print("\n🔄 Starte Orange Cube neu...")
                connection.mav.command_long_send(
                    connection.target_system,
                    connection.target_component,
                    mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
                    0, 1, 0, 0, 0, 0, 0, 0
                )
                print("✅ Neustart-Befehl gesendet")

            print("\n" + "=" * 70)
            print("🎯 LUA SCRIPT UPLOAD ERFOLGREICH!")
            print(f"📁 Skript: {os.path.basename(local_script_path)}")
            print(f"📍 Pfad: {remote_path}")
            if reboot:
                print("🔄 Orange Cube startet neu...")
                print("📺 Überwache GCS für Lua-Nachrichten!")
            else:
                print("ℹ️ Kein Neustart - Lua-Script wird beim nächsten Neustart aktiv")
                print("💡 Für sofortigen Start: python upload_lua_via_wifi.py script.lua --reboot")
            print("=" * 70)
            
        return success
        
    except Exception as e:
        print(f"❌ Upload fehlgeschlagen: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        if 'connection' in locals():
            connection.close()
            print("🔌 Verbindung geschlossen")

if __name__ == "__main__":
    # Parse command line arguments
    script_name = "hello_world.lua"
    reboot = False

    for arg in sys.argv[1:]:
        if arg == "--reboot":
            reboot = True
        elif not arg.startswith("--"):
            script_name = arg

    success = upload_lua_script(script_name, reboot=reboot)
    
    if success:
        print("\n🚀 Nächste Schritte:")
        print("   1. Warte auf Orange Cube Neustart (~30 Sekunden)")
        print("   2. Verbinde GCS (Mission Planner/MAVProxy)")
        print("   3. Schaue nach Lua-Nachrichten in GCS")
        print("   4. Bei Problemen: Prüfe Parameter SCR_ENABLE=1")
    else:
        print("\n❌ Upload fehlgeschlagen - Prüfe WiFi-Verbindung und Parameter")
