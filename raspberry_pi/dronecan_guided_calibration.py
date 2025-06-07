#!/usr/bin/env python3
"""
DroneCAN ESC Geführte Kalibrierung
Führt Schritt-für-Schritt durch alle Bewegungen für präzise Kalibrierung
"""

import time
import dronecan
import json
from datetime import datetime

class GuidedCalibrationTool:
    def __init__(self):
        self.calibration_steps = [
            {"name": "NEUTRAL", "instruction": "Stick LOSLASSEN (Neutral-Position)", "duration": 3},
            {"name": "FORWARD", "instruction": "Stick GANZ NACH OBEN (Vollgas vorwärts)", "duration": 3},
            {"name": "REVERSE", "instruction": "Stick GANZ NACH UNTEN (Vollgas rückwärts)", "duration": 3},
            {"name": "TURN_LEFT", "instruction": "Stick GANZ NACH LINKS (Vollgas links drehen)", "duration": 3},
            {"name": "TURN_RIGHT", "instruction": "Stick GANZ NACH RECHTS (Vollgas rechts drehen)", "duration": 3},
            {"name": "FORWARD_LEFT", "instruction": "Stick DIAGONAL OBEN-LINKS (Linkskurve)", "duration": 3},
            {"name": "FORWARD_RIGHT", "instruction": "Stick DIAGONAL OBEN-RECHTS (Rechtskurve)", "duration": 3},
            {"name": "REVERSE_LEFT", "instruction": "Stick DIAGONAL UNTEN-LINKS (Rückwärts links)", "duration": 3},
            {"name": "REVERSE_RIGHT", "instruction": "Stick DIAGONAL UNTEN-RECHTS (Rückwärts rechts)", "duration": 3}
        ]
        
        self.current_step = 0
        self.step_data = {}
        self.step_start_time = 0
        self.collecting = False
        self.samples_this_step = []
        
    def start_next_step(self):
        """Startet den nächsten Kalibrierungsschritt"""
        if self.current_step >= len(self.calibration_steps):
            return False
            
        step = self.calibration_steps[self.current_step]
        self.samples_this_step = []
        self.collecting = False
        
        print(f"\n{'='*60}")
        print(f"🎯 SCHRITT {self.current_step + 1}/{len(self.calibration_steps)}: {step['name']}")
        print(f"{'='*60}")
        print(f"📋 ANWEISUNG: {step['instruction']}")
        print(f"⏱️  Dauer: {step['duration']} Sekunden")
        print(f"🚀 Drücken Sie ENTER wenn bereit...")
        
        input()  # Warten auf Benutzer-Eingabe
        
        print(f"⏳ Sammle Daten für {step['duration']} Sekunden...")
        self.step_start_time = time.time()
        self.collecting = True
        
        return True
    
    def esc_rawcommand_handler(self, event):
        """Handler für ESC Raw Commands während der Kalibrierung"""
        if not self.collecting:
            return
            
        if len(event.message.cmd) >= 2:
            # Motor 0 = Rechts, Motor 1 = Links
            right_raw = event.message.cmd[0]
            left_raw = event.message.cmd[1]
            
            # Sample speichern
            sample = {
                'timestamp': time.time(),
                'left_raw': left_raw,
                'right_raw': right_raw
            }
            self.samples_this_step.append(sample)
            
            # Live-Anzeige
            elapsed = time.time() - self.step_start_time
            remaining = self.calibration_steps[self.current_step]['duration'] - elapsed
            
            if len(self.samples_this_step) % 5 == 0:  # Alle 5 Samples
                print(f"⏱️  {remaining:.1f}s | Links: {left_raw:4d} | Rechts: {right_raw:4d}")
    
    def finish_current_step(self):
        """Beendet den aktuellen Schritt und analysiert die Daten"""
        if not self.samples_this_step:
            print("⚠️  Keine Daten gesammelt!")
            return
            
        step_name = self.calibration_steps[self.current_step]['name']
        
        # Statistiken berechnen
        left_values = [s['left_raw'] for s in self.samples_this_step]
        right_values = [s['right_raw'] for s in self.samples_this_step]
        
        stats = {
            'left': {
                'min': min(left_values),
                'max': max(left_values),
                'avg': sum(left_values) / len(left_values),
                'samples': len(left_values)
            },
            'right': {
                'min': min(right_values),
                'max': max(right_values),
                'avg': sum(right_values) / len(right_values),
                'samples': len(right_values)
            },
            'raw_samples': self.samples_this_step
        }
        
        self.step_data[step_name] = stats
        
        # Ergebnisse anzeigen
        print(f"\n📊 ERGEBNISSE für {step_name}:")
        print(f"   Links  - Min: {stats['left']['min']:4d} | Max: {stats['left']['max']:4d} | Avg: {stats['left']['avg']:6.1f}")
        print(f"   Rechts - Min: {stats['right']['min']:4d} | Max: {stats['right']['max']:4d} | Avg: {stats['right']['avg']:6.1f}")
        print(f"   Samples: {stats['left']['samples']}")
        
        self.collecting = False
        self.current_step += 1
    
    def run_calibration(self, node):
        """Führt die komplette geführte Kalibrierung durch"""
        print("🎯 GEFÜHRTE DroneCAN ESC KALIBRIERUNG")
        print("="*60)
        print("📋 Diese Kalibrierung führt Sie durch alle Bewegungen")
        print("⚠️  WICHTIG: Fahrzeug muss ARMED sein!")
        print("🎮 Verwenden Sie Ihren Single-Stick für alle Bewegungen")
        print("\nDrücken Sie ENTER um zu beginnen...")
        input()
        
        # Durch alle Schritte gehen
        while self.start_next_step():
            step_duration = self.calibration_steps[self.current_step - 1]['duration']
            end_time = time.time() + step_duration
            
            # Daten sammeln für die angegebene Dauer
            while time.time() < end_time:
                node.spin(timeout=0.1)
            
            self.finish_current_step()
            
            if self.current_step < len(self.calibration_steps):
                print("\n⏸️  Kurze Pause... Nächster Schritt in 2 Sekunden")
                time.sleep(2)
    
    def generate_final_report(self):
        """Erstellt den finalen Kalibrierungsbericht"""
        print("\n" + "="*60)
        print("🎯 FINALER KALIBRIERUNGSBERICHT")
        print("="*60)
        
        # Globale Min/Max-Werte finden
        global_left_min = 8191
        global_left_max = 0
        global_right_min = 8191
        global_right_max = 0
        
        print(f"\n📊 DETAILLIERTE ERGEBNISSE:")
        print(f"{'Bewegung':<15} {'Links Min':<10} {'Links Max':<10} {'Rechts Min':<11} {'Rechts Max':<11}")
        print("-" * 60)
        
        for step_name, data in self.step_data.items():
            left_min = data['left']['min']
            left_max = data['left']['max']
            right_min = data['right']['min']
            right_max = data['right']['max']
            
            print(f"{step_name:<15} {left_min:<10} {left_max:<10} {right_min:<11} {right_max:<11}")
            
            # Globale Extremwerte aktualisieren
            global_left_min = min(global_left_min, left_min)
            global_left_max = max(global_left_max, left_max)
            global_right_min = min(global_right_min, right_min)
            global_right_max = max(global_right_max, right_max)
        
        print("\n" + "="*60)
        print("🎯 GLOBALE BEREICHE:")
        print(f"   Links  - Min: {global_left_min:4d} | Max: {global_left_max:4d} | Range: {global_left_max - global_left_min:4d}")
        print(f"   Rechts - Min: {global_right_min:4d} | Max: {global_right_max:4d} | Range: {global_right_max - global_right_min:4d}")
        
        # Asymmetrie-Analyse
        left_range = global_left_max - global_left_min
        right_range = global_right_max - global_right_min
        
        if left_range > 0 and right_range > 0:
            asymmetry = abs(left_range - right_range) / max(left_range, right_range) * 100
            print(f"\n⚖️  ASYMMETRIE-ANALYSE:")
            print(f"   Range-Unterschied: {abs(left_range - right_range)} Raw-Werte")
            print(f"   Asymmetrie: {asymmetry:.1f}%")
            
            if asymmetry > 10:
                print("   ⚠️  WARNUNG: Hohe Asymmetrie - Software-Kalibrierung empfohlen!")
            elif asymmetry > 5:
                print("   ⚡ Moderate Asymmetrie - Software-Kalibrierung möglich")
            else:
                print("   ✅ Niedrige Asymmetrie - gut kalibriert")
        
        return {
            'global_ranges': {
                'left': {'min': global_left_min, 'max': global_left_max, 'range': left_range},
                'right': {'min': global_right_min, 'max': global_right_max, 'range': right_range}
            },
            'asymmetry_percent': asymmetry if 'asymmetry' in locals() else 0,
            'step_data': self.step_data,
            'timestamp': datetime.now().isoformat()
        }
    
    def save_calibration(self, filename='guided_esc_calibration.json'):
        """Speichert die Kalibrierungsdaten"""
        calibration_data = self.generate_final_report()
        
        with open(filename, 'w') as f:
            json.dump(calibration_data, f, indent=2)
        
        print(f"\n✅ Kalibrierungsdaten gespeichert in: {filename}")
        return True

def main():
    try:
        # DroneCAN Node initialisieren
        node = dronecan.make_node('can0', node_id=100, bitrate=1000000)
        
        # Geführtes Kalibrierungs-Tool erstellen
        calibrator = GuidedCalibrationTool()
        
        # Handler registrieren
        node.add_handler(dronecan.uavcan.equipment.esc.RawCommand, calibrator.esc_rawcommand_handler)
        
        print("🤖 DroneCAN Node gestartet (can0, 1 Mbps)")
        
        # Kalibrierung durchführen
        calibrator.run_calibration(node)
        
        # Finalen Bericht erstellen und speichern
        calibrator.save_calibration()
        
        print("\n🎯 Geführte Kalibrierung erfolgreich abgeschlossen!")
        
    except KeyboardInterrupt:
        print("\n\n🛑 Kalibrierung abgebrochen durch Benutzer")
        
    except Exception as e:
        print(f"❌ Fehler: {e}")

if __name__ == "__main__":
    main()
