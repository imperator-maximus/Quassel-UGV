#!/usr/bin/env python3
"""
Node ID Fix Verification Script
Testet ob das Beyond Robotics Board jetzt Node ID 25 verwendet statt DNA
"""

import serial
import time
import re
from datetime import datetime

class NodeIDTester:
    def __init__(self, port='COM8', baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.node_id_found = None
        self.dna_requests = 0
        self.fixed_id_confirmed = False

    def connect(self):
        """Verbindung zum Beyond Robotics Board herstellen"""
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            print(f"✅ Verbunden mit Beyond Robotics Board auf {self.port}")
            return True
        except Exception as e:
            print(f"❌ Verbindungsfehler: {e}")
            return False

    def parse_line(self, line):
        """Analysiert eine Zeile der seriellen Ausgabe"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Node ID Zuweisung
        if "Using fixed Node ID:" in line:
            try:
                node_id = int(line.split(":")[1].strip())
                self.node_id_found = node_id
                self.fixed_id_confirmed = True
                print(f"✅ {timestamp} | FIXED NODE ID BESTÄTIGT: {node_id}")
                return 'fixed_id'
            except (ValueError, IndexError):
                pass

        # DNA Requests (sollten NICHT auftreten)
        elif "Requesting ID" in line:
            self.dna_requests += 1
            try:
                requested_id = line.split("ID")[1].strip()
                print(f"⚠️ {timestamp} | DNA REQUEST (UNERWÜNSCHT): ID {requested_id}")
            except IndexError:
                print(f"⚠️ {timestamp} | DNA REQUEST (UNERWÜNSCHT)")
            return 'dna_request'

        # Node ID allocated (DNA Erfolg - sollte nicht passieren)
        elif "Node ID allocated:" in line:
            try:
                allocated_id = int(line.split(":")[1].strip())
                print(f"❌ {timestamp} | DNA ALLOCATION (PROBLEM): ID {allocated_id}")
                return 'dna_allocated'
            except (ValueError, IndexError):
                pass

        # DroneCAN Initialisierung
        elif "Setting fixed Node ID:" in line:
            try:
                config_id = int(line.split(":")[1].strip())
                print(f"🔧 {timestamp} | Konfigurierte Node ID: {config_id}")
                return 'config_id'
            except (ValueError, IndexError):
                pass

        # Node ID Parameter
        elif "Node ID:" in line and "NODEID" not in line:
            try:
                param_id = float(line.split(":")[1].strip())
                print(f"📋 {timestamp} | Parameter Node ID: {param_id}")
                return 'param_id'
            except (ValueError, IndexError):
                pass

        # CAN Initialisierung
        elif "CAN1 initialize ok" in line:
            print(f"🔗 {timestamp} | CAN-Bus initialisiert")
            return 'can_init'

        # System bereit
        elif "Ready for Orange Cube integration" in line:
            print(f"🚀 {timestamp} | System bereit für Orange Cube")
            return 'system_ready'

        return None

    def test_node_id(self, duration=30):
        """Testet Node ID Konfiguration für eine bestimmte Zeit"""
        print("=" * 80)
        print("    🔍 Node ID Fix Verification Test")
        print("=" * 80)
        print("Testet ob Beyond Robotics Board Node ID 25 verwendet")
        print("DNA (Dynamic Node Allocation) sollte NICHT auftreten")
        print("=" * 80)
        print()

        print(f"⏱️ Test läuft für {duration} Sekunden...")
        end_time = time.time() + duration
        print()

        try:
            while time.time() < end_time:
                if self.ser.in_waiting > 0:
                    try:
                        line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                        if line:
                            self.parse_line(line)
                    except (UnicodeDecodeError, IndexError, ValueError):
                        pass

                time.sleep(0.01)

        except KeyboardInterrupt:
            print("\n🛑 Test beendet")

        self.print_results()

    def print_results(self):
        """Zeigt Testergebnisse"""
        print("\n" + "=" * 80)
        print("    📊 TEST ERGEBNISSE")
        print("=" * 80)

        # Node ID Status
        if self.fixed_id_confirmed and self.node_id_found == 25:
            print("✅ ERFOLG: Fixed Node ID 25 bestätigt")
        elif self.node_id_found:
            print(f"⚠️ WARNUNG: Node ID {self.node_id_found} gefunden (erwartet: 25)")
        else:
            print("❌ FEHLER: Keine Node ID Bestätigung gefunden")

        # DNA Status
        if self.dna_requests == 0:
            print("✅ ERFOLG: Keine DNA Requests (korrekt)")
        else:
            print(f"❌ FEHLER: {self.dna_requests} DNA Requests gefunden")

        print("\n" + "=" * 80)
        print("    🎯 FAZIT")
        print("=" * 80)

        if self.fixed_id_confirmed and self.node_id_found == 25 and self.dna_requests == 0:
            print("🎉 NODE ID FIX ERFOLGREICH!")
            print("   ✅ Beyond Robotics Board verwendet Node ID 25")
            print("   ✅ Keine DNA Requests")
            print("   ✅ Orange Cube (Node 10) kann jetzt kommunizieren")
            print("\n🚀 Nächster Schritt: Orange Cube Test mit monitor_real_esc_commands.py")
        else:
            print("❌ NODE ID FIX FEHLGESCHLAGEN")
            print("   Mögliche Probleme:")
            if self.node_id_found != 25:
                print("   - Node ID nicht korrekt gesetzt")
            if self.dna_requests > 0:
                print("   - DNA Prozess läuft noch")
            print("\n🔧 Lösung: Firmware neu kompilieren und flashen")

def main():
    tester = NodeIDTester()

    if not tester.connect():
        print("❌ Kann nicht mit Beyond Robotics Board verbinden")
        print("Prüfen Sie:")
        print("- USB-Verbindung zu COM8")
        print("- Beyond Robotics Board ist eingeschaltet")
        print("- Hardware-Reset durchgeführt")
        return

    try:
        print("\n📋 Test-Optionen:")
        print("1. Schnelltest (30 Sekunden)")
        print("2. Ausführlicher Test (60 Sekunden)")
        print("3. Kurzer Test (10 Sekunden)")

        choice = input("\nWählen Sie eine Option (1-3): ").strip()

        if choice == '1':
            tester.test_node_id(30)
        elif choice == '2':
            tester.test_node_id(60)
        elif choice == '3':
            tester.test_node_id(10)
        else:
            print("❌ Ungültige Auswahl, verwende Standardtest (30s)")
            tester.test_node_id(30)

    except Exception as e:
        print(f"❌ Fehler: {e}")

    finally:
        if tester.ser and tester.ser.is_open:
            tester.ser.close()
            print("🔌 Serielle Verbindung geschlossen")

if __name__ == "__main__":
    main()
