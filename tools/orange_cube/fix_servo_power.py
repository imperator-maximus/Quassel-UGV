#!/usr/bin/env python3
"""
Fix Orange Cube Servo Power

Setzt BRD_PWM_VOLT_SEL = 1 um die Servo-Stromversorgung zu aktivieren.
"""

import time
import sys
from pymavlink import mavutil

DEFAULT_CONNECTION = 'COM4'
DEFAULT_BAUDRATE = 115200

def connect_to_orange_cube(connection_string, baudrate):
    """Verbindung zum Orange Cube herstellen"""
    print(f"🔌 Verbinde mit Orange Cube auf {connection_string}...")

    try:
        master = mavutil.mavlink_connection(connection_string, baud=baudrate)
        master.wait_heartbeat()
        print(f"✅ Verbindung hergestellt! System ID: {master.target_system}")
        return master
    except Exception as e:
        print(f"❌ Verbindung fehlgeschlagen: {e}")
        return None

def set_parameter_with_confirmation(connection, param_name, param_value):
    """Parameter setzen und auf Bestätigung warten"""
    print(f"📝 Setze {param_name} = {param_value}")

    # Parameter setzen
    connection.mav.param_set_send(
        connection.target_system,
        connection.target_component,
        param_name.encode('utf-8'),
        param_value,
        mavutil.mavlink.MAV_PARAM_TYPE_REAL32
    )

    # Auf Bestätigung warten
    start_time = time.time()
    while time.time() - start_time < 5:
        msg = connection.recv_match(type='PARAM_VALUE', blocking=True, timeout=0.5)
        if msg is not None:
            # Parameter-ID richtig dekodieren
            if hasattr(msg.param_id, 'decode'):
                received_param = msg.param_id.decode('utf-8').rstrip('\x00')
            else:
                received_param = str(msg.param_id).rstrip('\x00')

            if received_param == param_name:
                print(f"✅ {param_name} erfolgreich gesetzt auf {msg.param_value}")
                return True

    print(f"❌ Timeout beim Setzen von {param_name}")
    return False

def main():
    print("⚡ Orange Cube Servo Power Fix")
    print("=" * 40)
    print("Aktiviert die Servo-Stromversorgung durch Setzen von BRD_PWM_VOLT_SEL = 1")
    print()

    # Verbindung herstellen
    connection = connect_to_orange_cube(DEFAULT_CONNECTION, DEFAULT_BAUDRATE)
    if not connection:
        sys.exit(1)

    try:
        # BRD_PWM_VOLT_SEL auf 1 setzen (5V Servo-Versorgung aktivieren)
        success = set_parameter_with_confirmation(connection, 'BRD_PWM_VOLT_SEL', 1.0)

        if success:
            print("\n🎉 Servo-Stromversorgung aktiviert!")
            print("\n📋 Nächste Schritte:")
            print("1. Orange Cube neu starten (Strom aus/an)")
            print("2. SBUS-Empfänger sollte jetzt Strom bekommen")
            print("3. RC-Test mit python rc_test_guide.py")
        else:
            print("\n❌ Fehler beim Aktivieren der Servo-Stromversorgung")
            print("Versuchen Sie einen Orange Cube Neustart und wiederholen Sie den Vorgang")

    except KeyboardInterrupt:
        print("\n⚠️ Abgebrochen")
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
