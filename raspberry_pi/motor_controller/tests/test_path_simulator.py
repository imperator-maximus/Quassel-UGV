import math
import threading
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.mapping.plan_manager import MowingPlanManager
from motor_controller.navigation.navigation_controller import NavigationController
from motor_controller.simulation.path_simulator import (
    MowingPathSimulator,
    SimulationParameters,
    _SimulationMotor,
)
from motor_controller.web.web_server import WebServer
from motor_controller.tests.web_test_support import (
    authenticated_client,
    web_config as build_web_config,
)


class PathSimulatorTests(unittest.TestCase):
    ORIGIN_LAT = 52.0
    ORIGIN_LON = 10.0

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = MowingPlanManager(self.temp_dir.name)
        self.nav_config = SimpleNamespace(
            watchdog_timeout_s=3.0,
            geofence_radius_m=50.0,
            max_joystick=0.30,
            acceptance_radius_m=0.40,
            slowdown_radius_m=0.5,
            turn_kp=0.02,
            track_lookahead_m=0.8,
            pivot_heading_threshold_deg=70.0,
            goto_divergence_limit_m=0.75,
            goto_divergence_samples=5,
            track_cross_track_limit_m=1.0,
            track_heading_block_deg=25.0,
            min_inner_wheel_speed=0.50,
        )
        self.pwm_config = SimpleNamespace(forward_factor=500.0, turn_factor=300.0)
        self.simulator = MowingPathSimulator(
            self.manager,
            self.nav_config,
            self.pwm_config,
        )
        self.params = SimulationParameters(
            step_s=0.05,
            max_wheel_speed_m_s=0.8,
            command_response_s=0.1,
            sample_distance_m=0.2,
            sample_interval_s=0.25,
            max_steps=20000,
        )

    def test_model_reproduces_the_measured_turn_rate(self):
        """Das Fahrzeugmodell muss die Realfahrt vom 02.08. treffen.

        Gemessen bei vollem Lenkbefehl (x=0.300, y=0.180): Kurs 144.7° ->
        151.2° in 2.2 s, also 2.9°/s, bei rund 0.25 m/s Fahrt. Das ideale
        Differenzmodell sagte an derselben Stelle 31°/s voraus - und liess
        die Simulation Strecken abnicken, an denen das Fahrzeug anschliessend
        der Kurve nicht folgen konnte.
        """
        simulator = MowingPathSimulator(self.manager, self.nav_config, self.pwm_config)
        params = SimulationParameters(step_s=0.05, command_response_s=0.0)
        pose = {"latitude": self.ORIGIN_LAT, "longitude": self.ORIGIN_LON, "heading_deg": 0.0}

        linear, angular = 0.0, 0.0
        for _ in range(20):  # 1 s
            linear, angular = simulator._integrate(
                pose, {"x": 0.300, "y": 0.180}, linear, angular, params
            )

        self.assertAlmostEqual(2.9, math.degrees(angular), delta=0.8)
        self.assertAlmostEqual(0.25, linear, delta=0.08)

    def test_full_throttle_matches_the_measured_ground_speed(self):
        simulator = MowingPathSimulator(self.manager, self.nav_config, self.pwm_config)
        params = SimulationParameters(step_s=0.05, command_response_s=0.0)
        pose = {"latitude": self.ORIGIN_LAT, "longitude": self.ORIGIN_LON, "heading_deg": 0.0}

        linear, angular = simulator._integrate(
            pose, {"x": 0.0, "y": 0.300}, 0.0, 0.0, params
        )

        # Real gemessen: 0.33 m/s Track-Fortschritt bei y=0.300.
        self.assertAlmostEqual(0.35, linear, delta=0.05)
        self.assertAlmostEqual(0.0, angular, delta=1e-9)

    def test_forward_track_completes_with_real_navigation_controller(self):
        plan = self._plan([self._segment(0, [(0.0, 0.0), (8.0, 0.0)])])

        result = self.simulator.simulate(
            plan,
            start_coordinate=self._coord(0.0, 0.0),
            start_heading_deg=90.0,
            parameters=self.params,
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["safe"], result.get("reason"))
        self.assertEqual("completed", result["state"])
        self.assertEqual("completed", result["segments"][0]["state"])
        self.assertGreater(result["actual_length_m"], 6.5)
        self.assertLess(self._distance_to_xy(result["final_pose"], 8.0, 0.0), 0.6)

    def test_reverse_track_moves_along_path_without_turnaround(self):
        reverse = self._segment(0, [(0.0, 0.0), (6.0, 0.0)], direction="reverse")
        plan = self._plan([reverse])

        result = self.simulator.simulate(
            plan,
            start_coordinate=self._coord(0.0, 0.0),
            start_heading_deg=270.0,
            parameters=self.params,
        )

        self.assertTrue(result["safe"], result.get("reason"))
        self.assertEqual("reverse", result["segments"][0]["direction"])
        self.assertLess(self._distance_to_xy(result["final_pose"], 6.0, 0.0), 0.6)
        self.assertTrue(any(item.get("command_y", 0.0) < 0.0 for item in result["trajectory"]))

    def test_close_straight_lanes_drive_directly_forward_then_reverse(self):
        first = self._segment(0, [(0.0, 0.0), (10.0, 0.0)], direction="forward")
        second = self._segment(1, [(10.0, 0.35), (0.0, 0.35)], direction="reverse")
        plan = self._plan([first, second])

        result = self.simulator.simulate(
            plan,
            start_coordinate=self._coord(0.0, 0.0),
            start_heading_deg=90.0,
            parameters=self.params,
        )

        self.assertTrue(result["safe"], result.get("reason"))
        self.assertEqual("completed", result["state"])
        self.assertEqual(["mow", "mow"], [item["type"] for item in result["segments"]])
        self.assertEqual(["forward", "reverse"], [item["direction"] for item in result["segments"]])
        self.assertLess(self._distance_to_xy(result["final_pose"], 0.0, 0.35), 0.6)

    def test_opposite_short_transition_is_reversed_but_blocks_on_heading(self):
        """The router still picks the direction that needs the smaller turn
        (reverse here). The remaining 38 degree error exceeds this test's
        track_heading_block_deg (25) - above the roll-alignment band the
        controller still refuses to guess and blocks instead of driving
        through it; see test_stalled_reverse_transition_blocks_instead_of_realigning
        for why an even larger error is unsafe even for rolling."""
        first = self._segment(0, [(0.0, 0.0), (10.0, 0.0)])
        second = self._segment(1, [(8.0, 1.0), (0.0, 1.0)], direction="reverse")
        plan = self._plan([first, second])

        result = self.simulator.simulate(
            plan,
            start_coordinate=self._coord(0.0, 0.0),
            start_heading_deg=90.0,
            parameters=self.params,
        )

        self.assertFalse(result["safe"])
        self.assertEqual("heading_block", result["state"])
        transition = next(item for item in result["segments"] if item["type"] == "transition")
        self.assertEqual("reverse", transition["direction"])
        self.assertEqual("heading_block", transition["state"])

    def test_grass_model_does_not_invent_counter_rotation_motion(self):
        pose = self._pose(0.0, 0.0, 220.0)
        params = SimulationParameters(
            step_s=0.1,
            command_response_s=0.0,
            counter_rotation_supported=False,
        )

        linear, angular = self.simulator._integrate(
            pose,
            {"x": 0.30, "y": -0.04},
            0.0,
            0.0,
            params,
        )

        self.assertEqual(0.0, linear)
        self.assertEqual(0.0, angular)
        self.assertAlmostEqual(220.0, pose["heading_deg"])

    def test_stalled_reverse_transition_blocks_instead_of_realigning(self):
        """Regression for the 2026-07-25 real transition stall.

        The vehicle was already 0.24 m along a 1.73 m reverse transition,
        about 0.32 m off its line and facing 222.5 degrees. The old
        controller requested x=+0.30/y=-0.04, i.e. opposing tracks, and the
        loaded UGV stopped moving. The resulting ~47 degree error exceeds
        this test's track_heading_block_deg (25) - real driving the same
        day showed even the roll-alignment mechanism (proven convergent at
        29.7 degrees, see NavigationControllerTests) is not something to
        trust blindly at this size, and a symmetric-pivot alternative was
        shown to not rotate the real UGV at all (segment-36 stall, same
        date, >4 minutes without any heading change). At this magnitude the
        controller must stop deterministically and report the heading error
        instead of guessing a recovery.
        """
        motor = _SimulationMotor(self.pwm_config)
        navigation = NavigationController(motor, self.nav_config)
        pose = self._pose(0.24, 0.32, 222.5)
        waypoints = [
            {"longitude": self._coord(0.0, 0.0)[0], "latitude": self._coord(0.0, 0.0)[1]},
            {"longitude": self._coord(1.73, 0.0)[0], "latitude": self._coord(1.73, 0.0)[1]},
        ]
        try:
            navigation.set_waypoints(waypoints, mode="track", direction="reverse")
            self.assertTrue(navigation.start())
            # Mehrere Posen: die Sperre verlangt einen anhaltenden Fehler.
            for _ in range(3):
                navigation.on_pose_update(pose)
            status = navigation.get_status()
        finally:
            navigation.shutdown()

        self.assertFalse(status["running"])
        self.assertEqual("heading_block", status["state"])
        self.assertIn("Winkelfehler", status["last_error"])

    def test_simulation_stops_when_driven_footprint_enters_sub_zone(self):
        plan = self._plan(
            [self._segment(0, [(0.0, 0.0), (8.0, 0.0)])],
            zone=[(3.0, -1.0), (5.0, -1.0), (5.0, 1.0), (3.0, 1.0)],
        )

        result = self.simulator.simulate(
            plan,
            start_coordinate=self._coord(0.0, 0.0),
            start_heading_deg=90.0,
            parameters=self.params,
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["safe"])
        self.assertEqual("nogo_stop", result["state"])
        self.assertIn("Footprint", result["reason"])
        self.assertLess(result["actual_length_m"], 5.0)

    def test_simulation_honors_server_cancellation_event(self):
        plan = self._plan(
            [self._segment(0, [(0.0, 0.0), (8.0, 0.0)])],
        )
        cancel_event = threading.Event()
        cancel_event.set()

        result = self.simulator.simulate(
            plan,
            start_coordinate=self._coord(0.0, 0.0),
            start_heading_deg=90.0,
            parameters=self.params,
            cancel_event=cancel_event,
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["safe"])
        self.assertEqual("cancelled", result["state"])
        self.assertEqual(0, result["step_count"])

    def test_simulation_reports_route_and_controller_progress(self):
        plan = self._plan(
            [self._segment(0, [(0.0, 0.0), (3.0, 0.0)])],
        )
        updates = []

        result = self.simulator.simulate(
            plan,
            start_coordinate=self._coord(0.0, 0.0),
            start_heading_deg=90.0,
            parameters=self.params,
            progress_callback=updates.append,
        )

        self.assertTrue(result["success"])
        self.assertEqual("route_building", updates[0]["phase"])
        self.assertTrue(any(
            update.get("phase") == "simulating"
            and update.get("executable_segment_count") == 1
            for update in updates
        ))

    def test_mismatched_saved_transition_is_rerouted_after_orientation(self):
        first = self._segment(0, [(-6.0, 0.0), (-3.0, 0.0)])
        second = self._segment(1, [(3.0, 0.0), (6.0, 0.0)])
        plan = self._plan(
            [first, second],
            zone=[(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)],
        )
        plan["transitions"] = [{
            "type": "transition",
            "transition_index": 0,
            "from_segment_index": 0,
            "to_segment_index": 1,
            "from_type": "rest_lane",
            "to_type": "rest_lane",
            "safe": True,
            "reason": "ok",
            "route_kind": "direct",
            "coordinates": [self._coord(-6.0, -4.0), self._coord(6.0, -4.0)],
            "length_m": 12.0,
        }]

        executable = self.manager.executable_segments(
            plan,
            start_coordinate=self._coord(-6.0, 0.0),
            start_pose=self._pose(-6.0, 0.0, 90.0),
        )

        self.assertEqual(["mow", "transition", "mow"], [item["type"] for item in executable])
        self.assertEqual("runtime_around_sub", executable[1]["route_kind"])
        self.assertGreater(len(executable[1]["coordinates"]), 2)
        self.assertNotIn("direct_reposition", [item.get("route_kind") for item in executable])

    def test_mismatched_transition_without_geometry_is_blocked_not_repositioned(self):
        first = self._segment(0, [(-6.0, 0.0), (-3.0, 0.0)])
        second = self._segment(1, [(3.0, 0.0), (6.0, 0.0)])
        plan = {
            "success": True,
            "name": "Legacy",
            "sequence": [first, second],
            "transitions": [{
                "type": "transition",
                "transition_index": 0,
                "from_segment_index": 0,
                "to_segment_index": 1,
                "safe": True,
                "route_kind": "direct",
                "coordinates": [self._coord(-6.0, -4.0), self._coord(6.0, -4.0)],
                "length_m": 12.0,
            }],
        }

        with self.assertRaisesRegex(ValueError, "nicht sicher neu geroutet"):
            self.manager.executable_segments(
                plan,
                start_coordinate=self._coord(-6.0, 0.0),
                start_pose=self._pose(-6.0, 0.0, 90.0),
            )

    def test_simulation_api_returns_renderable_trajectory_without_hardware(self):
        plan = self._plan([self._segment(0, [(0.0, 0.0), (3.0, 0.0)])])
        web_config = build_web_config()
        dummy = SimpleNamespace()
        mapping = SimpleNamespace(
            plans=self.manager,
            load_plan=lambda _name: {"success": True, "plan": plan},
        )
        navigation = SimpleNamespace(config=self.nav_config)
        server = WebServer(
            web_config,
            dummy,
            dummy,
            dummy,
            dummy,
            navigation_controller=navigation,
            mapping_recorder=mapping,
        )

        response = authenticated_client(server).post(
            "/api/mapping/maps/Simulation/plan/simulate",
            json={
                "plan": plan,
                "start_segment_index": 0,
                "start_coordinate": self._coord(0.0, 0.0),
                "start_heading_deg": 90.0,
                "max_source_segments": 1,
                "parameters": {"max_steps": 10000},
            },
        )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["safe"], payload.get("reason"))
        self.assertGreater(len(payload["trajectory"]), 2)
        self.assertIn("final_footprint", payload)
        self.assertEqual(1, payload["source_segment_limit"])

    def test_simulation_api_rejects_parallel_run(self):
        plan = self._plan([self._segment(0, [(0.0, 0.0), (3.0, 0.0)])])
        web_config = build_web_config()
        dummy = SimpleNamespace()
        mapping = SimpleNamespace(
            plans=self.manager,
            load_plan=lambda _name: {"success": True, "plan": plan},
        )
        server = WebServer(
            web_config,
            dummy,
            dummy,
            dummy,
            dummy,
            navigation_controller=SimpleNamespace(config=self.nav_config),
            mapping_recorder=mapping,
        )
        server._simulation_lock.acquire()
        try:
            response = authenticated_client(server).post(
                "/api/mapping/maps/Simulation/plan/simulate",
                json={"plan": plan},
            )
        finally:
            server._simulation_lock.release()

        self.assertEqual(409, response.status_code)
        self.assertEqual("simulation_busy", response.get_json()["state"])

    def test_simulation_status_and_cancel_api(self):
        plan = self._plan([self._segment(0, [(0.0, 0.0), (3.0, 0.0)])])
        web_config = build_web_config()
        dummy = SimpleNamespace()
        server = WebServer(
            web_config,
            dummy,
            dummy,
            dummy,
            dummy,
            navigation_controller=SimpleNamespace(config=self.nav_config),
            mapping_recorder=SimpleNamespace(
                plans=self.manager,
                load_plan=lambda _name: {"success": True, "plan": plan},
            ),
        )
        server._set_simulation_state({
            "running": True,
            "phase": "simulating",
            "executable_index": 4,
            "executable_segment_count": 20,
            "started_at": 1.0,
        })

        status = authenticated_client(server).get(
            "/api/mapping/maps/Simulation/plan/simulate/status"
        )
        cancel = authenticated_client(server).post(
            "/api/mapping/maps/Simulation/plan/simulate/cancel"
        )

        self.assertEqual(200, status.status_code)
        self.assertTrue(status.get_json()["running"])
        self.assertEqual(4, status.get_json()["executable_index"])
        self.assertEqual(200, cancel.status_code)
        self.assertTrue(cancel.get_json()["cancel_requested"])
        self.assertTrue(server._simulation_cancel_event.is_set())

    def test_playback_api_compiles_executable_route_without_running_controller(self):
        plan = self._plan([self._segment(0, [(0.0, 0.0), (3.0, 0.0)])])
        web_config = build_web_config()
        dummy = SimpleNamespace()
        mapping = SimpleNamespace(
            plans=self.manager,
            load_plan=lambda _name: {"success": True, "plan": plan},
        )
        server = WebServer(
            web_config,
            dummy,
            dummy,
            dummy,
            dummy,
            navigation_controller=SimpleNamespace(config=self.nav_config),
            mapping_recorder=mapping,
        )

        response = authenticated_client(server).post(
            "/api/mapping/maps/Simulation/plan/playback",
            json={
                "plan": plan,
                "start_segment_index": 0,
                "start_coordinate": self._coord(1.0, 0.0),
                "use_current_pose": False,
            },
        )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["success"])
        self.assertEqual("selected_position", payload["start_mode"])
        self.assertEqual(1, payload["executable_segment_count"])
        self.assertEqual("mow", payload["executable_segments"][0]["type"])
        self.assertAlmostEqual(self._coord(1.0, 0.0)[0], payload["executable_segments"][0]["coordinates"][0][0])
        self.assertEqual({"length_m": 1.15, "width_m": 0.79}, payload["vehicle"])

    def test_playback_api_returns_route_in_fast_source_chunks(self):
        plan = self._plan([
            self._segment(0, [(0.0, 0.0), (3.0, 0.0)]),
            self._segment(1, [(3.0, 1.0), (0.0, 1.0)], direction="reverse"),
        ])
        web_config = build_web_config()
        dummy = SimpleNamespace()
        server = WebServer(
            web_config,
            dummy,
            dummy,
            dummy,
            dummy,
            navigation_controller=SimpleNamespace(config=self.nav_config),
            mapping_recorder=SimpleNamespace(
                plans=self.manager,
                load_plan=lambda _name: {"success": True, "plan": plan},
            ),
        )

        response = authenticated_client(server).post(
            "/api/mapping/maps/Simulation/plan/playback",
            json={
                "plan": plan,
                "start_segment_index": 0,
                "start_coordinate": self._coord(0.0, 0.0),
                "max_source_segments": 1,
            },
        )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["has_more"])
        self.assertEqual(1, payload["source_segment_count"])
        self.assertEqual(1, payload["next_source_segment_index"])
        self.assertEqual([0], [item["source_index"] for item in payload["executable_segments"] if item["type"] == "mow"])

    def test_playback_api_previews_rtk_approach_for_legacy_unsafe_plan(self):
        plan = self._plan([self._segment(0, [(0.0, 0.0), (3.0, 0.0)])])
        plan["transitions"] = [{
            "type": "transition",
            "transition_index": 0,
            "from_segment_index": 10,
            "to_segment_index": 11,
            "safe": False,
            "route_kind": "failed",
            "coordinates": [],
            "length_m": 0.0,
        }]
        web_config = build_web_config()
        can = SimpleNamespace(get_sensor_data=lambda: self._pose(-2.0, 0.0, 90.0))
        server = WebServer(
            web_config,
            SimpleNamespace(),
            SimpleNamespace(),
            can,
            SimpleNamespace(),
            navigation_controller=SimpleNamespace(config=self.nav_config),
            mapping_recorder=SimpleNamespace(
                plans=self.manager,
                load_plan=lambda _name: {"success": True, "plan": plan},
            ),
        )

        response = authenticated_client(server).post(
            "/api/mapping/maps/Simulation/plan/playback",
            json={
                "plan": plan,
                "start_segment_index": 0,
                "start_coordinate": self._coord(0.0, 0.0),
                "use_current_pose": True,
                "max_source_segments": 1,
            },
        )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["success"])
        self.assertEqual("current_rtk", payload["start_mode"])
        self.assertEqual(["positioning", "mow"], [item["type"] for item in payload["executable_segments"]])
        self.assertGreater(payload["executable_segments"][0]["length_m"], 1.0)

        with self.assertRaisesRegex(ValueError, "Unsafe transitions"):
            self.manager.executable_segments(plan)

    def test_simulation_reroutes_legacy_unsafe_transition_instead_of_refusing(self):
        """A planning-time unsafe flag must not block the preview.

        The simulator re-routes every transfer through the runtime router, so
        the stored flag describes a route that is not the one being driven.
        Refusing here left the user with an error instead of the answer.
        """
        plan = self._plan([
            self._segment(0, [(0.0, 0.0), (6.0, 0.0)]),
            self._segment(1, [(6.0, 0.35), (0.0, 0.35)], direction="reverse"),
        ])
        plan["transitions"] = [{
            "type": "transition",
            "transition_index": 0,
            "from_segment_index": 0,
            "to_segment_index": 1,
            "safe": False,
            "route_kind": "failed",
            "coordinates": [],
            "length_m": 0.0,
        }]

        result = self.simulator.simulate(
            plan,
            start_coordinate=self._coord(0.0, 0.0),
            start_heading_deg=90.0,
            parameters=self.params,
        )

        self.assertTrue(result["success"], result.get("reason"))
        self.assertNotEqual("route_error", result["state"])
        self.assertEqual(["mow", "mow"], [item["type"] for item in result["segments"]])

    def _plan(self, sequence, zone=None):
        boundary = [(-10.0, -8.0), (10.0, -8.0), (10.0, 8.0), (-10.0, 8.0)]
        plan = {
            "success": True,
            "name": "Simulation",
            "map_name": "Simulation",
            "parameters": {"outer_margin_m": 0.0},
            "sequence": sequence,
            "lanes": [],
            "rest_lanes": sequence,
            "transitions": [],
            "exclusion_contours": [],
            "subs": [],
            "map": self._feature_collection(boundary),
        }
        if zone:
            ring = [self._coord(x, y) for x, y in zone]
            ring.append(ring[0])
            plan["exclusion_contours"] = [{
                "type": "sub_buffer_boundary",
                "coordinates": ring,
                "length_m": 0.0,
            }]
        return plan

    def _segment(self, index, points, direction="forward"):
        coords = [self._coord(x, y) for x, y in points]
        return {
            "type": "rest_lane",
            "segment_index": index,
            "rest_index": index,
            "rest_group": 0,
            "direction": direction,
            "coordinates": coords,
            "length_m": sum(
                math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
                for i in range(len(points) - 1)
            ),
        }

    def _feature_collection(self, points):
        ring = [self._coord(x, y) for x, y in points]
        ring.append(ring[0])
        return {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"type": "boundary"},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }],
        }

    def _coord(self, x, y):
        return [
            self.ORIGIN_LON + x / (111320.0 * math.cos(math.radians(self.ORIGIN_LAT))),
            self.ORIGIN_LAT + y / 111320.0,
        ]

    def _pose(self, x, y, heading):
        coord = self._coord(x, y)
        return {"longitude": coord[0], "latitude": coord[1], "heading_deg": heading}

    def _distance_to_xy(self, pose, x, y):
        target = self._pose(x, y, 0.0)
        return MowingPlanManager._coord_distance_m(
            [pose["longitude"], pose["latitude"]],
            [target["longitude"], target["latitude"]],
        )


if __name__ == "__main__":
    unittest.main()
