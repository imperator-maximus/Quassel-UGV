#!/usr/bin/env python3
"""
DroneCAN ESC Controller - Monitoring + PWM-Ausgabe
Verwendet neue Kalibrierungsdaten mit verbesserten Orange Cube Parametern
Neue Werte: Rückwärts ~-8000, Neutral ~0, Vorwärts ~+8000

Modi:
- Monitor: Zeigt DroneCAN ESC-Kommandos mit kalibrierten % und PWM-Werten
- PWM: Gibt PWM-Signale an GPIO-Pins aus (Hardware-PWM für Sicherheit)
- Both: Monitor + PWM gleichzeitig

Sicherheitsfeatures:
- Hardware-PWM für Freeze-Schutz
- Signal-Handler für sauberes Shutdown
- Timeout-Überwachung
"""

import time
import dronecan
import json
import argparse
import signal
import sys
import atexit

class CalibratedESCController:
    def __init__(self, enable_pwm=False, pwm_pins=[18, 19], enable_monitor=True, quiet=False,
                 enable_ramping=True, acceleration_rate=25, deceleration_rate=800, brake_rate=1500):
        # Kalibrierungswerte AKTUALISIERT mit neuen Orange Cube Parametern
        # Motor 0 = Rechts, Motor 1 = Links
        # Neue Werte: Rückwärts ~-8000, Neutral ~0, Vorwärts ~+8000
        self.calibration = {
            'left': {
                'neutral': -114,    # AKTUALISIERT: Motor 1 Neutral-Wert aus neuer Kalibrierung
                'min': -8191,       # Minimum bei Vollgas rückwärts
                'max': 8191,        # Maximum bei Vollgas vorwärts
                'forward_max': 8191, # Max bei reinem Vorwärts
                'reverse_min': -8191 # Min bei reinem Rückwärts
            },
            'right': {
                'neutral': 0,       # AKTUALISIERT: Motor 0 Neutral-Wert aus neuer Kalibrierung
                'min': -8191,       # Minimum bei Vollgas rückwärts
                'max': 8191,        # Maximum bei Vollgas vorwärts
                'forward_max': 8191, # Max bei reinem Vorwärts
                'reverse_min': -8191 # Min bei reinem Rückwärts
            }
        }

        # Konfiguration
        self.enable_pwm = enable_pwm
        self.enable_monitor = enable_monitor
        self.quiet = quiet
        self.pwm_pins = {'left': pwm_pins[1], 'right': pwm_pins[0]}  # Links=GPIO19, Rechts=GPIO18

        # PWM-Objekte
        self.pwm_objects = {}
        self.last_pwm_values = {'left': 1500, 'right': 1500}

        # Ramping-Konfiguration
        self.enable_ramping = enable_ramping
        self.acceleration_rate = acceleration_rate  # μs/Sekunde für Beschleunigung (langsam)
        self.deceleration_rate = deceleration_rate  # μs/Sekunde für Verzögerung (schnell)
        self.brake_rate = brake_rate                # μs/Sekunde für Bremsung zu Neutral (sehr schnell)

        # Ramping-Zustand
        self.current_pwm_values = {'left': 1500, 'right': 1500}  # Aktuelle PWM-Werte (gerampt)
        self.target_pwm_values = {'left': 1500, 'right': 1500}   # Ziel-PWM-Werte (vom DroneCAN)
        self.last_ramping_time = time.time()

        # Ausgabe-Dämpfung
        self.last_command = (0, 0)
        self.last_output_time = 0
        self.output_interval = 0.5  # Sekunden zwischen Ausgaben

        # Sicherheit
        self.last_command_time = time.time()
        self.command_timeout = 2.0  # 2 Sekunden Timeout

        # PWM initialisieren falls aktiviert
        if self.enable_pwm:
            self._init_pwm()

    def _init_pwm(self):
        """Initialisiert Hardware-PWM für sichere ESC-Steuerung"""
        try:
            import pigpio
            self.pi = pigpio.pi()

            if not self.pi.connected:
                raise Exception("Kann nicht mit pigpio daemon verbinden")

            # Hardware-PWM auf beiden Pins initialisieren
            for side, pin in self.pwm_pins.items():
                # Hardware-PWM mit 50Hz (20ms Periode)
                self.pi.hardware_PWM(pin, 50, 75000)  # 75000 = 7.5% = 1500μs bei 50Hz
                if not self.quiet:
                    print(f"✅ Hardware-PWM initialisiert: {side.capitalize()} Motor → GPIO{pin}")

            # Sicherheits-Handler registrieren
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            atexit.register(self._cleanup_pwm)

            if not self.quiet:
                print("🛡️ Sicherheits-Handler registriert (SIGINT, SIGTERM, atexit)")

        except ImportError:
            print("❌ FEHLER: pigpio library nicht installiert!")
            print("   Installieren mit: sudo apt install pigpio python3-pigpio")
            print("   Daemon starten mit: sudo systemctl start pigpiod")
            sys.exit(1)
        except Exception as e:
            print(f"❌ PWM-Initialisierung fehlgeschlagen: {e}")
            sys.exit(1)

    def _signal_handler(self, signum, frame):
        """Signal-Handler für sauberes Shutdown"""
        print(f"\n🛑 Signal {signum} empfangen - Sicherheits-Shutdown...")
        self._emergency_stop()
        sys.exit(0)

    def _emergency_stop(self):
        """Notfall-Stop: Alle Motoren auf Neutral"""
        if self.enable_pwm and hasattr(self, 'pi'):
            for side, pin in self.pwm_pins.items():
                self.pi.hardware_PWM(pin, 50, 75000)  # 1500μs neutral
            print("🚨 EMERGENCY STOP: Alle Motoren auf Neutral (1500μs)")

    def _cleanup_pwm(self):
        """PWM-Cleanup beim Beenden"""
        if self.enable_pwm and hasattr(self, 'pi'):
            self._emergency_stop()
            self.pi.stop()
            if not self.quiet:
                print("🧹 PWM-Cleanup abgeschlossen")

    def _apply_ramping(self, side, target_pwm):
        """Wendet Ramping-Logik auf PWM-Werte an"""
        if not self.enable_ramping:
            return target_pwm

        current_time = time.time()
        dt = current_time - self.last_ramping_time

        # Minimale Zeitdifferenz für Stabilität
        if dt < 0.01:  # 10ms
            return self.current_pwm_values[side]

        current_pwm = self.current_pwm_values[side]
        pwm_diff = target_pwm - current_pwm

        if abs(pwm_diff) < 1:  # Bereits am Ziel
            return target_pwm

        # Bestimme Ramping-Rate basierend auf Situation
        neutral_threshold = 50  # μs um Neutral (1500μs)

        # Prüfe ob wir zu Neutral bremsen (Stopp)
        if (abs(target_pwm - 1500) < neutral_threshold and
            abs(current_pwm - 1500) > neutral_threshold):
            # Bremsung zu Neutral - sehr schnell
            rate = self.brake_rate
            direction = "BRAKE"
        elif abs(target_pwm) < abs(current_pwm):
            # Verzögerung - schnell
            rate = self.deceleration_rate
            direction = "DECEL"
        else:
            # Beschleunigung - langsam
            rate = self.acceleration_rate
            direction = "ACCEL"

        # Berechne maximale Änderung für diesen Zeitschritt
        max_change = rate * dt

        # Begrenze die Änderung
        if abs(pwm_diff) <= max_change:
            new_pwm = target_pwm  # Ziel erreicht
        else:
            new_pwm = current_pwm + (max_change if pwm_diff > 0 else -max_change)

        # Debug-Ausgabe (reduziert)
        if (not self.quiet and abs(pwm_diff) > 10 and
            time.time() - getattr(self, '_last_ramp_debug', 0) > 2.0):
            print(f"🏃 Ramping {side}: {current_pwm:.0f}→{target_pwm:.0f}μs "
                  f"({direction}, {rate}μs/s, Δ{pwm_diff:.0f})")
            self._last_ramp_debug = time.time()

        return new_pwm

    def _set_motor_pwm(self, side, pwm_us):
        """Setzt PWM-Wert für einen Motor (mit Sicherheitsprüfung und Ramping)"""
        if not self.enable_pwm or not hasattr(self, 'pi'):
            return

        # Sicherheitsbegrenzung
        pwm_us = max(1000, min(2000, pwm_us))

        # Ziel-PWM setzen für Ramping
        self.target_pwm_values[side] = pwm_us

        # Ramping anwenden
        ramped_pwm = self._apply_ramping(side, pwm_us)
        self.current_pwm_values[side] = ramped_pwm

        # Konvertiere μs zu pigpio duty cycle (0-1000000)
        # Bei 50Hz: 1000μs = 5%, 1500μs = 7.5%, 2000μs = 10%
        duty_cycle = int((ramped_pwm / 20000.0) * 1000000)

        pin = self.pwm_pins[side]
        self.pi.hardware_PWM(pin, 50, duty_cycle)
        self.last_pwm_values[side] = ramped_pwm

        # Debug-Ausgabe (reduziert)
        if not self.quiet and time.time() - getattr(self, '_last_pwm_debug', 0) > 5.0:
            print(f"🔧 PWM Debug: {side.capitalize()} GPIO{pin} = {ramped_pwm:.0f}μs")
            self._last_pwm_debug = time.time()

    def _update_ramping(self):
        """Aktualisiert Ramping-Zustand (muss regelmäßig aufgerufen werden)"""
        if not self.enable_ramping or not self.enable_pwm:
            return

        current_time = time.time()

        # Prüfe ob Ramping noch aktiv ist
        for side in ['left', 'right']:
            if abs(self.current_pwm_values[side] - self.target_pwm_values[side]) > 1:
                # Ramping noch aktiv - PWM aktualisieren
                ramped_pwm = self._apply_ramping(side, self.target_pwm_values[side])
                self.current_pwm_values[side] = ramped_pwm

                # PWM Hardware aktualisieren
                if hasattr(self, 'pi'):
                    duty_cycle = int((ramped_pwm / 20000.0) * 1000000)
                    pin = self.pwm_pins[side]
                    self.pi.hardware_PWM(pin, 50, duty_cycle)
                    self.last_pwm_values[side] = ramped_pwm

        self.last_ramping_time = current_time

    def _check_command_timeout(self):
        """Prüft Kommando-Timeout und setzt ggf. auf Neutral"""
        if self.enable_pwm and time.time() - self.last_command_time > self.command_timeout:
            # Timeout erreicht - auf Neutral setzen (mit Ramping)
            self._set_motor_pwm('left', 1500)
            self._set_motor_pwm('right', 1500)
            if not self.quiet:
                print("⚠️ Kommando-Timeout - Motoren auf Neutral gesetzt")
            self.last_command_time = time.time()  # Reset um Spam zu vermeiden
        
    def raw_to_percent(self, raw_value, motor_side):
        """Konvertiert Raw-Werte zu kalibrierten Prozent-Werten"""
        cal = self.calibration[motor_side]
        neutral = cal['neutral']

        if raw_value == neutral:
            return 0.0
        elif raw_value > neutral:
            # Vorwärts: neutral bis max → 0% bis +100%
            max_range = cal['forward_max'] - neutral
            if max_range == 0:
                return 0.0
            percent = ((raw_value - neutral) / max_range) * 100.0
        else:
            # Rückwärts: min bis neutral → -100% bis 0%
            min_range = neutral - cal['reverse_min']
            if min_range == 0:
                return 0.0
            percent = ((raw_value - neutral) / min_range) * 100.0

        return round(percent, 1)

    def raw_to_pwm(self, raw_value, motor_side):
        """Konvertiert DroneCAN Raw-Werte zu Standard PWM-Werten (1000-2000 μs)"""
        # KORRIGIERT: Verwendet jetzt kalibrierte Prozent-Werte für konsistente Umrechnung
        # Raw → Kalibrierte % → PWM μs

        # Zuerst kalibrierte Prozent-Werte berechnen
        percent = self.raw_to_percent(raw_value, motor_side)

        # Dann Prozent zu PWM konvertieren
        # 0% = 1500μs (Neutral), -100% = 1000μs, +100% = 2000μs
        pwm_us = int(1500 + (percent / 100.0) * 500)

        # Begrenze auf gültigen PWM-Bereich
        pwm_us = max(1000, min(2000, pwm_us))

        return pwm_us
    
    def analyze_direction(self, left_pct, right_pct):
        """Analysiert Bewegungsrichtung basierend auf kalibrierten Prozent-Werten"""
        threshold = 1.5  # REDUZIERT: Für bessere Diagonal-Erkennung (war 3.0)

        # Neutral/Stop
        if abs(left_pct) < threshold and abs(right_pct) < threshold:
            return "NEUTRAL"

        # Vorwärts/Rückwärts (beide Motoren gleiche Richtung)
        elif left_pct > threshold and right_pct > threshold:
            diff = abs(left_pct - right_pct)
            if diff < threshold * 2:  # Größere Toleranz für "geradeaus"
                return "FORWARD"
            elif left_pct > right_pct + threshold:
                return "FORWARD + TURN_LEFT"
            else:
                return "FORWARD + TURN_RIGHT"

        elif left_pct < -threshold and right_pct < -threshold:
            diff = abs(left_pct - right_pct)
            if diff < threshold * 2:  # Größere Toleranz für "geradeaus"
                return "REVERSE"
            elif left_pct < right_pct - threshold:
                return "REVERSE + TURN_LEFT"
            else:
                return "REVERSE + TURN_RIGHT"

        # Spot-Turns (ein Motor vorwärts, einer rückwärts)
        elif left_pct > threshold and right_pct < -threshold:
            return "TURN_LEFT (Spot)"
        elif left_pct < -threshold and right_pct > threshold:
            return "TURN_RIGHT (Spot)"

        # Einseitige Bewegungen (ein Motor aktiv, anderer neutral)
        elif left_pct > threshold and abs(right_pct) < threshold:
            return "TURN_LEFT"
        elif right_pct > threshold and abs(left_pct) < threshold:
            return "TURN_RIGHT"
        elif left_pct < -threshold and abs(right_pct) < threshold:
            return "REVERSE_LEFT"
        elif right_pct < -threshold and abs(left_pct) < threshold:
            return "REVERSE_RIGHT"

        # Diagonale Bewegungen (beide Motoren aktiv, aber unterschiedliche Stärke)
        elif left_pct > threshold and right_pct > 0 and right_pct < left_pct:
            return "FORWARD + TURN_LEFT"
        elif right_pct > threshold and left_pct > 0 and left_pct < right_pct:
            return "FORWARD + TURN_RIGHT"
        elif left_pct < -threshold and right_pct < 0 and right_pct > left_pct:
            return "REVERSE + TURN_LEFT"
        elif right_pct < -threshold and left_pct < 0 and left_pct > right_pct:
            return "REVERSE + TURN_RIGHT"
        else:
            return f"MIXED (L:{left_pct:.1f}% R:{right_pct:.1f}%)"
    
    def format_percent(self, percent):
        """Formatiert Prozent-Werte mit Vorzeichen"""
        if percent > 0:
            return f"+{percent}%"
        elif percent < 0:
            return f"{percent}%"
        else:
            return "0.0%"
    
    def esc_rawcommand_handler(self, event):
        """Handler für ESC Raw Commands mit Kalibrierung und PWM-Ausgabe"""
        if len(event.message.cmd) < 2:
            return

        # Motor-Zuordnung FINAL KORRIGIERT: Tausche Links/Rechts
        right_raw = event.message.cmd[0]  # Motor 0 = Rechts
        left_raw = event.message.cmd[1]   # Motor 1 = Links

        current_command = (left_raw, right_raw)
        current_time = time.time()

        # Kommando-Timestamp für Timeout-Überwachung aktualisieren
        self.last_command_time = current_time

        # Ausgabe-Dämpfung - nur Zeitbegrenzung, nicht Werte-Vergleich
        if self.enable_monitor and current_time - self.last_output_time < self.output_interval:
            # PWM trotzdem ausgeben, auch wenn Monitor gedämpft ist
            if self.enable_pwm:
                left_pwm = self.raw_to_pwm(left_raw, 'left')
                right_pwm = self.raw_to_pwm(right_raw, 'right')
                self._set_motor_pwm('left', left_pwm)
                self._set_motor_pwm('right', right_pwm)
            return

        self.last_command = current_command
        self.last_output_time = current_time

        # Kalibrierte Prozent-Werte berechnen
        left_percent = self.raw_to_percent(left_raw, 'left')
        right_percent = self.raw_to_percent(right_raw, 'right')

        # PWM-Werte berechnen (mit Kalibrierung)
        left_pwm = self.raw_to_pwm(left_raw, 'left')
        right_pwm = self.raw_to_pwm(right_raw, 'right')

        # PWM-Ausgabe (falls aktiviert)
        if self.enable_pwm:
            self._set_motor_pwm('left', left_pwm)
            self._set_motor_pwm('right', right_pwm)

        # Monitor-Ausgabe (falls aktiviert und nicht quiet)
        if self.enable_monitor and not self.quiet:
            # Richtungsanalyse
            direction = self.analyze_direction(left_percent, right_percent)

            # Formatierte Ausgabe
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            left_str = self.format_percent(left_percent)
            right_str = self.format_percent(right_percent)

            # Farbige Ausgabe je nach Richtung
            direction_emoji = {
                "NEUTRAL": "⏸️",
                "FORWARD": "⬆️",
                "REVERSE": "⬇️",
                "TURN_LEFT": "↰",
                "TURN_RIGHT": "↱",
                "TURN_LEFT (Spot)": "🔄",
                "TURN_RIGHT (Spot)": "🔃",
                "FORWARD + TURN_LEFT": "↗️",
                "FORWARD + TURN_RIGHT": "↖️",
                "REVERSE + TURN_LEFT": "↙️",
                "REVERSE + TURN_RIGHT": "↘️"
            }.get(direction, "🔀")

            print(f"\n[{timestamp}] 🚗 ESC RawCommand von Node ID {event.transfer.source_node_id}:")
            print(f"    {direction_emoji} L/R: Links={left_str:<7} | Rechts={right_str:<7} | {direction}")
            print(f"    🔧 Raw: Links={left_raw:4d} | Rechts={right_raw:4d} | Neutral: L={self.calibration['left']['neutral']} R={self.calibration['right']['neutral']}")
            print(f"    📡 PWM: Links={left_pwm:4d}μs | Rechts={right_pwm:4d}μs | Neutral=1500μs")
            if self.enable_pwm:
                print(f"    ⚡ GPIO: Links=GPIO{self.pwm_pins['left']} | Rechts=GPIO{self.pwm_pins['right']}")
            print("-" * 70)

