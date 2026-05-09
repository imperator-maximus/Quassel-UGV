#!/usr/bin/env python3
"""
S1-Bearing-Hold-Wegpunkt-Controller.

Pose-Daten kommen vom Sensor-Hub über den CAN-Bus (Telemetrie-Stream).
Der Controller wird per ``on_pose_update`` vom CAN-Handler gefüttert und
erzeugt Joystick-Kommandos für die vorhandene MotorControl-API mit Ramping.
"""

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class Waypoint:
    latitude: float
    longitude: float

    def as_dict(self) -> Dict[str, float]:
        return {'latitude': self.latitude, 'longitude': self.longitude}


class NavigationController:
    """Einfacher Bearing-Hold-Controller für Wegpunktnavigation."""

    def __init__(self, motor_control, config, safety_monitor=None):
        self.logger = logging.getLogger(__name__)
        self.motor = motor_control
        self.config = config
        self.safety = safety_monitor

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None
        self._waypoints: List[Waypoint] = []
        self._active_index = 0
        self._running = False
        self._state = 'idle'
        self._last_pose_time = 0.0
        self._last_command_time = 0.0
        self._last_error: Optional[str] = None
        self._last_pose: Optional[Dict[str, float]] = None
        self._last_command = {'x': 0.0, 'y': 0.0}
        self._last_debug_log = 0.0
        # Overshoot-Detector: minimale je erreichte Distanz zum aktiven Wegpunkt
        # plus Zähler aufeinanderfolgender Samples mit wachsender Distanz.
        self._waypoint_min_distance: Optional[float] = None
        self._waypoint_overshoot_count = 0

    def set_waypoints(self, raw_waypoints: Iterable[Dict[str, float]]) -> List[Dict[str, float]]:
        waypoints = [self._parse_waypoint(item) for item in raw_waypoints]
        if not waypoints:
            raise ValueError('Mindestens ein Wegpunkt ist erforderlich')

        with self._lock:
            self._waypoints = waypoints
            self._active_index = 0
            self._running = False
            self._state = 'ready'
            self._last_error = None
            self._last_command = {'x': 0.0, 'y': 0.0}
            self._waypoint_min_distance = None
            self._waypoint_overshoot_count = 0

        self._neutral_with_ramping()
        return [wp.as_dict() for wp in waypoints]

    def clear_waypoints(self) -> None:
        self.stop(reason='cleared')
        with self._lock:
            self._waypoints = []
            self._active_index = 0
            self._state = 'idle'
            self._last_error = None
            self._waypoint_min_distance = None
            self._waypoint_overshoot_count = 0

    def start(self) -> bool:
        with self._lock:
            if not self._waypoints:
                self._last_error = 'Keine Wegpunkte gesetzt'
                return False
            self._running = True
            self._state = 'running'
            self._active_index = min(self._active_index, len(self._waypoints) - 1)
            self._last_pose_time = time.time()
            self._last_error = None
            self._waypoint_min_distance = None
            self._waypoint_overshoot_count = 0

        self._ensure_watchdog()
        self.logger.info('🧭 Navigation gestartet (%d Wegpunkte)', len(self._waypoints))
        return True

    def stop(self, reason: str = 'stopped') -> None:
        with self._lock:
            was_running = self._running
            self._running = False
            if was_running:
                self._state = reason
            self._last_command = {'x': 0.0, 'y': 0.0}

        self._neutral_with_ramping()
        if was_running:
            self.logger.info('🛑 Navigation gestoppt: %s', reason)

    def shutdown(self) -> None:
        self.stop(reason='shutdown')
        self._stop_event.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=2.0)

    def on_pose_update(self, payload: Dict[str, Any]) -> None:
        """CAN-Telemetrie-Hook: extrahiert Pose und triggert einen Regelschritt."""
        try:
            lat, lon, heading = self._parse_pose(payload)
        except ValueError:
            return
        self._handle_pose(lat, lon, heading)

    def on_navigation_command(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """CAN-Befehls-Hook für nav_*-Kommandos vom Sensor-Hub."""
        cmd = payload.get('cmd')
        try:
            if cmd == 'nav_set_waypoints':
                waypoints = self.set_waypoints(payload.get('waypoints') or [])
                return {'ok': True, 'waypoints': waypoints}
            if cmd == 'nav_clear':
                self.clear_waypoints()
                return {'ok': True}
            if cmd == 'nav_start':
                return {'ok': self.start()}
            if cmd == 'nav_stop':
                self.stop()
                return {'ok': True}
        except ValueError as exc:
            self._set_error(str(exc))
            return {'ok': False, 'error': str(exc)}
        return {'ok': False, 'error': f'Unbekannter Nav-Befehl: {cmd}'}

    def get_status(self) -> Dict[str, object]:
        with self._lock:
            active = self._waypoints[self._active_index].as_dict() if self._waypoints and self._active_index < len(self._waypoints) else None
            return {
                'running': self._running,
                'state': self._state,
                'waypoints': [wp.as_dict() for wp in self._waypoints],
                'active_index': self._active_index,
                'active_waypoint': active,
                'last_pose_time': self._last_pose_time,
                'last_command_time': self._last_command_time,
                'last_pose': self._last_pose,
                'last_command': self._last_command.copy(),
                'last_error': self._last_error,
                'limits': {
                    'watchdog_timeout_s': self.config.watchdog_timeout_s,
                    'geofence_radius_m': self.config.geofence_radius_m,
                    'max_joystick': self.config.max_joystick,
                },
            }

    @staticmethod
    def distance_m(a: Waypoint, b: Waypoint) -> float:
        lat1 = math.radians(a.latitude)
        lat2 = math.radians(b.latitude)
        d_lat = lat2 - lat1
        d_lon = math.radians(b.longitude - a.longitude)
        h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
        return 6371000.0 * 2.0 * math.atan2(math.sqrt(h), math.sqrt(1.0 - h))

    @staticmethod
    def bearing_deg(a: Waypoint, b: Waypoint) -> float:
        lat1 = math.radians(a.latitude)
        lat2 = math.radians(b.latitude)
        d_lon = math.radians(b.longitude - a.longitude)
        y = math.sin(d_lon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
        return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    @staticmethod
    def heading_error_deg(target: float, current: float) -> float:
        return ((target - current + 540.0) % 360.0) - 180.0

    def _ensure_watchdog(self) -> None:
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return
        self._stop_event.clear()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        interval = max(0.05, min(0.5, float(self.config.watchdog_timeout_s) / 4.0))
        while not self._stop_event.is_set():
            self._check_watchdog()
            self._stop_event.wait(interval)

    def _handle_pose(self, lat: float, lon: float, heading: float) -> None:
        now = time.time()
        current = Waypoint(lat, lon)

        with self._lock:
            self._last_pose_time = now
            self._last_pose = {'latitude': lat, 'longitude': lon, 'heading_deg': heading}
            if not self._running or not self._waypoints:
                return
            first = self._waypoints[0]
            target = self._waypoints[self._active_index]

        if self.distance_m(first, current) > float(self.config.geofence_radius_m):
            self.stop(reason='geofence')
            self._set_error('Geofence überschritten')
            return

        distance = self.distance_m(current, target)
        if distance <= float(self.config.acceptance_radius_m):
            if self._advance_waypoint():
                return
            with self._lock:
                target = self._waypoints[self._active_index]
            distance = self.distance_m(current, target)

        # Overshoot-Detection: wenn das Fahrzeug schon nahe am Wegpunkt war
        # (innerhalb 2x Acceptance bzw. min. 0.5 m) und die Distanz danach
        # mehrere Samples in Folge wieder wächst, wurde der Wegpunkt physisch
        # passiert. Das löst den Endlos-Pivot-Modus auf, der entsteht, wenn
        # der reale Mindestabstand wegen GPS-Rauschen / Drivetrain-Trägheit
        # knapp über dem Acceptance-Radius liegt.
        acceptance = float(self.config.acceptance_radius_m)
        engagement_radius = max(2.0 * acceptance, 0.5)
        jitter_tolerance = 0.03  # 3 cm gegen RTK-Rauschen
        if self._waypoint_min_distance is None or distance < self._waypoint_min_distance:
            self._waypoint_min_distance = distance
            self._waypoint_overshoot_count = 0
        elif distance > self._waypoint_min_distance + jitter_tolerance:
            self._waypoint_overshoot_count += 1

        if (self._waypoint_min_distance is not None
                and self._waypoint_min_distance <= engagement_radius
                and self._waypoint_overshoot_count >= 2):
            self.logger.info(
                '🎯 Wegpunkt %d passiert (min=%.2fm, jetzt=%.2fm) → erreicht',
                self._active_index, self._waypoint_min_distance, distance,
            )
            if self._advance_waypoint():
                return
            with self._lock:
                target = self._waypoints[self._active_index]
            distance = self.distance_m(current, target)

        bearing = self.bearing_deg(current, target)
        error = self.heading_error_deg(bearing, heading)
        x, y = self._calculate_command(error, distance)
        self._send_command(x, y)

        if now - self._last_debug_log >= 1.0:
            self._last_debug_log = now
            self.logger.info(
                '🧭 nav: idx=%d dist=%.2fm bearing=%.1f° hdg=%.1f° err=%.1f° → x=%.3f y=%.3f',
                self._active_index, distance, bearing, heading, error, x, y,
            )

    def _advance_waypoint(self) -> bool:
        with self._lock:
            self._active_index += 1
            self._waypoint_min_distance = None
            self._waypoint_overshoot_count = 0
            if self._active_index >= len(self._waypoints):
                self._running = False
                self._state = 'completed'
                self._last_command = {'x': 0.0, 'y': 0.0}
                completed = True
            else:
                completed = False

        if completed:
            self._neutral_with_ramping()
            self.logger.info('✅ Navigation abgeschlossen')
        return completed

    def _calculate_command(self, heading_error: float, distance: float) -> Tuple[float, float]:
        limit = min(0.30, max(0.0, float(self.config.max_joystick)))
        turn = self._clamp(heading_error * float(self.config.turn_kp), -limit, limit)
        heading_factor = max(0.0, 1.0 - abs(heading_error) / 90.0)
        distance_factor = self._clamp(distance / float(self.config.slowdown_radius_m), 0.0, 1.0)
        forward = limit * heading_factor * distance_factor
        return turn, self._clamp(forward, 0.0, limit)

    def _send_command(self, x: float, y: float) -> None:
        self.motor.set_joystick(x, y, use_ramping=False)
        now = time.time()
        with self._lock:
            self._last_command_time = now
            self._last_command = {'x': x, 'y': y}
            self._last_error = None
        if self.safety:
            if hasattr(self.safety, 'update_command_time'):
                self.safety.update_command_time()
            if hasattr(self.safety, 'update_joystick_time'):
                self.safety.update_joystick_time()

    def _neutral_with_ramping(self) -> None:
        try:
            self.motor.set_joystick(0.0, 0.0, use_ramping=True)
        except Exception as e:
            self.logger.error('Neutral-Kommando fehlgeschlagen: %s', e)

    def _check_watchdog(self) -> None:
        with self._lock:
            running = self._running
            last_pose = self._last_pose_time
        if running and (not last_pose or time.time() - last_pose > float(self.config.watchdog_timeout_s)):
            self._set_error('CAN-Pose Watchdog-Timeout')
            self.stop(reason='watchdog')

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message
        self.logger.warning(message)

    @staticmethod
    def _parse_waypoint(item: Dict[str, float]) -> Waypoint:
        if not isinstance(item, dict):
            raise ValueError('Wegpunkt muss ein Objekt sein')
        lat = item.get('latitude', item.get('lat'))
        lon = item.get('longitude', item.get('lon', item.get('lng')))
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            raise ValueError('Wegpunkt benötigt latitude/longitude')
        if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
            raise ValueError('Wegpunkt-Koordinaten außerhalb gültiger Grenzen')
        return Waypoint(lat_f, lon_f)

    @staticmethod
    def _parse_pose(pose: Dict[str, Any]) -> Tuple[float, float, float]:
        """Akzeptiert sowohl die CAN-Telemetrie ({'gps':{'lat','lon'},'heading'})
        als auch flache Pose-Dicts ({'latitude','longitude','heading_deg'})."""
        if not isinstance(pose, dict):
            raise ValueError('Pose muss ein Objekt sein')
        gps = pose.get('gps') if isinstance(pose.get('gps'), dict) else None
        lat = pose.get('latitude', pose.get('lat'))
        lon = pose.get('longitude', pose.get('lon', pose.get('lng')))
        if lat is None and gps is not None:
            lat = gps.get('lat', gps.get('latitude'))
        if lon is None and gps is not None:
            lon = gps.get('lon', gps.get('lng', gps.get('longitude')))
        heading = pose.get('heading_deg', pose.get('heading'))
        if heading is None:
            imu = pose.get('imu') if isinstance(pose.get('imu'), dict) else None
            if imu is not None:
                heading = imu.get('heading')
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            heading_f = float(heading) % 360.0
        except (TypeError, ValueError):
            raise ValueError('Pose benötigt latitude/longitude/heading')
        if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
            raise ValueError('Pose-Koordinaten außerhalb gültiger Grenzen')
        return lat_f, lon_f, heading_f

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
