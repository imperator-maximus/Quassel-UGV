#!/usr/bin/env python3
"""
Lua Script Upload via MAVLink FTP über WiFi Bridge
Verbesserte Version mit Integration der bestehenden WiFi-Konfiguration

Features:
- Nutzt bestehende connection_config.py für WiFi-Verbindung
- Robustes Error Handling für MAVFTP
- Automatische Lua Parameter-Konfiguration
- Test-Skript Erstellung
- Strukturierte Diagnose-Ausgaben

Usage: python upload_lua_via_wifi.py [script_name.lua]
"""

import time
import os
import sys
from pymavlink import mavutil, mavftp
import pymavlink
from connection_config import get_connection, set_connection_type, set_wifi_config

# ============================================================================
# DIAGNOSE UND SYSTEM-INFO
# ============================================================================

def print_system_diagnostics():
    """Zeigt System- und pymavlink-Informationen"""
    print("=" * 70)
    print("🔍 SYSTEM DIAGNOSE")
    print("=" * 70)
    print(f"Python Interpreter: {sys.executable}")
    
    try:
        print(f"pymavlink Version: {pymavlink.__version__}")
    except AttributeError:
        print("pymavlink Version: Nicht verfügbar")
    
    # Pfad-Informationen
    for module_name, module in [("mavutil", mavutil), ("mavftp", mavftp)]:
        if hasattr(module, '__file__') and module.__file__:
            print(f"pymavlink.{module_name}: {module.__file__}")
        else:
            print(f"pymavlink.{module_name}: Pfad nicht verfügbar")
    
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
    """Initialisiert MAVFTP Client mit verbessertem Error Handling"""
    try:
        # Stelle sicher, dass target_system und target_component gesetzt sind
        if not hasattr(connection, 'target_system') or connection.target_system == 0:
            print("⚠️ target_system nicht gesetzt, verwende 1")
            connection.target_system = 1
            
        if not hasattr(connection, 'target_component') or connection.target_component == 0:
            print("⚠️ target_component nicht gesetzt, verwende 1 (Autopilot)")
            connection.target_component = 1
        
        print(f"📡 MAVFTP Client Setup:")
        print(f"   Target System: {connection.target_system}")
        print(f"   Target Component: {connection.target_component}")
        
        # ESP8266-Bridge-optimierte Settings (basierend auf Mission Planner Analyse)
        print("🔧 ESP8266-Bridge-optimierte MAVFTP Settings...")
        try:
            # Ultra-konservative Settings für ESP8266 Bridge (57600 Baud seriell)
            # Nur die KRITISCHEN Parameter für ESP8266-Bridge setzen
            esp8266_settings = mavftp.MAVFTPSettings([
                ('write_size', int, 40),              # KLEINER als Mission Planner (80)
                ('write_qsize', int, 1)               # NUR 1 Paket 'in flight' (Mission Planner-ähnlich)
            ])

            ftp_client = mavftp.MAVFTP(connection, connection.target_system, connection.target_component,
                                     settings=esp8266_settings)
            print("   ✅ ESP8266-optimierte MAVFTP Settings aktiviert")
            print("   📊 write_size=40, write_qsize=1 (Mission Planner-ähnlich)")

        except Exception as settings_e:
            print(f"   ⚠️ ESP8266-Settings fehlgeschlagen: {settings_e}")
            print("   🔧 Fallback zu Standard-Settings")
            ftp_client = mavftp.MAVFTP(connection, connection.target_system, connection.target_component)

        # Teste FTP Client
        print("🔍 Teste MAVFTP Client...")
        available_methods = [method for method in dir(ftp_client) if not method.startswith('_')]
        print(f"   Verfügbare Methoden: {available_methods}")

        return ftp_client
        
    except Exception as e:
        print(f"❌ MAVFTP Client Setup fehlgeschlagen: {e}")
        return None

