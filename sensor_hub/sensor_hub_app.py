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
import json
from pathlib import Path

# Konfiguration laden
sys.path.insert(0, str(Path(__file__).parent))
import config
from gps_handler import GPSHandler
from ntrip_client import NTRIPClient
from gps_ntrip_bridge import GPSNTRIPBridge
from imu_handler_refactored import ICM42688P
from sensor_fusion import SensorFusion

# Logging konfigurieren
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT
)
logger = logging.getLogger(__name__)

# Flask imports
from flask import Flask, render_template, jsonify
import threading

# CAN imports
try:
    import can
    CAN_AVAILABLE = True
except ImportError:
    CAN_AVAILABLE = False
    logger.warning("⚠️  python-can nicht installiert, CAN deaktiviert")


class SensorHubApp:
    """Hauptanwendung für Sensor Hub"""

    def __init__(self):
        """Initialisiert Sensor Hub"""
        self.running = True
        self.gps = None
        self.ntrip = None
        self.bridge = None
        self.imu = None
        self.fusion = None  # Sensor Fusion Engine
        self.can_bus = None
        self.can_sender_thread = None
        self.can_receiver_thread = None
        self.app = Flask(__name__, template_folder='templates')
        self._setup_routes()
        self._init_sensors()
        self._init_can_bus()
    
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

        # IMU initialisieren wenn aktiviert
        if config.IMU_ENABLED:
            self.imu = ICM42688P(
                bus=config.IMU_BUS,
                address=config.IMU_ADDRESS,
                sample_rate=config.IMU_SAMPLE_RATE
            )

            if self.imu.connect():
                logger.info("✅ IMU (ICM-42688-P) aktiviert")

                # IMU kalibrieren (5 Sekunden warten für Stabilisierung)
                logger.info("⏳ Warte 5 Sekunden für IMU-Stabilisierung...")
                time.sleep(5.0)
                if self.imu.calibrate(samples=1000):
                    logger.info("✅ IMU kalibriert")

                # Sensor Fusion Engine initialisieren
                self.fusion = SensorFusion(sample_rate=config.IMU_SAMPLE_RATE)
                logger.info("✅ Sensor Fusion Engine initialisiert")

                # Fusion Thread starten
                self.fusion_thread = threading.Thread(target=self._sensor_fusion_loop, daemon=True)
                self.fusion_thread.start()
                logger.info("✅ Sensor Fusion Loop gestartet")
            else:
                logger.warning("⚠️  IMU konnte nicht verbunden werden")
                self.imu = None
        else:
            logger.info("ℹ️  IMU deaktiviert")

    def _init_can_bus(self):
        """Initialisiert CAN-Bus für JSON-Kommunikation"""
        if not config.CAN_ENABLED:
            logger.info("ℹ️  CAN deaktiviert")
            return

        if not CAN_AVAILABLE:
            logger.error("❌ python-can nicht verfügbar, CAN deaktiviert")
            return

        try:
            self.can_bus = can.interface.Bus(
                channel=config.CAN_INTERFACE,
                interface='socketcan'
                # bitrate nicht angeben, da CAN bereits via ip link konfiguriert ist
            )

            # CAN Sender Thread starten (50Hz)
            self.can_sender_thread = threading.Thread(target=self._can_sender_loop, daemon=True)
            self.can_sender_thread.start()

            # CAN Receiver Thread starten
            self.can_receiver_thread = threading.Thread(target=self._can_receiver_loop, daemon=True)
            self.can_receiver_thread.start()

            logger.info(f"✅ CAN-Bus initialisiert ({config.CAN_INTERFACE}, {config.CAN_BITRATE} bps)")

        except Exception as e:
            logger.error(f"❌ CAN-Bus Initialisierung fehlgeschlagen: {e}")
            self.can_bus = None

    def _can_sender_loop(self):
        """Sendet Sensor-Daten über CAN (50Hz)"""
        interval = 1.0 / config.FUSION_RATE  # 50Hz = 20ms

        while self.running:
            try:
                if not self.can_bus:
                    time.sleep(0.1)
                    continue

                # Sensor-Daten sammeln
                sensor_data = self._get_sensor_data()

                # JSON-String erstellen
                json_str = json.dumps(sensor_data)

                # CAN-Nachricht senden (max 8 Bytes pro Frame)
                # Bei längeren Nachrichten müssen wir fragmentieren
                self._send_can_json(json_str)

                time.sleep(interval)

            except Exception as e:
                logger.error(f"❌ CAN-Sender Fehler: {e}")
                time.sleep(0.1)

    def _can_receiver_loop(self):
        """Empfängt CAN-Befehle vom Controller"""
        while self.running:
            try:
                if not self.can_bus:
                    time.sleep(0.1)
                    continue

                msg = self.can_bus.recv(timeout=1.0)
                if msg is None:
                    continue

                # JSON aus CAN-Daten dekodieren
                try:
                    data = json.loads(msg.data.decode('utf-8'))
                    self._process_can_command(data)
                except:
                    pass  # Nicht-JSON Nachrichten ignorieren

            except Exception as e:
                logger.error(f"❌ CAN-Receiver Fehler: {e}")
                time.sleep(0.1)

    def _sensor_fusion_loop(self):
        """
        Sensor Fusion Loop
        Liest IMU-Rohdaten und GPS-Heading, führt Fusion durch
        """
        logger.info("🔄 Sensor Fusion Loop gestartet")

        while self.running:
            try:
                if self.imu and self.imu.connected and self.fusion:
                    # IMU-Rohdaten holen (kalibriert)
                    imu_data = self.imu.get_data()

                    # GPS Heading holen (falls verfügbar)
                    gps_heading = None
                    if self.gps:
                        gps_status = self.gps.get_status()
                        gps_heading = gps_status.get('heading')

                    # Fusion durchführen
                    self.fusion.update(
                        accel=imu_data['accel'],
                        gyro=imu_data['gyro'],
                        gps_heading=gps_heading
                    )

                time.sleep(1.0 / config.IMU_SAMPLE_RATE)  # Mit IMU-Sample-Rate laufen

            except Exception as e:
                logger.debug(f"⚠️  Sensor Fusion Fehler: {e}")
                time.sleep(0.1)

    def _get_sensor_data(self):
        """Sammelt aktuelle Sensor-Daten"""
        data = {
            'timestamp': time.time()
        }

        # GPS-Daten
        if self.gps:
            gps_status = self.gps.get_status()
            data['gps'] = {
                'lat': gps_status.get('latitude', 0.0),
                'lon': gps_status.get('longitude', 0.0),
                'altitude': gps_status.get('altitude', 0.0)
            }
            data['rtk_status'] = gps_status.get('quality_indicator', 'NONE')

        # IMU-Daten (Orientierung aus Fusion Engine)
        if self.imu and self.imu.connected and self.fusion:
            imu_data = self.imu.get_data()
            orientation = self.fusion.get_orientation()

            data['imu'] = {
                'roll': orientation['roll'],
                'pitch': orientation['pitch'],
                'yaw': orientation['yaw'],
                'heading': orientation['heading'],
                'is_calibrated': imu_data['is_calibrated']
            }
            # Heading aus Fusion Engine (fusioniert mit GPS wenn verfügbar)
            data['heading'] = orientation['heading']

        return data

    def _send_can_json(self, json_str):
        """Sendet JSON-String über CAN (Multi-Frame für längere Nachrichten)"""
        data_bytes = json_str.encode('utf-8')

        # Multi-Frame Übertragung (6 Bytes Nutzdaten pro Frame, 2 Bytes Header)
        chunk_size = 6
        total_frames = (len(data_bytes) + chunk_size - 1) // chunk_size

        for frame_idx in range(total_frames):
            start = frame_idx * chunk_size
            end = min(start + chunk_size, len(data_bytes))
            chunk = data_bytes[start:end]

            # Frame-Header: [frame_idx, total_frames, ...data (max 6 bytes)]
            frame_data = bytes([frame_idx, total_frames]) + chunk

            # Auf 8 Bytes auffüllen
            frame_data = frame_data + b'\x00' * (8 - len(frame_data))

            msg = can.Message(
                arbitration_id=0x100,  # Sensor Hub ID
                data=frame_data,
                is_extended_id=False
            )

            try:
                self.can_bus.send(msg)
                # Kleine Pause zwischen Frames
                time.sleep(0.001)  # 1ms
            except Exception as e:
                logger.error(f"❌ CAN-Send Fehler (Frame {frame_idx}/{total_frames}): {e}")
                break

    def _process_can_command(self, data):
        """Verarbeitet CAN-Befehle vom Controller"""
        cmd = data.get('cmd') or data.get('request')

        if cmd == 'status_request' or cmd == 'sensor_status':
            logger.info("📡 Status-Anfrage empfangen")
            # TODO: Status-Antwort senden

        elif cmd == 'restart':
            logger.warning("🔄 Restart-Befehl empfangen")
            # TODO: Restart implementieren

        else:
            logger.debug(f"📡 Unbekannter CAN-Befehl: {cmd}")

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

            status = self.gps.get_status()
            return jsonify({
                'latitude': status['latitude'],
                'longitude': status['longitude'],
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

        @self.app.route('/api/imu/data')
        def api_imu_data():
            """API: IMU Sensor-Daten (Rohdaten + Orientierung aus Fusion)"""
            if not self.imu or not self.imu.connected:
                return jsonify({'error': 'IMU nicht verbunden'}), 503

            # Rohdaten vom IMU
            imu_data = self.imu.get_data()

            # Orientierung von Fusion Engine
            orientation = {'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0, 'heading': 0.0}
            if self.fusion:
                orientation = self.fusion.get_orientation()

            return jsonify({
                'accel': imu_data['accel'],
                'gyro': imu_data['gyro'],
                'temperature': imu_data['temperature'],
                'roll': orientation['roll'],
                'pitch': orientation['pitch'],
                'yaw': orientation['yaw'],
                'heading': orientation['heading'],
                'is_calibrated': imu_data['is_calibrated'],
                'timestamp': imu_data['timestamp']
            })

        @self.app.route('/api/imu/status')
        def api_imu_status():
            """API: IMU Status"""
            if not self.imu:
                return jsonify({'error': 'IMU nicht aktiviert'}), 503

            return jsonify({
                'connected': self.imu.connected,
                'running': self.imu.running,
                'address': f'0x{self.imu.address:02x}',
                'bus': self.imu.bus_num,
                'sample_rate': self.imu.sample_rate
            })
    
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
        if self.imu:
            self.imu.disconnect()
        if self.gps:
            self.gps.disconnect()
        if self.can_bus:
            self.can_bus.shutdown()
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

