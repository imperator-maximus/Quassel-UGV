#!/usr/bin/env python3
"""
Cleanup Orange Cube Directory
Behält nur die 4 finalen, wichtigen Scripts und archiviert den Rest
"""

import os
import shutil
from pathlib import Path

def cleanup_orange_cube_directory():
    print("🧹 Cleaning up Orange Cube directory...")
    
    # Scripts die BLEIBEN sollen (finale, wichtige Scripts)
    KEEP_SCRIPTS = {
        'master_orange_cube_config.py',      # Master configuration script
        'monitor_pwm_before_can.py',         # PWM monitor (vor CAN)
        'monitor_orange_cube.py',            # Orange Cube monitor (wichtig!)
        'find_throttle_channel.py',          # RC channel analysis (nützlich)
        'dump_all_parameters.py',            # Parameter dump utility
        'README.md',                         # Documentation
        'external_sbus_power_guide.md',      # SBUS guide
    }
    
    # Aktuelles Verzeichnis
    orange_cube_dir = Path('.')
    archive_dir = orange_cube_dir / 'archive'
    
    # Archive Verzeichnis erstellen falls nicht vorhanden
    archive_dir.mkdir(exist_ok=True)
    
    # Alle Python-Dateien finden
    all_files = list(orange_cube_dir.glob('*.py')) + list(orange_cube_dir.glob('*.md'))
    
    moved_count = 0
    kept_count = 0
    
    print(f"\n📁 Processing {len(all_files)} files...")
    
    for file_path in all_files:
        filename = file_path.name
        
        if filename in KEEP_SCRIPTS:
            print(f"✅ KEEP: {filename}")
            kept_count += 1
        else:
            # Ins Archive verschieben
            archive_path = archive_dir / filename
            try:
                if archive_path.exists():
                    archive_path.unlink()  # Überschreiben falls vorhanden
                shutil.move(str(file_path), str(archive_path))
                print(f"📦 ARCHIVE: {filename}")
                moved_count += 1
            except Exception as e:
                print(f"❌ ERROR moving {filename}: {e}")
    
    print(f"\n✅ Cleanup complete!")
    print(f"   📁 Kept: {kept_count} files")
    print(f"   📦 Archived: {moved_count} files")
    
    # Finale Verzeichnisstruktur anzeigen
    print(f"\n📋 Final Orange Cube directory structure:")
    remaining_files = list(orange_cube_dir.glob('*.py')) + list(orange_cube_dir.glob('*.md'))
    for file_path in sorted(remaining_files):
        print(f"   ✅ {file_path.name}")
    
    print(f"\n📦 Archived files in archive/ directory:")
    archived_files = list(archive_dir.glob('*.py')) + list(archive_dir.glob('*.md'))
    print(f"   📁 {len(archived_files)} files archived")
    
    print(f"\n🎯 FINAL SCRIPTS (ready to use):")
    print(f"   1. master_orange_cube_config.py  - Complete Orange Cube setup")
    print(f"   2. monitor_pwm_before_can.py     - PWM values before CAN")
    print(f"   3. monitor_orange_cube.py        - Orange Cube monitoring")
    print(f"   4. find_throttle_channel.py      - RC channel analysis")
    print(f"   5. dump_all_parameters.py        - Parameter backup utility")

if __name__ == "__main__":
    cleanup_orange_cube_directory()
