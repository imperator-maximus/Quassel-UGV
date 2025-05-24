#!/usr/bin/env python3
"""
COM Port Scanner - Findet alle verfügbaren COM-Ports
"""

import serial.tools.list_ports
import serial
import time

def scan_com_ports():
    """Scannt alle verfügbaren COM-Ports"""
    print("=" * 60)
    print("COM Port Scanner")
    print("=" * 60)
    
    # Alle verfügbaren Ports auflisten
    ports = serial.tools.list_ports.comports()
    
    if not ports:
        print("❌ Keine COM-Ports gefunden!")
        return []
    
    print(f"✅ {len(ports)} COM-Port(s) gefunden:")
    print()
    
    available_ports = []
    
    for port in ports:
        print(f"📍 {port.device}")
        print(f"   Beschreibung: {port.description}")
        print(f"   Hardware-ID: {port.hwid}")
        print(f"   Hersteller: {port.manufacturer}")
        print()
        
        # Teste ob Port verfügbar ist
        try:
            ser = serial.Serial(port.device, 115200, timeout=0.1)
            ser.close()
            available_ports.append(port.device)
            print(f"   ✅ Port {port.device} ist verfügbar")
        except Exception as e:
            print(f"   ❌ Port {port.device} nicht verfügbar: {e}")
        print("-" * 40)
    
    return available_ports

def test_port_for_data(port, duration=5):
    """Testet einen Port auf eingehende Daten"""
    print(f"\n🔍 Teste {port} für {duration} Sekunden auf Daten...")
    
    try:
        ser = serial.Serial(port, 115200, timeout=0.1)
        start_time = time.time()
        data_received = False
        
        while time.time() - start_time < duration:
            if ser.in_waiting > 0:
                data = ser.readline().decode('utf-8', errors='ignore').strip()
                if data:
                    print(f"📨 {port}: {data}")
                    data_received = True
            time.sleep(0.1)
        
        ser.close()
        
        if data_received:
            print(f"✅ {port}: Daten empfangen!")
        else:
            print(f"⚠️  {port}: Keine Daten empfangen")
            
        return data_received
        
    except Exception as e:
        print(f"❌ {port}: Fehler beim Testen: {e}")
        return False

def main():
    """Hauptfunktion"""
    # Alle Ports scannen
    available_ports = scan_com_ports()
    
    if not available_ports:
        print("Keine verfügbaren Ports zum Testen.")
        return
    
    print("\n" + "=" * 60)
    print("DATEN-TEST")
    print("=" * 60)
    
    # Jeden verfügbaren Port auf Daten testen
    for port in available_ports:
        test_port_for_data(port, 5)
    
    print("\n" + "=" * 60)
    print("EMPFEHLUNG")
    print("=" * 60)
    
    # Spezielle Suche nach STM32/ST-LINK Ports
    stm32_ports = []
    for port in serial.tools.list_ports.comports():
        desc_lower = port.description.lower()
        hwid_lower = port.hwid.lower()
        
        if any(keyword in desc_lower or keyword in hwid_lower for keyword in 
               ['stm32', 'st-link', 'stlink', 'st link', 'usb serial']):
            stm32_ports.append(port.device)
    
    if stm32_ports:
        print("🎯 Mögliche STM32/ST-LINK Ports gefunden:")
        for port in stm32_ports:
            print(f"   {port}")
        print("\nVersuchen Sie diese Ports für das Beyond Robotics Board.")
    else:
        print("⚠️  Keine offensichtlichen STM32/ST-LINK Ports gefunden.")
        print("Das Beyond Robotics Board könnte einen anderen Port verwenden.")

if __name__ == "__main__":
    main()
