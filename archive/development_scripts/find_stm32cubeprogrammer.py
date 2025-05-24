#!/usr/bin/env python3
"""
STM32CubeProgrammer Finder
Sucht STM32CubeProgrammer auf dem System
"""

import os
import glob
from pathlib import Path

def print_header(title):
    """Print formatted header"""
    print(f"\n{'='*60}")
    print(f"🔍 {title}")
    print(f"{'='*60}")

def check_path(path, description):
    """Check if path exists and report"""
    if os.path.exists(path):
        print(f"✅ GEFUNDEN: {description}")
        print(f"   📁 Pfad: {path}")
        return True
    else:
        print(f"❌ Nicht gefunden: {description}")
        print(f"   📁 Pfad: {path}")
        return False

def find_stm32cubeprogrammer():
    """Find STM32CubeProgrammer installation"""
    print_header("STM32CubeProgrammer Suche")
    
    # Standard installation paths
    standard_paths = [
        r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32CubeProgrammer.exe",
        r"C:\Program Files (x86)\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32CubeProgrammer.exe",
        r"C:\ST\STM32CubeProgrammer\bin\STM32CubeProgrammer.exe",
        r"C:\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32CubeProgrammer.exe"
    ]
    
    found_paths = []
    
    print("🔍 Prüfe Standard-Installationspfade...")
    for i, path in enumerate(standard_paths, 1):
        if check_path(path, f"Standard-Pfad {i}"):
            found_paths.append(path)
    
    # Search in common directories
    print(f"\n🔍 Suche in häufigen Verzeichnissen...")
    search_dirs = [
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"C:\ST",
        r"C:\STMicroelectronics"
    ]
    
    for search_dir in search_dirs:
        if os.path.exists(search_dir):
            print(f"📂 Durchsuche: {search_dir}")
            try:
                # Search for STM32CubeProgrammer.exe
                pattern = os.path.join(search_dir, "**", "STM32CubeProgrammer.exe")
                matches = glob.glob(pattern, recursive=True)
                
                for match in matches:
                    if match not in found_paths:
                        print(f"✅ GEFUNDEN: {match}")
                        found_paths.append(match)
                        
            except Exception as e:
                print(f"⚠️  Fehler beim Durchsuchen von {search_dir}: {e}")
    
    # Search in PATH environment
    print(f"\n🔍 Prüfe PATH-Umgebungsvariable...")
    path_env = os.environ.get('PATH', '')
    for path_dir in path_env.split(os.pathsep):
        stm_exe = os.path.join(path_dir, "STM32CubeProgrammer.exe")
        if os.path.exists(stm_exe) and stm_exe not in found_paths:
            print(f"✅ GEFUNDEN in PATH: {stm_exe}")
            found_paths.append(stm_exe)
    
    # Results
    print_header("Suchergebnisse")
    
    if found_paths:
        print(f"🎯 {len(found_paths)} Installation(en) gefunden:")
        for i, path in enumerate(found_paths, 1):
            print(f"\n{i}. {path}")
            
            # Check if it's executable
            if os.access(path, os.X_OK):
                print(f"   ✅ Ausführbar")
            else:
                print(f"   ⚠️  Möglicherweise nicht ausführbar")
            
            # Get file info
            try:
                stat = os.stat(path)
                size_mb = stat.st_size / (1024 * 1024)
                print(f"   📊 Größe: {size_mb:.1f} MB")
            except:
                pass
        
        print(f"\n🚀 EMPFEHLUNG:")
        print(f"Verwende diesen Pfad: {found_paths[0]}")
        
        # Create shortcut script
        create_shortcut_script(found_paths[0])
        
    else:
        print("❌ STM32CubeProgrammer nicht gefunden!")
        print("\n🔧 LÖSUNGSVORSCHLÄGE:")
        print("1. Prüfe, ob die Installation vollständig war")
        print("2. Suche manuell nach 'STM32CubeProgrammer.exe'")
        print("3. Neuinstallation von STM32CubeProgrammer")
        print("4. Prüfe Downloads-Ordner auf .zip-Datei")

def create_shortcut_script(exe_path):
    """Create a shortcut script to launch STM32CubeProgrammer"""
    script_content = f'''@echo off
echo ========================================
echo STM32CubeProgrammer Starter
echo ========================================
echo.
echo Starte STM32CubeProgrammer...
echo Pfad: {exe_path}
echo.

"{exe_path}"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Fehler beim Starten von STM32CubeProgrammer
    echo Prüfe den Pfad und die Installation
    pause
)
'''
    
    script_file = "start_stm32cubeprogrammer.bat"
    try:
        with open(script_file, 'w', encoding='utf-8') as f:
            f.write(script_content)
        print(f"\n📝 Shortcut-Script erstellt: {script_file}")
        print(f"   Doppelklick auf {script_file} um STM32CubeProgrammer zu starten")
    except Exception as e:
        print(f"⚠️  Konnte Shortcut-Script nicht erstellen: {e}")

if __name__ == "__main__":
    find_stm32cubeprogrammer()
