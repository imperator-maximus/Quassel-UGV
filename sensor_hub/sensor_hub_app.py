#!/usr/bin/env python3
"""
Quassel UGV Sensor Hub - Hauptanwendung
RTK-GPS + IMU Sensor Fusion für Raspberry Pi Zero 2W
"""

import sys
import os
import logging
import signal
import time
from pathlib import Path

# Konfiguration laden
sys.path.insert(0, str(Path(__file__).parent))
import config
from gps_handler import GPSHandler
from ntrip_client import NTRIPClient
from gps_ntrip_bridge import GPSNTRIPBridge

# Logging konfigurieren
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT
)
logger = logging.getLogger(__name__)

# Flask imports
from flask import Flask, render_template, jsonify
import threading


class SensorHubApp:
    """Hauptanwendung für Sensor Hub"""
    
    def __init__(self):
        """Initialisiert Sensor Hub"""
        self.running = True
        self.gps = None
        self.ntrip = None
        self.bridge = None
        self.app = Flask(__name__, template_folder='templates')
        self._setup_routes()
        self._init_sensors()
    
    def _init_sensors(self):
        """Initialisiert Sensoren"""
        logger.info("🚀 Initialisiere Sensoren...")

        # GPS initialisieren
        self.gps = GPSHandler(
            port=config.GPS_PORT,
            baudrate=config.GPS_BAUDRATE,
            timeout=config.GPS_TIMEOUT
        )

        if self.gps.connect():
            logger.info("✅ GPS initialisiert")
        else:
            logger.error("❌ GPS-Initialisierung fehlgeschlagen")
            return

        # NTRIP initialisieren wenn aktiviert
        if config.NTRIP_ENABLED:
            self.ntrip = NTRIPClient(
                host=config.NTRIP_HOST,
                port=config.NTRIP_PORT,
                mountpoint=config.NTRIP_MOUNTPOINT,
                username=config.NTRIP_USERNAME,
                password=config.NTRIP_PASSWORD,
                timeout=config.NTRIP_TIMEOUT,
                reconnect_interval=config.NTRIP_RECONNECT_INTERVAL
            )

            # GPS-NTRIP Bridge starten
            self.bridge = GPSNTRIPBridge(self.gps, self.ntrip)
            if self.bridge.start():
                logger.info("✅ NTRIP/RTK aktiviert")
            else:
                logger.warning("⚠️  NTRIP konnte nicht verbunden werden")
        else:
            logger.info("ℹ️  NTRIP deaktiviert")
    
    def _setup_routes(self):
        """Konfiguriert Flask Routes"""
        
        @self.app.route('/')
        def index():
            """Hauptseite"""
            return render_template('sensor_hub.html')
        
        @self.app.route('/api/status')
        def api_status():
            """API: Aktueller Status"""
            if not self.gps:
                return jsonify({'error': 'GPS nicht initialisiert'}), 500
            
            status = self.gps.get_status()
            return jsonify({
                'gps': status,
                'timestamp': time.time()
            })
        
        @self.app.route('/api/coordinates')
        def api_coordinates():
            """API: Koordinaten"""
            if not self.gps:
                return jsonify({'error': 'GPS nicht initialisiert'}), 500
            
            lat, lon = self.gps.get_coordinates()
            return jsonify({
                'latitude': lat,
                'longitude': lon,
                'bing_maps_url': self.gps.get_bing_maps_url()
            })
        
        @self.app.route('/api/health')
        def api_health():
            """API: Health Check"""
            return jsonify({
                'status': 'ok',
                'gps_connected': self.gps.running if self.gps else False,
                'ntrip_connected': self.ntrip.is_connected() if self.ntrip else False,
                'timestamp': time.time()
            })

        @self.app.route('/api/ntrip/status')
        def api_ntrip_status():
            """API: NTRIP Status"""
            if not self.ntrip:
                return jsonify({'error': 'NTRIP nicht aktiviert'}), 503

            return jsonify(self.ntrip.get_status())

        @self.app.route('/api/bridge/status')
        def api_bridge_status():
            """API: GPS-NTRIP Bridge Status"""
            if not self.bridge:
                return jsonify({'error': 'Bridge nicht aktiviert'}), 503

            return jsonify(self.bridge.get_status())
    
    def run(self, host: str = None, port: int = None, debug: bool = None):
        """Startet die Anwendung"""
        host = host or config.WEB_HOST
        port = port or config.WEB_PORT
        debug = debug if debug is not None else config.WEB_DEBUG
        
        logger.info(f"🌐 Starte Web-Interface auf {host}:{port}")
        
        try:
            self.app.run(host=host, port=port, debug=debug, threaded=True)
        except KeyboardInterrupt:
            logger.info("⏹️  Beende Anwendung...")
            self.shutdown()
    
    def shutdown(self):
        """Beendet die Anwendung"""
        self.running = False
        if self.bridge:
            self.bridge.stop()
        if self.ntrip:
            self.ntrip.disconnect()
        if self.gps:
            self.gps.disconnect()
        logger.info("✅ Sensor Hub beendet")


def signal_handler(sig, frame):
    """Signal Handler für Ctrl+C"""
    logger.info("⏹️  Signal empfangen, beende...")
    sys.exit(0)


def main():
    """Haupteinstiegspunkt"""
    signal.signal(signal.SIGINT, signal_handler)
    
    app = SensorHubApp()
    app.run()


if __name__ == '__main__':
    main()

