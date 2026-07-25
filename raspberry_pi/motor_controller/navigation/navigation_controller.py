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

        # Skid-Steer-PWM-Verhältnis turn_factor/forward_factor: aus dem
        # MotorControl-PWM-Config lesen (Fallback 0.6 = 300/500), wird in
        # _calculate_command für die Innen-Rad-Garantie gebraucht.
        pwm_cfg = getattr(motor_control, 'pwm_config', None)
        ff = float(getattr(pwm_cfg, 'forward_factor', 500.0) or 500.0)
        tf = float(getattr(pwm_cfg, 'turn_factor', 300.0))
        self._turn_to_forward_ratio = tf / ff if ff > 0 else 0.6

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None
        self._waypoints: List[Waypoint] = []
        self._mode = 'goto'
        self._direction = 'forward'
        self._track_lookahead_m = float(getattr(config, 'track_lookahead_m', 0.8))
        self._active_index = 0
        self._running = False
        self._paused = False
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
        # Goto-Fortschrittswächter. Die Referenz wird erst gesetzt, wenn das
        # Fahrzeug zum Ziel ausgerichtet ist. So kann die am Fahrzeugheck
        # sitzende GNSS-Antenne beim Pivot einen kleinen Bogen beschreiben,
        # ohne fälschlich einen Divergenzstopp auszulösen.
        self._waypoint_progress_reference: Optional[float] = None
        self._waypoint_divergence_count = 0
        self._track_aligning = False
        self._track_progress_m = 0.0
        self._track_stall_reference_m = 0.0
        self._track_stall_reference_time = 0.0

        # State-Feedback an Sensor-Hub/UI: feuert bei jedem Übergang.
        self._state_callback: Optional[Any] = None

    def set_state_callback(self, callback) -> None:
        """Registriert Callback für State-Änderungen (idle/ready/running/completed/stopped/error)."""
        self._state_callback = callback

    def _emit_state(self) -> None:
        cb = self._state_callback
        if cb is None:
            return
        with self._lock:
            payload = {
                'state': self._state,
                'mode': self._mode,
                'direction': self._direction,
                'running': self._running,
                'active_index': self._active_index,
                'total': len(self._waypoints),
                'last_error': self._last_error,
            }
        try:
            cb(payload)
        except Exception as exc:
            self.logger.warning('State-Callback Fehler: %s', exc)

    def set_waypoints(
        self,
        raw_waypoints: Iterable[Dict[str, float]],
        mode: str = 'goto',
        lookahead_m: Optional[float] = None,
        direction: str = 'forward',
    ) -> List[Dict[str, float]]:
        waypoints = [self._parse_waypoint(item) for item in raw_waypoints]
        if not waypoints:
            raise ValueError('Mindestens ein Wegpunkt ist erforderlich')
        mode = self._parse_mode(mode)
        direction = self._parse_direction(direction)
        if direction == 'reverse' and mode != 'track':
            raise ValueError('Rückwärtsfahrt ist nur im Track-Modus unterstützt')
        if mode == 'track' and len(waypoints) < 2:
            raise ValueError('Track-Modus benötigt mindestens zwei Wegpunkte')
        if lookahead_m is None:
            lookahead = float(getattr(self.config, 'track_lookahead_m', self._track_lookahead_m))
        else:
            try:
                lookahead = float(lookahead_m)
            except (TypeError, ValueError):
                raise ValueError('lookahead_m muss eine Zahl sein')
        if lookahead <= 0.0:
            raise ValueError('lookahead_m muss > 0 sein')

        with self._lock:
            self._waypoints = waypoints
            self._mode = mode
            self._direction = direction
            self._track_lookahead_m = lookahead
            self._active_index = 0
            self._running = False
            self._paused = False
            self._state = 'ready'
            self._last_error = None
            self._last_command = {'x': 0.0, 'y': 0.0}
            self._waypoint_min_distance = None
            self._waypoint_overshoot_count = 0
            self._waypoint_progress_reference = None
            self._waypoint_divergence_count = 0
            self._track_aligning = False
            self._track_progress_m = 0.0
            self._track_stall_reference_m = 0.0
            self._track_stall_reference_time = 0.0

        self._neutral_with_ramping()
        self._emit_state()
        return [wp.as_dict() for wp in waypoints]

    def clear_waypoints(self) -> None:
        self.stop(reason='cleared')
        with self._lock:
            self._waypoints = []
            self._mode = 'goto'
            self._direction = 'forward'
            self._active_index = 0
            self._state = 'idle'
            self._last_error = None
            self._waypoint_min_distance = None
            self._waypoint_overshoot_count = 0
            self._waypoint_progress_reference = None
            self._waypoint_divergence_count = 0
            self._track_aligning = False
            self._track_progress_m = 0.0
            self._track_stall_reference_m = 0.0
            self._track_stall_reference_time = 0.0
        self._emit_state()

    def start(self) -> bool:
        if (
            self.safety
            and hasattr(self.safety, 'is_motion_allowed')
            and not self.safety.is_motion_allowed()
        ):
            self._set_error('Sicherheitsstopp ist verriegelt')
            return False
        with self._lock:
            if not self._waypoints:
                self._last_error = 'Keine Wegpunkte gesetzt'
                started = False
            else:
                self._running = True
                self._paused = False
                self._state = 'running'
                self._active_index = min(self._active_index, len(self._waypoints) - 1)
                self._last_pose_time = time.time()
                self._last_error = None
                self._waypoint_min_distance = None
                self._waypoint_overshoot_count = 0
                self._waypoint_progress_reference = None
                self._waypoint_divergence_count = 0
                self._track_aligning = False
                self._track_progress_m = 0.0
                self._track_stall_reference_m = 0.0
                self._track_stall_reference_time = time.time()
                started = True

        if started:
            self._ensure_watchdog()
            self.logger.info('🧭 Navigation gestartet (%s, %d Wegpunkte)', self._mode, len(self._waypoints))
        self._emit_state()
        return started

    def stop(self, reason: str = 'stopped') -> None:
        with self._lock:
            was_running = self._running
            self._running = False
            self._paused = False
            if was_running:
                self._state = reason
            self._last_command = {'x': 0.0, 'y': 0.0}

        self._neutral_with_ramping()
        if self.safety and hasattr(self.safety, 'deactivate_command_watchdog'):
            self.safety.deactivate_command_watchdog()
        if was_running:
            self.logger.info('🛑 Navigation gestoppt: %s', reason)
            self._emit_state()

    def pause(self, reason: str = 'paused') -> bool:
        """Freeze navigation in memory without losing path progress."""
        with self._lock:
            if not self._running:
                return False
            if self._paused:
                return True
            self._paused = True
            self._state = reason
            self._last_command = {'x': 0.0, 'y': 0.0}

        self._neutral_with_ramping()
        if self.safety and hasattr(self.safety, 'deactivate_command_watchdog'):
            self.safety.deactivate_command_watchdog()
        self.logger.info('⏸️ Navigation eingefroren: %s', reason)
        self._emit_state()
        return True

    def resume(self) -> bool:
        """Continue an in-memory pause at the exact same waypoint/progress."""
        if (
            self.safety
            and hasattr(self.safety, 'is_motion_allowed')
            and not self.safety.is_motion_allowed()
        ):
            return False
        with self._lock:
            if not self._running or not self._paused:
                return False
            self._paused = False
            self._state = 'running'
            self._last_pose_time = time.time()
            self._last_error = None
            self._track_stall_reference_m = self._track_progress_m
            self._track_stall_reference_time = self._last_pose_time
        self.logger.info('▶️ Navigation aus Speicherpause fortgesetzt')
        self._emit_state()
        return True

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
                waypoints = self.set_waypoints(
                    payload.get('waypoints') or [],
                    mode=payload.get('mode', 'goto'),
                    lookahead_m=payload.get('lookahead_m'),
                    direction=payload.get('direction', 'forward'),
                )
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
                'paused': self._paused,
                'state': self._state,
                'mode': self._mode,
                'direction': self._direction,
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
                    'pivot_joystick': self._pivot_turn_level(),
                    'track_lookahead_m': self._track_lookahead_m,
                    'pivot_heading_threshold_deg': self._pivot_heading_threshold_deg(),
                    'goto_divergence_limit_m': float(getattr(self.config, 'goto_divergence_limit_m', 0.75)),
                    'goto_divergence_samples': int(getattr(self.config, 'goto_divergence_samples', 5)),
                'track_cross_track_limit_m': float(getattr(self.config, 'track_cross_track_limit_m', 1.0)),
                    'track_alignment_enter_deg': self._track_alignment_enter_deg(),
                    'track_alignment_exit_deg': self._track_alignment_exit_deg(),
                    'track_aligning': self._track_aligning,
                    'track_progress_m': round(self._track_progress_m, 2),
                    'track_stall_timeout_s': self._track_stall_timeout_s(),
                    'track_stall_min_progress_m': self._track_stall_min_progress_m(),
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
            if not self._running or self._paused or not self._waypoints:
                return
            first = self._waypoints[0]
            mode = self._mode
            direction = self._direction
            target = self._waypoints[self._active_index]

        if self.distance_m(first, current) > float(self.config.geofence_radius_m):
            self.stop(reason='geofence')
            self._set_error('Geofence überschritten')
            return

        if mode == 'track':
            self._handle_track_pose(current, heading, now, direction=direction)
            return

        distance = self.distance_m(current, target)
        if distance <= float(self.config.acceptance_radius_m):
            if self._advance_waypoint():
                return
            with self._lock:
                target = self._waypoints[self._active_index]
            distance = self.distance_m(current, target)

        # Overshoot-Detection: wenn das Fahrzeug schon nahe am Wegpunkt war
        # (innerhalb 3x Acceptance bzw. min. 1.5 m — deckt auch tangentiale
        # Streiftreffer mit dem Roll-Bogen-Wenderadius ab) und die Distanz
        # danach mehrere Samples in Folge wieder wächst, wurde der Wegpunkt
        # physisch passiert. Das löst den Endlos-Pivot/Orbit-Modus auf, der
        # entsteht, wenn der reale Mindestabstand wegen GPS-Rauschen,
        # Drivetrain-Trägheit oder breitem Wenderadius knapp über dem
        # Acceptance-Radius liegt.
        acceptance = float(self.config.acceptance_radius_m)
        engagement_radius = max(3.0 * acceptance, 1.5)
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
        if self._goto_is_diverging(distance, error):
            message = (
                f'Navigation entfernt sich vom Ziel: Wegpunkt {self._active_index}, '
                f'Distanz {distance:.2f} m'
            )
            self.stop(reason='divergence_stop')
            self._set_error(message)
            return
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
            self._waypoint_progress_reference = None
            self._waypoint_divergence_count = 0
            if self._active_index >= len(self._waypoints):
                self._running = False
                self._state = 'completed'
                self._last_command = {'x': 0.0, 'y': 0.0}
                completed = True
            else:
                completed = False

        if completed:
            self._neutral_with_ramping()
            if self.safety and hasattr(self.safety, 'deactivate_command_watchdog'):
                self.safety.deactivate_command_watchdog()
            self.logger.info('✅ Navigation abgeschlossen')
        self._emit_state()
        return completed

    def _handle_track_pose(self, current: Waypoint, heading: float, now: float, direction: str = 'forward') -> None:
        with self._lock:
            waypoints = list(self._waypoints)
            lookahead = self._track_lookahead_m
            progress_hint_m = self._track_progress_m

        target, progress_m, remaining_m, segment_index, raw_t, cross_track_m = self._pure_pursuit_target(
            current,
            waypoints,
            lookahead,
            progress_hint_m=progress_hint_m,
        )
        total_m = progress_m + remaining_m

        with self._lock:
            self._track_progress_m = max(self._track_progress_m, progress_m)
            progress_m = self._track_progress_m

        distance_to_end = self.distance_m(current, waypoints[-1])
        acceptance_m = float(self.config.acceptance_radius_m)
        closed_track = (
            len(waypoints) >= 3
            and self.distance_m(waypoints[0], waypoints[-1]) <= 0.05
        )
        if closed_track:
            # A rotated contour starts and ends at the selected point. It must
            # not therefore complete on its very first pose sample. Completion
            # is allowed only after progress has traversed the whole ring.
            completed = total_m > acceptance_m and progress_m >= total_m - acceptance_m
        else:
            completed = (
                distance_to_end <= acceptance_m
                or (segment_index >= len(waypoints) - 2 and raw_t >= 1.0)
            )
        if completed:
            self._complete_track()
            return

        cross_track_limit = max(
            0.25,
            float(getattr(self.config, 'track_cross_track_limit_m', 1.0)),
        )
        if cross_track_m > cross_track_limit:
            message = (
                f'Navigation zu weit vom Pfad entfernt: {cross_track_m:.2f} m '
                f'(Grenze {cross_track_limit:.2f} m)'
            )
            self.stop(reason='cross_track_stop')
            self._set_error(message)
            return

        bearing = self.bearing_deg(current, target)
        if direction == 'reverse':
            bearing = (bearing + 180.0) % 360.0
        error = self.heading_error_deg(bearing, heading)

        # Ein Track darf nicht mit grossem Winkelfehler und gleichzeitigem
        # Vorwaertsschub angefahren werden. Genau das hat im Realbetrieb einen
        # Bogen von der Bahn weg erzeugt: ein Rad stand, das andere fuhr weiter.
        # Vorwaerts deshalb zuerst symmetrisch auf der Stelle ausrichten und
        # erst nach Verlassen der Hysterese laengs fahren. Die bewaehrte
        # Rueckwaertsausrichtung bleibt unveraendert.
        enter_deg = self._track_alignment_enter_deg()
        exit_deg = self._track_alignment_exit_deg()
        with self._lock:
            if self._track_aligning:
                self._track_aligning = abs(error) > exit_deg
            elif abs(error) >= enter_deg:
                self._track_aligning = True
            aligning = self._track_aligning

        if aligning:
            if direction != 'reverse':
                # Kein longitudinaler Anteil: bei turn_factor=300 ergibt
                # x=0.50 an beiden Ketten denselben Betrag von 150 us in
                # entgegengesetzter Richtung. So bleibt der Drehmittelpunkt
                # am Fahrzeug statt seitlich an der stehenden Kette.
                turn = math.copysign(self._pivot_turn_level(), error)
                longitudinal = 0.0
                align_mode = 'pivot'
            else:
                # Rueckwaerts ist der Roll-Aligner real bereits bewaehrt und
                # wird von dieser gezielten Vorwaerts-Korrektur nicht beruehrt.
                self._reset_track_stall_watchdog(progress_m, now)
                limit = min(0.30, max(0.0, float(self.config.max_joystick)))
                turn = self._clamp(
                    error * float(self.config.turn_kp),
                    -limit,
                    limit,
                )
                longitudinal = -min(
                    limit,
                    abs(turn) * self._turn_to_forward_ratio,
                )
                align_mode = 'roll'

            self._send_command(turn, longitudinal)
            if now - self._last_debug_log >= 1.0:
                self._last_debug_log = now
                self.logger.info(
                    '🧭 track-align-%s(%s): seg=%d xtrack=%.2fm hdg=%.1f° err=%.1f° → x=%.3f y=%.3f',
                    align_mode, direction, segment_index, cross_track_m,
                    heading, error, turn, longitudinal,
                )
            return

        if self._track_is_stalled(progress_m, now):
            timeout_s = self._track_stall_timeout_s()
            message = (
                f'Navigation ohne Track-Fortschritt: bei {progress_m:.2f} m '
                f'seit {timeout_s:.1f} s festgefahren'
            )
            self.stop(reason='track_stall')
            self._set_error(message)
            return

        x, y = self._calculate_command(error, max(remaining_m, lookahead), direction=direction)
        self._send_command(x, y)

        with self._lock:
            self._active_index = min(segment_index, max(0, len(self._waypoints) - 1))

        if now - self._last_debug_log >= 1.0:
            self._last_debug_log = now
            self.logger.info(
                '🧭 track(%s): seg=%d prog=%.2fm rem=%.2fm xtrack=%.2fm target=(%.7f,%.7f) hdg=%.1f° err=%.1f° → x=%.3f y=%.3f',
                direction, segment_index, progress_m, remaining_m, cross_track_m,
                target.latitude, target.longitude, heading, error, x, y,
            )

    def _complete_track(self) -> None:
        with self._lock:
            self._running = False
            self._state = 'completed'
            self._active_index = max(0, len(self._waypoints) - 1)
            self._last_command = {'x': 0.0, 'y': 0.0}
        self._neutral_with_ramping()
        if self.safety and hasattr(self.safety, 'deactivate_command_watchdog'):
            self.safety.deactivate_command_watchdog()
        self.logger.info('✅ Track-Navigation abgeschlossen')
        self._emit_state()

    @classmethod
    def _pure_pursuit_target(
        cls,
        current: Waypoint,
        waypoints: List[Waypoint],
        lookahead_m: float,
        progress_hint_m: float = 0.0,
    ) -> Tuple[Waypoint, float, float, int, float, float]:
        origin = waypoints[0]
        path_xy = [cls._to_local_xy(wp, origin) for wp in waypoints]
        current_xy = cls._to_local_xy(current, origin)
        lengths = [0.0]
        total = 0.0
        for index in range(len(path_xy) - 1):
            total += cls._distance_xy(path_xy[index], path_xy[index + 1])
            lengths.append(total)

        candidates = []
        for index in range(len(path_xy) - 1):
            a = path_xy[index]
            b = path_xy[index + 1]
            ab = (b[0] - a[0], b[1] - a[1])
            seg_len_sq = ab[0] * ab[0] + ab[1] * ab[1]
            if seg_len_sq <= 1e-9:
                continue
            ap = (current_xy[0] - a[0], current_xy[1] - a[1])
            raw_t = (ap[0] * ab[0] + ap[1] * ab[1]) / seg_len_sq
            t = cls._clamp(raw_t, 0.0, 1.0)
            proj = (a[0] + ab[0] * t, a[1] + ab[1] * t)
            dist = cls._distance_xy(current_xy, proj)
            progress = lengths[index] + math.sqrt(seg_len_sq) * t
            candidates.append((dist, progress, index, raw_t))

        # Prefer the local continuation of the path. On a closed ring the
        # first and last segment touch at the selected start point; a global
        # nearest-segment search otherwise jumps directly to the end and
        # falsely completes the entire contour.
        backward_tolerance_m = max(0.25, lookahead_m * 0.5)
        forward_window_m = max(3.0, lookahead_m * 3.0)
        local_candidates = [
            candidate for candidate in candidates
            if candidate[1] >= max(0.0, progress_hint_m - backward_tolerance_m)
            and candidate[1] <= progress_hint_m + forward_window_m
        ]
        pool = local_candidates or candidates
        best = min(pool, key=lambda candidate: candidate[0]) if pool else None

        if best is None:
            return waypoints[-1], 0.0, 0.0, 0, 0.0, 0.0

        cross_track, progress, segment_index, raw_t = best
        target_progress = min(total, progress + lookahead_m)
        target_xy = cls._point_at_progress(path_xy, lengths, target_progress)
        target = cls._from_local_xy(target_xy, origin)
        return target, progress, max(0.0, total - progress), segment_index, raw_t, cross_track

    @classmethod
    def _point_at_progress(cls, path_xy: List[Tuple[float, float]], lengths: List[float], progress: float) -> Tuple[float, float]:
        if progress <= 0.0:
            return path_xy[0]
        if progress >= lengths[-1]:
            return path_xy[-1]
        for index in range(len(path_xy) - 1):
            start = lengths[index]
            end = lengths[index + 1]
            if progress <= end:
                span = end - start
                t = 0.0 if span <= 1e-9 else (progress - start) / span
                a = path_xy[index]
                b = path_xy[index + 1]
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        return path_xy[-1]

    @staticmethod
    def _to_local_xy(point: Waypoint, origin: Waypoint) -> Tuple[float, float]:
        lat0 = math.radians(origin.latitude)
        x = math.radians(point.longitude - origin.longitude) * 6371000.0 * math.cos(lat0)
        y = math.radians(point.latitude - origin.latitude) * 6371000.0
        return x, y

    @staticmethod
    def _from_local_xy(point: Tuple[float, float], origin: Waypoint) -> Waypoint:
        lat0 = math.radians(origin.latitude)
        lat = origin.latitude + math.degrees(point[1] / 6371000.0)
        lon = origin.longitude + math.degrees(point[0] / (6371000.0 * math.cos(lat0)))
        return Waypoint(lat, lon)

    @staticmethod
    def _distance_xy(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        return math.hypot(b[0] - a[0], b[1] - a[1])

    def _calculate_command(self, heading_error: float, distance: float, direction: str = 'forward') -> Tuple[float, float]:
        limit = min(0.30, max(0.0, float(self.config.max_joystick)))
        distance_factor = self._clamp(distance / float(self.config.slowdown_radius_m), 0.0, 1.0)

        # Heading-proportionaler Turn, in der Slowdown-Zone proportional
        # heruntergeskaliert (sonst würde die Innen-Rad-Garantie unten den
        # Vorwärts-Anteil am WP wieder hochziehen und das Fahrzeug rasen lassen).
        turn = self._clamp(heading_error * float(self.config.turn_kp), -limit, limit) * distance_factor
        heading_factor = max(0.0, 1.0 - abs(heading_error) / 90.0)
        forward = limit * heading_factor * distance_factor

        # Bei großem Richtungsfehler niemals einen fahrenden U-Turn erzwingen.
        # Das Fahrzeug dreht zunächst auf der Stelle und erhält erst danach
        # Vorwärtsfahrt. Damit kann ein falscher Anfahrwinkel es nicht in einem
        # großen Bogen aus der geplanten Fläche tragen.
        pivot_threshold = self._pivot_heading_threshold_deg()
        pivoting = direction != 'reverse' and abs(heading_error) >= pivot_threshold
        if pivoting:
            # ``turn_factor`` ist am realen UGV kleiner als
            # ``forward_factor`` (300 vs. 500). Ein x-Limit von 0.30 liefert
            # deshalb beim Pivot nur 90 us PWM-Offset und bleibt auf Gras in
            # der Totzone. Skaliere reine Drehungen so, dass beide Raeder
            # denselben absoluten PWM-Offset wie 30 % Vorwaertsfahrt erhalten.
            pivot_turn = self._pivot_turn_level()
            return math.copysign(pivot_turn, turn or heading_error), 0.0

        # Innen-Rad-Garantie (anti-Pivot): das kurveninnere Skid-Rad darf
        # nicht rückwärts laufen (Scrubbing). PWM-Mix:
        #   inner = neutral + (y - |x| · turn_factor/forward_factor) · forward_factor
        # Der No-Reverse-Schutz (forward ≥ |turn|·ratio) gilt IMMER. Der
        # zusätzliche Roll-Floor (min_inner·limit·distance_factor), der das
        # Innen-Rad aktiv aus der ESC-Totzone holt, wird mit heading_factor
        # skaliert: bei großem Heading-Fehler (>90°) wird der Floor auf 0
        # zurückgenommen, sodass der Wenderadius schrumpft (Innen-Rad ruht
        # in Totzone, kein Scrubbing weil torque klein bleibt) und das
        # Fahrzeug Wegpunkte mit großen Bearing-Sprüngen einkreisen kann.
        # Im Sättigungsfall wird turn proportional zurückgenommen, damit
        # forward das Limit nicht sprengt.
        ratio = self._turn_to_forward_ratio
        if direction == 'reverse':
            # Auch unterhalb der Ausricht-Hysterese duerfen die Ketten nicht
            # gegeneinander laufen. Genau dieser Zustand (x=0.30/y=-0.04)
            # blieb im Brunnen-Test auf Gras wirkungslos stehen.
            forward = max(forward, abs(turn) * ratio)
        min_inner = self._clamp(float(getattr(self.config, 'min_inner_wheel_speed', 0.0)), 0.0, 1.0)
        if min_inner > 0.0 and direction != 'reverse':
            inner_floor = min_inner * limit * distance_factor * heading_factor
            required_forward = inner_floor + abs(turn) * ratio
            if required_forward <= limit:
                forward = max(forward, required_forward)
            else:
                forward = limit
                if ratio > 0.0:
                    max_turn = max(0.0, (limit - inner_floor) / ratio)
                    turn = self._clamp(turn, -max_turn, max_turn)
        signed_forward = -forward if direction == 'reverse' else forward
        return turn, self._clamp(signed_forward, -limit, limit)

    def _pivot_heading_threshold_deg(self) -> float:
        return self._clamp(
            float(getattr(self.config, 'pivot_heading_threshold_deg', 70.0)),
            30.0,
            89.0,
        )

    def _pivot_turn_level(self) -> float:
        limit = min(0.30, max(0.0, float(self.config.max_joystick)))
        ratio = max(0.01, float(self._turn_to_forward_ratio))
        return self._clamp(limit / ratio, limit, 1.0)

    def _track_alignment_enter_deg(self) -> float:
        return self._clamp(
            float(getattr(self.config, 'track_alignment_enter_deg', 25.0)),
            10.0,
            60.0,
        )

    def _track_alignment_exit_deg(self) -> float:
        enter = self._track_alignment_enter_deg()
        return self._clamp(
            float(getattr(self.config, 'track_alignment_exit_deg', 10.0)),
            2.0,
            max(2.0, enter - 2.0),
        )

    def _track_stall_timeout_s(self) -> float:
        return self._clamp(
            float(getattr(self.config, 'track_stall_timeout_s', 10.0)),
            3.0,
            60.0,
        )

    def _track_stall_min_progress_m(self) -> float:
        return self._clamp(
            float(getattr(self.config, 'track_stall_min_progress_m', 0.15)),
            0.05,
            1.0,
        )

    def _reset_track_stall_watchdog(self, progress_m: float, now: float) -> None:
        with self._lock:
            self._track_stall_reference_m = progress_m
            self._track_stall_reference_time = now

    def _track_is_stalled(self, progress_m: float, now: float) -> bool:
        min_progress_m = self._track_stall_min_progress_m()
        timeout_s = self._track_stall_timeout_s()
        with self._lock:
            if (
                self._track_stall_reference_time <= 0.0
                or progress_m >= self._track_stall_reference_m + min_progress_m
            ):
                self._track_stall_reference_m = progress_m
                self._track_stall_reference_time = now
                return False
            return now - self._track_stall_reference_time >= timeout_s

    def _goto_is_diverging(self, distance: float, heading_error: float) -> bool:
        """Stoppt eine ausgerichtete Goto-Fahrt, die sich vom Ziel entfernt."""
        if abs(heading_error) >= self._pivot_heading_threshold_deg():
            self._waypoint_progress_reference = None
            self._waypoint_divergence_count = 0
            return False

        if self._waypoint_progress_reference is None or distance < self._waypoint_progress_reference:
            self._waypoint_progress_reference = distance
            self._waypoint_divergence_count = 0
            return False

        limit_m = max(
            0.25,
            float(getattr(self.config, 'goto_divergence_limit_m', 0.75)),
        )
        required_samples = max(
            2,
            int(getattr(self.config, 'goto_divergence_samples', 5)),
        )
        if distance > self._waypoint_progress_reference + limit_m:
            self._waypoint_divergence_count += 1
        else:
            self._waypoint_divergence_count = 0
        return self._waypoint_divergence_count >= required_samples

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
            paused = self._paused
            last_pose = self._last_pose_time
        if running and not paused and (
            not last_pose or time.time() - last_pose > float(self.config.watchdog_timeout_s)
        ):
            self._set_error('CAN-Pose Watchdog-Timeout')
            self.stop(reason='watchdog')

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message
        self.logger.warning(message)
        self._emit_state()

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
    def _parse_mode(mode: str) -> str:
        parsed = str(mode or 'goto').strip().lower()
        if parsed not in ('goto', 'track'):
            raise ValueError('Navigationsmodus muss goto oder track sein')
        return parsed

    @staticmethod
    def _parse_direction(direction: str) -> str:
        parsed = str(direction or 'forward').strip().lower()
        if parsed not in ('forward', 'reverse'):
            raise ValueError('Fahrtrichtung muss forward oder reverse sein')
        return parsed

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
