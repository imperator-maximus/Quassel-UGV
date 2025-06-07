#!/usr/bin/env python3
"""
Einfaches DroneCAN Script für ESC-Kommandos
Verwendet die dronecan Python-Bibliothek direkt
"""

import time
import dronecan

# --- Handler für NodeStatus (gedämpft) ---
last_node_status_time = 0
def node_status_handler(event):
    global last_node_status_time
    current_time = time.time()

    # Nur alle 10 Sekunden Node Status ausgeben
    if current_time - last_node_status_time > 10.0:
        print(f"📡 Node Status von Node ID {event.transfer.source_node_id}: "
              f"Uptime={event.message.uptime_sec}s, "
              f"Health={event.message.health}, "
              f"Mode={event.message.mode}")
        last_node_status_time = current_time

# --- Handler für GPS-Position ---
def gps_fix_handler(event):
    lat_deg = event.message.latitude_deg_1e7 / 1e7
    lon_deg = event.message.longitude_deg_1e7 / 1e7
    print(f"GPS Fix von Node ID {event.transfer.source_node_id}: "
          f"Lat={lat_deg:.6f}, Lon={lon_deg:.6f}, "
          f"Satelliten={event.message.sats_used}")

# --- Handler für ESC-Kommandos (falls Setpoint verfügbar wäre) ---
# def esc_setpoint_handler(event):
#     # event.message.setpoint ist eine Liste von Werten (einer pro ESC)
#     # Wir formatieren die Liste für eine schönere Ausgabe
#     setpoint_str = ", ".join(map(str, event.message.setpoint))
#     print(f"ESC Setpoint von Node ID {event.transfer.source_node_id}: "
#           f"[{setpoint_str}] (0=min, 8191=max)")

# Globale Variablen für Ausgabe-Dämpfung
last_command = None
last_output_time = 0
output_interval = 0.5  # Mindestens 0.5 Sekunden zwischen Ausgaben

