#!/usr/bin/env python3
"""
Orange Cube Monitor - Überwacht die Aktivität eines Orange Cube über MAVLink
und zeigt DroneCAN-bezogene Parameter und Nachrichten an.
"""

import time
import sys
from pymavlink import mavutil
from pymavlink.dialects.v20 import ardupilotmega as mavlink

# Verbindungseinstellungen
connection_string = 'COM4'  # Ändern Sie dies auf den COM-Port, an dem der Orange Cube angeschlossen ist
baud_rate = 57600

def connect_to_autopilot():
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

def request_parameters(master):
    """Alle Parameter vom Autopiloten anfordern"""
    print("Fordere Parameter an...")
    master.mav.param_request_list_send(master.target_system, master.target_component)

def request_specific_parameter(master, param_name):
    """Einen bestimmten Parameter anfordern"""
    print(f"Fordere Parameter {param_name} an...")
    master.mav.param_request_read_send(
        master.target_system, master.target_component,
        param_name.encode('utf-8'),
        -1  # -1 bedeutet: nach Namen suchen, nicht nach Index
    )

def monitor_messages(master, duration=60):
    """MAVLink-Nachrichten für eine bestimmte Dauer überwachen"""
    print(f"Überwache MAVLink-Nachrichten für {duration} Sekunden...")

    # Interessante Parameter für DroneCAN
    dronecan_params = [
        "CAN_D1_PROTOCOL",
        "CAN_D1_UC_NODE",
        "CAN_P1_DRIVER",
        "CAN_P1_BITRATE",
        "CAN_D1_UC_ESC_BM",
        "SERVO_BLH_AUTO",
        "SERVO_BLH_MASK",
        "SERVO_BLH_OTYPE",
        "LOG_DISARMED",
        "FRAME_CLASS",
        "FRAME_TYPE",
        "SERVO1_FUNCTION",
        "SERVO3_FUNCTION",
        "ARMING_CHECK",
        "BRD_SAFETY_MASK"
    ]

    # Parameter anfordern
    for param in dronecan_params:
        request_specific_parameter(master, param)

    # Nachrichtenzähler
    message_counts = {}
    param_values = {}
    start_time = time.time()

    # Hauptüberwachungsschleife
    while time.time() - start_time < duration:
        # Auf neue Nachrichten prüfen
        msg = master.recv_match(blocking=True, timeout=1.0)
        if msg is None:
            continue

        # Nachrichtentyp zählen
        msg_type = msg.get_type()
        if msg_type in message_counts:
            message_counts[msg_type] += 1
        else:
            message_counts[msg_type] = 1

        # Parameter-Werte speichern
        if msg_type == 'PARAM_VALUE':
            param_id = msg.param_id.decode('utf-8') if hasattr(msg.param_id, 'decode') else msg.param_id
            param_values[param_id] = msg.param_value
            if param_id in dronecan_params:
                print(f"Parameter: {param_id} = {msg.param_value}")

        # Servo-Ausgänge anzeigen
        if msg_type == 'SERVO_OUTPUT_RAW':
            print(f"Servo-Ausgänge: 1={msg.servo1_raw}, 2={msg.servo2_raw}, 3={msg.servo3_raw}, 4={msg.servo4_raw}")

        # RC-Eingänge anzeigen
        if msg_type == 'RC_CHANNELS':
            print(f"RC-Kanäle: 1={msg.chan1_raw}, 2={msg.chan2_raw}, 3={msg.chan3_raw}, 4={msg.chan4_raw}")

        # DroneCAN-spezifische Nachrichten
        if msg_type == 'UAVCAN_NODE_STATUS':
            print(f"DroneCAN Node Status: ID={msg.node_id}, Health={msg.health}, Mode={msg.mode}")

        # Statusmeldungen
        if msg_type == 'STATUSTEXT':
            text = msg.text.decode('utf-8') if hasattr(msg.text, 'decode') else msg.text
            print(f"Status: {text}")

    # Zusammenfassung anzeigen
    print("\n--- Überwachung abgeschlossen ---")
    print("\nEmpfangene Nachrichtentypen:")
    for msg_type, count in sorted(message_counts.items()):
        print(f"  {msg_type}: {count}")

    print("\nDroneCAN-Parameter:")
    for param in dronecan_params:
        value = param_values.get(param, "Nicht empfangen")
        print(f"  {param}: {value}")

def send_rc_override(master, channel, pwm_value):
    """RC-Override-Nachricht senden, um einen Kanal zu steuern"""
    # Erstelle eine Liste mit 8 Kanälen, alle auf 0 (keine Änderung)
    rc_channels = [0] * 8
    # Setze den gewünschten Kanal (0-basierter Index)
    rc_channels[channel-1] = pwm_value

    # Sende die RC-Override-Nachricht
    master.mav.rc_channels_override_send(
        master.target_system,
        master.target_component,
        *rc_channels  # Entpacke die Liste als separate Argumente
    )
    print(f"RC-Override gesendet: Kanal {channel} = {pwm_value}")

