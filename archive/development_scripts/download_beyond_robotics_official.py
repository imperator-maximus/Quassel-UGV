#!/usr/bin/env python3
"""
Download Beyond Robotics Official Arduino-DroneCAN v1.2 Release Files
Based on support response recommendation
"""

import os
import requests
import zipfile
from pathlib import Path

def download_file(url, filename, description):
    """Download a file with progress indication"""
    print(f"\n📥 Downloading {description}...")
    print(f"URL: {url}")
    
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\rProgress: {percent:.1f}% ({downloaded}/{total_size} bytes)", end='')
        
        print(f"\n✅ Downloaded: {filename}")
        return True
        
    except Exception as e:
        print(f"\n❌ Error downloading {filename}: {e}")
        return False

def main():
    """Main download function"""
    print("🚀 Beyond Robotics Official Arduino-DroneCAN v1.2 Downloader")
    print("=" * 60)
    
    # Create downloads directory
    downloads_dir = Path("beyond_robotics_official")
    downloads_dir.mkdir(exist_ok=True)
    os.chdir(downloads_dir)
    
    # GitHub release URLs for v1.2
    base_url = "https://github.com/BeyondRobotix/Arduino-DroneCAN/releases/download/v1.2"
    
    files_to_download = [
        {
            "url": f"{base_url}/ArduinoDroneCAN.V1.2.zip",
            "filename": "ArduinoDroneCAN.V1.2.zip",
            "description": "Official Arduino-DroneCAN v1.2 Project"
        },
        {
            "url": f"{base_url}/AP_Bootloader.bin",
            "filename": "AP_Bootloader.bin", 
            "description": "AP Bootloader for STM32L431"
        }
    ]
    
    print(f"📁 Download directory: {downloads_dir.absolute()}")
    
    # Download files
    success_count = 0
    for file_info in files_to_download:
        if download_file(file_info["url"], file_info["filename"], file_info["description"]):
            success_count += 1
    
    print(f"\n📊 Download Summary:")
    print(f"✅ Successfully downloaded: {success_count}/{len(files_to_download)} files")
    
    # Extract Arduino-DroneCAN project if downloaded
    zip_file = "ArduinoDroneCAN.V1.2.zip"
    if os.path.exists(zip_file):
        print(f"\n📦 Extracting {zip_file}...")
        try:
            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                zip_ref.extractall(".")
            print("✅ Project extracted successfully")
            
            # List extracted contents
            print("\n📋 Extracted contents:")
            for item in os.listdir("."):
                if os.path.isdir(item) and item != "__pycache__":
                    print(f"  📁 {item}/")
                elif item.endswith(('.cpp', '.h', '.ini', '.md')):
                    print(f"  📄 {item}")
                    
        except Exception as e:
            print(f"❌ Error extracting {zip_file}: {e}")
    
    # Instructions
    print(f"\n🎯 Next Steps:")
    print(f"1. Download STM32CubeProgrammer from:")
    print(f"   https://www.st.com/en/development-tools/stm32cubeprog.html")
    print(f"")
    print(f"2. Flash AP_Bootloader.bin using STM32CubeProgrammer:")
    print(f"   - Start address: 0x8000000")
    print(f"   - File: {downloads_dir.absolute()}/AP_Bootloader.bin")
    print(f"")
    print(f"3. Open extracted Arduino-DroneCAN project in VSCode/PlatformIO")
    print(f"4. Upload firmware and test serial communication on COM8")
    
    print(f"\n✨ Ready to implement Beyond Robotics official solution!")

if __name__ == "__main__":
    main()
