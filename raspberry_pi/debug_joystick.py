#!/usr/bin/env python3
"""
Debug-Script für Joystick-Probleme
Testet WebSocket-Kommunikation und PWM-Ausgabe
"""

import time
import sys
import os

def test_websocket_connection():
    """Testet WebSocket-Verbindung"""
    print("🧪 Teste WebSocket-Verbindung...")
    
    try:
        import socketio
        
        # Socket.IO Client erstellen
        sio = socketio.Client()
        
        @sio.event
        def connect():
            print("✅ WebSocket-Client verbunden")
            
        @sio.event
        def disconnect():
            print("❌ WebSocket-Client getrennt")
            
        @sio.event
        def pwm_update(data):
            print(f"📡 PWM Update empfangen: {data}")
        
        # Verbindung herstellen
        sio.connect('http://localhost:5000')
        
        # Test-Joystick-Daten senden
        test_data = [
            {'x': 0.0, 'y': 0.5},   # Vorwärts
            {'x': 0.5, 'y': 0.0},   # Rechts
            {'x': 0.0, 'y': -0.5},  # Rückwärts
            {'x': -0.5, 'y': 0.0},  # Links
            {'x': 0.0, 'y': 0.0},   # Neutral
        ]
        
        for i, data in enumerate(test_data):
            print(f"📤 Sende Test {i+1}: {data}")
            sio.emit('joystick_update', data)
            time.sleep(1)
        
        # Release-Event senden
        print("📤 Sende joystick_release")
        sio.emit('joystick_release')
        
        time.sleep(2)
        sio.disconnect()
        
    except ImportError:
        print("❌ python-socketio nicht installiert")
        print("   Installiere mit: pip3 install python-socketio[client]")
        return False
    except Exception as e:
        print(f"❌ WebSocket-Test fehlgeschlagen: {e}")
        return False
    
    return True

def test_pwm_hardware():
    """Testet PWM-Hardware direkt"""
    print("\n🧪 Teste PWM-Hardware...")
    
    try:
        import pigpio
        
        pi = pigpio.pi()
        if not pi.connected:
            print("❌ pigpio-Daemon nicht erreichbar")
            print("   Starte mit: sudo pigpiod")
            return False
        
        print("✅ pigpio verbunden")
        
        # Test-PWM auf GPIO 18 und 19
        pins = [18, 19]
        test_values = [1000, 1500, 2000, 1500]  # Min, Neutral, Max, Neutral
        
        for pin in pins:
            print(f"🔧 Teste GPIO {pin}...")
            
            for value in test_values:
                print(f"   PWM {value}μs")
                pi.set_servo_pulsewidth(pin, value)
                time.sleep(1)
            
            # Stoppe PWM
            pi.set_servo_pulsewidth(pin, 0)
        
        pi.stop()
        print("✅ PWM-Hardware-Test abgeschlossen")
        return True
        
    except ImportError:
        print("❌ pigpio nicht installiert")
        print("   Installiere mit: sudo apt install python3-pigpio")
        return False
    except Exception as e:
        print(f"❌ PWM-Test fehlgeschlagen: {e}")
        return False

def test_can_status():
    """Testet CAN-Status über API"""
    print("\n🧪 Teste CAN-Status...")
    
    try:
        import requests
        
        response = requests.get('http://localhost:5000/api/status', timeout=5)
        if response.status_code == 200:
            data = response.json()
            print("✅ API-Status empfangen:")
            print(f"   CAN enabled: {data.get('can_enabled')}")
            print(f"   PWM enabled: {data.get('pwm_enabled')}")
            print(f"   Joystick enabled: {data.get('joystick_enabled')}")
            print(f"   Current PWM: {data.get('current_pwm')}")
            
            if data.get('can_enabled'):
                print("⚠️  CAN ist AKTIVIERT - Joystick sollte DEAKTIVIERT sein")
            else:
                print("✅ CAN ist DEAKTIVIERT - Joystick sollte AKTIV sein")
            
            return True
        else:
            print(f"❌ API-Fehler: {response.status_code}")
            return False
            
    except ImportError:
        print("❌ requests nicht installiert")
        print("   Installiere mit: pip3 install requests")
        return False
    except Exception as e:
        print(f"❌ API-Test fehlgeschlagen: {e}")
        return False

def main():
    """Hauptfunktion für Debug-Tests"""
    print("🔍 Joystick Debug-Tool")
    print("=" * 50)
    
    # Prüfe ob Controller läuft
    try:
        import requests
        response = requests.get('http://localhost:5000/api/status', timeout=2)
        print("✅ DroneCAN Controller läuft")
    except:
        print("❌ DroneCAN Controller läuft NICHT")
        print("   Starte mit: python3 dronecan_esc_controller.py --pwm --web")
        return
    
    # Tests ausführen
    tests = [
        ("CAN-Status", test_can_status),
        ("WebSocket", test_websocket_connection),
        ("PWM-Hardware", test_pwm_hardware),
    ]
    
    results = {}
    for name, test_func in tests:
        print(f"\n{'='*20} {name} {'='*20}")
        try:
            results[name] = test_func()
        except KeyboardInterrupt:
            print("\n🛑 Test abgebrochen")
            break
        except Exception as e:
            print(f"❌ Test-Fehler: {e}")
            results[name] = False
    
    # Zusammenfassung
    print(f"\n{'='*50}")
    print("📊 Test-Zusammenfassung:")
    for name, result in results.items():
        status = "✅ OK" if result else "❌ FEHLER"
        print(f"   {name}: {status}")
    
    if all(results.values()):
        print("\n🎉 Alle Tests erfolgreich!")
        print("💡 Falls Joystick trotzdem nicht funktioniert:")
        print("   1. Browser-Konsole (F12) auf Fehler prüfen")
        print("   2. CAN STOPPEN drücken (Joystick nur bei CAN AUS aktiv)")
        print("   3. Terminal-Output auf Debug-Meldungen prüfen")
    else:
        print("\n⚠️  Einige Tests fehlgeschlagen - siehe Details oben")

if __name__ == "__main__":
    main()