def arm_disarm(master, arm=True):
    """Fahrzeug armieren oder disarmieren"""
    # MAV_CMD_COMPONENT_ARM_DISARM (400)
    # param1: 1 zum Armieren, 0 zum Disarmieren
    # param2: 0 (normal) oder 21196 (force)
    force = 0
    if arm:
        print("Versuche Fahrzeug zu armieren...")
    else:
        print("Versuche Fahrzeug zu disarmieren...")

    # Sende Armierungs-/Disarmierungsbefehl
    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        400,  # MAV_CMD_COMPONENT_ARM_DISARM
        0,    # Confirmation
        1 if arm else 0,  # param1: 1 zum Armieren, 0 zum Disarmieren
        force,  # param2: 0 (normal) oder 21196 (force)
        0, 0, 0, 0, 0  # param3-7 (nicht verwendet)
    )

    # Warte auf Bestätigung
    start_time = time.time()
    while time.time() - start_time < 3:
        msg = master.recv_match(type='COMMAND_ACK', blocking=True, timeout=0.5)
        if msg is not None and msg.command == 400:
            if msg.result == 0:
                print(f"Fahrzeug erfolgreich {'armiert' if arm else 'disarmiert'}!")
            else:
                print(f"Fehler beim {'Armieren' if arm else 'Disarmieren'}: Ergebniscode {msg.result}")
                if msg.result == 4:  # MAV_RESULT_DENIED
                    print("Hinweis: Überprüfen Sie PreArm-Fehler in den Statusmeldungen")
            return

    print(f"Keine Bestätigung für {'Armieren' if arm else 'Disarmieren'} erhalten.")

def main():
    """Hauptfunktion"""
    # Verbindung herstellen
    master = connect_to_autopilot()

    # Benutzermenü
    while True:
        print("\n--- Orange Cube Monitor ---")
        print("1. Parameter anfordern")
        print("2. Nachrichten überwachen (60 Sekunden)")
        print("3. Servo-Test (RC-Override)")
        print("4. DroneCAN-Parameter anzeigen")
        print("5. Fahrzeug armieren")
        print("6. Fahrzeug disarmieren")
        print("7. Reboot Orange Cube")
        print("8. Beenden")

        choice = input("Wählen Sie eine Option: ")

        if choice == '1':
            # Alle Parameter anfordern und anzeigen
            print("Fordere ALLE Parameter an...")
            master.mav.param_request_list_send(master.target_system, master.target_component)

            # Parameter empfangen und anzeigen
            start_time = time.time()
            all_params = {}
            param_count = 0

            print("Empfange Parameter (30 Sekunden)...")
            while time.time() - start_time < 30:
                msg = master.recv_match(type='PARAM_VALUE', blocking=True, timeout=0.5)
                if msg is not None:
                    param_id = msg.param_id.decode('utf-8') if hasattr(msg.param_id, 'decode') else msg.param_id
                    param_id = param_id.rstrip('\x00')  # Null-Bytes entfernen
                    all_params[param_id] = msg.param_value
                    param_count += 1
                    print(f"Parameter: {param_id} = {msg.param_value}")

            print(f"\n✅ {param_count} Parameter empfangen")

            # Nach wichtigen SBUS/Servo-Parametern suchen
            important_params = ['BRD_PWM_VOLT_SEL', 'BRD_SERVO_VOLT', 'SERIAL1_PROTOCOL',
                              'SERIAL2_PROTOCOL', 'SERIAL8_PROTOCOL', 'RC_PROTOCOLS']

            print("\n🔍 Wichtige SBUS/Servo-Parameter:")
            for param in important_params:
                if param in all_params:
                    print(f"  ✅ {param} = {all_params[param]}")
                else:
                    print(f"  ❌ {param} = NICHT GEFUNDEN")
        elif choice == '2':
            monitor_messages(master)
        elif choice == '3':
            channel = int(input("Kanal (1-8): "))
            pwm = int(input("PWM-Wert (1000-2000): "))
            send_rc_override(master, channel, pwm)
            # Überwache die Nachrichten für 5 Sekunden nach dem Senden
            monitor_messages(master, 5)
        elif choice == '5':
            # Fahrzeug armieren
            arm_disarm(master, True)
            # Überwache die Nachrichten für 10 Sekunden nach dem Armieren
            print("Überwache Nachrichten nach dem Armieren...")
            monitor_messages(master, 10)
        elif choice == '6':
            # Fahrzeug disarmieren
            arm_disarm(master, False)
        elif choice == '7':
            # Reboot Orange Cube
            print("Sende Reboot-Befehl an Orange Cube...")
            master.mav.command_long_send(
                master.target_system,
                master.target_component,
                246,  # MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN
                0,    # Confirmation
                1,    # param1: 1 für Reboot
                0, 0, 0, 0, 0, 0  # param2-7 (nicht verwendet)
            )
            print("Reboot-Befehl gesendet. Warte 10 Sekunden...")
            time.sleep(10)
            print("Versuche, erneut zu verbinden...")
            master = connect_to_autopilot()
        elif choice == '4':
            # DroneCAN-spezifische Parameter anfordern
            print("Fordere alle DroneCAN-bezogenen Parameter an...")
            # Alle Parameter anfordern, die mit CAN beginnen
            master.mav.param_request_list_send(master.target_system, master.target_component)

            # Überwachen für 15 Sekunden, um alle Parameter zu erfassen
            start_time = time.time()
            can_params = {}

            print("Empfange Parameter (15 Sekunden)...")
            while time.time() - start_time < 15:
                msg = master.recv_match(type='PARAM_VALUE', blocking=True, timeout=0.5)
                if msg is not None:
                    param_id = msg.param_id.decode('utf-8') if hasattr(msg.param_id, 'decode') else msg.param_id
                    if param_id.startswith("CAN") or param_id.startswith("SERVO_BLH"):
                        can_params[param_id] = msg.param_value
                        print(f"Parameter: {param_id} = {msg.param_value}")

            # Zusammenfassung anzeigen
            print("\nZusammenfassung aller CAN-Parameter:")
            for param, value in sorted(can_params.items()):
                print(f"  {param}: {value}")
        elif choice == '8':
            print("Programm wird beendet.")
            break
        else:
            print("Ungültige Eingabe. Bitte erneut versuchen.")

if __name__ == "__main__":
    main()
