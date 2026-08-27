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

    # Letzter Riegel gegen eine verrutschte Konfiguration - nicht der
    # Betriebspunkt, der steht in ``max_joystick``. Lag bei 0.30 und war damit
    # zugleich die stillschweigende Obergrenze der Lenkautoritaet, weil die
    # Innen-Rad-Garantie den Drehanteil aus demselben Budget bedient.
    MAX_AUTONOMOUS_JOYSTICK = 0.50

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
        # Beginn und kleinster bisher gesehener Winkelfehler, solange er
        # ueber der Sperre liegt. None heisst, dass der Kurs in der Grenze lag.
        self._heading_block_since = None
        self._heading_block_best_deg = None
        # Beginn und bisher kleinster Abstand einer zu grossen
        # Querabweichung. None heisst, dass die Bahn gehalten wird.
        self._cross_track_since = None
        self._cross_track_best_m = None
        # Bester Winkelfehler des laufenden Ausrichtbogens und wann er zuletzt
        # verbessert wurde. Begrenzt eine Ausrichtung, die nicht konvergiert.
        self._align_reference_error = None
        self._align_reference_time = 0.0
        # Pose, an der die laufende Fahrt begonnen hat. Zusammen mit den
        # Wegpunkten spannt sie den Korridor auf, gegen den der Geofence misst.
        self._geofence_origin: Optional[Waypoint] = None

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
            self._heading_block_since = None
            self._heading_block_best_deg = None
            self._cross_track_since = None
            self._cross_track_best_m = None
            self._align_reference_error = None
            self._align_reference_time = 0.0

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
            self._heading_block_since = None
            self._heading_block_best_deg = None
            self._cross_track_since = None
            self._cross_track_best_m = None
            self._align_reference_error = None
            self._align_reference_time = 0.0
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
                self._heading_block_since = None
                self._heading_block_best_deg = None
                self._cross_track_since = None
                self._cross_track_best_m = None
                self._align_reference_error = None
                self._align_reference_time = 0.0
                self._geofence_origin = None
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
                    'turn_gain_left': float(getattr(self.config, 'turn_gain_left', 1.0)),
                    'pivot_joystick': self._pivot_turn_level(),
                    'track_lookahead_m': self._track_lookahead_m,
                    'pivot_heading_threshold_deg': self._pivot_heading_threshold_deg(),
                    'goto_divergence_limit_m': float(getattr(self.config, 'goto_divergence_limit_m', 0.75)),
                    'goto_divergence_samples': int(getattr(self.config, 'goto_divergence_samples', 5)),
                'track_cross_track_limit_m': float(getattr(self.config, 'track_cross_track_limit_m', 1.0)),
                    'track_cross_track_max_m': float(getattr(self.config, 'track_cross_track_max_m', 8.0)),
                    'track_cross_track_recover_s': self._track_cross_track_recover_s(),
                    'track_heading_block_deg': self._track_heading_block_deg(),
                    'track_heading_recover_s': self._track_heading_recover_s(),
                    'track_heading_progress_deg': self._track_heading_progress_deg(),
                    'track_align_timeout_s': self._track_align_timeout_s(),
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
            if self._geofence_origin is None:
                self._geofence_origin = current
            route = [self._geofence_origin] + list(self._waypoints)
            mode = self._mode
            direction = self._direction
            target = self._waypoints[self._active_index]

        # Der Geofence begrenzt die Abweichung vom geplanten Korridor, nicht
        # die Länge der Fahrt. Gemessen wurde früher zum ersten Wegpunkt: damit
        # war jede Strecke, die länger als der Radius ist, prinzipiell nicht
        # fahrbar - eine 72 m lange Anfahrt zur ersten Bahn stoppte bei 50 m,
        # obwohl das Fahrzeug exakt auf der geplanten Route war (real, 02.08.).
        # Der Startpunkt der Fahrt gehört zum Korridor, damit auch eine
        # einzelne Goto-Zielkoordinate eine Strecke aufspannt und nicht nur
        # einen Punkt.
        if self._route_distance_m(current, route) > float(self.config.geofence_radius_m):
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
        # Ein einzelner Wert ueber der Grenze ist kein Grund aufzugeben. Am
        # 27.08. hing ein USB-Aufruf des Maehdecks, der Dienst startete neu,
        # und das Fahrzeug stand 1,42 m neben seiner Bahn. Die Navigation
        # stieg 50 ms nach dem Start aus, ohne einen Meter gefahren zu sein -
        # obwohl der Fehler vom Maehdeck kam und mit dem Fahren nichts zu tun
        # hatte. Diese Strecke faehrt der Regler im Vorbeifahren aus.
        #
        # Die Grenze soll einen Regler erwischen, der die Bahn *verliert*,
        # nicht eine Fortsetzung, die sie noch sucht. Entscheidend ist deshalb
        # nicht der Abstand selbst, sondern ob er kleiner wird. Dieselbe
        # Ueberlegung steht ein paar Zeilen weiter schon beim Winkelfehler.
        cross_track_max = max(
            cross_track_limit,
            float(getattr(self.config, 'track_cross_track_max_m', 8.0)),
        )
        if cross_track_m > cross_track_max:
            # So weit entfernt wird nichts mehr eingefangen: Zwischen Fahrzeug
            # und Bahn koennen Sperrzonen und Grenzen liegen, von denen der
            # Bahnregler nichts weiss.
            message = (
                f'Navigation zu weit vom Pfad entfernt: {cross_track_m:.2f} m '
                f'(Grenze {cross_track_max:.2f} m)'
            )
            self.stop(reason='cross_track_stop')
            self._set_error(message)
            return
        if self._track_aligning:
            # Waehrend des Ausrichtbogens waechst der Seitenversatz zwangs-
            # laeufig: Das Fahrzeug tauscht bewusst Abstand gegen Winkel und
            # faehrt dabei vorwaerts. Am 27.08. lief die Uhr hier schon mit -
            # als das Ausrichten fertig war und die Annaeherung haette
            # beginnen koennen, waren die zehn Sekunden abgelaufen, und der
            # Plan stoppte, ohne sie je versucht zu haben (seg=0, 1,51 -> 1,83 m,
            # Winkel 35° -> 5°). Das Ausrichten hat seinen eigenen Wächter.
            self._cross_track_since = None
            self._cross_track_best_m = None
        elif cross_track_m > cross_track_limit:
            # Eigene Uhr, bewusst nicht ``now``: Der Parameter traegt die
            # Zeitbasis fuer alles Weitere in dieser Methode.
            jetzt = time.monotonic()
            annaeherung_m = self._track_cross_track_progress_m()
            if (
                self._cross_track_since is None
                or self._cross_track_best_m is None
                or cross_track_m <= self._cross_track_best_m - annaeherung_m
            ):
                # Erste Ueberschreitung oder ein Stueck naeher als je zuvor:
                # Uhr neu stellen. Wer sich naehert, bekommt weiter Zeit.
                self._cross_track_since = jetzt
                self._cross_track_best_m = cross_track_m
            elif jetzt - self._cross_track_since >= self._track_cross_track_recover_s():
                message = (
                    f'Navigation kommt der Bahn nicht naeher: {cross_track_m:.2f} m '
                    f'(Grenze {cross_track_limit:.2f} m, '
                    f'{jetzt - self._cross_track_since:.0f} s ohne Annaeherung)'
                )
                self.stop(reason='cross_track_stop')
                self._set_error(message)
                return
        else:
            self._cross_track_since = None
            self._cross_track_best_m = None

        bearing = self.bearing_deg(current, target)
        if direction == 'reverse':
            bearing = (bearing + 180.0) % 360.0
        error = self.heading_error_deg(bearing, heading)

        # Genuinely extreme Winkelfehler (der urspruengliche Brunnen-Stall
        # lag bei -51.7° und wuchs weiter) sind jenseits dessen, was ein
        # Roll-Bogen sicher auffangen kann - dort deterministisch stoppen
        # statt zu raten. Gemessen wird gegen die Bahnrichtung und nicht
        # gegen die Zielpeilung, und der Fehler muss anhalten: ein einzelnes
        # Sample stoppt eine laufende Mahd nicht mehr.
        block_deg = self._track_heading_block_deg()
        path_error = self.heading_error_deg(
            self._path_direction_deg(waypoints, segment_index, direction),
            heading,
        )
        # Gezaehlt wurde frueher in Posen: drei ueber der Grenze, und die Fahrt
        # war beendet. Das sind rund drei Zehntelsekunden - in der Zeit dreht
        # sich kein Fahrzeug um 60°, und das Eindrehen ein paar Zeilen weiter
        # unten kam nie zum Zug. Am 27.08. verweigerte die Vorabpruefung
        # deshalb ganze Plaene, deren Anfahrt voellig normal war.
        #
        # Entscheidend ist wie bei der Querabweichung nicht der Betrag,
        # sondern ob er kleiner wird. Der urspruengliche Brunnen-Stall
        # (-51.7° und weiter wachsend) stoppt damit weiterhin - er wurde ja
        # gerade nicht kleiner.
        if abs(path_error) >= block_deg:
            jetzt = time.monotonic()
            annaeherung = self._track_heading_progress_deg()
            if (
                self._heading_block_since is None
                or self._heading_block_best_deg is None
                or abs(path_error) <= self._heading_block_best_deg - annaeherung
            ):
                self._heading_block_since = jetzt
                self._heading_block_best_deg = abs(path_error)
            elif jetzt - self._heading_block_since >= self._track_heading_recover_s():
                message = (
                    f'Fahrzeug dreht nicht auf die Bahn ein: {path_error:.1f}° '
                    f'(Grenze {block_deg:.1f}°, '
                    f'{jetzt - self._heading_block_since:.0f} s ohne Annaeherung) '
                    f'– Bahn wird nicht automatisch angefahren'
                )
                self.stop(reason='heading_block')
                self._set_error(message)
                return
        else:
            self._heading_block_since = None
            self._heading_block_best_deg = None

        # Gleichzeitiges Drehen und Vorwaertsfahren konvergiert auf diesem
        # Fahrzeug nicht, sobald der Turn-Anteil saettigt (~15° bei
        # turn_kp=0.02): der Vorwaertsschub laeuft schneller weg von der
        # Bahn, als die Drehung aufholen kann (real, 25.07.: -18.7° ->
        # -26.3° unter vollem x/y-Mix, Cross-Track 0.01 -> 0.16 m). Deshalb
        # zuerst ohne Vorwaertsschub um ein nahezu stehendes Kettenpaar
        # rollen, bis der Fehler unter die Austrittsschwelle faellt - erst
        # dann normal weiterfahren. Symmetrisch fuer beide Richtungen;
        # bewaehrt fuer reverse am selben Tag (29.7° -> 1.3° in 11s). Der
        # Gegenlauf-Pivot als Alternative dreht das reale UGV unter Last
        # gar nicht (Stillstand >4 Min, selbes Datum) und bleibt deshalb
        # aussen vor.
        #
        # Ein- und Austritt entscheidet der Kursfehler zur Bahn, nicht der
        # Regelfehler der Bahnverfolgung. Letzterer ist Kursfehler *plus*
        # Querversatz-Anteil - bei 0.15 m Versatz und 0.8 m Lookahead allein
        # atan(0.15/0.8) = 10.6 Grad. Genau dieser Anteil laesst sich nur
        # durch Vorwaertsfahren abbauen, und der Ausrichtbogen nimmt den
        # Vorwaertsschub weg. Die Austrittsschwelle war damit unerreichbar,
        # sobald ein Querversatz vorlag: das Fahrzeug stand bei perfektem
        # Kurs mitten in der Bahn fest (real 07.08., 7 Grad gemeldet,
        # Kurs 152.6 Grad konstant). Der Kursfehler zur Bahn kennt diesen
        # Anteil nicht - er wird durch Drehen kleiner, also durch genau das,
        # was der Bogen tut.
        # Beide Groessen zusammen entscheiden, und jede beantwortet genau eine
        # Frage.
        #
        # ``error`` (Bahnverfolgung, Kurs *plus* Querversatz-Anteil) sagt, ob
        # der Regler ueberhaupt ein Problem hat. Nur bei grossem Wert
        # konvergiert Drehen-und-Fahren nicht mehr - das ist der Grund, warum
        # es den Bogen gibt.
        #
        # ``path_error`` (Kurs gegen die Bahnrichtung) sagt, ob Drehen daran
        # etwas aendern kann und wann es fertig ist. Steht die Nase parallel
        # zur Bahn, ist der Rest reiner Querversatz - den baut nur
        # Vorwaertsfahren ab, niemals der Bogen.
        #
        # Jede Groesse allein fuehrt in eine Sackgasse: nur ``error`` laesst
        # den Bogen auf eine Schwelle warten, die er selbst unerreichbar macht
        # (real 07.08. 16:30, 7 Grad gemeldet bei 15 cm Versatz); nur
        # ``path_error`` startet ihn, obwohl der Regler laengst sauber faehrt
        # (real 07.08. 16:54, bahn 8.3 Grad bei folge 1.0 Grad).
        enter_deg = self._track_alignment_enter_deg()
        exit_deg = self._track_alignment_exit_deg()
        with self._lock:
            if self._track_aligning:
                self._track_aligning = (
                    abs(path_error) > exit_deg and abs(error) > exit_deg
                )
            elif abs(error) >= enter_deg and abs(path_error) > exit_deg:
                self._track_aligning = True
            aligning = self._track_aligning
            if not aligning:
                self._align_reference_error = None
                self._align_reference_time = 0.0

        if aligning:
            # Der Track-Fortschrittswaechter muss hier ruhen: ein Ausrichtbogen
            # macht bewusst kaum Bahnfortschritt. Dadurch war dieser Zweig
            # aber voellig unbegrenzt - dreht das Fahrzeug nicht, rollte es
            # ewig weiter, ohne Fortschritt, ohne Fehler, in der Oberflaeche
            # alles gruen (real 07.08.: 7 Grad Fehler, Kurs 152.6 Grad
            # konstant, PWM 1405/1500 - zu wenig, um das beladene Kettenfahrzeug
            # auf Gras zu drehen). Deshalb bekommt die Ausrichtung einen
            # eigenen Waechter auf den Winkelfehler.
            self._reset_track_stall_watchdog(progress_m, now)
            if self._align_is_stalled(path_error, now):
                timeout_s = self._track_align_timeout_s()
                message = (
                    f'Ausrichtung ohne Fortschritt: Kursfehler zur Bahn '
                    f'{path_error:.1f}° seit {timeout_s:.1f} s unveraendert '
                    f'– Fahrzeug dreht nicht'
                )
                self.stop(reason='align_stall')
                self._set_error(message)
                return
            # Das proportionale Kommando stirbt aus, bevor die
            # Austrittsschwelle erreicht ist. Gemessen am 07.08. auf Gras:
            # x=0.236 -> 1.3 Grad/s, x=0.155 -> 0.4 Grad/s, x=0.125 -> 0.
            # Die Ausrichtung kam so von 11.8 auf 6.1 Grad und blieb dort
            # stehen, waehrend sie 5 Grad erreichen musste. Solange
            # ausgerichtet wird, darf der Drehanteil deshalb nicht unter die
            # Losbrechgrenze fallen - lieber die letzten Grad zuegig drehen
            # als endlos mit wirkungslosem Kommando auf der Narbe zu stehen.
            limit = self._speed_limit()
            floor = min(limit, self._track_align_min_turn())
            magnitude = min(
                limit,
                max(floor, abs(path_error) * float(self.config.turn_kp)),
            )
            # Die Losbrechgrenze auf Gras ist nicht vorhersagbar - x=0.220
            # liess das Fahrzeug 14 s lang unbewegt (07.08. 16:54). Statt sie
            # zu raten, wird das Kommando hochgefahren, solange sich der Kurs
            # nicht bewegt, und faellt zurueck, sobald er es tut. So findet
            # das Fahrzeug den noetigen Wert selbst und die Narbe sieht nur
            # so viel Drehmoment, wie tatsaechlich gebraucht wird.
            magnitude = min(limit, magnitude + (limit - magnitude) * self._align_escalation(now))
            turn = self._turn_gain(
                math.copysign(magnitude, path_error) if path_error else 0.0
            )
            rolling = min(limit, abs(turn) * self._turn_to_forward_ratio)
            longitudinal = -rolling if direction == 'reverse' else rolling
            self._send_command(turn, longitudinal)
            if now - self._last_debug_log >= 1.0:
                self._last_debug_log = now
                self.logger.info(
                    '🧭 track-align-roll(%s): seg=%d xtrack=%.2fm hdg=%.1f° '
                    'bahn=%.1f° folge=%.1f° → x=%.3f y=%.3f',
                    direction, segment_index, cross_track_m, heading,
                    path_error, error, turn, longitudinal,
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
    def track_start_heading_error_deg(
        cls,
        coordinates: List[List[float]],
        heading_deg: float,
        direction: str = 'forward',
        lookahead_m: float = 0.8,
    ) -> Optional[float]:
        """Winkelfehler, den ``_handle_track_pose`` an diesem Bahnanfang saehe.

        Dieselbe Bezugsgroesse wie im Regler: die Richtung des Bahnstuecks,
        auf dem das Fahrzeug steht, mit derselben 180-Grad-Drehung fuer
        rueckwaerts. Frueher wurde hier wie dort gegen die Peilung zum
        Pure-Pursuit-Ziel gemessen; die ist einen Lookahead entfernt und
        deshalb dicht am Aufsetzpunkt extrem empfindlich gegen wenige
        Zentimeter Querversatz. Vorabpruefung und Regler muessen dieselbe
        Groesse verwenden, sonst lehnt die eine Seite Bahnen ab, die die
        andere problemlos faehrt.

        Aufsetzpunkt ist ``coordinates[0]``: dort steht das Fahrzeug, wenn die
        Bahn beginnt. Der uebergebene Kurs ist die einzige Groesse, die ein
        Aufrufer vor der Fahrt schaetzen muss.
        """
        if len(coordinates) < 2:
            return None
        try:
            waypoints = [
                Waypoint(latitude=float(coord[1]), longitude=float(coord[0]))
                for coord in coordinates
            ]
            heading = float(heading_deg)
        except (TypeError, ValueError, IndexError):
            return None
        current = waypoints[0]
        segment_index = cls._pure_pursuit_target(
            current, waypoints, float(lookahead_m)
        )[3]
        # Ohne Ausdehnung ist jede Peilung nur Rauschen (entartete Bahn, alle
        # Stuetzpunkte auf einem Fleck). Dann lieber nichts melden als eine
        # erfundene Sperre.
        last = max(0, len(waypoints) - 2)
        index = min(max(0, int(segment_index)), last)
        if cls.distance_m(waypoints[index], waypoints[index + 1]) <= 0.05:
            return None
        bearing = cls._path_direction_deg(waypoints, index, direction)
        return cls.heading_error_deg(bearing, heading)

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

    @classmethod
    def _route_distance_m(cls, current: Waypoint, route: List[Waypoint]) -> float:
        """Kürzester Abstand der Pose zum Streckenzug ``route``.

        Anders als ``_pure_pursuit_target`` sucht das hier bewusst global und
        ohne Fortschritts-Fenster: für den Geofence zählt nur, ob das Fahrzeug
        den Korridor irgendwo verlassen hat, nicht wo auf der Strecke es sich
        befindet.
        """
        if not route:
            return 0.0
        origin = route[0]
        current_xy = cls._to_local_xy(current, origin)
        path_xy = [cls._to_local_xy(point, origin) for point in route]
        best = cls._distance_xy(current_xy, path_xy[0])
        for index in range(len(path_xy) - 1):
            a = path_xy[index]
            b = path_xy[index + 1]
            ab = (b[0] - a[0], b[1] - a[1])
            seg_len_sq = ab[0] * ab[0] + ab[1] * ab[1]
            if seg_len_sq <= 1e-9:
                continue
            ap = (current_xy[0] - a[0], current_xy[1] - a[1])
            t = cls._clamp((ap[0] * ab[0] + ap[1] * ab[1]) / seg_len_sq, 0.0, 1.0)
            proj = (a[0] + ab[0] * t, a[1] + ab[1] * t)
            best = min(best, cls._distance_xy(current_xy, proj))
        return best

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
        limit = self._speed_limit()
        distance_factor = self._clamp(distance / float(self.config.slowdown_radius_m), 0.0, 1.0)

        # Heading-proportionaler Turn, in der Slowdown-Zone proportional
        # heruntergeskaliert (sonst würde die Innen-Rad-Garantie unten den
        # Vorwärts-Anteil am WP wieder hochziehen und das Fahrzeug rasen lassen).
        # Der Asymmetrie-Vorhalt kommt danach und darf ``limit`` auf der
        # schwachen Seite bewusst ueberschreiten - begrenzt wird der Drehanteil
        # ohnehin erst von der Innen-Rad-Garantie weiter unten.
        turn = self._clamp(heading_error * float(self.config.turn_kp), -limit, limit) * distance_factor
        turn = self._turn_gain(turn)
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
            return self._turn_gain(math.copysign(pivot_turn, turn or heading_error)), 0.0

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

    def _speed_limit(self) -> float:
        return min(
            self.MAX_AUTONOMOUS_JOYSTICK,
            max(0.0, float(self.config.max_joystick)),
        )

    def _turn_gain(self, turn: float) -> float:
        """Haelt die gemessene Links/Rechts-Asymmetrie des Antriebs vor.

        Der Antrieb hat keine Rueckmeldung, die Software kann also nicht
        merken, dass derselbe Zahlenwert nach links weniger bewirkt als nach
        rechts (gemessen 09.08.: Rechtsbefehl etwa doppelt so wirksam, dazu
        0.42 Grad/s Rechtszug bei neutralem Lenkbefehl). Der Faktor liegt
        deshalb vor der Innen-Rad-Garantie: deren PWM-Rechnung soll mit dem
        Wert arbeiten, der tatsaechlich an die Motoren geht, sonst laeuft das
        Innenrad unbemerkt rueckwaerts.
        """
        if turn >= 0.0:
            return turn
        gain = max(0.0, float(getattr(self.config, 'turn_gain_left', 1.0)))
        return self._clamp(turn * gain, -1.0, 0.0)

    def _pivot_turn_level(self) -> float:
        limit = self._speed_limit()
        ratio = max(0.01, float(self._turn_to_forward_ratio))
        return self._clamp(limit / ratio, limit, 1.0)

    def _track_heading_recover_s(self) -> float:
        """Wie lange ein zu grosser Winkelfehler bestehen darf, ohne kleiner
        zu werden."""
        return max(
            1.0, float(getattr(self.config, 'track_heading_recover_s', 10.0))
        )

    def _track_heading_progress_deg(self) -> float:
        """Um wie viel Grad es naeher geworden sein muss, damit es zaehlt."""
        return max(
            0.2, float(getattr(self.config, 'track_heading_progress_deg', 2.0))
        )

    def _track_cross_track_recover_s(self) -> float:
        """Wie lange eine zu grosse Querabweichung bestehen darf, ohne kleiner
        zu werden."""
        return max(
            1.0, float(getattr(self.config, 'track_cross_track_recover_s', 10.0))
        )

    def _track_cross_track_progress_m(self) -> float:
        """Wie viel naeher es geworden sein muss, damit es als Annaeherung zaehlt.

        Ohne diese Schwelle setzt schon das Rauschen der Pose die Uhr immer
        wieder zurueck, und ein stehendes Fahrzeug bekaeme unbegrenzt Zeit.
        """
        return max(
            0.02, float(getattr(self.config, 'track_cross_track_progress_m', 0.1))
        )

    def _track_heading_block_deg(self) -> float:
        return self._clamp(
            float(getattr(self.config, 'track_heading_block_deg', 45.0)),
            10.0,
            60.0,
        )

    @classmethod
    def _path_direction_deg(
        cls,
        waypoints: List[Waypoint],
        segment_index: int,
        direction: str,
    ) -> float:
        """Sollkurs der Nase auf dem Bahnstueck, auf dem das Fahrzeug steht.

        Bewusst nicht die Peilung zum Pure-Pursuit-Ziel: das Ziel liegt nur
        einen Lookahead entfernt, und am Segmentanfang steht das Fahrzeug
        praktisch darauf. Dort verschiebt schon ein Ausrichtbogen - bei dem
        die GNSS-Antenne um den Drehpunkt schwenkt - die Peilung um Dutzende
        Grad, ohne dass sich die Ausrichtung zur Bahn nennenswert aendert
        (real 07.08.: 16.4 Grad auf 48.4 Grad in einer Sekunde bei 11 cm
        Querabstand und unveraendertem Kurs). Die Bahnrichtung ist stabil.
        """
        last = max(0, len(waypoints) - 2)
        index = min(max(0, int(segment_index)), last)
        bearing = cls.bearing_deg(waypoints[index], waypoints[index + 1])
        if direction == 'reverse':
            bearing = (bearing + 180.0) % 360.0
        return bearing

    def _track_alignment_enter_deg(self) -> float:
        return self._clamp(
            float(getattr(self.config, 'track_alignment_enter_deg', 10.0)),
            3.0,
            30.0,
        )

    def _track_alignment_exit_deg(self) -> float:
        enter = self._track_alignment_enter_deg()
        return self._clamp(
            float(getattr(self.config, 'track_alignment_exit_deg', 5.0)),
            1.0,
            max(1.0, enter - 2.0),
        )

    def _reset_track_stall_watchdog(self, progress_m: float, now: float) -> None:
        with self._lock:
            self._track_stall_reference_m = progress_m
            self._track_stall_reference_time = now

    def _track_align_timeout_s(self) -> float:
        return max(
            1.0,
            float(getattr(self.config, 'track_align_timeout_s', 10.0)),
        )

    def _track_align_min_progress_deg(self) -> float:
        # Bewusst fein: der Waechter soll eine Ausrichtung erkennen, die gar
        # nicht mehr dreht, und keine, die langsam konvergiert. Mit 2 Grad
        # stoppte er am 07.08. eine Ausrichtung, die in 10 s um 1.7 Grad
        # vorangekommen und noch 1 Grad von der Austrittsschwelle entfernt war.
        return max(
            0.1,
            float(getattr(self.config, 'track_align_min_progress_deg', 0.5)),
        )

    def _align_escalation(self, now: float) -> float:
        """0 bis 1, je laenger die Ausrichtung ohne Kursfortschritt laeuft."""
        escalate_s = max(
            0.5,
            float(getattr(self.config, 'track_align_escalate_s', 3.0)),
        )
        with self._lock:
            reference_time = self._align_reference_time
        if reference_time <= 0.0:
            return 0.0
        return self._clamp((now - reference_time) / escalate_s, 0.0, 1.0)

    def _track_align_min_turn(self) -> float:
        return self._clamp(
            float(getattr(self.config, 'track_align_min_turn', 0.22)),
            0.0,
            0.30,
        )

    def _align_is_stalled(self, error: float, now: float) -> bool:
        """True, wenn der Ausrichtbogen den Winkelfehler nicht mehr verkleinert.

        Bezug ist der jeweils beste erreichte Fehler. Verbessert er sich um
        mindestens ``track_align_min_progress_deg``, laeuft die Frist neu -
        eine langsame, aber fortschreitende Drehung wird also nicht gestoppt.
        """
        magnitude = abs(float(error))
        min_progress = self._track_align_min_progress_deg()
        with self._lock:
            if (
                self._align_reference_time <= 0.0
                or self._align_reference_error is None
                or magnitude <= self._align_reference_error - min_progress
            ):
                self._align_reference_error = magnitude
                self._align_reference_time = now
                return False
            return now - self._align_reference_time >= self._track_align_timeout_s()

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
