#!/usr/bin/env python3
"""
CAN Handler - CAN-Bus-Kommunikation mit Sensor Hub
JSON-basierte Kommunikation mit Multi-Frame-Support
"""

import json
import logging
import threading
import time
from typing import Optional, Dict, Any, Callable

try:
    import can
    CAN_AVAILABLE = True
except ImportError:
    CAN_AVAILABLE = False
    logging.warning("python-can nicht verfügbar - CAN-Funktionen deaktiviert")

from .can_protocol import CANProtocol


class CANHandler:
    """
    CAN-Bus-Handler für JSON-Kommunikation mit Sensor Hub
    Thread-Safe mit automatischer Reconnect-Logik
    """
    
    def __init__(self, config):
        """
        Initialisiert CAN-Handler
        
        Args:
            config: CANConfig-Instanz
        """
        self.logger = logging.getLogger(__name__)
        self.config = config
        
        # CAN-Bus
        self.can_available = CAN_AVAILABLE
        self.can_bus: Optional[can.interface.Bus] = None
        self.can_enabled = True
        
        # Protokoll
        self.protocol = CANProtocol(
            max_frame_size=config.max_frame_size,
            frame_timeout=config.frame_timeout
        )
        
        # Reader-Thread
        self.reader_running = False
        self.reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Sensor-Daten
        self._sensor_data: Dict[str, Any] = {}
        self._sensor_data_lock = threading.Lock()
        self._last_sensor_data_monotonic = 0.0

        # Empfangene ODrive/ODESC-Heartbeats. Diese Erfassung ist absichtlich
        # unabhaengig von der Maehdeck-Steuerung, damit die Web-Oberflaeche den
        # CAN-Netzwerkzustand auch bei gestopptem Maehdeck anzeigen kann.
        self._odrive_heartbeats: Dict[int, Dict[str, Any]] = {}
        self._odrive_heartbeats_lock = threading.Lock()
        
        # Callbacks
        self.sensor_data_callback: Optional[Callable] = None
        self.navigation_command_callback: Optional[Callable] = None
        self.odrive_heartbeat_callback: Optional[Callable] = None

        if self.can_available:
            self._init_can_bus()
    
    def _init_can_bus(self):
        """Initialisiert CAN-Bus"""
        try:
            self.can_bus = can.interface.Bus(
                channel=self.config.interface,
                interface='socketcan'
            )
            self.logger.info(f"✅ CAN-Bus initialisiert ({self.config.interface}, {self.config.bitrate} bps)")
        
        except Exception as e:
            self.logger.error(f"❌ CAN-Bus Initialisierung fehlgeschlagen: {e}")
            self.can_available = False
            self.can_bus = None
    
    def start_reader(self):
        """Startet CAN-Reader-Thread"""
        if self.reader_running:
            self.logger.warning("CAN-Reader läuft bereits")
            return
        
        if not self.can_available or not self.can_bus:
            self.logger.error("CAN-Bus nicht verfügbar - Reader kann nicht gestartet werden")
            return
        
        self.reader_running = True
        self._stop_event.clear()
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()
        self.logger.info("✅ CAN-Reader gestartet")
    
    def stop_reader(self):
        """Stoppt CAN-Reader-Thread"""
        if not self.reader_running:
            return
        
        self.reader_running = False
        self._stop_event.set()
        
        if self.reader_thread:
            self.reader_thread.join(timeout=2.0)
        
        self.logger.info("CAN-Reader gestoppt")
    
    def _reader_loop(self):
        """CAN-Reader-Loop mit Error-Recovery"""
        self.logger.info("CAN-Reader-Loop gestartet")
        error_count = 0
        max_errors = 10
        
        while not self._stop_event.is_set():
            try:
                if not self.can_bus:
                    self._stop_event.wait(1.0)
                    continue
                
                # CAN-Nachricht empfangen (mit Timeout)
                msg = self.can_bus.recv(timeout=1.0)
                
                if msg is None:
                    continue
                
                # Sensor Hub Nachrichten verarbeiten
                if msg.arbitration_id == self.config.sensor_hub_id:
                    json_str = self.protocol.decode_frame(msg.arbitration_id, msg.data)
                    
                    if json_str:
                        try:
                            data = json.loads(json_str)
                            self._process_sensor_data(data)
                            error_count = 0  # Reset bei Erfolg
                        
                        except json.JSONDecodeError as e:
                            self.logger.error(f"❌ JSON-Decode Fehler: {e}")
                            error_count += 1

                # ODrive/ODESC Heartbeat (CAN-Simple cmd 0x01) auswerten
                # Format: [uint32 error LE][uint32 state LE]
                # Arbitration-ID = (node_id << 5) | 0x01
                elif (msg.arbitration_id & 0x1F) == 0x01 and len(msg.data) >= 8:
                    import struct as _struct
                    node_id = msg.arbitration_id >> 5
                    odrive_error = _struct.unpack("<I", bytes(msg.data[0:4]))[0]
                    odrive_state = _struct.unpack("<I", bytes(msg.data[4:8]))[0]
                    self._record_odrive_heartbeat(node_id, odrive_error, odrive_state)
                    if self.odrive_heartbeat_callback:
                        try:
                            self.odrive_heartbeat_callback(node_id, odrive_error, odrive_state)
                        except Exception as e:
                            self.logger.error(f"❌ ODrive-Heartbeat Callback Fehler: {e}")

                # Alte Buffers aufräumen
                self.protocol.cleanup_old_buffers()
            
            except Exception as e:
                self.logger.error(f"❌ CAN-Reader Fehler: {e}")
                error_count += 1
                
                # Exponential Backoff bei Fehlern
                if error_count >= max_errors:
                    self.logger.critical(f"❌ Zu viele CAN-Fehler ({error_count}) - Reader pausiert")
                    self._stop_event.wait(5.0)
                    error_count = 0
                else:
                    backoff_time = min(0.1 * (2 ** error_count), 2.0)
                    self._stop_event.wait(backoff_time)
        
        self.logger.info("CAN-Reader-Loop beendet")
    
    def _process_sensor_data(self, data: Dict[str, Any]):
        """
        Verarbeitet Daten vom Sensor Hub (Thread-Safe).

        Trennt zwischen Telemetrie und Navigations-Befehlen anhand des
        ``cmd``-Feldes: ``cmd``-Strings die mit ``nav_`` beginnen werden an den
        ``navigation_command_callback`` weitergereicht und nicht in den
        Telemetrie-Cache geschrieben.
        """
        cmd = data.get('cmd') if isinstance(data, dict) else None
        if isinstance(cmd, str) and cmd.startswith('nav_'):
            if self.navigation_command_callback:
                try:
                    self.navigation_command_callback(data)
                except Exception as e:
                    self.logger.error(f"❌ Navigation-Command Callback Fehler: {e}")
            else:
                self.logger.debug(f"📡 Nav-Command ohne Listener verworfen: {cmd}")
            return

        with self._sensor_data_lock:
            self._sensor_data = data
            self._last_sensor_data_monotonic = time.monotonic()

        # Callback aufrufen
        if self.sensor_data_callback:
            try:
                self.sensor_data_callback(data)
            except Exception as e:
                self.logger.error(f"❌ Sensor-Data Callback Fehler: {e}")
    
    def get_sensor_data(self) -> Dict[str, Any]:
        """
        Gibt letzte Sensor-Daten zurück (Thread-Safe)
        
        Returns:
            Dictionary mit Sensor-Daten
        """
        with self._sensor_data_lock:
            return self._sensor_data.copy()
    
    def send_command(self, cmd_type: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Sendet JSON-Befehl an Sensor Hub
        
        Args:
            cmd_type: Befehlstyp (z.B. 'status_request', 'restart')
            data: Optional zusätzliche Daten
            
        Returns:
            True bei Erfolg, False bei Fehler
        """
        if not self.can_available or not self.can_bus:
            self.logger.error("CAN-Bus nicht verfügbar")
            return False
        
        try:
            # Nachricht erstellen
            msg_data = {'cmd': cmd_type}
            if data:
                msg_data.update(data)
            
            # In Frames kodieren
            frames = self.protocol.encode_message(msg_data)
            
            if not frames:
                return False
            
            # Frames senden
            for frame_data in frames:
                msg = can.Message(
                    arbitration_id=self.config.motor_controller_id,
                    data=frame_data,
                    is_extended_id=False
                )
                self.can_bus.send(msg)
            
            self.logger.debug(f"📤 CAN-Befehl gesendet: {msg_data}")
            return True
        
        except Exception as e:
            self.logger.error(f"❌ CAN-Befehl Fehler: {e}")
            return False
    
    def request_sensor_status(self) -> bool:
        """
        Fordert Sensor-Status vom Sensor Hub an
        
        Returns:
            True bei Erfolg, False bei Fehler
        """
        return self.send_command('status_request')
    
    def restart_sensor_hub(self) -> bool:
        """
        Startet Sensor Hub neu
        
        Returns:
            True bei Erfolg, False bei Fehler
        """
        return self.send_command('restart')
    
    def set_sensor_data_callback(self, callback: Callable):
        """
        Setzt Callback für Sensor-Daten

        Args:
            callback: Funktion die bei neuen Sensor-Daten aufgerufen wird
        """
        self.sensor_data_callback = callback

    def set_navigation_command_callback(self, callback: Callable):
        """
        Setzt Callback für Navigations-Befehle vom Sensor-Hub.

        Args:
            callback: Funktion die bei eingehenden ``cmd: 'nav_*'``-Payloads
                gerufen wird (z. B. ``nav_set_waypoints``, ``nav_start``).
        """
        self.navigation_command_callback = callback

    def set_odrive_heartbeat_callback(self, callback: Callable):
        """
        Setzt Callback für ODrive/ODESC-Heartbeat-Nachrichten.

        Wird bei jedem empfangenen Heartbeat (CAN-Simple cmd 0x01) gerufen.
        Signature: callback(node_id: int, error: int, state: int)

        Args:
            callback: Funktion die bei jedem ODrive-Heartbeat aufgerufen wird.
        """
        self.odrive_heartbeat_callback = callback

    def _record_odrive_heartbeat(self, node_id: int, error: int, state: int):
        """Speichert den letzten Heartbeat eines ODrive-Knotens."""
        with self._odrive_heartbeats_lock:
            self._odrive_heartbeats[int(node_id)] = {
                'error': int(error),
                'state': int(state),
                'last_seen_monotonic': time.monotonic(),
            }

    def get_status(
        self,
        expected_odrive_node_ids=None,
        sensor_timeout_s: float = 2.0,
        odrive_timeout_s: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Gibt CAN-Handler-Status zurück
        
        Returns:
            Dictionary mit Status-Informationen
        """
        now = time.monotonic()
        with self._sensor_data_lock:
            sensor_last_seen = self._last_sensor_data_monotonic
        sensor_age = None if sensor_last_seen <= 0.0 else max(0.0, now - sensor_last_seen)
        sensor_online = sensor_age is not None and sensor_age <= float(sensor_timeout_s)

        expected_nodes = [] if expected_odrive_node_ids is None else [
            int(node_id) for node_id in expected_odrive_node_ids
        ]
        with self._odrive_heartbeats_lock:
            heartbeat_snapshot = {
                node_id: dict(heartbeat)
                for node_id, heartbeat in self._odrive_heartbeats.items()
            }

        node_ids = sorted(set(expected_nodes) | set(heartbeat_snapshot))
        odrive_nodes = {}
        for node_id in node_ids:
            heartbeat = heartbeat_snapshot.get(node_id)
            age = None
            if heartbeat:
                age = max(0.0, now - heartbeat['last_seen_monotonic'])
            odrive_nodes[str(node_id)] = {
                'online': age is not None and age <= float(odrive_timeout_s),
                'age_s': None if age is None else round(age, 2),
                'error': None if heartbeat is None else heartbeat['error'],
                'state': None if heartbeat is None else heartbeat['state'],
            }

        expected_online = [
            node_id
            for node_id in expected_nodes
            if odrive_nodes.get(str(node_id), {}).get('online', False)
        ]
        expected_error_nodes = [
            node_id
            for node_id in expected_nodes
            if odrive_nodes.get(str(node_id), {}).get('error') not in (None, 0)
        ]
        all_expected_online = bool(expected_nodes) and len(expected_online) == len(expected_nodes)
        all_expected_healthy = all_expected_online and not expected_error_nodes
        interface_online = bool(self.can_available and self.can_enabled and self.reader_running)

        return {
            'can_available': self.can_available,
            'can_enabled': self.can_enabled,
            'reader_running': self.reader_running,
            'interface': self.config.interface,
            'bitrate': self.config.bitrate,
            'protocol_status': self.protocol.get_buffer_status(),
            'interface_online': interface_online,
            'sensor_hub': {
                'online': sensor_online,
                'age_s': None if sensor_age is None else round(sensor_age, 2),
                'can_id': self.config.sensor_hub_id,
            },
            'odrives': {
                'expected_node_ids': expected_nodes,
                'online_count': len(expected_online),
                'expected_count': len(expected_nodes),
                'all_online': all_expected_online,
                'error_node_ids': expected_error_nodes,
                'all_healthy': all_expected_healthy,
                'nodes': odrive_nodes,
            },
            'network_healthy': interface_online and sensor_online and all_expected_healthy,
        }
    
    def cleanup(self):
        """Cleanup CAN-Handler"""
        self.stop_reader()
        
        if self.can_bus:
            try:
                self.can_bus.shutdown()
            except:
                pass
        
        self.logger.info("CAN-Handler cleanup durchgeführt")
    
    def __del__(self):
        """Destruktor - Cleanup bei Objektzerstörung"""
        self.cleanup()

