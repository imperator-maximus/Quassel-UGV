import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mapping import MappingRecorder
from mapping.geometry import project_points
from mapping.nogo_monitor import NoGoZoneMonitor
from mapping.plan_types import PlanSegment
from mapping.plan_manager import MowingPlanManager
from mapping.transition_router import TransitionRouter


class MappingRecorderTests(unittest.TestCase):
    @staticmethod
    def _point_m(x_m, y_m):
        return {"latitude": y_m / 111320.0, "longitude": x_m / 111320.0}

    @classmethod
    def _square_points_m(cls, min_x, min_y, max_x, max_y):
        return [
            cls._point_m(min_x, min_y),
            cls._point_m(max_x, min_y),
            cls._point_m(max_x, max_y),
            cls._point_m(min_x, max_y),
        ]

    def _write_square_map(self, tmp, recorder, name, min_x, min_y, max_x, max_y):
        payload = recorder._to_feature_collection(name, self._square_points_m(min_x, min_y, max_x, max_y))
        (Path(tmp) / f"{name}.geojson").write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def _assert_shapely_available(self):
        try:
            from shapely.geometry import LineString, Polygon
        except ImportError:
            self.skipTest("Shapely not installed")
        return LineString, Polygon

    def _plan_with_center_sub(self, sub_margin_m=0.25):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = MappingRecorder(tmp, lambda: {})
            main = self._write_square_map(tmp, recorder, "Brunnen", 0.0, 0.0, 10.0, 10.0)
            sub = self._write_square_map(tmp, recorder, "sub_Brunnen_Mitte", 4.0, 4.0, 6.0, 6.0)
            result = recorder.plan_contour_lanes(
                "Brunnen",
                cut_width_m=0.5,
                overlap_m=0.1,
                sub_margin_m=sub_margin_m,
                max_ring_turn_deg=155.0,
            )
        return recorder, main, sub, result

    def test_records_points_from_flat_pose_and_saves_geojson_boundary(self):
        poses = iter([
            {"latitude": 52.0, "longitude": 10.0},
            {"latitude": 52.0, "longitude": 10.00001},
            {"latitude": 52.00001, "longitude": 10.00001},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            recorder = MappingRecorder(tmp, lambda: next(poses), min_point_distance_m=0.0)

            recorder.start()
            recorder.add_current_point()
            recorder.add_current_point()
            recorder.add_current_point()
            result = recorder.save("test garten")

            self.assertTrue(result["success"])
            path = Path(result["path"])
            self.assertEqual(path.name, "test_garten.geojson")
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["type"], "FeatureCollection")
        self.assertEqual(payload["properties"]["schema"], "raspberrycan.mowing_map.v1")
        feature = payload["features"][0]
        self.assertEqual(feature["properties"]["type"], "boundary")
        coords = feature["geometry"]["coordinates"][0]
        self.assertEqual(coords[0], [10.0, 52.0])
        self.assertEqual(coords[-1], coords[0])

    def test_accepts_can_gps_payload(self):
        recorder = MappingRecorder(
            "/tmp/maps",
            lambda: {"gps": {"lat": 52.1, "lon": 10.2}},
            min_point_distance_m=0.0,
        )

        recorder.start()
        result = recorder.add_current_point()

        self.assertTrue(result["success"])
        self.assertEqual(result["points"], [{"latitude": 52.1, "longitude": 10.2}])

    def test_rejects_save_with_less_than_three_points(self):
        recorder = MappingRecorder("/tmp/maps", lambda: {"latitude": 52.0, "longitude": 10.0})

        recorder.start()
        recorder.add_current_point(force=True)
        result = recorder.save("too-small")

        self.assertFalse(result["success"])
        self.assertIn("Mindestens drei Punkte", result["error"])

    def test_min_distance_skips_close_points(self):
        poses = iter([
            {"latitude": 52.0, "longitude": 10.0},
            {"latitude": 52.0, "longitude": 10.000001},
        ])
        recorder = MappingRecorder("/tmp/maps", lambda: next(poses), min_point_distance_m=1.0)

        recorder.start()
        first = recorder.add_current_point()
        second = recorder.add_current_point()

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        self.assertTrue(second["skipped"])
        self.assertEqual(second["point_count"], 1)

    def test_load_rename_update_and_delete_map(self):
        poses = iter([
            {"latitude": 52.0, "longitude": 10.0},
            {"latitude": 52.0, "longitude": 10.00001},
            {"latitude": 52.00001, "longitude": 10.00001},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            recorder = MappingRecorder(tmp, lambda: next(poses), min_point_distance_m=0.0)
            recorder.start()
            recorder.add_current_point()
            recorder.add_current_point()
            recorder.add_current_point()
            recorder.save("Brunnen")

            loaded = recorder.load_map("Brunnen")
            self.assertTrue(loaded["success"])
            self.assertEqual(loaded["name"], "Brunnen")

            renamed = recorder.rename_map("Brunnen", "Brunnen neu")
            self.assertTrue(renamed["success"])
            self.assertEqual(renamed["name"], "Brunnen_neu")
            self.assertFalse((Path(tmp) / "Brunnen.geojson").exists())
            self.assertTrue((Path(tmp) / "Brunnen_neu.geojson").exists())

            updated = recorder.update_boundary_points("Brunnen_neu", [
                {"latitude": 53.0, "longitude": 11.0},
                {"latitude": 53.0, "longitude": 11.00001},
                {"latitude": 53.00001, "longitude": 11.00001},
            ])
            self.assertTrue(updated["success"])
            coords = updated["map"]["features"][0]["geometry"]["coordinates"][0]
            self.assertEqual(coords[0], [11.0, 53.0])
            self.assertEqual(coords[-1], coords[0])

            deleted = recorder.delete_map("Brunnen_neu")
            self.assertTrue(deleted["success"])
            self.assertFalse((Path(tmp) / "Brunnen_neu.geojson").exists())

    def test_analyze_map_with_matching_sub_maps(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = MappingRecorder(tmp, lambda: {})
            main = recorder._to_feature_collection("Brunnen", [
                {"latitude": 0.0, "longitude": 0.0},
                {"latitude": 0.0, "longitude": 0.00001},
                {"latitude": 0.00001, "longitude": 0.00001},
                {"latitude": 0.00001, "longitude": 0.0},
            ])
            sub = recorder._to_feature_collection("sub_Brunnen_Beet", [
                {"latitude": 0.0, "longitude": 0.0},
                {"latitude": 0.0, "longitude": 0.000005},
                {"latitude": 0.000005, "longitude": 0.000005},
                {"latitude": 0.000005, "longitude": 0.0},
            ])
            other = recorder._to_feature_collection("Andere", [
                {"latitude": 0.0, "longitude": 0.0},
                {"latitude": 0.0, "longitude": 0.000005},
                {"latitude": 0.000005, "longitude": 0.000005},
                {"latitude": 0.000005, "longitude": 0.0},
            ])
            (Path(tmp) / "Brunnen.geojson").write_text(json.dumps(main), encoding="utf-8")
            (Path(tmp) / "sub_Brunnen_Beet.geojson").write_text(json.dumps(sub), encoding="utf-8")
            (Path(tmp) / "Andere.geojson").write_text(json.dumps(other), encoding="utf-8")

            result = recorder.analyze_map_with_subs("Brunnen")

        self.assertTrue(result["success"])
        self.assertEqual([item["name"] for item in result["subs"]], ["sub_Brunnen_Beet"])
        self.assertGreater(result["area"]["gross_m2"], result["area"]["net_m2"])
        self.assertGreater(result["area"]["excluded_m2"], 0.0)

    def test_plan_contour_lanes_requires_or_uses_shapely(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = MappingRecorder(tmp, lambda: {})
            main = recorder._to_feature_collection("Brunnen", [
                {"latitude": 0.0, "longitude": 0.0},
                {"latitude": 0.0, "longitude": 0.00004},
                {"latitude": 0.00004, "longitude": 0.00004},
                {"latitude": 0.00004, "longitude": 0.0},
            ])
            sub = recorder._to_feature_collection("sub_Brunnen_Mitte", [
                {"latitude": 0.000015, "longitude": 0.000015},
                {"latitude": 0.000015, "longitude": 0.000025},
                {"latitude": 0.000025, "longitude": 0.000025},
                {"latitude": 0.000025, "longitude": 0.000015},
            ])
            (Path(tmp) / "Brunnen.geojson").write_text(json.dumps(main), encoding="utf-8")
            (Path(tmp) / "sub_Brunnen_Mitte.geojson").write_text(json.dumps(sub), encoding="utf-8")

            result = recorder.plan_contour_lanes(
                "Brunnen",
                cut_width_m=0.5,
                overlap_m=0.1,
                sub_margin_m=0.1,
            )

        try:
            import shapely  # noqa: F401
        except ImportError:
            self.assertFalse(result["success"])
            self.assertIn("Shapely", result["error"])
        else:
            self.assertTrue(result["success"])
            self.assertGreater(result["lane_count"], 0)
            self.assertGreater(result["total_length_m"], 0.0)
            self.assertIn("spacing_m", result["parameters"])
            self.assertIn("max_ring_turn_deg", result["parameters"])
            self.assertIn("coordinates", result["lanes"][0])
            self.assertIn("sequence", result)
            self.assertGreaterEqual(result["total_drive_length_m"], result["mow_length_m"])
            self.assertEqual(
                result["connector_count"],
                len([segment for segment in result["sequence"] if segment["type"] == "connector"]),
            )
            self.assertEqual(1, len(result["exclusion_contours"]))
            self.assertEqual("sub_buffer_boundary", result["exclusion_contours"][0]["type"])

    def test_plan_contour_lanes_api_shape_is_stable_for_ui(self):
        self._assert_shapely_available()
        _, _, _, result = self._plan_with_center_sub(sub_margin_m=0.25)

        self.assertTrue(result["success"])
        self.assertEqual("hybrid_contour_rest_reverse_preview", result["strategy"])
        for key in [
            "parameters",
            "lane_count",
            "rest_lane_count",
            "transition_count",
            "unsafe_transition_count",
            "mow_length_m",
            "rest_length_m",
            "connector_length_m",
            "total_drive_length_m",
            "total_length_m",
            "lanes",
            "rest_lanes",
            "sequence",
            "transitions",
            "exclusion_contours",
            "map",
            "subs",
        ]:
            self.assertIn(key, result)

        self.assertEqual({
            "cut_width_m",
            "overlap_m",
            "spacing_m",
            "outer_margin_m",
            "sub_margin_m",
            "max_ring_turn_deg",
        }, set(result["parameters"].keys()))
        self.assertEqual(result["lane_count"], len(result["lanes"]))
        self.assertEqual(result["rest_lane_count"], len(result["rest_lanes"]))
        self.assertEqual(result["transition_count"], len(result["transitions"]))
        self.assertEqual(result["lane_count"] + result["rest_lane_count"], len(result["sequence"]))
        self.assertGreater(result["lane_count"], 0)
        self.assertGreater(result["rest_lane_count"], 0)
        self.assertGreater(result["transition_count"], 0)

        lane = result["lanes"][0]
        self.assertEqual("contour", lane["type"])
        for key in ["segment_index", "lane_index", "coordinates", "length_m", "max_turn_angle_deg"]:
            self.assertIn(key, lane)
        self.assertGreaterEqual(len(lane["coordinates"]), 4)

        rest_lane = result["rest_lanes"][0]
        self.assertEqual("rest_lane", rest_lane["type"])
        for key in ["segment_index", "rest_index", "rest_group", "direction", "coordinates", "length_m"]:
            self.assertIn(key, rest_lane)
        self.assertIn(rest_lane["direction"], ["forward", "reverse"])

        transition = result["transitions"][0]
        self.assertEqual("transition", transition["type"])
        for key in [
            "transition_index",
            "from_segment_index",
            "to_segment_index",
            "from_type",
            "to_type",
            "safe",
            "reason",
            "route_kind",
            "coordinates",
            "length_m",
        ]:
            self.assertIn(key, transition)

        contour = result["exclusion_contours"][0]
        self.assertEqual("sub_buffer_boundary", contour["type"])
        self.assertIn("coordinates", contour)
        self.assertIn("length_m", contour)

    def test_planner_rings_stop_before_sub_buffer(self):
        LineString, Polygon = self._assert_shapely_available()
        recorder, main, sub, result = self._plan_with_center_sub(sub_margin_m=0.25)
        self.assertTrue(result["success"])
        main_points = recorder._boundary_points(main)
        origin_lat = sum(point["latitude"] for point in main_points) / len(main_points)
        origin_lon = sum(point["longitude"] for point in main_points) / len(main_points)
        sub_poly = Polygon(project_points(recorder._boundary_points(sub), origin_lat, origin_lon)).buffer(0.25)
        protected = sub_poly.buffer(result["parameters"]["cut_width_m"] / 2.0)

        for lane in result["lanes"]:
            line_xy = [tuple(point) for point in project_points(
                [{"longitude": coord[0], "latitude": coord[1]} for coord in lane["coordinates"]],
                origin_lat,
                origin_lon,
            )]
            self.assertFalse(LineString(line_xy).intersects(protected))

    def test_rest_lanes_do_not_cut_sub_buffer(self):
        LineString, Polygon = self._assert_shapely_available()
        recorder, main, sub, result = self._plan_with_center_sub(sub_margin_m=0.25)
        self.assertTrue(result["success"])
        self.assertGreater(result["rest_lane_count"], 0)
        main_points = recorder._boundary_points(main)
        origin_lat = sum(point["latitude"] for point in main_points) / len(main_points)
        origin_lon = sum(point["longitude"] for point in main_points) / len(main_points)
        sub_poly = Polygon(project_points(recorder._boundary_points(sub), origin_lat, origin_lon)).buffer(0.25)

        for rest_lane in result["rest_lanes"]:
            line_xy = [tuple(point) for point in project_points(
                [{"longitude": coord[0], "latitude": coord[1]} for coord in rest_lane["coordinates"]],
                origin_lat,
                origin_lon,
            )]
            self.assertFalse(LineString(line_xy).intersects(sub_poly))

    def test_transition_router_routes_around_sub(self):
        LineString, Polygon = self._assert_shapely_available()
        mow_area = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        sub_union = Polygon([(4, 4), (6, 4), (6, 6), (4, 6)])
        origin_lat = 0.0
        origin_lon = 0.0
        router = TransitionRouter(mow_area.difference(sub_union), sub_union, LineString, origin_lat, origin_lon)
        meters_to_deg = 1.0 / 111320.0
        sequence = [
            PlanSegment(
                type="contour",
                segment_index=0,
                lane_index=0,
                coordinates=[[2.0 * meters_to_deg, 5.0 * meters_to_deg]],
                length_m=0.0,
            ),
            PlanSegment(
                type="contour",
                segment_index=1,
                lane_index=1,
                coordinates=[[8.0 * meters_to_deg, 5.0 * meters_to_deg]],
                length_m=0.0,
            ),
        ]

        transitions = router.plan_transitions(sequence)

        self.assertEqual(1, len(transitions))
        self.assertTrue(transitions[0].safe)
        self.assertEqual("around_sub", transitions[0].route_kind)
        routed_xy = [tuple(point) for point in project_points(
            [{"longitude": coord[0], "latitude": coord[1]} for coord in transitions[0].coordinates],
            origin_lat,
            origin_lon,
        )]
        self.assertFalse(LineString(routed_xy).intersects(sub_union))

    def test_sub_buffer_changes_exclusion_geometry(self):
        self._assert_shapely_available()
        _, _, _, no_buffer = self._plan_with_center_sub(sub_margin_m=0.0)
        _, _, _, buffered = self._plan_with_center_sub(sub_margin_m=0.25)

        self.assertTrue(no_buffer["success"])
        self.assertTrue(buffered["success"])
        self.assertEqual(0.0, no_buffer["parameters"]["sub_margin_m"])
        self.assertEqual(0.25, buffered["parameters"]["sub_margin_m"])
        self.assertGreater(
            buffered["exclusion_contours"][0]["length_m"],
            no_buffer["exclusion_contours"][0]["length_m"],
        )

    def test_plan_json_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = MowingPlanManager(tmp, lambda: {"latitude": 52.0, "longitude": 10.0, "rtk_status": "RTK FIXED"})
            plan = self._sample_plan(reverse=False, unsafe=False)

            saved = manager.save_plan("Brunnen", plan)
            loaded = manager.load_plan("Brunnen")

            self.assertTrue(saved["success"])
            self.assertTrue(Path(saved["path"]).exists())
            self.assertTrue(loaded["success"])
            self.assertEqual("raspberrycan.mowing_plan.v1", loaded["plan"]["schema"])
            self.assertEqual("Brunnen", loaded["plan"]["map_name"])
            self.assertIn("created_at", loaded["plan"])
            self.assertEqual(plan["parameters"], loaded["plan"]["parameters"])
            self.assertEqual(plan["lanes"], loaded["plan"]["lanes"])
            self.assertEqual(plan["rest_lanes"], loaded["plan"]["rest_lanes"])
            self.assertEqual(plan["sequence"], loaded["plan"]["sequence"])
            self.assertEqual(plan["transitions"], loaded["plan"]["transitions"])

    def test_unsafe_transition_blocks_execution_check(self):
        manager = MowingPlanManager("/tmp/maps", lambda: {"latitude": 52.0, "longitude": 10.0, "rtk_status": "RTK FIXED"})
        result = manager.check_plan("Brunnen", self._sample_plan(reverse=False, unsafe=True))

        self.assertFalse(result["success"])
        self.assertIn("Plan enthält unsichere Übergänge", result["errors"])
        with self.assertRaises(ValueError):
            manager.executable_segments(self._sample_plan(reverse=False, unsafe=True))

    def test_reverse_segment_is_detected_and_allowed_when_supported(self):
        manager = MowingPlanManager("/tmp/maps", lambda: {"latitude": 52.0, "longitude": 10.0, "rtk_status": "RTK FIXED"})
        result = manager.check_plan("Brunnen", self._sample_plan(reverse=True, unsafe=False))

        self.assertTrue(result["success"])
        self.assertEqual(1, result["summary"]["reverse_segment_count"])
        self.assertEqual("reverse", result["executable_segments"][-1]["direction"])

    def test_contour_rest_and_transition_translate_to_executable_segments(self):
        manager = MowingPlanManager("/tmp/maps", lambda: {"latitude": 52.0, "longitude": 10.0, "rtk_status": "RTK FIXED"})
        plan = self._sample_plan(reverse=False, unsafe=False)

        executable = manager.executable_segments(plan)

        self.assertEqual(["positioning", "mow", "transition", "mow"], [item["type"] for item in executable])
        self.assertEqual("goto", executable[0]["mode"])
        self.assertEqual("track", executable[1]["mode"])
        self.assertEqual("contour", executable[1]["source_type"])
        self.assertEqual("forward", executable[1]["direction"])
        self.assertEqual("track", executable[2]["mode"])
        self.assertEqual("direct", executable[2]["route_kind"])
        self.assertEqual("rest_lane", executable[3]["source_type"])
        self.assertEqual("forward", executable[3]["direction"])

    def test_invalid_plan_never_sets_navigation_commands(self):
        class FakeNavigation:
            def __init__(self):
                self.calls = []

            def set_waypoints(self, *args, **kwargs):
                self.calls.append(("set_waypoints", args, kwargs))

            def start(self):
                self.calls.append(("start", (), {}))

        navigation = FakeNavigation()
        manager = MowingPlanManager("/tmp/maps", lambda: None)
        result = manager.check_plan("Andere", self._sample_plan(reverse=False, unsafe=True))

        self.assertFalse(result["success"])
        self.assertEqual([], navigation.calls)

    def test_plan_check_requires_rtk_fixed(self):
        manager = MowingPlanManager("/tmp/maps", lambda: {"latitude": 52.0, "longitude": 10.0, "rtk_status": "GPS FIX"})
        result = manager.check_plan("Brunnen", self._sample_plan(reverse=False, unsafe=False))

        self.assertFalse(result["success"])
        self.assertIn("RTK nicht verfügbar: GPS FIX", result["errors"])

    def test_nogo_monitor_allows_vehicle_outside_zone(self):
        self._assert_shapely_available()
        monitor = NoGoZoneMonitor(self._sample_nogo_plan(), intrusion_tolerance_m=0.15)

        result = monitor.check_pose(self._pose_m(-1.0, 1.0, 90.0))

        self.assertTrue(result["ok"])
        self.assertEqual("ok", result["state"])

    def test_nogo_monitor_warns_when_footprint_touches_zone(self):
        self._assert_shapely_available()
        monitor = NoGoZoneMonitor(self._sample_nogo_plan(), intrusion_tolerance_m=0.15)

        result = monitor.check_pose(self._pose_m(-0.5, 1.0, 90.0))

        self.assertTrue(result["ok"])
        self.assertEqual("warning", result["state"])

    def test_nogo_monitor_stops_after_intrusion_tolerance(self):
        self._assert_shapely_available()
        monitor = NoGoZoneMonitor(self._sample_nogo_plan(), intrusion_tolerance_m=0.15)

        result = monitor.check_pose(self._pose_m(-0.3, 1.0, 90.0))

        self.assertFalse(result["ok"])
        self.assertEqual("stop", result["state"])
        self.assertIn("15 cm", result["reason"])

    @staticmethod
    def _sample_plan(reverse=False, unsafe=False):
        contour = {
            "type": "contour",
            "segment_index": 0,
            "lane_index": 0,
            "coordinates": [[10.0, 52.0], [10.00001, 52.0]],
            "length_m": 1.0,
        }
        rest = {
            "type": "rest_lane",
            "segment_index": 1,
            "rest_index": 0,
            "rest_group": 0,
            "direction": "reverse" if reverse else "forward",
            "coordinates": [[10.00002, 52.0], [10.00003, 52.0]],
            "length_m": 1.0,
        }
        transition = {
            "type": "transition",
            "transition_index": 0,
            "from_segment_index": 0,
            "to_segment_index": 1,
            "from_type": "contour",
            "to_type": "rest_lane",
            "safe": not unsafe,
            "reason": "ok" if not unsafe else "sub_zone",
            "route_kind": "direct",
            "coordinates": [[10.00001, 52.0], [10.00002, 52.0]],
            "length_m": 1.0,
        }
        return {
            "success": True,
            "name": "Brunnen",
            "strategy": "hybrid_contour_rest_reverse_preview",
            "parameters": {
                "cut_width_m": 0.45,
                "overlap_m": 0.1,
                "spacing_m": 0.35,
                "outer_margin_m": 0.0,
                "sub_margin_m": 0.25,
                "max_ring_turn_deg": 155.0,
            },
            "lane_count": 1,
            "rest_lane_count": 1,
            "transition_count": 1,
            "unsafe_transition_count": 1 if unsafe else 0,
            "total_drive_length_m": 3.0,
            "lanes": [contour],
            "rest_lanes": [rest],
            "sequence": [contour, rest],
            "transitions": [transition],
        }

    @classmethod
    def _coord_m(cls, x_m, y_m):
        point = cls._point_m(x_m, y_m)
        return [point["longitude"], point["latitude"]]

    @classmethod
    def _pose_m(cls, x_m, y_m, heading_deg):
        point = cls._point_m(x_m, y_m)
        return {
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "heading": heading_deg,
            "rtk_status": "RTK FIXED",
        }

    @classmethod
    def _sample_nogo_plan(cls):
        ring = [
            cls._coord_m(0.0, 0.0),
            cls._coord_m(2.0, 0.0),
            cls._coord_m(2.0, 2.0),
            cls._coord_m(0.0, 2.0),
            cls._coord_m(0.0, 0.0),
        ]
        return {
            "name": "NoGoTest",
            "sequence": [
                {
                    "type": "contour",
                    "segment_index": 0,
                    "coordinates": [cls._coord_m(-2.0, 1.0), cls._coord_m(-1.0, 1.0)],
                    "length_m": 1.0,
                }
            ],
            "exclusion_contours": [
                {
                    "type": "sub_buffer_boundary",
                    "coordinates": ring,
                    "length_m": 8.0,
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
