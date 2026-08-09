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
import glob
import subprocess
from pathlib import Path

# Konfiguration laden
sys.path.insert(0, str(Path(__file__).parent))
import config
from gps_handler import GPSHandler
from ntrip_client import NTRIPClient
from gps_ntrip_bridge import GPSNTRIPBridge
from can_protocol import CANProtocol
from telemetry_payload import build_status_payload, build_telemetry_payload, serialize_can_payload
from vehicle_geometry import build_local_footprint, build_visual_markers_local, correct_to_vehicle_center, load_vehicle_geometry, select_heading_for_visualization
from imu_heading_calibration import ImuHeadingOffsetEstimator
from web_auth import LoginThrottle, WebAuthGuard

# Logging konfigurieren
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT
)
logger = logging.getLogger(__name__)

# Flask imports
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
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
        self.can_bus = None
        self.can_send_lock = threading.Lock()
        self.resolved_gps_port = config.GPS_PORT
        self.resolved_imu_port = None
        self.can_messages_sent = 0
        self.can_send_errors = 0
        self.last_command = None
        self.last_command_time = None
        self.can_protocol = CANProtocol(
            max_frame_size=config.CAN_MAX_FRAME_SIZE,
            frame_timeout=config.CAN_FRAME_TIMEOUT
        )
        self.can_sender_thread = None
        self.can_receiver_thread = None
        self.last_nav_waypoints = []
        self.last_nav_mode = 'goto'
        self.last_nav_command = None
        self.last_nav_command_time = None
        self.last_nav_status = None
        self.last_nav_status_time = None
        self.app = Flask(__name__, template_folder='templates')
        self.vehicle_geometry = None
        self.vehicle_footprint_local = []
        self.vehicle_markers_local = {}
        self.imu_heading_estimator = None
        self.auth = None
        self._load_vehicle_geometry()
        self._init_auth()
        self._setup_routes()
        self._init_sensors()
        self._init_can_bus()

    def _load_vehicle_geometry(self):
        """Lädt die statische Fahrzeuggeometrie für UI/Diagnose."""
        try:
            self.vehicle_geometry = load_vehicle_geometry(config.VEHICLE_GEOMETRY_PATH)
            self.vehicle_footprint_local = build_local_footprint(self.vehicle_geometry)
            self.vehicle_markers_local = build_visual_markers_local(self.vehicle_geometry)
            dimensions = self.vehicle_geometry.get('dimensions_m', {})
            logger.info(
                "📐 Fahrzeuggeometrie geladen (%.2fm x %.2fm)",
                float(dimensions.get('length', 0.0)),
                float(dimensions.get('width', 0.0)),
            )
        except Exception as e:
            logger.warning(f"⚠️  Fahrzeuggeometrie konnte nicht geladen werden: {e}")
            self.vehicle_geometry = None
            self.vehicle_footprint_local = []
            self.vehicle_markers_local = {}

        self.imu_heading_estimator = self._build_imu_heading_estimator()

    def _build_imu_heading_estimator(self):
        """Erzeugt den IMU-Heading-Offset-Estimator anhand der Geometrie-Konfig."""
        cfg = (self.vehicle_geometry or {}).get('imu', {}).get('calibration', {}) or {}
        try:
            window_size = int(cfg.get('window_size', 60))
        except (TypeError, ValueError):
            window_size = 60
        try:
            min_samples = int(cfg.get('min_samples', 10))
        except (TypeError, ValueError):
            min_samples = 10
        try:
            max_rate = float(cfg.get('max_heading_rate_dps', 5.0))
        except (TypeError, ValueError):
            max_rate = 5.0
        statuses = cfg.get('allowed_rtk_statuses') or ['RTK FIXED', 'RTK FLOAT']
        try:
            statuses_tuple = tuple(str(s) for s in statuses)
        except TypeError:
            statuses_tuple = ('RTK FIXED', 'RTK FLOAT')
        return ImuHeadingOffsetEstimator(
            window_size=window_size,
            min_samples=min_samples,
            max_heading_rate_dps=max_rate,
            allowed_rtk_statuses=statuses_tuple,
        )
    
    def _init_sensors(self):
        """Initialisiert Sensoren"""
        logger.info("🚀 Initialisiere Sensoren...")

        gps_port = self._resolve_device_path(config.GPS_PORT)
        self.resolved_gps_port = gps_port
        logger.info(f"📡 Verwende GPS-Port: {gps_port}")

        # GPS initialisieren
        self.gps = GPSHandler(
            port=gps_port,
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
            try:
                from imu_handler import create_imu_handler
            except ImportError as e:
                logger.error(f"❌ IMU aktiviert, aber Abhängigkeit fehlt: {e}")
                logger.info("ℹ️  Starte ohne IMU")
                return

            imu_port = self._resolve_device_path(config.IMU_PORT)
            self.resolved_imu_port = imu_port
            logger.info(f"🧭 Verwende IMU-Port: {imu_port}")

            try:
                self.imu = create_imu_handler(
                    config.IMU_TYPE,
                    port=imu_port,
                    baudrate=config.IMU_BAUDRATE,
                    timeout=config.IMU_TIMEOUT,
                    sample_rate=config.IMU_SAMPLE_RATE,
                )
            except ValueError as e:
                logger.error(f"❌ Ungültige IMU-Konfiguration: {e}")
                logger.info("ℹ️  Starte ohne IMU")
                return

            if self.imu.connect():
                imu_status = self.imu.get_status() if hasattr(self.imu, 'get_status') else {}
                logger.info(f"✅ IMU aktiviert ({imu_status.get('imu_type', config.IMU_TYPE)})")
                logger.info("ℹ️  WitMotion liefert native Orientierung und Bewegungsdaten")
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

            # CAN Sender Thread starten (50Hz) - nur wenn Telemetrie per CAN aktiv
            if config.CAN_TELEMETRY_ENABLED:
                self.can_sender_thread = threading.Thread(target=self._can_sender_loop, daemon=True)
                self.can_sender_thread.start()
            else:
                logger.info("ℹ️  CAN-Telemetrie-Versand deaktiviert (CAN_TELEMETRY_ENABLED=false), Empfang bleibt aktiv")

            # CAN Receiver Thread starten
            self.can_receiver_thread = threading.Thread(target=self._can_receiver_loop, daemon=True)
            self.can_receiver_thread.start()

            logger.info(f"✅ CAN-Bus initialisiert ({config.CAN_INTERFACE}, {config.CAN_BITRATE} bps)")

        except Exception as e:
            logger.error(f"❌ CAN-Bus Initialisierung fehlgeschlagen: {e}")
            self.can_bus = None

    def _can_sender_loop(self):
        """Sendet Sensor-Daten über CAN mit konfigurierbarer Rate"""
        interval = 1.0 / config.CAN_SEND_RATE

        while self.running:
            try:
                if not self.can_bus:
                    time.sleep(0.1)
                    continue

                # Sensor-Daten sammeln
                sensor_data = self._get_sensor_data()

                # JSON-String erstellen
                json_str = serialize_can_payload(sensor_data)

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

                if msg.arbitration_id != config.CAN_CONTROLLER_ID:
                    self.can_protocol.cleanup_old_buffers()
                    continue

                try:
                    json_str = self.can_protocol.decode_frame(msg.arbitration_id, bytes(msg.data))
                    if not json_str:
                        self.can_protocol.cleanup_old_buffers()
                        continue

                    data = json.loads(json_str)
                    self._process_can_command(data)
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️  CAN JSON-Decode Fehler: {e}")

                self.can_protocol.cleanup_old_buffers()

            except Exception as e:
                logger.error(f"❌ CAN-Receiver Fehler: {e}")
                time.sleep(0.1)

    def _get_sensor_data(self):
        """Sammelt aktuelle Sensor-Daten"""
        gps_status = None
        if self.gps:
            gps_status = self.gps.get_status()

        imu_data = None
        orientation = None
        if self.imu and self.imu.connected:
            imu_data = self.imu.get_data()
            orientation = self._get_orientation()

        heading_info = self._compute_heading_info(gps_status, orientation)
        gps_status_for_payload = self._apply_lever_arm_correction(gps_status, heading_info)
        return build_telemetry_payload(
            gps_status=gps_status_for_payload,
            orientation=orientation,
            imu_data=imu_data,
            heading_info=heading_info,
        )

    def _apply_lever_arm_correction(self, gps_status, heading_info):
        """Erzeugt eine Kopie von ``gps_status`` mit lat/lon am Fahrzeugzentrum.

        Wendet den Hebelarm der GPS-Primärantenne an, sofern Geometrie und ein
        verlässliches Heading vorliegen. Lässt ``gps_status`` unverändert,
        wenn keine Korrektur möglich ist.
        """
        if not gps_status:
            return gps_status
        heading_source = (heading_info or {}).get('heading_source')
        if heading_source in (None, '', 'unknown'):
            return gps_status
        heading_deg = (heading_info or {}).get('heading_deg')
        if heading_deg is None:
            return gps_status
        try:
            ant_lat = float(gps_status.get('latitude'))
            ant_lon = float(gps_status.get('longitude'))
        except (TypeError, ValueError):
            return gps_status
        center_lat, center_lon = correct_to_vehicle_center(
            antenna_latitude=ant_lat,
            antenna_longitude=ant_lon,
            heading_deg=heading_deg,
            geometry=self.vehicle_geometry,
        )
        if center_lat == ant_lat and center_lon == ant_lon:
            return gps_status
        corrected = dict(gps_status)
        corrected['latitude'] = center_lat
        corrected['longitude'] = center_lon
        return corrected

    def _get_orientation(self):
        """Liefert Orientierung direkt vom WitMotion-Treiber."""
        if not self.imu or not self.imu.connected:
            return None

        if hasattr(self.imu, 'get_orientation'):
            return self.imu.get_orientation()

        return None

    def _get_motion_status(self):
        """Liefert Bewegungsstatus direkt vom WitMotion-Treiber."""
        if self.imu and hasattr(self.imu, 'get_motion_status'):
            return self.imu.get_motion_status()

        return None

    def _compute_heading_info(self, gps_status, orientation):
        """Berechnet die korrigierte Heading inkl. Offsets (zentral für Pose+CAN).

        Aktualisiert bei verfügbarem dual-Antenna-GPS auch den
        IMU-Live-Offset-Estimator und liefert das Ergebnis von
        :func:`select_heading_for_visualization`. GPS-Heading hat Vorrang vor
        IMU-Yaw.
        """
        gnss_cfg = (self.vehicle_geometry or {}).get('gnss', {}) if self.vehicle_geometry else {}
        try:
            gps_heading_offset = float(gnss_cfg.get('heading_offset_deg', 0.0))
        except (TypeError, ValueError):
            gps_heading_offset = 0.0

        imu_cfg = (self.vehicle_geometry or {}).get('imu', {}) if self.vehicle_geometry else {}
        try:
            imu_static_offset = float(imu_cfg.get('heading_offset_deg', 0.0))
        except (TypeError, ValueError):
            imu_static_offset = 0.0

        gps_heading_raw = None
        if gps_status is not None:
            try:
                gps_heading_raw = float(gps_status.get('heading', 0.0))
            except (TypeError, ValueError):
                gps_heading_raw = None
        imu_heading = None
        if orientation is not None:
            try:
                imu_heading = float(orientation.get('heading', 0.0))
            except (TypeError, ValueError):
                imu_heading = None

        if (
            self.imu_heading_estimator is not None
            and gps_heading_raw is not None
            and abs(gps_heading_raw) > 0.01
            and imu_heading is not None
        ):
            corrected_gps = (gps_heading_raw + gps_heading_offset) % 360.0
            self.imu_heading_estimator.update(
                corrected_gps_heading_deg=corrected_gps,
                imu_heading_deg=imu_heading,
                rtk_status=(gps_status or {}).get('rtk_status'),
                timestamp=time.time(),
            )

        live_offset = (
            self.imu_heading_estimator.current_offset_deg()
            if self.imu_heading_estimator is not None
            else None
        )
        if live_offset is not None:
            imu_offset_deg = live_offset
            imu_offset_source = 'live'
        elif abs(imu_static_offset) > 1e-6:
            imu_offset_deg = imu_static_offset
            imu_offset_source = 'static'
        else:
            imu_offset_deg = 0.0
            imu_offset_source = 'none'

        return select_heading_for_visualization(
            gps_status=gps_status,
            orientation=orientation,
            gps_heading_offset_deg=gps_heading_offset,
            imu_heading_offset_deg=imu_offset_deg,
            imu_offset_source=imu_offset_source,
        )

    def _get_vehicle_pose(self):
        """Liefert aktuelle Pose für Visualisierung/Diagnose."""
        gps_status = self.gps.get_status() if self.gps else None
        orientation = self._get_orientation() if self.imu and self.imu.connected else None

        heading_info = self._compute_heading_info(gps_status, orientation)
        corrected_gps = self._apply_lever_arm_correction(gps_status, heading_info)
        latitude = corrected_gps.get('latitude') if corrected_gps else None
        longitude = corrected_gps.get('longitude') if corrected_gps else None

        pose = {
            'latitude': latitude,
            'longitude': longitude,
            'heading_deg': heading_info['heading_deg'],
            'heading_source': heading_info['heading_source'],
        }
        for key in ('heading_raw_deg', 'heading_offset_deg',
                    'imu_heading_offset_deg', 'imu_offset_source'):
            if key in heading_info:
                pose[key] = heading_info[key]

        if self.imu_heading_estimator is not None:
            est_status = self.imu_heading_estimator.status()
            pose['imu_heading_calibration'] = {
                'sample_count': est_status['sample_count'],
                'window_size': est_status['window_size'],
                'min_samples': est_status['min_samples'],
                'ready': est_status['ready'],
                'live_offset_deg': est_status['live_offset_deg'],
                'last_reject_reason': est_status['last_reject_reason'],
            }
        return pose

    def _get_vehicle_footprint_response(self):
        """Erstellt die Antwort für Fahrzeuggeometrie/Footprint."""
        if not self.vehicle_geometry:
            return None

        return {
            'geometry': self.vehicle_geometry,
            'footprint': {
                'outline_local_m': self.vehicle_footprint_local,
                'reference_point': self.vehicle_geometry.get('reference_frame', {}).get('origin', 'vehicle_center'),
                'markers_local_m': self.vehicle_markers_local,
            },
            'pose': self._get_vehicle_pose(),
            'timestamp': time.time(),
        }

    def _get_status_response(self):
        """Erstellt eine erweiterte Status-Antwort für On-Demand-Kommandos."""
        return build_status_payload(
            self._get_sensor_data(),
            {
                'source': 'sensor_hub_status',
                'gps_connected': bool(self.gps and self.gps.running),
                'gps_port': self.resolved_gps_port,
                'imu_enabled': config.IMU_ENABLED,
                'imu_type': config.IMU_TYPE,
                'imu_connected': bool(self.imu and self.imu.connected),
                'imu_port': self.resolved_imu_port,
                'ntrip_enabled': config.NTRIP_ENABLED,
                'ntrip_connected': bool(self.ntrip and self.ntrip.is_connected()),
                'can_enabled': bool(self.can_bus),
                'can_interface': config.CAN_INTERFACE,
                'messages_sent': self.can_messages_sent,
                'send_errors': self.can_send_errors,
                'last_command': self.last_command,
                'last_command_time': self.last_command_time,
            }
        )

    def _send_can_json(self, json_str):
        """Sendet JSON-String über CAN (Multi-Frame für längere Nachrichten)"""
        if not self.can_bus:
            return False

        with self.can_send_lock:
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
                    arbitration_id=config.CAN_SENSOR_HUB_ID,
                    data=frame_data,
                    is_extended_id=False
                )

                try:
                    self.can_bus.send(msg)
                    # Kleine Pause zwischen Frames
                    time.sleep(0.001)  # 1ms
                except Exception as e:
                    self.can_send_errors += 1
                    logger.error(f"❌ CAN-Send Fehler (Frame {frame_idx}/{total_frames}): {e}")
                    return False

        self.can_messages_sent += 1
        return True

    def _process_can_command(self, data):
        """Verarbeitet CAN-Befehle vom Controller"""
        cmd = data.get('cmd') or data.get('request')
        self.last_command = cmd
        self.last_command_time = round(time.time(), 3)

        if cmd == 'status_request' or cmd == 'sensor_status':
            logger.info("📡 Status-Anfrage empfangen")
            status_response = self._get_status_response()
            if self._send_can_json(serialize_can_payload(status_response)):
                logger.info("📤 Sensor-Status über CAN gesendet")

        elif cmd == 'restart':
            logger.warning("🔄 Restart-Befehl empfangen")
            threading.Thread(target=self._restart_service_async, daemon=True).start()

        elif cmd == 'nav_status':
            self.last_nav_status = {
                'state': data.get('state'),
                'running': bool(data.get('running')),
                'active_index': data.get('active_index'),
                'total': data.get('total'),
                'last_error': data.get('last_error'),
            }
            self.last_nav_status_time = round(time.time(), 3)
            logger.info(
                "🧭 Nav-Status empfangen: %s (idx=%s/%s)",
                self.last_nav_status['state'],
                self.last_nav_status['active_index'],
                self.last_nav_status['total'],
            )

        else:
            logger.debug(f"📡 Unbekannter CAN-Befehl: {cmd}")

    def _restart_service_async(self):
        """Startet den Sensor-Hub-Dienst asynchron neu."""
        try:
            time.sleep(0.5)
            subprocess.Popen(
                ['sudo', 'systemctl', 'restart', 'sensor-hub.service'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        except Exception as e:
            logger.error(f"❌ Restart fehlgeschlagen: {e}")

    def _init_auth(self):
        """Baut den Zugangsschutz auf und haengt ihn vor jede Route.

        Der Telemetriestrom des Raspberry laeuft ueber dieselben Routen. Passt
        das Passwort dort nicht, bleibt die Pose aus und der Fahrantrieb
        pausiert - der Fehler ist damit auffaellig, aber ungefaehrlich.
        """
        self.auth = WebAuthGuard(
            username=config.WEB_AUTH_USERNAME,
            password=config.WEB_AUTH_PASSWORD,
            realm=config.WEB_AUTH_REALM,
            enabled=config.WEB_AUTH_ENABLED,
            throttle=LoginThrottle(
                max_failures=config.WEB_AUTH_MAX_FAILURES,
                lockout_s=config.WEB_AUTH_LOCKOUT_S,
            ),
            logger=logger,
        )

        if not config.WEB_AUTH_ENABLED:
            logger.warning(
                "⚠️ SensorHub-Zugangsschutz ist ABGESCHALTET - die Position "
                "des Fahrzeugs liest jeder, der die Adresse kennt"
            )
        elif not self.auth.configured:
            logger.critical(
                "🔒 Kein WEB_AUTH_PASSWORD in der .env gesetzt - "
                "der SensorHub antwortet auf jede Anfrage mit 503"
            )
        else:
            logger.info(
                "🔒 SensorHub-Zugangsschutz aktiv (Benutzer %s)",
                config.WEB_AUTH_USERNAME,
            )

        @self.app.before_request
        def enforce_authentication():
            decision = self.auth.authorize(
                method=request.method,
                headers=request.headers,
                host=request.host,
                remote_addr=request.remote_addr or '',
            )
            if decision.allowed:
                return None

            response = jsonify({'error': decision.message})
            response.status_code = decision.status
            if decision.challenge:
                response.headers['WWW-Authenticate'] = (
                    f'Basic realm="{self.auth.realm}", charset="UTF-8"'
                )
            if decision.retry_after:
                response.headers['Retry-After'] = str(decision.retry_after)
            return response

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

        @self.app.route('/api/telemetry')
        def api_telemetry():
            """API: Exakt dieselbe kompakte Pose wie im CAN-Telemetriestrom."""
            return jsonify(self._get_sensor_data())

        @self.app.route('/api/telemetry/stream')
        def api_telemetry_stream():
            """Kontinuierlicher NDJSON-Strom der kompakten Sensor-Pose.

            Der Raspberry haelt damit eine TCP-Verbindung offen, statt fuer
            jedes 5-Hz-Telemetriepaket den NAT-Hairpin der Fritzbox erneut zu
            durchlaufen.
            """
            def generate():
                while self.running:
                    payload = self._get_sensor_data()
                    yield json.dumps(payload, separators=(',', ':')) + '\n'
                    time.sleep(0.2)

            return Response(
                stream_with_context(generate()),
                content_type='application/x-ndjson',
                headers={
                    'Cache-Control': 'no-cache, no-transform',
                    'X-Accel-Buffering': 'no',
                },
            )
        
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

        @self.app.route('/api/vehicle/geometry')
        def api_vehicle_geometry():
            """API: Statische Fahrzeuggeometrie"""
            if not self.vehicle_geometry:
                return jsonify({'error': 'Fahrzeuggeometrie nicht verfügbar'}), 503

            return jsonify(self.vehicle_geometry)

        @self.app.route('/api/vehicle/footprint')
        def api_vehicle_footprint():
            """API: Fahrzeug-Footprint für Visualisierung"""
            response = self._get_vehicle_footprint_response()
            if not response:
                return jsonify({'error': 'Fahrzeuggeometrie nicht verfügbar'}), 503

            return jsonify(response)
        
        @self.app.route('/api/health')
        def api_health():
            """API: Health Check"""
            return jsonify({
                'status': 'ok',
                'gps_connected': self.gps.running if self.gps else False,
                'ntrip_connected': self.ntrip.is_connected() if self.ntrip else False,
                'can_enabled': bool(self.can_bus),
                'gps_port': self.resolved_gps_port,
                'imu_enabled': config.IMU_ENABLED,
                'imu_type': config.IMU_TYPE,
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
            """API: IMU Sensor-Daten (Rohdaten + Orientierung)"""
            if not self.imu or not self.imu.connected:
                return jsonify({'error': 'IMU nicht verbunden'}), 503

            imu_data = self.imu.get_data()
            orientation = {'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0, 'heading': 0.0,
                          'is_stationary': False, 'gyro_bias': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                          'gps_weight': 0.0}
            imu_status = self.imu.get_status() if hasattr(self.imu, 'get_status') else {}
            driver_orientation = self._get_orientation()
            if driver_orientation:
                orientation = driver_orientation

            return jsonify({
                'accel': imu_data['accel'],
                'gyro': imu_data['gyro'],
                'mag': imu_data.get('mag'),
                'temperature': imu_data['temperature'],
                'roll': orientation['roll'],
                'pitch': orientation['pitch'],
                'yaw': orientation['yaw'],
                'heading': orientation['heading'],
                'is_calibrated': imu_data['is_calibrated'],
                'is_stationary': orientation['is_stationary'],
                'gyro_bias': orientation['gyro_bias'],
                'gps_weight': orientation['gps_weight'],
                'imu_type': imu_status.get('imu_type', config.IMU_TYPE),
                'orientation_source': orientation.get('source', imu_status.get('orientation_source', 'unknown')),
                'timestamp': imu_data['timestamp']
            })

        @self.app.route('/api/imu/status')
        def api_imu_status():
            """API: IMU Status"""
            if not self.imu:
                return jsonify({'error': 'IMU nicht aktiviert'}), 503

            return jsonify(self.imu.get_status())

        @self.app.route('/api/imu/motion')
        def api_imu_motion():
            """API: IMU Bewegungsstatus"""
            motion_status = self._get_motion_status()
            if not motion_status:
                return jsonify({'error': 'IMU Bewegungsstatus nicht verfügbar'}), 503

            return jsonify(motion_status)

        @self.app.route('/api/navigation/waypoints', methods=['GET', 'POST', 'DELETE', 'OPTIONS'])
        def api_navigation_waypoints():
            """Wegpunkte für die Motor-Controller-Navigation (Forward via CAN)."""
            if request.method == 'OPTIONS':
                return ('', 204)

            if request.method == 'GET':
                return jsonify({
                    'waypoints': list(self.last_nav_waypoints),
                    'mode': self.last_nav_mode,
                    'last_command': self.last_nav_command,
                    'last_command_time': self.last_nav_command_time,
                })

            if request.method == 'DELETE':
                ok = self._send_navigation_command({'cmd': 'nav_clear'})
                if ok:
                    self.last_nav_waypoints = []
                return jsonify({'success': ok, 'waypoints': []}), (200 if ok else 503)

            data = request.get_json(silent=True) or {}
            raw = data if isinstance(data, list) else data.get('waypoints')
            mode = 'goto' if isinstance(data, list) else data.get('mode', 'goto')
            if str(mode).lower() not in ('goto', 'track'):
                return jsonify({'error': 'mode muss goto oder track sein'}), 400
            try:
                waypoints = self._validate_waypoints(raw)
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400

            ok = self._send_navigation_command({
                'cmd': 'nav_set_waypoints',
                'mode': str(mode).lower(),
                'waypoints': waypoints,
            })
            if ok:
                self.last_nav_waypoints = waypoints
                self.last_nav_mode = str(mode).lower()
            return jsonify({'success': ok, 'waypoints': waypoints}), (200 if ok else 503)

        @self.app.route('/api/navigation/start', methods=['POST', 'OPTIONS'])
        def api_navigation_start():
            if request.method == 'OPTIONS':
                return ('', 204)
            ok = self._send_navigation_command({'cmd': 'nav_start'})
            return jsonify({'success': ok}), (200 if ok else 503)

        @self.app.route('/api/navigation/stop', methods=['POST', 'OPTIONS'])
        def api_navigation_stop():
            if request.method == 'OPTIONS':
                return ('', 204)
            ok = self._send_navigation_command({'cmd': 'nav_stop'})
            return jsonify({'success': ok}), (200 if ok else 503)

        @self.app.route('/api/navigation/status', methods=['GET'])
        def api_navigation_status():
            """Letzter über CAN gemeldeter Navigations-State des Motor-Controllers."""
            return jsonify({
                'status': self.last_nav_status,
                'status_time': self.last_nav_status_time,
            })

    def _send_navigation_command(self, payload):
        """Sendet einen Navigations-Befehl als JSON-Frame über CAN an den Motor-Controller."""
        if not self.can_bus:
            logger.warning("⚠️  Nav-Befehl ohne CAN-Bus verworfen: %s", payload.get('cmd'))
            return False
        try:
            json_str = serialize_can_payload(payload)
        except Exception as exc:
            logger.error(f"❌ Nav-Payload konnte nicht serialisiert werden: {exc}")
            return False
        ok = self._send_can_json(json_str)
        if ok:
            self.last_nav_command = payload.get('cmd')
            self.last_nav_command_time = round(time.time(), 3)
            logger.info("📤 Nav-Befehl über CAN gesendet: %s", self.last_nav_command)
        return ok

    @staticmethod
    def _validate_waypoints(raw):
        if not isinstance(raw, list) or not raw:
            raise ValueError('Mindestens ein Wegpunkt {latitude, longitude} erforderlich')
        cleaned = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f'Wegpunkt {index + 1} muss ein Objekt sein')
            lat = item.get('latitude', item.get('lat'))
            lon = item.get('longitude', item.get('lon', item.get('lng')))
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except (TypeError, ValueError):
                raise ValueError(f'Wegpunkt {index + 1} benötigt latitude/longitude')
            if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
                raise ValueError(f'Wegpunkt {index + 1} außerhalb gültiger Grenzen')
            cleaned.append({'latitude': round(lat_f, 7), 'longitude': round(lon_f, 7)})
        return cleaned

    @staticmethod
    def _resolve_device_path(path_pattern: str) -> str:
        """Löst Wildcards für stabile /dev/serial/by-id-Pfade auf."""
        if any(token in path_pattern for token in '*?['):
            matches = sorted(glob.glob(path_pattern))
            if matches:
                return matches[0]
        return path_pattern
    
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
