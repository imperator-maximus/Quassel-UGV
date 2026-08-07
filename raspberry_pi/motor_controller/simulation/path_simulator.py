"""Controller-in-the-loop simulation of executable mowing plans.

This is deliberately a light-weight kinematic model, not a terrain physics
engine.  Its purpose is to expose what the production NavigationController
will command after segment orientation, transition routing and start-point
selection have transformed the planner preview into an executable route.
"""

import math
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from ..mapping.nogo_monitor import NoGoZoneMonitor
from ..mapping.plan_manager import MowingPlanManager
from ..navigation.navigation_controller import NavigationController, Waypoint


@dataclass(frozen=True)
class SimulationParameters:
    step_s: float = 0.05
    # Gemessen am 02.08. an der realen Planfahrt: bei vollem Vorwärtsbefehl
    # legte das Fahrzeug 0.33 m/s zurück (Track-Fortschritt zwischen zwei
    # Log-Zeilen). Die vorherigen 0.80 m/s waren geschätzt und liessen jede
    # Simulation doppelt so schnell und damit viel zu wendig erscheinen.
    max_wheel_speed_m_s: float = 0.35
    # Anteil der ideal berechneten Gierrate, der real ankommt. Ebenfalls am
    # 02.08. gemessen: 2.9°/s statt der modellierten 31°/s bei vollem
    # Lenkbefehl. Ohne diesen Faktor meldete die Simulation Strecken als
    # fahrbar, an denen das Fahrzeug anschliessend geradeaus weiterfuhr,
    # weil es der Kurve nicht folgen konnte.
    yaw_efficiency: float = 0.10
    track_width_m: float = 0.64
    command_response_s: float = 0.25
    wheel_command_deadband: float = 0.08
    counter_rotation_supported: bool = False
    sample_distance_m: float = 0.25
    sample_interval_s: float = 0.50
    max_steps: int = 150000
    segment_timeout_factor: float = 5.0
    vehicle_length_m: float = 1.15
    vehicle_width_m: float = 0.79

    @classmethod
    def from_payload(cls, payload: Optional[Dict[str, Any]] = None):
        payload = payload or {}

        def number(name, default, minimum, maximum):
            try:
                value = float(payload.get(name, default))
            except (TypeError, ValueError):
                value = default
            return max(minimum, min(maximum, value))

        try:
            max_steps = int(payload.get("max_steps", cls.max_steps))
        except (TypeError, ValueError):
            max_steps = cls.max_steps
        counter_rotation_supported = payload.get(
            "counter_rotation_supported",
            cls.counter_rotation_supported,
        ) is True
        return cls(
            step_s=number("step_s", cls.step_s, 0.02, 0.20),
            max_wheel_speed_m_s=number(
                "max_wheel_speed_m_s", cls.max_wheel_speed_m_s, 0.10, 3.0
            ),
            yaw_efficiency=number("yaw_efficiency", cls.yaw_efficiency, 0.01, 1.0),
            track_width_m=number("track_width_m", cls.track_width_m, 0.20, 2.0),
            command_response_s=number(
                "command_response_s", cls.command_response_s, 0.0, 3.0
            ),
            wheel_command_deadband=number(
                "wheel_command_deadband", cls.wheel_command_deadband, 0.0, 0.50
            ),
            counter_rotation_supported=counter_rotation_supported,
            sample_distance_m=number(
                "sample_distance_m", cls.sample_distance_m, 0.05, 2.0
            ),
            sample_interval_s=number(
                "sample_interval_s", cls.sample_interval_s, 0.05, 5.0
            ),
            max_steps=max(1000, min(500000, max_steps)),
            segment_timeout_factor=number(
                "segment_timeout_factor", cls.segment_timeout_factor, 1.5, 20.0
            ),
            vehicle_length_m=number(
                "vehicle_length_m", cls.vehicle_length_m, 0.20, 5.0
            ),
            vehicle_width_m=number(
                "vehicle_width_m", cls.vehicle_width_m, 0.20, 5.0
            ),
        )


class _SimulationMotor:
    def __init__(self, pwm_config=None):
        self.pwm_config = pwm_config or SimpleNamespace(
            forward_factor=500.0,
            turn_factor=300.0,
        )
        self.command = {"x": 0.0, "y": 0.0}

    def set_joystick(self, x: float, y: float, use_ramping: bool = False):
        self.command = {"x": float(x), "y": float(y)}


