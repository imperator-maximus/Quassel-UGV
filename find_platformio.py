#!/usr/bin/env python3
"""
PlatformIO Finder und Upload Helper
"""

import os
import subprocess
import sys
from pathlib import Path

def find_platformio():
    """Find PlatformIO installation"""
    print("🔍 Suche PlatformIO Installation...")
    
    # Common PlatformIO paths
    possible_paths = [
        os.path.expanduser("~/.platformio/penv/Scripts/platformio.exe"),
        os.path.expanduser("~/.platformio/penv/Scripts/pio.exe"),
        os.path.expanduser("~/AppData/Local/Programs/Python/Python*/Scripts/platformio.exe"),
        os.path.expanduser("~/AppData/Roaming/Python/Python*/Scripts/platformio.exe"),
        "C:/Users/" + os.getenv('USERNAME', '') + "/.platformio/penv/Scripts/platformio.exe",
        "C:/Users/" + os.getenv('USERNAME', '') + "/.platformio/penv/Scripts/pio.exe"
    ]
    
    # Check each path
    for path in possible_paths:
        if '*' in path:
            # Handle wildcard paths
            import glob
            matches = glob.glob(path)
            for match in matches:
                if os.path.exists(match):
                    print(f"✅ PlatformIO gefunden: {match}")
                    return match
        else:
            if os.path.exists(path):
                print(f"✅ PlatformIO gefunden: {path}")
                return path
    
    # Try to find via pip
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "show", "platformio"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ PlatformIO über pip gefunden")
            return "python -m platformio"
    except:
        pass
    
    print("❌ PlatformIO nicht gefunden")
    return None

def upload_firmware(pio_path):
    """Upload firmware using PlatformIO"""
    print("\n🚀 Starte Firmware Upload...")
    
    # Change to project directory
    project_dir = "beyond_robotics_working"
    if not os.path.exists(project_dir):
        print(f"❌ Projekt-Verzeichnis nicht gefunden: {project_dir}")
        return False
    
    os.chdir(project_dir)
    print(f"📁 Wechsle zu: {os.getcwd()}")
    
    # Prepare command
    if pio_path == "python -m platformio":
        cmd = [sys.executable, "-m", "platformio", "run", "--target", "upload"]
    else:
        cmd = [pio_path, "run", "--target", "upload"]
    
    print(f"🔧 Führe aus: {' '.join(cmd)}")
    
    try:
        # Run upload command
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        print("\n📋 OUTPUT:")
        print(result.stdout)
        
        if result.stderr:
            print("\n⚠️ ERRORS/WARNINGS:")
            print(result.stderr)
        
        if result.returncode == 0:
            print("\n✅ UPLOAD ERFOLGREICH!")
            return True
        else:
            print(f"\n❌ Upload fehlgeschlagen (Exit Code: {result.returncode})")
            return False
            
    except subprocess.TimeoutExpired:
        print("\n⏰ Upload-Timeout (5 Minuten)")
        return False
    except Exception as e:
        print(f"\n❌ Fehler beim Upload: {e}")
        return False

def main():
    print("=" * 60)
    print("🚀 Beyond Robotics Firmware Upload Helper")
    print("=" * 60)
    
    # Find PlatformIO
    pio_path = find_platformio()
    
    if not pio_path:
        print("\n❌ PlatformIO nicht gefunden!")
        print("\nLÖSUNGSVORSCHLÄGE:")
        print("1. PlatformIO über VSCode installieren")
        print("2. PlatformIO Core manuell installieren:")
        print("   pip install platformio")
        print("3. VSCode mit PlatformIO Extension verwenden")
        return
    
    # Upload firmware
    success = upload_firmware(pio_path)
    
    if success:
        print("\n🎯 NÄCHSTE SCHRITTE:")
        print("1. Board reset (Reset-Button drücken)")
        print("2. Serial Monitor testen auf COM8")
        print("3. DroneCAN Nachrichten prüfen")
    else:
        print("\n🔧 TROUBLESHOOTING:")
        print("1. ST-LINK Verbindung prüfen")
        print("2. Board power-cycle")
        print("3. VSCode mit PlatformIO verwenden")

if __name__ == "__main__":
    main()
