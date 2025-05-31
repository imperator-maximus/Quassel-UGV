#!/usr/bin/env python3
"""
Test WiFi Connection to Orange Cube
Quick test to verify WiFi Bridge connectivity before Lua upload
"""

import time
from pymavlink import mavutil

def test_wifi_connection():
    print("=" * 70)
    print("    📶 WiFi Verbindungstest - Orange Cube")
    print("=" * 70)
    print("Testet WiFi Bridge Verbindung zu 192.168.178.101")
    print("=" * 70)

    # WiFi Bridge settings
    wifi_ip = "192.168.178.101"
    wifi_port = 14550

    print(f"🔌 Teste WiFi Verbindung...")
    print(f"   IP: {wifi_ip}:{wifi_port}")

    try:
        # Connect via UDP (WiFi) - WICHTIG: UDP nicht TCP!
        connection_string = f"udpin:0.0.0.0:{wifi_port}"
        print(f"   Verbindungsstring: {connection_string}")

        connection = mavutil.mavlink_connection(connection_string)
        print(f"   Warte auf Heartbeat...")

        connection.wait_heartbeat(timeout=10)
        print("✅ WiFi Verbindung erfolgreich!")
        print(f"   System ID: {connection.target_system}")
        print(f"   Component ID: {connection.target_component}")

        # Test parameter read
        print(f"\n🔍 Teste Parameter-Zugriff...")

        # Verwende korrekte System/Component IDs wie vorgeschlagen
        vehicle_sysid = connection.target_system
        vehicle_compid = mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1  # Explizit Autopilot anfragen

        connection.mav.param_request_read_send(
            vehicle_sysid,
            vehicle_compid,
            b'SYSID_THISMAV',
            -1
        )

        msg = connection.recv_match(type='PARAM_VALUE', blocking=True, timeout=5)
        if msg:
            try:
                # Bessere Behandlung des param_id
                if isinstance(msg.param_id, bytes):
                    param_name = msg.param_id.strip(b'\x00').decode('utf-8')
                elif isinstance(msg.param_id, str):
                    param_name = msg.param_id.strip('\x00')
                else:
                    param_name = str(msg.param_id)
                print(f"✅ Parameter gelesen: {param_name} = {msg.param_value}")
            except Exception as e:
                print(f"⚠️  Parameter-Dekodierung fehlgeschlagen: {e}")
                print(f"   Raw param_id: {msg.param_id} (type: {type(msg.param_id)})")
                print(f"   Param value: {msg.param_value}")
        else:
            print("⚠️  Parameter-Zugriff timeout")

        # Test system status
        print(f"\n📊 Teste System Status...")
        msg = connection.recv_match(type='SYS_STATUS', blocking=True, timeout=5)
        if msg:
            print(f"✅ System Status empfangen")
            print(f"   Battery Voltage: {msg.voltage_battery/1000:.2f}V")
            print(f"   CPU Load: {msg.load/10:.1f}%")
        else:
            print("⚠️  System Status timeout")

        connection.close()

        print(f"\n" + "=" * 70)
        print("🎯 WiFi Verbindung funktioniert!")
        print("📤 Bereit für Lua Script Upload")
        print("🚀 Führe aus: python upload_lua_via_wifi.py")
        print("=" * 70)

        return True

    except Exception as e:
        print(f"❌ WiFi Verbindung fehlgeschlagen: {e}")
        print(f"\n💡 Troubleshooting:")
        print(f"   • Ist WiFi Bridge eingeschaltet?")
        print(f"   • Ist Orange Cube mit WiFi Bridge verbunden?")
        print(f"   • Ist IP 192.168.178.101 erreichbar?")
        print(f"   • Ping test: ping 192.168.178.101")
        print(f"   • Telnet test: telnet 192.168.178.101 14550")

        # Try other ports
        print(f"\n🔍 Versuche andere Ports...")
        for port in [14551, 5760, 5761]:
            try:
                connection_string = f"tcp:{wifi_ip}:{port}"
                print(f"   Teste Port {port}...")
                connection = mavutil.mavlink_connection(connection_string)
                connection.wait_heartbeat(timeout=3)
                print(f"✅ Verbindung über Port {port} erfolgreich!")
                connection.close()
                return True
            except:
                print(f"   Port {port} nicht erreichbar")
                continue

        print(f"\n❌ Keine WiFi Verbindung möglich")
        return False

if __name__ == "__main__":
    test_wifi_connection()