# --- Handler für ESC RawCommand ---
def esc_rawcommand_handler(event):
    global last_command, last_output_time

    # event.message.cmd ist eine Liste von Werten (einer pro ESC)
    cmd_str = ", ".join(map(str, event.message.cmd))
    current_command = tuple(event.message.cmd)
    current_time = time.time()

    # Nur ausgeben wenn sich die Werte signifikant geändert haben ODER genug Zeit vergangen ist
    if current_command == last_command:
        return

    # Zusätzliche Zeitbegrenzung für Ausgabe
    if current_time - last_output_time < output_interval:
        last_command = current_command  # Werte trotzdem speichern
        return

    last_command = current_command
    last_output_time = current_time

    # Für Skid Steering: 2 Motoren - KORRIGIERTE ZUORDNUNG
    if len(event.message.cmd) >= 2:
        # KORREKTUR: Motor 0 = Rechts, Motor 1 = Links (basierend auf Ihrem Feedback)
        right_raw = event.message.cmd[0]  # Motor 0 = Rechts
        left_raw = event.message.cmd[1]   # Motor 1 = Links

        # KALIBRIERTE Konvertierung basierend auf gemessenen Werten
        # Links: Neutral=4038, Min=0, Max=8191
        # Rechts: Neutral=4095, Min=0, Max=7167
        def raw_to_percent(raw_value, motor_side):
            if motor_side == 'left':
                neutral = 4038
                max_val = 8191
                min_val = 0
            else:  # right
                neutral = 4095
                max_val = 7167
                min_val = 0

            if raw_value == neutral:
                return 0.0
            elif raw_value > neutral:
                # Forward: neutral bis max → 0% bis +100%
                percent = ((raw_value - neutral) / (max_val - neutral)) * 100.0
            else:
                # Reverse: min bis neutral → -100% bis 0%
                percent = ((raw_value - neutral) / (neutral - min_val)) * 100.0
            return round(percent, 1)

        left_percent = raw_to_percent(left_raw, 'left')
        right_percent = raw_to_percent(right_raw, 'right')

        # Verbesserte Richtungsanalyse
        def analyze_direction(left_pct, right_pct):
            threshold = 5.0  # Mindest-Prozent für Bewegung (erhöht für bessere Erkennung)

            # Neutral/Stop
            if abs(left_pct) < threshold and abs(right_pct) < threshold:
                return "NEUTRAL"

            # Vorwärts/Rückwärts (beide Motoren gleiche Richtung)
            elif left_pct > threshold and right_pct > threshold:
                if abs(left_pct - right_pct) < threshold:
                    return "FORWARD"
                elif left_pct > right_pct:
                    return "FORWARD + TURN_LEFT"
                else:
                    return "FORWARD + TURN_RIGHT"
            elif left_pct < -threshold and right_pct < -threshold:
                if abs(left_pct - right_pct) < threshold:
                    return "REVERSE"
                elif left_pct < right_pct:
                    return "REVERSE + TURN_LEFT"
                else:
                    return "REVERSE + TURN_RIGHT"

            # Reine Drehungen (ein Motor vorwärts, einer rückwärts oder neutral)
            elif left_pct > threshold and right_pct < -threshold:
                return "TURN_LEFT (Spot)"
            elif left_pct < -threshold and right_pct > threshold:
                return "TURN_RIGHT (Spot)"
            elif left_pct > threshold and abs(right_pct) < threshold:
                return "TURN_LEFT"
            elif right_pct > threshold and abs(left_pct) < threshold:
                return "TURN_RIGHT"
            elif left_pct < -threshold and abs(right_pct) < threshold:
                return "REVERSE_LEFT"
            elif right_pct < -threshold and abs(left_pct) < threshold:
                return "REVERSE_RIGHT"
            else:
                return "MIXED"

        direction = analyze_direction(left_percent, right_percent)

        # Formatierung der Ausgabe
        timestamp = time.strftime("%H:%M:%S", time.localtime())

        # Vorzeichen für bessere Lesbarkeit
        left_sign = "+" if left_percent > 0 else "" if left_percent == 0 else ""
        right_sign = "+" if right_percent > 0 else "" if right_percent == 0 else ""

        print(f"\n[{timestamp}] 🚗 ESC RawCommand von Node ID {event.transfer.source_node_id}:")
        print(f"    L/R: Links={left_sign}{left_percent}% | Rechts={right_sign}{right_percent}% | {direction}")
        print(f"    Raw: [{cmd_str}] (Debug)")
        print("-" * 60)
    else:
        # Fallback für weniger als 2 Motoren
        throttle_percent = []
        for cmd in event.message.cmd:
            throttle = cmd / 8192.0
            percent = round(throttle * 100, 1)
            throttle_percent.append(f"{percent}%")

        percent_str = ", ".join(throttle_percent)
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        print(f"[{timestamp}] 🚗 ESC RawCommand von Node ID {event.transfer.source_node_id}: "
              f"Raw=[{cmd_str}] → Throttle=[{percent_str}]")

try:
    # Initialisiert die Verbindung zur CAN-Schnittstelle 'can0' (nicht 'can1')
    # Bitrate auf 1000000 für Orange Cube
    node = dronecan.make_node('can0', node_id=100, bitrate=1000000)

    # Registriert die Handler
    # node.add_handler(dronecan.uavcan.protocol.NodeStatus, node_status_handler)  # Auskommentiert - zu viel Spam
    node.add_handler(dronecan.uavcan.equipment.gnss.Fix, gps_fix_handler)
    # node.add_handler(dronecan.uavcan.equipment.esc.Setpoint, esc_setpoint_handler)  # Nicht verfügbar
    node.add_handler(dronecan.uavcan.equipment.esc.RawCommand, esc_rawcommand_handler)  # Das ist was wir brauchen!

    print("🤖 DroneCAN Node gestartet (can0, 1 Mbps)")
    print("📡 Lausche auf DroneCAN-Nachrichten...")
    print("🚗 Warte auf ESC-Kommandos (System muss 'armed' sein)...")
    print("   Press Ctrl+C to stop")
    print("=" * 60)

    # Endlosschleife zum Verarbeiten der Nachrichten
    while True:
        node.spin(timeout=1)

except Exception as e:
    print(f"❌ Ein Fehler ist aufgetreten: {e}")
