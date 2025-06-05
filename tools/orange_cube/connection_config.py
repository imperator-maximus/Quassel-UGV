#!/usr/bin/env python3
"""
Orange Cube Connection Configuration
Zentrale Konfiguration für COM/WiFi Verbindungen zu Orange Cube

Unterstützt:
- USB/COM Verbindungen (COM4, COM5, etc.)
- WiFi Bridge Verbindungen (UDP)
- Automatische Verbindungstyp-Erkennung
- Einfache Integration in bestehende Scripts

Usage:
    from connection_config import get_connection
    connection = get_connection()
"""

import os
from pymavlink import mavutil

# ============================================================================
# GLOBALE KONFIGURATION
# ============================================================================

# Verbindungstyp: 'auto', 'com', 'wifi'
CONNECTION_TYPE = 'auto'

# COM Port Einstellungen
COM_PORT = 'COM4'
COM_BAUDRATE = 115200

# WiFi Bridge Einstellungen
WIFI_IP = '192.168.178.134'
WIFI_PORT = 14550

# Timeout für Verbindungsversuche
CONNECTION_TIMEOUT = 10

# ============================================================================
# VERBINDUNGS-FUNKTIONEN
# ============================================================================

def get_connection_string():
    """
    Gibt den korrekten Connection String basierend auf Konfiguration zurück
    
    Returns:
        str: MAVLink connection string
    """
    if CONNECTION_TYPE == 'com':
        return COM_PORT
    elif CONNECTION_TYPE == 'wifi':
        # WICHTIG: UDP Output verwenden (wie MAVProxy)
        return f"udpout:{WIFI_IP}:{WIFI_PORT}"
    elif CONNECTION_TYPE == 'auto':
        # Auto-Detection: Erst WiFi, dann COM
        return 'auto'
    else:
        raise ValueError(f"Unbekannter CONNECTION_TYPE: {CONNECTION_TYPE}")

def test_com_connection():
    """
    Testet COM Verbindung
    
    Returns:
        mavutil.mavlink_connection or None
    """
    try:
        print(f"   🔌 Teste COM Verbindung: {COM_PORT}")
        connection = mavutil.mavlink_connection(COM_PORT, baud=COM_BAUDRATE)
        connection.wait_heartbeat(timeout=3)
        print(f"   ✅ COM Verbindung erfolgreich")
        return connection
    except Exception as e:
        print(f"   ❌ COM Verbindung fehlgeschlagen: {e}")
        return None

def test_wifi_connection():
    """
    Testet WiFi Bridge Verbindung
    
    Returns:
        mavutil.mavlink_connection or None
    """
    try:
        print(f"   📶 Teste WiFi Verbindung: {WIFI_IP}:{WIFI_PORT}")
        # EXAKT wie MAVProxy: udpout mit input=True für bidirektionale Kommunikation
        connection_string = f"udpout:{WIFI_IP}:{WIFI_PORT}"
        print(f"   🔧 Connection String (wie MAVProxy): {connection_string}")

        # WICHTIG: input=True für bidirektionale UDP-Kommunikation!
        connection = mavutil.mavlink_connection(
            connection_string,
            baud=115200,        # Für UDP irrelevant, aber Standardwert
            source_system=255,  # Identifiziert Script als GCS
            input=True,         # KRITISCH: Aktiviert Input für udpout
            autoreconnect=True  # Auto-Reconnect bei Verbindungsverlust
        )

        print(f"   ⏰ Teste Verbindung ohne Heartbeat-Wait...")
        # Setze target_system/component manuell (wie MAVProxy es macht)
        connection.target_system = 1
        connection.target_component = 1

        print(f"   ✅ WiFi Verbindung erfolgreich (ohne Heartbeat-Wait)")
        print(f"   📡 Target System: {connection.target_system}, Component: {connection.target_component}")
        return connection

    except Exception as e:
        print(f"   ❌ WiFi Verbindung fehlgeschlagen: {e}")
        return None

