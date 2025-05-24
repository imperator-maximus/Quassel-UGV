#!/usr/bin/env python3
"""
Orange Cube CAN Parameter Setter - Dieses Skript setzt CAN-bezogene Parameter auf dem Orange Cube
über MAVLink, ohne Mission Planner zu verwenden.
"""

import time
import sys
import argparse
from pymavlink import mavutil

# Standard-Verbindungseinstellungen
DEFAULT_CONNECTION = 'COM4'  # Ändern Sie dies auf den COM-Port, an dem der Orange Cube angeschlossen ist
DEFAULT_BAUD = 57600

# Parameter-Definitionen mit Standardwerten
CAN_PARAMETERS = {
    # Grundlegende CAN-Konfiguration
    'CAN_P1_DRIVER': 1,       # CAN-Treiber aktivieren
    'CAN_P1_BITRATE': 1000000, # 1 Mbps Bitrate (Standard DroneCAN für Beyond Robotics)

    # DroneCAN-Protokoll-Konfiguration
    'CAN_D1_PROTOCOL': 1,     # DroneCAN-Protokoll aktivieren
    'CAN_D1_UC_NODE': 10,     # Node-ID des Orange Cube

    # Benachrichtigungsrate erhöhen
    'CAN_D1_UC_NTF_RT': 100,  # Erhöht auf 100 Hz (war 20 Hz)

    # ESC-Konfiguration
    'CAN_D1_UC_ESC_BM': 5,    # ESC-Bitmask auf 5 setzen (ESCs 1 und 3)

    # Servo-Konfiguration
    'CAN_D1_UC_SRV_BM': 5,    # Servo-Bitmask auf 5 setzen (Servos 1 und 3)
    'CAN_D1_UC_SRV_RT': 100,  # Servo-Rate auf 100 Hz erhöhen (war 50 Hz)

    # BlHeli-Konfiguration
    'SERVO_BLH_MASK': 5,      # BlHeli-Mask auf 5 setzen (Servos 1 und 3)
    'SERVO_BLH_AUTO': 1,      # Automatische Erkennung aktivieren

    # Logging im nicht-armierten Zustand
    'LOG_DISARMED': 1,        # Logging auch im nicht-armierten Zustand

    # Optionen
    'CAN_D1_UC_OPTION': 0,    # Keine speziellen Optionen
}

def connect_to_autopilot(connection_string, baud_rate):
    """Verbindung zum Autopiloten herstellen"""
    print(f"Verbinde mit Orange Cube auf {connection_string}...")
    try:
        # Verbindung herstellen
        master = mavutil.mavlink_connection(connection_string, baud=baud_rate)

        # Warten auf Heartbeat
        print("Warte auf Heartbeat...")
        master.wait_heartbeat()
        print(f"Verbunden mit System: {master.target_system}, Komponente: {master.target_component}")
        return master
    except Exception as e:
        print(f"Fehler beim Verbinden: {e}")
        sys.exit(1)

def set_parameter(master, param_name, param_value):
    """Einen Parameter setzen und auf Bestätigung warten"""
    # Parameter-Typ bestimmen (int oder float)
    if isinstance(param_value, int):
        param_type = mavutil.mavlink.MAV_PARAM_TYPE_INT32
    else:
        param_type = mavutil.mavlink.MAV_PARAM_TYPE_REAL32

    # Parameter setzen
    master.mav.param_set_send(
        master.target_system,
        master.target_component,
        param_name.encode('utf-8'),
        float(param_value),
        param_type
    )

    # Auf Bestätigung warten
    start_time = time.time()
    while time.time() - start_time < 5:  # 5 Sekunden Timeout
        msg = master.recv_match(type='PARAM_VALUE', blocking=True, timeout=1)
        if msg is not None:
            param_id = msg.param_id.decode('utf-8') if hasattr(msg.param_id, 'decode') else msg.param_id
            if param_id == param_name:
                if abs(msg.param_value - float(param_value)) < 0.00001:
                    print(f"Parameter {param_name} erfolgreich auf {param_value} gesetzt.")
                    return True
                else:
                    print(f"Parameter {param_name} konnte nicht gesetzt werden. Aktueller Wert: {msg.param_value}")
                    return False

    print(f"Timeout beim Setzen von Parameter {param_name}.")
    return False