class MowingPathSimulator:
    """Runs the real navigation controller against a kinematic vehicle."""

    def __init__(
        self,
        plan_manager: MowingPlanManager,
        navigation_config,
        pwm_config=None,
    ):
        self.plan_manager = plan_manager
        self.navigation_config = navigation_config
        self.pwm_config = pwm_config

    def simulate(
        self,
        plan: Dict[str, Any],
        *,
        start_segment_index: Optional[int] = None,
        start_coordinate: Optional[List[float]] = None,
        start_heading_deg: Optional[float] = None,
        start_pose: Optional[Dict[str, Any]] = None,
        parameters: Optional[SimulationParameters] = None,
        max_source_segments: Optional[int] = None,
        cancel_event=None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        params = parameters or SimulationParameters()
        self._report_progress(progress_callback, {
            "phase": "route_building",
            "step_count": 0,
            "max_steps": params.max_steps,
        })
        try:
            selected_start = self._selected_start(plan, start_segment_index, start_coordinate)
            pose = self._initial_pose(selected_start, start_pose, start_heading_deg)
            executable = self.plan_manager.executable_segments(
                plan,
                start_segment_index=start_segment_index,
                start_coordinate=start_coordinate,
                start_pose=pose,
                max_source_segments=max_source_segments,
                # Same reasoning as the playback endpoint: the simulation
                # drives no hardware, and every transition is re-routed here
                # by the runtime router anyway, so a planning-time unsafe flag
                # says nothing about the route that is actually simulated.
                # Rejecting the whole plan up front hid exactly the result the
                # user wants to see. Where no map geometry is available the
                # runtime router is absent and _transfer_segment still refuses
                # the stored unsafe transition; real execution stays blocked
                # by check_plan().
                allow_unsafe_plan=True,
            )
        except ValueError as exc:
            return {
                "success": False,
                "safe": False,
                "state": "route_error",
                "reason": str(exc),
                "trajectory": [],
                "segments": [],
            }
        if not executable:
            return {
                "success": False,
                "safe": False,
                "state": "route_error",
                "reason": "Plan enthält keine ausführbaren Segmente",
                "trajectory": [],
                "segments": [],
            }

        if cancel_event is not None and cancel_event.is_set():
            return self._cancelled_result(params, executable)

        self._report_progress(progress_callback, {
            "phase": "simulating",
            "step_count": 0,
            "max_steps": params.max_steps,
            "executable_index": 0,
            "executable_segment_count": len(executable),
            "actual_length_m": 0.0,
            "elapsed_s": 0.0,
        })

        if start_heading_deg is None and self._heading_from_pose(start_pose) is None:
            pose["heading_deg"] = self._initial_heading(executable)

        motor = _SimulationMotor(self.pwm_config)
        navigation = NavigationController(motor, self.navigation_config)
        # Keep simulated controller messages distinguishable from commands
        # sent by the production navigation instance in the service journal.
        navigation.logger = logging.getLogger(__name__ + ".navigation")
        try:
            monitor = NoGoZoneMonitor(
                plan,
                vehicle_length_m=params.vehicle_length_m,
                vehicle_width_m=params.vehicle_width_m,
                enforce_outer_boundary=False,
            )
        except ValueError as exc:
            return {
                "success": False,
                "safe": False,
                "state": "simulation_error",
                "reason": str(exc),
                "trajectory": [],
                "segments": [],
            }

        trajectory: List[Dict[str, Any]] = []
        segment_results: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        elapsed_s = 0.0
        actual_distance_m = 0.0
        linear_speed = 0.0
        angular_speed = 0.0
        step_count = 0
        last_sample_pose = dict(pose)
        last_sample_time = -params.sample_interval_s
        stop_state = None
        stop_reason = None
        stop_nogo = None

        self._append_sample(trajectory, pose, 0, executable[0], motor.command, elapsed_s)
        try:
            for executable_index, segment in enumerate(executable):
                if cancel_event is not None and cancel_event.is_set():
                    stop_state = "cancelled"
                    stop_reason = "Simulation abgebrochen"
                    break
                coords = segment.get("coordinates") or []
                if not coords:
                    continue
                waypoints = [
                    {"longitude": coord[0], "latitude": coord[1]}
                    for coord in coords
                ]
                mode = segment.get("mode", "goto")
                direction = segment.get("direction", "forward")
                navigation.set_waypoints(waypoints, mode=mode, direction=direction)
                if not navigation.start():
                    stop_state = "navigation_error"
                    stop_reason = navigation.get_status().get("last_error") or "Navigation konnte nicht starten"
                    break

                segment_start_s = elapsed_s
                segment_start_distance = actual_distance_m
                segment_steps = 0
                segment_timeout_s = self._segment_timeout(segment, pose, params)
                segment_state = "running"

                while step_count < params.max_steps:
                    if cancel_event is not None and cancel_event.is_set():
                        stop_state = "cancelled"
                        stop_reason = "Simulation abgebrochen"
                        navigation.stop(reason=stop_state)
                        segment_state = stop_state
                        break
                    nogo = monitor.check_pose(pose)
                    if nogo.get("state") == "warning":
                        if not warnings or warnings[-1].get("executable_index") != executable_index:
                            warnings.append({
                                "executable_index": executable_index,
                                "reason": nogo.get("reason"),
                                "time_s": round(elapsed_s, 2),
                            })
                    if not nogo.get("ok"):
                        stop_state = "nogo_stop"
                        stop_reason = nogo.get("reason") or "No-Go-Zone verletzt"
                        stop_nogo = nogo
                        navigation.stop(reason="simulation_nogo_stop")
                        segment_state = stop_state
                        break

                    navigation.on_pose_update(pose)
                    nav_status = navigation.get_status()
                    if not nav_status.get("running"):
                        segment_state = nav_status.get("state") or "stopped"
                        if segment_state != "completed":
                            stop_state = segment_state
                            stop_reason = nav_status.get("last_error") or f"Navigation endete mit {segment_state}"
                        break

                    previous_pose = dict(pose)
                    linear_speed, angular_speed = self._integrate(
                        pose,
                        motor.command,
                        linear_speed,
                        angular_speed,
                        params,
                    )
                    travelled = self._distance_pose(previous_pose, pose)
                    actual_distance_m += travelled
                    elapsed_s += params.step_s
                    step_count += 1
                    segment_steps += 1

                    if step_count == 1 or step_count % 100 == 0:
                        self._report_progress(progress_callback, {
                            "phase": "simulating",
                            "step_count": step_count,
                            "max_steps": params.max_steps,
                            "executable_index": executable_index,
                            "executable_segment_count": len(executable),
                            "actual_length_m": round(actual_distance_m, 2),
                            "elapsed_s": round(elapsed_s, 2),
                        })

                    if (
                        self._distance_pose(last_sample_pose, pose) >= params.sample_distance_m
                        or elapsed_s - last_sample_time >= params.sample_interval_s
                    ):
                        self._append_sample(
                            trajectory,
                            pose,
                            executable_index,
                            segment,
                            motor.command,
                            elapsed_s,
                        )
                        last_sample_pose = dict(pose)
                        last_sample_time = elapsed_s

                    if elapsed_s - segment_start_s > segment_timeout_s:
                        stop_state = "segment_timeout"
                        stop_reason = (
                            f"Segment {executable_index} wurde nach "
                            f"{segment_timeout_s:.1f} s nicht abgeschlossen"
                        )
                        navigation.stop(reason=stop_state)
                        segment_state = stop_state
                        break

                if step_count >= params.max_steps and stop_state is None:
                    stop_state = "step_limit"
                    stop_reason = f"Simulationslimit von {params.max_steps} Schritten erreicht"
                    navigation.stop(reason=stop_state)
                    segment_state = stop_state

                segment_results.append({
                    "executable_index": executable_index,
                    "type": segment.get("type"),
                    "source_type": segment.get("source_type"),
                    "source_index": segment.get("source_index"),
                    "mode": mode,
                    "direction": direction,
                    "route_kind": segment.get("route_kind"),
                    "planned_length_m": round(float(segment.get("length_m", 0.0) or 0.0), 2),
                    "actual_length_m": round(actual_distance_m - segment_start_distance, 2),
                    "duration_s": round(elapsed_s - segment_start_s, 2),
                    "steps": segment_steps,
                    "state": segment_state,
                })
                self._append_sample(
                    trajectory,
                    pose,
                    executable_index,
                    segment,
                    motor.command,
                    elapsed_s,
                )
                self._report_progress(progress_callback, {
                    "phase": "simulating",
                    "step_count": step_count,
                    "max_steps": params.max_steps,
                    "executable_index": executable_index,
                    "executable_segment_count": len(executable),
                    "actual_length_m": round(actual_distance_m, 2),
                    "elapsed_s": round(elapsed_s, 2),
                })
                if stop_state is not None:
                    break
        finally:
            navigation.shutdown()

        safe = stop_state is None
        state = "completed" if safe else stop_state
        return {
            "success": True,
            "safe": safe,
            "state": state,
            "reason": "Simulation vollständig abgeschlossen" if safe else stop_reason,
            "parameters": params.__dict__,
            "executable_segment_count": len(executable),
            "source_segment_limit": max_source_segments,
            "route_signature": self.plan_manager.route_signature(executable),
            "route_signature_segment_count": len(executable),
            "completed_segment_count": len([
                item for item in segment_results if item.get("state") == "completed"
            ]),
            "planned_length_m": round(sum(
                float(item.get("length_m", 0.0) or 0.0) for item in executable
            ), 2),
            "actual_length_m": round(actual_distance_m, 2),
            "duration_s": round(elapsed_s, 2),
            "step_count": step_count,
            "trajectory": trajectory,
            "segments": segment_results,
            "warnings": warnings,
            "nogo_status": stop_nogo,
            "final_pose": dict(pose),
            "final_footprint": self._footprint_coords(pose, params),
        }

    @staticmethod
    def _report_progress(callback, state):
        if callback is not None:
            callback(dict(state))

    def _cancelled_result(self, params, executable):
        return {
            "success": True,
            "safe": False,
            "state": "cancelled",
            "reason": "Simulation abgebrochen",
            "parameters": params.__dict__,
            "executable_segment_count": len(executable),
            "source_segment_limit": None,
            "route_signature": self.plan_manager.route_signature(executable),
            "route_signature_segment_count": len(executable),
            "completed_segment_count": 0,
            "planned_length_m": round(sum(
                float(item.get("length_m", 0.0) or 0.0) for item in executable
            ), 2),
            "actual_length_m": 0.0,
            "duration_s": 0.0,
            "step_count": 0,
            "trajectory": [],
            "segments": [],
            "warnings": [],
            "nogo_status": None,
            "final_pose": None,
            "final_footprint": [],
        }

    def _selected_start(self, plan, start_segment_index, start_coordinate):
        validated = self.plan_manager._validated_coord(start_coordinate)
        if validated is not None:
            return validated
        sequence = [item for item in plan.get("sequence") or [] if self.plan_manager._coords(item)]
        if start_segment_index is not None:
            sequence = [
                item for item in sequence
                if int(item.get("segment_index", -1)) >= int(start_segment_index)
            ]
        if not sequence:
            raise ValueError("Startsegment liegt außerhalb des Plans")
        return list(self.plan_manager._coords(sequence[0])[0])

    @classmethod
    def _initial_pose(cls, coordinate, start_pose, start_heading_deg):
        parsed_heading = cls._heading_from_pose(start_pose)
        heading = parsed_heading if start_heading_deg is None else float(start_heading_deg)
        pose_coord = MowingPlanManager._pose_coord(start_pose)
        coord = pose_coord or coordinate
        return {
            "latitude": float(coord[1]),
            "longitude": float(coord[0]),
            "heading_deg": float(heading or 0.0) % 360.0,
        }

    @staticmethod
    def _heading_from_pose(pose):
        if not isinstance(pose, dict):
            return None
        heading = pose.get("heading_deg", pose.get("heading"))
        try:
            return float(heading) % 360.0
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _initial_heading(executable):
        for segment in executable:
            coords = segment.get("coordinates") or []
            if len(coords) < 2:
                continue
            a = Waypoint(latitude=float(coords[0][1]), longitude=float(coords[0][0]))
            b = Waypoint(latitude=float(coords[1][1]), longitude=float(coords[1][0]))
            heading = NavigationController.bearing_deg(a, b)
            if segment.get("direction") == "reverse":
                heading = (heading + 180.0) % 360.0
            return heading
        return 0.0

    @staticmethod
    def _segment_timeout(segment, pose, params):
        length = float(segment.get("length_m", 0.0) or 0.0)
        coords = segment.get("coordinates") or []
        if coords:
            length = max(length, MowingPathSimulator._distance_pose(
                pose,
                {"latitude": coords[-1][1], "longitude": coords[-1][0]},
            ))
        nominal_s = length / max(0.05, params.max_wheel_speed_m_s)
        return max(20.0, nominal_s * params.segment_timeout_factor + 10.0)

    def _integrate(self, pose, command, linear_speed, angular_speed, params):
        max_level = max(0.01, float(getattr(self.navigation_config, "max_joystick", 0.3)))
        forward_factor = float(getattr(self.pwm_config, "forward_factor", 500.0) or 500.0)
        turn_factor = float(getattr(self.pwm_config, "turn_factor", 300.0))
        ratio = turn_factor / forward_factor
        x = float(command.get("x", 0.0))
        y = float(command.get("y", 0.0))
        # Die Räder können nicht schneller als ihr Maximum. Ohne diese Grenze
        # rechnete das Modell aus x=0.300/y=0.180 eine Radgeschwindigkeit von
        # 0.96 m/s bei 0.8 m/s Maximum - und daraus eine Drehrate, die das
        # Fahrzeug nie erreicht.
        left_level = max(-1.0, min(1.0, (y + x * ratio) / max_level))
        right_level = max(-1.0, min(1.0, (y - x * ratio) / max_level))
        if (
            not params.counter_rotation_supported
            and left_level * right_level < -1e-6
        ):
            # Conservative grass/load model. The real skid-steer stalled in
            # this exact counter-rotating state although the ideal differential
            # model predicted a clean pivot. Never hide that known limitation.
            left_level = 0.0
            right_level = 0.0

        def effective_level(value):
            if abs(value) < params.wheel_command_deadband:
                return 0.0
            return value

        left_speed = effective_level(left_level) * params.max_wheel_speed_m_s
        right_speed = effective_level(right_level) * params.max_wheel_speed_m_s
        target_linear = (left_speed + right_speed) / 2.0
        # Ein Skid-Steer dreht sich nicht so, wie es die reine Differenz der
        # Radgeschwindigkeiten hergibt: die Räder müssen dafür seitlich über
        # den Boden schrammen, und auf Gras unter Last bleibt davon wenig
        # übrig. Gemessen am 02.08. bei vollem Lenkbefehl (x=0.300, y=0.180):
        # 144.7° -> 151.2° in 2.2 s, also 2.9°/s - das ideale Differenzmodell
        # sagt an derselben Stelle 31°/s voraus.
        target_angular = (
            (left_speed - right_speed) / params.track_width_m * params.yaw_efficiency
        )
        if params.command_response_s <= 0.0:
            alpha = 1.0
        else:
            alpha = 1.0 - math.exp(-params.step_s / params.command_response_s)
        linear_speed += (target_linear - linear_speed) * alpha
        angular_speed += (target_angular - angular_speed) * alpha
        heading_mid = math.radians(
            (float(pose["heading_deg"]) + math.degrees(angular_speed * params.step_s) / 2.0) % 360.0
        )
        distance = linear_speed * params.step_s
        north_m = math.cos(heading_mid) * distance
        east_m = math.sin(heading_mid) * distance
        pose["latitude"] += math.degrees(north_m / 6371000.0)
        cos_lat = max(0.01, math.cos(math.radians(pose["latitude"])))
        pose["longitude"] += math.degrees(east_m / (6371000.0 * cos_lat))
        pose["heading_deg"] = (
            float(pose["heading_deg"]) + math.degrees(angular_speed * params.step_s)
        ) % 360.0
        return linear_speed, angular_speed

    @staticmethod
    def _distance_pose(a, b):
        return NavigationController.distance_m(
            Waypoint(float(a["latitude"]), float(a["longitude"])),
            Waypoint(float(b["latitude"]), float(b["longitude"])),
        )

    @staticmethod
    def _append_sample(trajectory, pose, executable_index, segment, command, elapsed_s):
        item = {
            "longitude": round(float(pose["longitude"]), 9),
            "latitude": round(float(pose["latitude"]), 9),
            "heading_deg": round(float(pose["heading_deg"]), 2),
            "time_s": round(elapsed_s, 2),
            "executable_index": executable_index,
            "command_x": round(float(command.get("x", 0.0)), 3),
            "command_y": round(float(command.get("y", 0.0)), 3),
        }
        if segment:
            item.update({
                "type": segment.get("type"),
                "source_type": segment.get("source_type"),
                "source_index": segment.get("source_index"),
                "direction": segment.get("direction"),
                "route_kind": segment.get("route_kind"),
            })
        if not trajectory or any(
            item.get(key) != trajectory[-1].get(key)
            for key in ("longitude", "latitude", "heading_deg", "executable_index")
        ):
            trajectory.append(item)

    @staticmethod
    def _footprint_coords(pose, params):
        heading = math.radians(float(pose["heading_deg"]))
        forward = (math.sin(heading), math.cos(heading))
        right = (math.cos(heading), -math.sin(heading))
        half_length = params.vehicle_length_m / 2.0
        half_width = params.vehicle_width_m / 2.0
        result = []
        for forward_m, right_m in (
            (half_length, -half_width),
            (half_length, half_width),
            (-half_length, half_width),
            (-half_length, -half_width),
            (half_length, -half_width),
        ):
            east_m = forward[0] * forward_m + right[0] * right_m
            north_m = forward[1] * forward_m + right[1] * right_m
            lat = float(pose["latitude"]) + math.degrees(north_m / 6371000.0)
            cos_lat = max(0.01, math.cos(math.radians(lat)))
            lon = float(pose["longitude"]) + math.degrees(east_m / (6371000.0 * cos_lat))
            result.append([round(lon, 9), round(lat, 9)])
        return result
