#!/usr/bin/env python3
"""
DroneCAN ESC Kalibriertes Monitoring - AKTUALISIERT
Verwendet neue Kalibrierungsdaten mit verbesserten Orange Cube Parametern
Neue Werte: Rückwärts ~-8000, Neutral ~0, Vorwärts ~+8000
"""

import time
import dronecan
import json

class CalibratedESCMonitor:
    def __init__(self):
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
        
        # Ausgabe-Dämpfung
        self.last_command = Nonewo?(0,0)
        self.last_output_time = 0
        self.output_interval = 0.5  # Sekunden zwischen Ausgaben
        
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
        """Handler für ESC Raw Commands mit Kalibrierung"""
        if len(event.message.cmd) < 2:
            return
            
        # Motor-Zuordnung FINAL KORRIGIERT: Tausche Links/Rechts
        right_raw = event.message.cmd[0]  # Motor 0 = Rechts
        left_raw = event.message.cmd[1]   # Motor 1 = Links
        
        current_command = (left_raw, right_raw)
        current_time = time.time()
        
        # Ausgabe-Dämpfung - nur Zeitbegrenzung, nicht Werte-Vergleich
        if current_time - self.last_output_time < self.output_interval:
            return
        
        self.last_command = current_command
        self.last_output_time = current_time
        
        # Kalibrierte Prozent-Werte berechnen
        left_percent = self.raw_to_percent(left_raw, 'left')
        right_percent = self.raw_to_percent(right_raw, 'right')
        
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
    print("🎯 DroneCAN ESC Kalibriertes Monitoring - AKTUALISIERT")
    print("🔧 Neue Orange Cube Parameter: Rückwärts ~-8000, Neutral ~0, Vorwärts ~+8000")
    print("="*70)
    
    # Monitoring-Tool erstellen
    monitor = CalibratedESCMonitor()
    
    # Versuche Kalibrierung aus Datei zu laden
    file_calibration = load_calibration_from_file()
    if file_calibration:
        monitor.calibration = file_calibration
        print("🔧 Verwende NEUE Kalibrierungsdaten aus Datei")
    else:
        print("🔧 Verwende eingebaute AKTUALISIERTE Standard-Kalibrierung")
    
    print(f"\n📊 KALIBRIERUNGS-INFO:")
    print(f"   Links  - Neutral: {monitor.calibration['left']['neutral']:4d} | Range: {monitor.calibration['left']['min']}-{monitor.calibration['left']['max']}")
    print(f"   Rechts - Neutral: {monitor.calibration['right']['neutral']:4d} | Range: {monitor.calibration['right']['min']}-{monitor.calibration['right']['max']}")
    
    try:
        # DroneCAN Node initialisieren
        node = dronecan.make_node('can0', node_id=100, bitrate=1000000)
        
        # Handler registrieren
        node.add_handler(dronecan.uavcan.equipment.esc.RawCommand, monitor.esc_rawcommand_handler)
        
        print(f"\n🤖 DroneCAN Node gestartet (can0, 1 Mbps)")
        print(f"📡 Kalibriertes Monitoring aktiv...")
        print(f"🚗 Warte auf ESC-Kommandos (System muss 'armed' sein)...")
        print(f"   Press Ctrl+C to stop")
        print("=" * 70)
        
        # Hauptschleife
        while True:
            node.spin(timeout=1)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Monitoring beendet durch Benutzer")
        print("🎯 Kalibriertes Monitoring abgeschlossen!")
        
    except Exception as e:
        print(f"❌ Fehler: {e}")

if __name__ == "__main__":
    main()