def load_calibration_from_file(filename='guided_esc_calibration.json'):
    """Lädt Kalibrierungsdaten aus JSON-Datei (optional)"""
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        
        # Extrahiert relevante Kalibrierungswerte aus neuer JSON-Datei
        calibration = {
            'left': {
                'neutral': int(data['step_data']['NEUTRAL']['left']['avg']),  # AKTUALISIERT: -114
                'min': int(data['global_ranges']['left']['min']),             # -8191
                'max': int(data['global_ranges']['left']['max']),             # +8191
                'forward_max': int(data['step_data']['FORWARD']['left']['max']),
                'reverse_min': int(data['step_data']['REVERSE']['left']['min'])
            },
            'right': {
                'neutral': int(data['step_data']['NEUTRAL']['right']['avg']), # AKTUALISIERT: 0
                'min': int(data['global_ranges']['right']['min']),            # -8191
                'max': int(data['global_ranges']['right']['max']),            # +8191
                'forward_max': int(data['step_data']['FORWARD']['right']['max']),
                'reverse_min': int(data['step_data']['REVERSE']['right']['min'])
            }
        }
        
        print(f"✅ Kalibrierungsdaten geladen aus: {filename}")
        return calibration
        
    except FileNotFoundError:
        print(f"⚠️  Kalibrierungsdatei {filename} nicht gefunden - verwende Standard-Werte")
        return None
    except Exception as e:
        print(f"❌ Fehler beim Laden der Kalibrierung: {e}")
        return None