def get_parameter(master, param_name):
    """Einen Parameter abfragen"""
    # Parameter anfordern
    master.mav.param_request_read_send(
        master.target_system,
        master.target_component,
        param_name.encode('utf-8'),
        -1  # -1 bedeutet: nach Namen suchen, nicht nach Index
    )

    # Auf Antwort warten
    start_time = time.time()
    while time.time() - start_time < 5:  # 5 Sekunden Timeout
        msg = master.recv_match(type='PARAM_VALUE', blocking=True, timeout=1)
        if msg is not None:
            param_id = msg.param_id.decode('utf-8') if hasattr(msg.param_id, 'decode') else msg.param_id
            if param_id == param_name:
                return msg.param_value

    print(f"Timeout beim Abfragen von Parameter {param_name}.")
    return None

def reboot_autopilot(master):
    """Orange Cube neustarten"""
    print("Sende Reboot-Befehl an Orange Cube...")
    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
        0,  # Confirmation
        1,  # param1: 1 für Reboot
        0, 0, 0, 0, 0, 0  # param2-7 (nicht verwendet)
    )

    # Auf Bestätigung warten
    start_time = time.time()
    while time.time() - start_time < 3:  # 3 Sekunden Timeout
        msg = master.recv_match(type='COMMAND_ACK', blocking=True, timeout=0.5)
        if msg is not None and msg.command == mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN:
            if msg.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                print("Reboot-Befehl akzeptiert.")
            else:
                print(f"Reboot-Befehl abgelehnt. Ergebniscode: {msg.result}")
            break

    print("Warte 15 Sekunden auf Neustart...")
    time.sleep(15)

def main():
    """Hauptfunktion"""
    # Kommandozeilenargumente parsen
    parser = argparse.ArgumentParser(description='Orange Cube CAN Parameter Setter')
    parser.add_argument('--port', default=DEFAULT_CONNECTION, help='Serieller Port (z.B. COM4)')
    parser.add_argument('--baud', type=int, default=DEFAULT_BAUD, help='Baudrate')
    parser.add_argument('--reboot', action='store_true', help='Orange Cube nach dem Setzen der Parameter neustarten')
    parser.add_argument('--check-only', action='store_true', help='Nur Parameter überprüfen, nicht setzen')
    args = parser.parse_args()

    # Verbindung herstellen
    master = connect_to_autopilot(args.port, args.baud)

    if args.check_only:
        # Nur Parameter überprüfen
        print("\nÜberprüfe aktuelle Parameter:")
        for param_name in CAN_PARAMETERS:
            value = get_parameter(master, param_name)
            if value is not None:
                print(f"{param_name} = {value}")
    else:
        # Parameter setzen
        print("\nSetze CAN-Parameter:")
        for param_name, param_value in CAN_PARAMETERS.items():
            current_value = get_parameter(master, param_name)
            if current_value is not None:
                print(f"Aktueller Wert von {param_name}: {current_value}")
                if abs(current_value - param_value) < 0.00001:
                    print(f"Parameter {param_name} ist bereits auf {param_value} gesetzt.")
                else:
                    set_parameter(master, param_name, param_value)
            else:
                print(f"Parameter {param_name} konnte nicht abgefragt werden.")

        # Reboot, wenn gewünscht
        if args.reboot:
            reboot_autopilot(master)
            # Nach dem Reboot erneut verbinden
            master = connect_to_autopilot(args.port, args.baud)

            # Parameter überprüfen
            print("\nÜberprüfe Parameter nach Neustart:")
            for param_name in CAN_PARAMETERS:
                value = get_parameter(master, param_name)
                if value is not None:
                    print(f"{param_name} = {value}")

    print("\nFertig.")

if __name__ == "__main__":
    main()