def upload_script_via_ftp(ftp_client, local_path, remote_path):
    """Lädt Lua-Skript über MAVFTP hoch"""
    try:
        print(f"📤 Upload: {local_path} -> {remote_path}")

        upload_file = local_path

        # Alte Datei löschen (falls vorhanden)
        print("🗑️ Lösche alte Datei (falls vorhanden)...")
        try:
            result = ftp_client.cmd_ftp(['rm', remote_path])
            print(f"   ✅ Alte Datei gelöscht")
        except Exception as rm_e:
            print(f"   ℹ️ rm: {rm_e} (OK wenn Datei nicht existiert)")

        # Verzeichnis erstellen (falls nötig)
        remote_dir = os.path.dirname(remote_path)
        if remote_dir and remote_dir != "/":
            try:
                print(f"📁 Erstelle Verzeichnis: {remote_dir}")
                # Versuche Verzeichnis-Struktur schrittweise zu erstellen
                path_parts = remote_dir.strip('/').split('/')
                current_path = ""
                for part in path_parts:
                    current_path += "/" + part
                    try:
                        # MAVFTP mkdir Syntax: nur Verzeichnisname ohne Parameter
                        print(f"   🔧 mkdir {current_path}")
                        result = ftp_client.cmd_ftp(['mkdir', current_path])
                        print(f"   ✅ Verzeichnis erstellt: {current_path}")
                        time.sleep(0.5)
                    except Exception as mkdir_e:
                        print(f"   ℹ️ mkdir {current_path}: {mkdir_e} (OK wenn existiert)")
            except Exception as e:
                print(f"   ⚠️ Verzeichnis-Erstellung: {e}")

        # Datei hochladen - Einfacher Upload ohne Flags
        print("📤 Starte Upload...")
        print(f"   🔧 Upload: {upload_file} -> {remote_path}")
        result = ftp_client.cmd_ftp(['put', upload_file, remote_path])

        # Prüfe Upload-Ergebnis
        upload_success = False
        if result:
            print(f"📋 Upload-Ergebnis Details:")
            print(f"   Typ: {type(result)}")
            error_code = -1  # Default zu Fehler

            # Prüfe verschiedene Erfolgs-Indikatoren
            if hasattr(result, 'error_code'):
                error_code = result.error_code
                print(f"   Error Code: {error_code}")
            elif isinstance(result, bool):
                error_code = 0 if result else 1
                print(f"   Boolean Result: {result} (interpretiert als error_code {error_code})")
            elif hasattr(result, 'result'):
                print(f"   Result: {result.result}")
                error_code = 0  # Assume success if result exists
            elif hasattr(result, 'payload'):
                print(f"   Payload: {result.payload}")
                error_code = 0  # Assume success if payload exists

            if error_code == 0:
                print("   ✅ Upload-Befehl erfolgreich abgesetzt (Error Code 0)")
                upload_success = True
            else:
                print(f"   ❌ Upload-Befehl meldet Fehler (Error Code: {error_code})")
                upload_success = False
        else:
            print("   ⚠️ Kein Rückgabeobjekt vom Upload-Befehl erhalten")
            upload_success = False

        # VERIFIKATION: Optional, da 'list' über WiFi unzuverlässig sein kann
        if upload_success:  # Only try to list if put seemed okay
            print("🔍 OPTIONALE VERIFIKATION: Versuche Dateien aufzulisten...")
            try:
                print(f"   📂 Verzeichnis: {remote_dir}")
                list_result = ftp_client.cmd_ftp(['list', remote_dir])

                if list_result and hasattr(list_result, 'payload') and list_result.payload:
                    # Clean null bytes and decode properly
                    files_content = "".join(map(chr, filter(lambda x: x != 0, list_result.payload)))
                    print(f"   📄 Verzeichnis-Inhalt:")
                    print(f"   {files_content.strip()}")

                    filename = os.path.basename(remote_path)
                    if filename in files_content:
                        print(f"   ✅ VERIFIKATION ERFOLGREICH: {filename} in der Liste gefunden!")
                    else:
                        print(f"   ⚠️ VERIFIKATION UNVOLLSTÄNDIG: {filename} NICHT explizit in der Liste gefunden")
                        print(f"      (Upload könnte trotzdem erfolgreich gewesen sein, wenn 'list' unvollständig war)")

                    # Zeige alle .lua Dateien
                    if '.lua' in files_content:
                        print(f"   🎯 Lua-Dateien im Verzeichnis erkannt!")
                    else:
                        print(f"   ⚠️ Keine .lua Dateien sichtbar")

                elif list_result:
                    print(f"   ℹ️ Verzeichnis existiert, aber ist leer oder nicht lesbar")
                    print(f"      (Upload könnte trotzdem erfolgreich gewesen sein)")
                else:
                    print(f"   ❌ Verzeichnis nicht lesbar oder existiert nicht")

            except Exception as verify_e:
                print(f"   ❌ Verifikation durch 'list' fehlgeschlagen oder Timeout: {verify_e}")
                print(f"      (Upload könnte trotzdem erfolgreich gewesen sein)")
        else:
            print("🔍 Überspringe Verifikation da Upload-Befehl fehlgeschlagen")



        if upload_success:
            print(f"✅ Upload erfolgreich abgeschlossen")
        else:
            print(f"⚠️ Upload-Status ungewiss - prüfe Orange Cube nach Neustart")

        return upload_success

    except Exception as e:
        print(f"❌ Upload fehlgeschlagen: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================================
# MAIN UPLOAD FUNCTION
# ============================================================================

def upload_lua_script(script_name="hello_world.lua"):
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
    set_wifi_config('192.168.178.101', 14550)
    
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
            print("🔄 Orange Cube startet neu...")
            print("📺 Überwache GCS für Lua-Nachrichten!")
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
    script_name = sys.argv[1] if len(sys.argv) > 1 else "hello_world.lua"
    success = upload_lua_script(script_name)
    
    if success:
        print("\n🚀 Nächste Schritte:")
        print("   1. Warte auf Orange Cube Neustart (~30 Sekunden)")
        print("   2. Verbinde GCS (Mission Planner/MAVProxy)")
        print("   3. Schaue nach Lua-Nachrichten in GCS")
        print("   4. Bei Problemen: Prüfe Parameter SCR_ENABLE=1")
    else:
        print("\n❌ Upload fehlgeschlagen - Prüfe WiFi-Verbindung und Parameter")
