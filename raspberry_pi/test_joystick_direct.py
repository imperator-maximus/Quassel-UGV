#!/usr/bin/env python3
"""
Test-Script für direkten Joystick-PWM (ohne Ramping)
Simuliert Joystick-Bewegungen über WebSocket
"""

import time
import socketio

def test_direct_joystick():
    """Testet direkten Joystick-PWM ohne Ramping"""
    print("🧪 Teste direkten Joystick-PWM...")
    
    try:
        # Socket.IO Client erstellen
        sio = socketio.Client()
        
        @sio.event
        def connect():
            print("✅ WebSocket verbunden")
            
        @sio.event
        def pwm_update(data):
            print(f"📡 PWM: L={data.get('left')}μs R={data.get('right')}μs")
        
        # Verbindung herstellen
        sio.connect('http://localhost:5000')
        time.sleep(1)
        
        print("\n🎮 Teste verschiedene Joystick-Bewegungen:")
        print("   (Stelle sicher, dass CAN GESTOPPT ist!)")
        
        # Test-Sequenz
        movements = [
            (0.0, 0.0, "Neutral"),
            (0.0, 0.5, "Vorwärts 50%"),
            (0.0, 1.0, "Vorwärts 100%"),
            (0.0, 0.0, "Neutral"),
            (0.5, 0.0, "Rechts drehen 50%"),
            (1.0, 0.0, "Rechts drehen 100%"),
            (0.0, 0.0, "Neutral"),
            (-0.5, 0.0, "Links drehen 50%"),
            (0.0, -0.5, "Rückwärts 50%"),
            (0.0, 0.0, "Neutral"),
            (0.5, 0.5, "Diagonal: Vorwärts+Rechts"),
            (0.0, 0.0, "Neutral"),
        ]
        
        for x, y, description in movements:
            print(f"\n📤 {description}: X={x:+.1f} Y={y:+.1f}")
            sio.emit('joystick_update', {'x': x, 'y': y})
            time.sleep(2)  # 2 Sekunden pro Bewegung
        
        # Final release
        print("\n📤 Joystick Release")
        sio.emit('joystick_release')
        time.sleep(1)
        
        sio.disconnect()
        print("\n✅ Test abgeschlossen!")
        
    except Exception as e:
        print(f"❌ Test fehlgeschlagen: {e}")

def main():
    print("🎯 Joystick Direct-PWM Test")
    print("=" * 40)
    print("WICHTIG: Stelle sicher, dass:")
    print("1. DroneCAN Controller läuft: python3 dronecan_esc_controller.py --pwm --web")
    print("2. CAN ist GESTOPPT (Joystick nur bei CAN AUS aktiv)")
    print("3. Motoren sind sicher angeschlossen")
    print()
    
    input("Drücke Enter um zu starten...")
    test_direct_joystick()

if __name__ == "__main__":
    main()