def main():
    # Command-Line-Argumente parsen
    parser = argparse.ArgumentParser(
        description='DroneCAN ESC Controller - Monitoring + PWM-Ausgabe',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python3 dronecan_esc_controller.py                    # Nur Monitor
  python3 dronecan_esc_controller.py --pwm              # Monitor + PWM mit Ramping
  python3 dronecan_esc_controller.py --pwm --quiet      # Nur PWM (kein Monitor)
  python3 dronecan_esc_controller.py --pins 12,13       # Andere GPIO-Pins
  python3 dronecan_esc_controller.py --pwm --no-ramping # PWM ohne Ramping (sofort)
  python3 dronecan_esc_controller.py --pwm --accel-rate 100 --brake-rate 2000  # Angepasste Ramping-Raten
        """
    )

    parser.add_argument('--pwm', action='store_true',
                       help='PWM-Ausgabe aktivieren (Hardware-PWM)')
    parser.add_argument('--pins', default='18,19',
                       help='GPIO-Pins für PWM (Format: rechts,links) (default: 18,19)')
    parser.add_argument('--quiet', '-q', action='store_true',
                       help='Keine Monitor-Ausgabe (nur PWM)')
    parser.add_argument('--no-monitor', action='store_true',
                       help='Monitor komplett deaktivieren')

    # Ramping-Parameter
    parser.add_argument('--no-ramping', action='store_true',
                       help='Ramping deaktivieren (sofortige PWM-Änderungen)')
    parser.add_argument('--accel-rate', type=int, default=25,
                       help='Beschleunigungsrate in μs/Sekunde (default: 25, sehr langsam)')
    parser.add_argument('--decel-rate', type=int, default=800,
                       help='Verzögerungsrate in μs/Sekunde (default: 800, schnell)')
    parser.add_argument('--brake-rate', type=int, default=1500,
                       help='Bremsrate zu Neutral in μs/Sekunde (default: 1500, sehr schnell)')

    parser.add_argument('--interface', default='can0',
                       help='CAN-Interface (default: can0)')
    parser.add_argument('--bitrate', type=int, default=1000000,
                       help='CAN-Bitrate (default: 1000000)')
    parser.add_argument('--node-id', type=int, default=100,
                       help='DroneCAN Node-ID (default: 100)')

    args = parser.parse_args()

    # GPIO-Pins parsen
    try:
        pin_parts = args.pins.split(',')
        if len(pin_parts) != 2:
            raise ValueError("Pins müssen im Format 'rechts,links' angegeben werden")
        pwm_pins = [int(pin_parts[0]), int(pin_parts[1])]  # [rechts, links]
    except ValueError as e:
        print(f"❌ Ungültige Pin-Konfiguration: {e}")
        sys.exit(1)

    # Konfiguration
    enable_monitor = not args.no_monitor
    enable_pwm = args.pwm
    quiet = args.quiet

    if args.no_monitor and not args.pwm:
        print("❌ Fehler: --no-monitor ohne --pwm macht keinen Sinn")
        sys.exit(1)

    # Header ausgeben
    if not quiet:
        print("🎯 DroneCAN ESC Controller - Monitoring + PWM-Ausgabe")
        print("🔧 Neue Orange Cube Parameter: Rückwärts ~-8000, Neutral ~0, Vorwärts ~+8000")
        if enable_pwm:
            print(f"⚡ Hardware-PWM: Rechts=GPIO{pwm_pins[0]}, Links=GPIO{pwm_pins[1]}")
            if not args.no_ramping:
                print(f"🏃 Ramping: Beschl.={args.accel_rate}μs/s, Verzög.={args.decel_rate}μs/s, Brems.={args.brake_rate}μs/s")
            else:
                print("⚡ Ramping: DEAKTIVIERT (sofortige PWM-Änderungen)")
        print("="*70)

    # Controller erstellen
    controller = CalibratedESCController(
        enable_pwm=enable_pwm,
        pwm_pins=pwm_pins,
        enable_monitor=enable_monitor,
        quiet=quiet,
        enable_ramping=not args.no_ramping,
        acceleration_rate=args.accel_rate,
        deceleration_rate=args.decel_rate,
        brake_rate=args.brake_rate
    )

    # Versuche Kalibrierung aus Datei zu laden
    file_calibration = load_calibration_from_file()
    if file_calibration:
        controller.calibration = file_calibration
        if not quiet:
            print("🔧 Verwende NEUE Kalibrierungsdaten aus Datei")
    else:
        if not quiet:
            print("🔧 Verwende eingebaute AKTUALISIERTE Standard-Kalibrierung")

    if not quiet:
        print(f"\n📊 KALIBRIERUNGS-INFO:")
        print(f"   Links  - Neutral: {controller.calibration['left']['neutral']:4d} | Range: {controller.calibration['left']['min']}-{controller.calibration['left']['max']}")
        print(f"   Rechts - Neutral: {controller.calibration['right']['neutral']:4d} | Range: {controller.calibration['right']['min']}-{controller.calibration['right']['max']}")

    try:
        # DroneCAN Node initialisieren
        node = dronecan.make_node(args.interface, node_id=args.node_id, bitrate=args.bitrate)

        # Handler registrieren
        node.add_handler(dronecan.uavcan.equipment.esc.RawCommand, controller.esc_rawcommand_handler)

        if not quiet:
            print(f"\n🤖 DroneCAN Node gestartet ({args.interface}, {args.bitrate//1000} kbps, Node-ID {args.node_id})")
            if enable_monitor:
                print(f"📡 Kalibriertes Monitoring aktiv...")
            if enable_pwm:
                print(f"⚡ Hardware-PWM aktiv auf GPIO{pwm_pins[0]}/GPIO{pwm_pins[1]}")
            print(f"🚗 Warte auf ESC-Kommandos (System muss 'armed' sein)...")
            print(f"   Press Ctrl+C to stop")
            print("=" * 70)

        # Hauptschleife mit Timeout-Überwachung und Ramping-Updates
        while True:
            node.spin(timeout=0.1)  # Kürzeres Timeout für flüssiges Ramping
            # Timeout-Prüfung für PWM-Sicherheit
            if enable_pwm:
                controller._check_command_timeout()
                # Ramping-Updates für flüssige Bewegung
                controller._update_ramping()

    except KeyboardInterrupt:
        if not quiet:
            print("\n\n🛑 Controller beendet durch Benutzer")
            print("🎯 Sicherheits-Shutdown abgeschlossen!")

    except Exception as e:
        print(f"❌ Fehler: {e}")
        if enable_pwm:
            controller._emergency_stop()

if __name__ == "__main__":
    main()