def get_connection(verbose=True):
    """
    Stellt Verbindung zu Orange Cube her basierend auf Konfiguration
    
    Args:
        verbose (bool): Ausgabe von Status-Meldungen
        
    Returns:
        mavutil.mavlink_connection: Aktive Verbindung
        
    Raises:
        Exception: Wenn keine Verbindung hergestellt werden kann
    """
    if verbose:
        print("🔌 Orange Cube Verbindung wird hergestellt...")
        print(f"   Konfiguration: {CONNECTION_TYPE}")
    
    connection = None
    
    if CONNECTION_TYPE == 'com':
        connection = test_com_connection()
        
    elif CONNECTION_TYPE == 'wifi':
        connection = test_wifi_connection()
        
    elif CONNECTION_TYPE == 'auto':
        if verbose:
            print("   🔍 Auto-Detection: Teste verfügbare Verbindungen...")
        
        # Erst WiFi versuchen (oft bevorzugt)
        connection = test_wifi_connection()
        
        # Falls WiFi fehlschlägt, COM versuchen
        if connection is None:
            connection = test_com_connection()
    
    if connection is None:
        error_msg = f"❌ Keine Verbindung zu Orange Cube möglich!"
        if verbose:
            print(error_msg)
            print(f"   💡 Troubleshooting:")
            print(f"      • WiFi: Ist {WIFI_IP}:{WIFI_PORT} erreichbar?")
            print(f"      • COM: Ist {COM_PORT} verfügbar?")
            print(f"      • Ist Orange Cube eingeschaltet?")
        raise Exception(error_msg)
    
    if verbose:
        print(f"✅ Verbunden mit Orange Cube")
        print(f"   System ID: {connection.target_system}")
        print(f"   Component ID: {connection.target_component}")
    
    return connection

def get_connection_info():
    """
    Gibt Informationen über aktuelle Verbindungskonfiguration zurück
    
    Returns:
        dict: Verbindungsinformationen
    """
    return {
        'type': CONNECTION_TYPE,
        'com_port': COM_PORT,
        'com_baudrate': COM_BAUDRATE,
        'wifi_ip': WIFI_IP,
        'wifi_port': WIFI_PORT,
        'connection_string': get_connection_string() if CONNECTION_TYPE != 'auto' else 'auto-detect'
    }

def set_connection_type(conn_type):
    """
    Setzt den Verbindungstyp zur Laufzeit
    
    Args:
        conn_type (str): 'auto', 'com', oder 'wifi'
    """
    global CONNECTION_TYPE
    if conn_type not in ['auto', 'com', 'wifi']:
        raise ValueError(f"Ungültiger Verbindungstyp: {conn_type}")
    CONNECTION_TYPE = conn_type

def set_com_config(port, baudrate=115200):
    """
    Setzt COM Konfiguration zur Laufzeit
    
    Args:
        port (str): COM Port (z.B. 'COM4')
        baudrate (int): Baudrate (Standard: 115200)
    """
    global COM_PORT, COM_BAUDRATE
    COM_PORT = port
    COM_BAUDRATE = baudrate

def set_wifi_config(ip, port=14550):
    """
    Setzt WiFi Konfiguration zur Laufzeit
    
    Args:
        ip (str): WiFi Bridge IP (z.B. '192.168.178.101')
        port (int): WiFi Bridge Port (Standard: 14550)
    """
    global WIFI_IP, WIFI_PORT
    WIFI_IP = ip
    WIFI_PORT = port

# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

if __name__ == "__main__":
    print("🔧 Orange Cube Connection Config Test")
    print("=" * 50)
    
    # Zeige aktuelle Konfiguration
    config = get_connection_info()
    print(f"📋 Aktuelle Konfiguration:")
    for key, value in config.items():
        print(f"   {key}: {value}")
    
    print(f"\n🔍 Teste Verbindung...")
    try:
        connection = get_connection()
        print(f"🎯 Verbindung erfolgreich!")
        connection.close()
    except Exception as e:
        print(f"❌ Verbindung fehlgeschlagen: {e}")
