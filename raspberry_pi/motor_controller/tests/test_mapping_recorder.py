import json
import math
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mapping import MappingRecorder
from mapping.geometry import orient_ring_xy, project_points, signed_area_xy
from mapping.lane_planner import LanePlanner
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
            main = self._write_square_map(tmp, recorder, "Brunnen", 0.0, 0.0, 20.0, 20.0)
            sub = self._write_square_map(tmp, recorder, "sub_Brunnen_Mitte", 8.0, 8.0, 12.0, 12.0)
            result = recorder.plan_contour_lanes(
                "Brunnen",
                cut_width_m=0.5,
                overlap_m=0.1,
                sub_margin_m=sub_margin_m,
                max_ring_turn_deg=155.0,
                sub_contour_count=3,
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
            self.assertIn("sub_contour_count", result["parameters"])
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
        self.assertEqual("hybrid_contour_suboffset_rest_reverse", result["strategy"])
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
            "sub_contour_count",
            "rest_pattern",
            "max_lane_curvature_deg_per_m",
        }, set(result["parameters"].keys()))
        self.assertEqual(result["lane_count"], len(result["lanes"]))
        self.assertEqual(result["rest_lane_count"], len(result["rest_lanes"]))
        self.assertEqual(result["transition_count"], len(result["transitions"]))
        self.assertEqual(result["lane_count"] + result["rest_lane_count"], len(result["sequence"]))
        self.assertGreater(result["lane_count"], 0)
        self.assertGreater(
            len([segment for segment in result["sequence"] if segment["type"] in ("contour", "sub_contour")]),
            0,
        )
        self.assertGreater(result["transition_count"], 0)

        lane = result["lanes"][0]
        self.assertEqual("contour", lane["type"])
        for key in ["segment_index", "lane_index", "coordinates", "length_m", "max_turn_angle_deg"]:
            self.assertIn(key, lane)
        self.assertGreaterEqual(len(lane["coordinates"]), 4)

        if result["rest_lanes"]:
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

    def test_sub_contours_are_planned_before_rest_lanes(self):
        LineString, Polygon = self._assert_shapely_available()
        recorder, main, sub, result = self._plan_with_center_sub(sub_margin_m=0.25)

        self.assertTrue(result["success"])
        sub_contours = [segment for segment in result["sequence"] if segment["type"] == "sub_contour"]
        self.assertGreater(len(sub_contours), 0)
        rest_indices = [
            index for index, segment in enumerate(result["sequence"])
            if segment["type"] == "rest_lane"
        ]
        if rest_indices:
            self.assertLess(result["sequence"].index(sub_contours[0]), min(rest_indices))

        main_points = recorder._boundary_points(main)
        origin_lat = sum(point["latitude"] for point in main_points) / len(main_points)
        origin_lon = sum(point["longitude"] for point in main_points) / len(main_points)
        sub_poly = Polygon(project_points(recorder._boundary_points(sub), origin_lat, origin_lon)).buffer(0.25)
        protected = sub_poly.buffer(result["parameters"]["cut_width_m"] / 2.0)
        for sub_contour in sub_contours:
            line_xy = [tuple(point) for point in project_points(
                [{"longitude": coord[0], "latitude": coord[1]} for coord in sub_contour["coordinates"]],
                origin_lat,
                origin_lon,
            )]
            line = LineString(line_xy)
            self.assertFalse(line.intersects(protected))
            self.assertGreaterEqual(sub_contour["length_m"], 2.0)

    def test_rest_lanes_start_at_the_first_recorded_map_point(self):
        """Der Plan beginnt dort, wo die Kartenaufzeichnung begonnen hat.

        Die Abtastung läuft immer vom Südrand nach Norden; ohne Verankerung
        begann der Plan deshalb unabhängig von der Karte unten - auf der
        Wiese am entgegengesetzten Ende der Fläche.
        """
        self._assert_shapely_available()

        for corner, name in (((0.0, 0.0), "Suedwest"), ((30.0, 30.0), "Nordost")):
            with tempfile.TemporaryDirectory() as tmp:
                recorder = MappingRecorder(tmp, lambda: {})
                # Rand ab der jeweiligen Ecke aufgezeichnet.
                square = [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)]
                start = square.index(corner)
                points = [
                    self._point_m(x, y) for x, y in square[start:] + square[:start]
                ]
                payload = recorder._to_feature_collection("Brunnen", points)
                (Path(tmp) / "Brunnen.geojson").write_text(json.dumps(payload), encoding="utf-8")

                result = recorder.plan_contour_lanes(
                    "Brunnen", cut_width_m=0.85, overlap_m=0.5,
                    max_lane_curvature_deg_per_m=8.0,
                )

            self.assertTrue(result["success"], name)
            rest = [s for s in result["sequence"] if s["type"] == "rest_lane"]
            self.assertGreater(len(rest), 2, name)
            manager = MowingPlanManager("/tmp/maps")
            anchor = [points[0]["longitude"], points[0]["latitude"]]
            start = manager._coord_distance_m(rest[0]["coordinates"][0], anchor)
            # Keine Bahn im Plan darf naeher am Startpunkt liegen als die
            # erste. Nur "naeher als das Planende" zu pruefen liess einen
            # Start 13,2 m daneben durchgehen, obwohl 0,3 m moeglich waren
            # (real, 02.08.).
            best = min(
                min(manager._coord_distance_m(s["coordinates"][0], anchor),
                    manager._coord_distance_m(s["coordinates"][-1], anchor))
                for s in rest
            )
            # Der Plan beginnt am naechstgelegenen *Kettenende*, nicht an der
            # naechstgelegenen Bahn: die Kette wird nicht aufgetrennt, weil
            # der Wechsel zwischen den Haelften real 72,9° auf 5,92 m
            # verlangte und den Mäher nach der halben Wiese stoppte (06.08.).
            ende = manager._coord_distance_m(rest[-1]["coordinates"][-1], anchor)
            self.assertLess(
                start, ende,
                "Plan beginnt am falschen Kettenende (%.1f m statt %.1f m, %s)"
                % (start, ende, name),
            )

    def test_every_compiled_segment_starts_within_the_controller_limit(self):
        """Kein Segment darf mit mehr als 45° Winkelfehler beginnen.

        Der Regler sperrt am Bahnanfang unabhängig von der Segmentlänge. Real
        stoppte der Mäher deshalb nach der ersten Planhälfte: der Wechsel zur
        zweiten war 5,92 m lang und verlangte 70,8° (06.08.). Die Regel
        "Strecke reicht zum Drehen" hatte ihn durchgelassen.
        """
        self._assert_shapely_available()
        manager = MowingPlanManager("/tmp/maps")

        with tempfile.TemporaryDirectory() as tmp:
            recorder = MappingRecorder(tmp, lambda: {})
            self._write_square_map(tmp, recorder, "Brunnen", 0.0, 0.0, 24.0, 40.0)
            plan = recorder.plan_contour_lanes(
                "Brunnen", cut_width_m=0.85, overlap_m=0.5,
                max_lane_curvature_deg_per_m=8.0,
            )

        self.assertTrue(plan["success"])
        executable = manager.executable_segments(
            plan, start_segment_index=0, start_pose=self._pose_m(-6.0, 2.0, 90.0),
        )
        heading = 90.0
        schlimmster = 0.0
        for index, segment in enumerate(executable):
            coords = segment["coordinates"]
            if len(coords) >= 2:
                bearing = manager._edge_bearing_deg(coords[0], coords[1])
                if segment.get("direction") == "reverse":
                    bearing = (bearing + 180.0) % 360.0
                schlimmster = max(schlimmster, manager._angle_error_deg(bearing, heading))
                self.assertLessEqual(
                    manager._angle_error_deg(bearing, heading), 45.0,
                    "Segment %d (%s, %.2f m) beginnt mit zu grossem Winkelfehler"
                    % (index, segment["type"], segment.get("length_m", 0.0)),
                )
            heading = manager._segment_end_heading(segment, heading)
        self.assertGreater(len(executable), 10)

    def test_blocked_transfer_becomes_a_turn_in_manoeuvre(self):
        """Ein Spurwechsel wird eingedreht statt geknickt.

        Zwei parallele Bahnen mit seitlichem Versatz verlangen als direkter
        Übergang eine Drehung quer zur Fahrt - real 72,9° auf 5,92 m, vom
        Regler gesperrt, halbe Wiese ungemäht (06.08.). Stattdessen fährt das
        Fahrzeug in die Zielbahn hinein, stößt an deren Anfang zurück und
        beginnt sie dann ohne Winkelfehler.
        """
        manager = MowingPlanManager("/tmp/maps")
        # Zwei lange Bahnen nach Sueden, 6 m seitlich versetzt.
        erste = {
            "type": "rest_lane", "segment_index": 0, "direction": "forward",
            "coordinates": [self._coord_m(0.0, 40.0), self._coord_m(0.0, 0.0)],
        }
        zweite = {
            "type": "rest_lane", "segment_index": 1, "direction": "forward",
            "coordinates": [self._coord_m(6.0, 40.0), self._coord_m(6.0, 0.0)],
        }
        plan = {
            "success": True, "name": "Brunnen", "map_name": "Brunnen",
            "sequence": [erste, zweite], "transitions": [], "rest_lanes": [], "lanes": [],
            "parameters": {"outer_margin_m": 0.0},
            "map": self._map_feature(-15.0, -15.0, 25.0, 55.0),
            "total_drive_length_m": 80.0,
        }

        executable = manager.executable_segments(
            plan, start_segment_index=0, start_pose=self._pose_m(0.0, 41.0, 180.0),
        )

        # Das Manöver selbst: Anfahrt in die Bahn, dann rückwärts an deren
        # Anfang - und beides fahrbar.
        lane = executable[-1]["coordinates"]
        manoever = manager._turn_in_transfer(
            executable[0]["coordinates"][-1], 180.0, lane,
            manager._runtime_transition_router(plan),
        )
        self.assertIsNotNone(manoever)
        self.assertEqual(
            ["turn_in_approach", "turn_in_backup"],
            [item["route_kind"] for item in manoever],
        )
        self.assertEqual("reverse", manoever[1]["direction"])
        # Das Rückstoßstück endet am Bahnanfang.
        self.assertLess(
            manager._coord_distance_m(manoever[1]["coordinates"][-1], lane[0]), 0.05
        )

        # Und die kompilierte Kette ist durchgehend fahrbar.
        heading = 180.0
        for segment in executable:
            coords = segment["coordinates"]
            if len(coords) >= 2:
                bearing = manager._edge_bearing_deg(coords[0], coords[1])
                if segment.get("direction") == "reverse":
                    bearing = (bearing + 180.0) % 360.0
                self.assertLessEqual(
                    manager._angle_error_deg(bearing, heading), 45.0,
                    "%s beginnt zu schraeg" % segment.get("route_kind", segment["type"]),
                )
            heading = manager._segment_end_heading(segment, heading)

    def test_transition_across_a_concave_area_stays_inside(self):
        """Ein langer Wechsel wird innen am Rand geführt, nicht quer darüber.

        Auf einer nicht konvexen Fläche schneidet die gerade Verbindung
        zwischen zwei weit auseinanderliegenden Bahnenden über den Rand. Real
        blockierten dadurch zwei Übergänge (20 m und 33 m) den ganzen Plan mit
        "Plan enthält unsichere Übergänge" - Play tat nichts (02.08.).
        """
        LineString, Polygon = self._assert_shapely_available()
        # L-Form: die Verbindung der beiden Schenkelenden laeuft aussen herum.
        ecke = Polygon(project_points([
            self._point_m(0.0, 0.0), self._point_m(40.0, 0.0),
            self._point_m(40.0, 12.0), self._point_m(12.0, 12.0),
            self._point_m(12.0, 40.0), self._point_m(0.0, 40.0),
        ], 0.0, 0.0))
        router = TransitionRouter(ecke, None, LineString, 0.0, 0.0)

        start = [self._point_m(36.0, 6.0)["longitude"], self._point_m(36.0, 6.0)["latitude"]]
        end = [self._point_m(6.0, 36.0)["longitude"], self._point_m(6.0, 36.0)["latitude"]]
        result = router.plan_between(start, end).to_dict()

        self.assertTrue(result["safe"], result.get("reason"))
        self.assertEqual("inside_boundary", result["route_kind"])
        self.assertGreater(len(result["coordinates"]), 2)
        # Der gefahrene Weg bleibt in der Flaeche.
        self.assertTrue(router.is_polyline_safe(result["coordinates"]))
        # Und er ist laenger als die Sehne, weil er um die Ecke fuehrt.
        manager = MowingPlanManager("/tmp/maps")
        self.assertGreater(result["length_m"], manager._coord_distance_m(start, end))

    def test_lanes_follow_the_longest_boundary_edge(self):
        """Bahnen laufen entlang der langen Achse, nicht fest Ost-West.

        Die Abtastung war fest waagerecht. Auf einer 20 x 60 m langen Fläche
        standen die Bahnen damit quer - kurz, viele, und die Einfahrt lag
        quer zur Bahnrichtung. Real ist das die Wiese zwischen zwei Hecken,
        wo nur von der Schmalseite eingefahren werden kann (02.08.).
        """
        self._assert_shapely_available()

        with tempfile.TemporaryDirectory() as tmp:
            recorder = MappingRecorder(tmp, lambda: {})
            # Lange Achse Nord-Sued.
            self._write_square_map(tmp, recorder, "Brunnen", 0.0, 0.0, 20.0, 60.0)
            result = recorder.plan_contour_lanes(
                "Brunnen", cut_width_m=0.85, overlap_m=0.5,
                max_lane_curvature_deg_per_m=8.0,
            )

        self.assertTrue(result["success"])
        manager = MowingPlanManager("/tmp/maps")
        rest = [s for s in result["sequence"] if s["type"] == "rest_lane"]
        self.assertGreater(len(rest), 5)
        laengste = max(rest, key=lambda s: s["length_m"])
        richtung = manager._edge_bearing_deg(
            laengste["coordinates"][0], laengste["coordinates"][-1]
        )
        # Nord-Sued, in beliebiger Fahrtrichtung.
        self.assertLess(min(richtung % 180.0, 180.0 - (richtung % 180.0)), 15.0)
        self.assertGreater(laengste["length_m"], 30.0)

    def test_too_tight_rings_give_way_to_straight_lanes(self):
        """Ringe enden dort, wo das Fahrzeug ihnen nicht mehr folgen kann.

        Konturringe werden nach innen zwangsläufig enger (Krümmung ~ 1/Radius).
        Auf der Wiese enthielt der Plan dadurch Ringe mit bis zu 818°/m -
        das Fahrzeug schafft rollend rund 10-15°/m und lief real aus der Spur
        (02.08.). Die Fläche weiter innen gehört den geraden Bahnen.
        """
        self._assert_shapely_available()

        with tempfile.TemporaryDirectory() as tmp:
            recorder = MappingRecorder(tmp, lambda: {})
            self._write_square_map(tmp, recorder, "Brunnen", 0.0, 0.0, 12.0, 12.0)

            eng = recorder.plan_contour_lanes(
                "Brunnen", cut_width_m=0.85, overlap_m=0.5,
                max_lane_curvature_deg_per_m=8.0,
            )
            weit = recorder.plan_contour_lanes(
                "Brunnen", cut_width_m=0.85, overlap_m=0.5,
                max_lane_curvature_deg_per_m=60.0,
            )

        self.assertTrue(eng["success"])
        self.assertTrue(weit["success"])
        self.assertLess(eng["lane_count"], weit["lane_count"])
        self.assertGreater(eng["skipped_curved_lanes"], 0)
        # Die weggefallene Fläche verschwindet nicht, sie wird gerade gemäht.
        self.assertGreater(eng["rest_lane_count"], weit["rest_lane_count"])

    def test_all_planned_rings_share_one_traversal_sense(self):
        """Ringe müssen alle gleich herum laufen.

        Der aufgezeichnete Aussenrand behält die Reihenfolge, in der er
        abgefahren wurde, die inneren Ringe kommen aus Buffer-Operationen -
        beide Drehsinne landeten so in einem Plan. Das Fahrzeug erreichte das
        Ende eines Rings dann entgegen dem Start des nächsten und sollte auf
        0,39 m um 156° drehen (real, 02.08.), was kein Skid-Steer schafft.
        """
        self._assert_shapely_available()
        _, _, _, result = self._plan_with_center_sub(sub_margin_m=0.25)

        self.assertTrue(result["success"])
        rings = [
            segment for segment in result["sequence"]
            if segment["type"] in ("contour", "sub_contour")
        ]
        self.assertGreater(len(rings), 1)
        senses = {
            signed_area_xy([(coord[0], coord[1]) for coord in ring["coordinates"]]) < 0.0
            for ring in rings
        }
        self.assertEqual(1, len(senses), "Ringe laufen nicht alle gleich herum")

    def test_orient_ring_xy_flips_only_the_opposite_sense(self):
        counter_clockwise = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
        clockwise = list(reversed(counter_clockwise))

        self.assertLess(signed_area_xy(orient_ring_xy(counter_clockwise, clockwise=True)), 0.0)
        self.assertEqual(clockwise, orient_ring_xy(clockwise, clockwise=True))
        self.assertGreater(signed_area_xy(orient_ring_xy(clockwise, clockwise=False)), 0.0)
        # Der Ring bleibt geschlossen und behält alle Stützpunkte.
        flipped = orient_ring_xy(counter_clockwise, clockwise=True)
        self.assertEqual(len(counter_clockwise), len(flipped))
        self.assertEqual(flipped[0], flipped[-1])

    def test_sub_contour_count_is_tunable(self):
        self._assert_shapely_available()

        with tempfile.TemporaryDirectory() as tmp:
            recorder = MappingRecorder(tmp, lambda: {})
            self._write_square_map(tmp, recorder, "Brunnen", 0.0, 0.0, 20.0, 20.0)
            self._write_square_map(tmp, recorder, "sub_Brunnen_Mitte", 8.0, 8.0, 12.0, 12.0)

            without_sub_contours = recorder.plan_contour_lanes(
                "Brunnen",
                cut_width_m=0.5,
                overlap_m=0.1,
                sub_margin_m=0.25,
                sub_contour_count=0,
            )
            one_sub_contour = recorder.plan_contour_lanes(
                "Brunnen",
                cut_width_m=0.5,
                overlap_m=0.1,
                sub_margin_m=0.25,
                sub_contour_count=1,
            )

        self.assertTrue(without_sub_contours["success"])
        self.assertTrue(one_sub_contour["success"])
        self.assertEqual(0, without_sub_contours["parameters"]["sub_contour_count"])
        self.assertEqual(1, one_sub_contour["parameters"]["sub_contour_count"])
        self.assertEqual(0, len([
            segment for segment in without_sub_contours["sequence"]
            if segment["type"] == "sub_contour"
        ]))
        self.assertEqual(1, len([
            segment for segment in one_sub_contour["sequence"]
            if segment["type"] == "sub_contour"
        ]))

    def _serpentine_lanes(self, cut_width_m=0.85, overlap_m=0.50, width=20.0, height=12.0):
        """Run the rest-lane generator directly on a known rectangle.

        Ring lanes cover a convex area completely, so a whole-planner
        fixture yields no rest area at all; the pattern itself is what
        needs checking here.
        """
        LineString, Polygon = self._assert_shapely_available()
        planner = LanePlanner(
            cut_width_m=cut_width_m,
            overlap_m=overlap_m,
            rest_pattern="serpentine",
        )
        area = Polygon([(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)])
        lanes = planner._generate_rest_lanes(area, LineString, 0.0, 0.0)
        return planner, [lane.to_dict() for lane in lanes]

    def test_serpentine_passes_meet_end_to_end_without_sideways_steps(self):
        """The whole point of the pattern: no perpendicular connectors.

        A four-wheel skid-steer cannot translate sideways, so parallel lanes
        joined by a short perpendicular hop are unreachable for it - the hop
        demands a 60-90 degree turn for half a metre and the same turn
        straight back (real, 26.07.). Slanting each pass so it ends where the
        next one begins removes the hops entirely.
        """
        _, lanes = self._serpentine_lanes()

        self.assertGreater(len(lanes), 5)
        for previous, following in zip(lanes, lanes[1:]):
            if previous.get("rest_group") != following.get("rest_group"):
                continue
            gap = MowingPlanManager._coord_distance_m(
                previous["coordinates"][-1], following["coordinates"][0]
            )
            self.assertLess(gap, 0.05, "consecutive passes must share their endpoint")

    def test_serpentine_keeps_the_body_almost_straight_between_passes(self):
        _, lanes = self._serpentine_lanes()

        headings = []
        for lane in lanes:
            (lon1, lat1), (lon2, lat2) = lane["coordinates"][0], lane["coordinates"][-1]
            path = self._bearing_deg(lat1, lon1, lat2, lon2)
            headings.append((path + 180.0) % 360.0 if lane["direction"] == "reverse" else path)

        self.assertEqual(
            ["forward", "reverse"] * (len(lanes) // 2),
            [lane["direction"] for lane in lanes][: 2 * (len(lanes) // 2)],
        )
        for previous, following in zip(headings, headings[1:]):
            yaw = abs(((following - previous + 540.0) % 360.0) - 180.0)
            self.assertLess(yaw, 25.0, f"body had to yaw {yaw:.1f} deg between passes")

    def test_serpentine_covers_the_area_when_spacing_fits_the_deck(self):
        """Two passes converge at the turning end, so the local spacing
        doubles there and full coverage needs 2*spacing <= cut_width.
        Measured on the real 815 m2 area: 0.7 % uncut at cut 0.85 /
        spacing 0.35, but 14.4 % at cut 0.45 / spacing 0.35."""
        LineString, Polygon = self._assert_shapely_available()
        from shapely.ops import unary_union

        def uncut_fraction(cut_width_m, overlap_m):
            planner, lanes = self._serpentine_lanes(cut_width_m, overlap_m)
            swaths = []
            for lane in lanes:
                xy = [
                    (
                        coord[0] * 111320.0 * math.cos(0.0),
                        coord[1] * 111320.0,
                    )
                    for coord in lane["coordinates"]
                ]
                swaths.append(LineString(xy).buffer(cut_width_m / 2.0, cap_style=2))
            covered = unary_union(swaths)
            # Ignore a spacing-wide rim: the perimeter is the ring lanes' job.
            inner = Polygon([(0.0, 0.0), (20.0, 0.0), (20.0, 12.0), (0.0, 12.0)]).buffer(
                -planner.parameters.spacing_m * 2.0
            )
            return inner.difference(covered).area / inner.area

        self.assertLess(uncut_fraction(0.85, 0.50), 0.02)   # spacing 0.35, 2s <= cut
        self.assertGreater(uncut_fraction(0.45, 0.10), 0.05)  # spacing 0.35, 2s > cut

    def test_serpentine_warns_when_spacing_is_too_wide_for_the_deck(self):
        self._assert_shapely_available()
        with tempfile.TemporaryDirectory() as tmp:
            recorder = MappingRecorder(tmp, lambda: {})
            self._write_square_map(tmp, recorder, "Wiese", 0.0, 0.0, 20.0, 12.0)
            good = recorder.plan_contour_lanes(
                "Wiese", cut_width_m=0.85, overlap_m=0.50, rest_pattern="serpentine")
            bad = recorder.plan_contour_lanes(
                "Wiese", cut_width_m=0.45, overlap_m=0.10, rest_pattern="serpentine")

        self.assertEqual([], good["warnings"])
        self.assertTrue(bad["warnings"])
        self.assertIn("Bahnabstand", bad["warnings"][0])

    def test_parallel_pattern_stays_the_default(self):
        self._assert_shapely_available()
        _, _, _, result = self._plan_with_center_sub()

        self.assertEqual("parallel", result["parameters"]["rest_pattern"])
        self.assertEqual([], result["warnings"])

    def test_planner_does_not_emit_short_rest_lanes(self):
        self._assert_shapely_available()
        _, _, _, result = self._plan_with_center_sub(sub_margin_m=0.25)

        self.assertTrue(result["success"])
        self.assertEqual([], [
            segment for segment in result["rest_lanes"]
            if segment["length_m"] < 2.0
        ])

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

    def test_transition_router_routes_around_vehicle_footprint_clearance(self):
        LineString, Polygon = self._assert_shapely_available()
        mow_area = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        sub_union = Polygon([(4, 4), (6, 4), (6, 6), (4, 6)])
        router = TransitionRouter(
            mow_area.difference(sub_union), sub_union, LineString, 0.0, 0.0
        )
        meters_to_deg = 1.0 / 111320.0

        transition = router.plan_between(
            [2.0 * meters_to_deg, 3.7 * meters_to_deg],
            [8.0 * meters_to_deg, 3.7 * meters_to_deg],
        )

        self.assertTrue(transition.safe)
        self.assertEqual("around_sub", transition.route_kind)
        routed_xy = [tuple(point) for point in project_points(
            [{"longitude": coord[0], "latitude": coord[1]} for coord in transition.coordinates],
            0.0,
            0.0,
        )]
        self.assertGreater(LineString(routed_xy).distance(sub_union), 0.34)

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

    def test_runtime_rejected_transition_names_the_reason_not_the_legacy_flag(self):
        """Ein neu berechneter Übergang trägt seinen Grund im Ergebnis.

        Bis 02.08. meldete jeder verworfene Übergang "Unsafe transitions
        blockieren die Ausführung" - dieselbe Meldung wie für ein altes
        safe:false im gespeicherten Plan. Damit war nicht erkennbar, dass der
        Router gerade eben live entschieden hatte und warum.
        """
        manager = MowingPlanManager("/tmp/maps")

        with self.assertRaises(ValueError) as context:
            manager._transition_segment({
                "safe": False,
                "reason": "outside_mow_area",
                "from_segment_index": 0,
                "to_segment_index": 1,
                "route_kind": "direct",
                "coordinates": [],
            })

        message = str(context.exception)
        self.assertIn("Segment 0 → 1", message)
        self.assertIn("verlässt die Mähfläche", message)
        self.assertNotIn("Unsafe transitions", message)

    def test_legacy_unsafe_transition_without_reason_keeps_its_message(self):
        manager = MowingPlanManager("/tmp/maps")

        with self.assertRaisesRegex(ValueError, "Unsafe transitions"):
            manager._transition_segment({
                "safe": False,
                "route_kind": "direct",
                "coordinates": [],
            })

    def test_selected_start_is_projected_onto_the_path(self):
        """Der Slider-Punkt darf nicht als Bahnstützpunkt landen.

        Bis 1 m Abweichung wird bewusst toleriert; unprojiziert eingesetzt lag
        der Ringstart real 0,49 m ausserhalb der Mähfläche und der Übergang
        zum nächsten Ring wurde als outside_mow_area verworfen (02.08.).
        """
        manager = MowingPlanManager("/tmp/maps")
        segment = {
            "type": "contour",
            "coordinates": [
                [10.0, 52.0], [10.001, 52.0], [10.001, 52.001],
                [10.0, 52.001], [10.0, 52.0],
            ],
        }
        # Rund 0,5 m nördlich neben der unteren Ringkante.
        beside = [10.0005, 52.0000045]

        coords = manager._coords_from_selected_start(segment, beside)

        self.assertAlmostEqual(10.0005, coords[0][0], places=7)
        self.assertAlmostEqual(52.0, coords[0][1], places=7)
        self.assertEqual(coords[0], coords[-1])
        self.assertLess(
            manager._point_to_line_distance_m(coords[0], [10.0, 52.0], [10.001, 52.0]),
            0.01,
        )

    def test_reverse_segment_is_detected_and_allowed_when_supported(self):
        manager = MowingPlanManager("/tmp/maps", lambda: {"latitude": 52.0, "longitude": 10.0, "rtk_status": "RTK FIXED"})
        result = manager.check_plan("Brunnen", self._sample_plan(reverse=True, unsafe=False))

        self.assertTrue(result["success"])
        self.assertEqual(1, result["summary"]["reverse_segment_count"])
        # The plan is accepted rather than rejected - that is what this test
        # guards. The compiled drive direction is a separate decision: this
        # fixture puts the reverse rest lane collinear with and east of the
        # eastbound contour, so the vehicle reaches it already facing along
        # it. Driving forward needs no turn at all while honouring the
        # stored "reverse" flag would demand a pointless 180 degree
        # turnaround, so the heading-based choice picks forward. Real
        # boustrophedon lanes sit beside each other and keep the stored
        # alternation - see
        # test_resume_at_far_end_of_lane_keeps_heading_close_to_neighbours.
        self.assertEqual("forward", result["executable_segments"][-1]["direction"])

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

    def test_executable_segments_can_start_from_middle_segment(self):
        manager = MowingPlanManager("/tmp/maps", lambda: {"latitude": 52.0, "longitude": 10.0, "rtk_status": "RTK FIXED"})
        plan = self._sample_plan(reverse=False, unsafe=False)

        executable = manager.executable_segments(plan, start_segment_index=1)

        self.assertEqual(["positioning", "mow"], [item["type"] for item in executable])
        self.assertEqual("goto", executable[0]["mode"])
        self.assertEqual(plan["rest_lanes"][0]["coordinates"][0], executable[0]["coordinates"][0])
        self.assertEqual("rest_lane", executable[1]["source_type"])

    def test_selected_start_coordinate_trims_open_segment_exactly(self):
        manager = MowingPlanManager("/tmp/maps", lambda: self._pose_m(12.0, 0.0, 270.0))
        plan = self._reverse_transition_plan()
        selected = self._coord_m(5.0, 0.0)

        executable = manager.executable_segments(
            plan,
            start_segment_index=1,
            start_coordinate=selected,
            start_pose=self._pose_m(12.0, 0.0, 270.0),
        )

        self.assertEqual(["positioning", "mow"], [item["type"] for item in executable])
        self.assertEqual("forward", executable[0]["direction"])
        self.assertEqual(self._coord_m(12.0, 0.0), executable[0]["coordinates"][0])
        self.assertEqual(selected, executable[0]["coordinates"][-1])
        self.assertEqual("runtime_direct", executable[0]["route_kind"])
        self.assertEqual(selected, executable[1]["coordinates"][0])
        self.assertAlmostEqual(self._coord_m(0.0, 0.0)[0], executable[1]["coordinates"][-1][0])

    def test_positioning_reverses_when_vehicle_faces_away_from_start_route(self):
        manager = MowingPlanManager("/tmp/maps", lambda: self._pose_m(12.0, 0.0, 90.0))
        plan = self._reverse_transition_plan()
        selected = self._coord_m(5.0, 0.0)

        executable = manager.executable_segments(
            plan,
            start_segment_index=1,
            start_coordinate=selected,
            start_pose=self._pose_m(12.0, 0.0, 90.0),
        )

        self.assertEqual("positioning", executable[0]["type"])
        self.assertEqual("reverse", executable[0]["direction"])
        self.assertEqual(self._coord_m(12.0, 0.0), executable[0]["coordinates"][0])
        self.assertEqual(selected, executable[0]["coordinates"][-1])

    def test_a_crooked_stand_is_reported_instead_of_smoothed_away(self):
        """Quer geparkt und zu nah: dann gibt es keine Anfahrt, und das zählt.

        Das Fahrzeug steht 7 m vom Ziel und 60° verdreht - zu viel für den
        Track-Regler, zu wenig für rückwärts. Hier stand früher ein
        eingerollter Ersatzbogen, damit überhaupt etwas Fahrbares herauskam.
        Der war es aber nie: mit 0,6 m Schrittweite beschreibt er einen
        1,7-m-Kreis, und der Regler hält erst 7 m. Schlimmer noch, er drückte
        den Kursfehler im Plan auf 20° - der Plan-Check sah nichts mehr und
        gab eine Fahrt frei, die nach 2,5 m abbrach (real, 08.08.).

        Bei 7 m Abstand liegt das Ziel innerhalb des Wendekreises; dorthin
        führt in einem Zug kein Weg. Der Plan zeigt dann die gerade
        Verbindung mit ihrem echten Kursfehler, und der Check lehnt ab.
        """
        manager = MowingPlanManager("/tmp/maps", lambda: self._pose_m(12.0, 0.0, 90.0))
        plan = self._reverse_transition_plan()
        selected = self._coord_m(5.0, 0.0)

        executable = manager.executable_segments(
            plan,
            start_segment_index=1,
            start_coordinate=selected,
            start_pose=self._pose_m(12.0, 0.0, 210.0),
        )

        approach = executable[0]
        self.assertEqual("positioning", approach["type"])
        self.assertEqual("forward", approach["direction"])
        self.assertGreater(
            manager._route_heading_error(approach["coordinates"], 210.0),
            manager.ARRIVAL_ALIGNMENT_LIMIT_DEG,
            "Der wahre Kursfehler muss im Plan stehen, damit der Check ihn sieht",
        )

    def test_selected_start_stays_where_it_was_chosen(self):
        """Der gewaehlte Punkt ist der Startpunkt - ohne Ausnahme.

        Frueher rutschte der Start am Ring entlang, wenn die Bahn dort quer
        zur Anflugrichtung lag: nur so konnte die Anfahrt ihn geradeaus
        erreichen. Der Marker in der Karte blieb dabei stehen, das Fahrzeug
        fuhr sichtbar woandershin - beim Brunnen 12,45 m (real, 08.08.).
        Seit die Anfahrt selbst einschwenkt (_tangential_approach_coords),
        kommt sie aus jeder Richtung in Bahnrichtung an, und der Ring darf
        stehenbleiben. Eine Ecke am Anfang stoert dabei nicht: sie liegt auf
        der Naht zwischen Ringanfang und -ende und wird nie durchfahren.
        """
        manager = MowingPlanManager("/tmp/maps")
        # Stützpunkte alle 2 m wie in einem echten Konturring - sonst gibt es
        # neben der Spitze gar keinen Punkt, auf den ausgewichen werden kann.
        corners = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (10.0, 1.0), (0.0, 20.0), (0.0, 0.0)]
        densified = []
        for (x1, y1), (x2, y2) in zip(corners, corners[1:]):
            steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / 2.0))
            for step in range(steps):
                fraction = step / steps
                densified.append(self._coord_m(x1 + (x2 - x1) * fraction, y1 + (y2 - y1) * fraction))
        densified.append(self._coord_m(*corners[-1]))
        spike = {"type": "contour", "coordinates": densified}
        tip = self._coord_m(10.0, 1.0)

        # Auf der Spitze: der Ring beginnt genau dort und schliesst sich dort.
        kept = manager._coords_from_selected_start(spike, tip)
        self.assertLess(manager._coord_distance_m(kept[0], tip), 0.05)
        self.assertEqual(kept[0], kept[-1])

        # Mitten auf der geraden Unterkante: ebenso.
        on_edge = self._coord_m(10.0, 0.0)
        kept = manager._coords_from_selected_start(spike, on_edge)
        self.assertLess(manager._coord_distance_m(kept[0], on_edge), 0.05)

    def test_approach_ends_aligned_with_the_first_lane(self):
        """Die Anfahrt muss in Bahnrichtung enden, nicht nur dort ankommen.

        Regression der ersten Realfahrt (02.08.): das Einschwenken brach im
        ersten Schritt ab, weil die Reststrecke gegen die Vorausschau geprüft
        wurde. Das Fahrzeug erreichte den Ringanfang mit 43,9°, der Roll
        vergrößerte den Fehler auf 49,4° und der Regler brach ab. Die
        Simulation hatte das nicht gezeigt - dieser Test prüft die geplante
        Ankunftsrichtung direkt.
        """
        manager = MowingPlanManager("/tmp/maps", lambda: self._pose_m(-12.0, 14.0, 90.0))
        ring = [
            self._coord_m(0.0, 0.0), self._coord_m(20.0, 0.0),
            self._coord_m(20.0, 20.0), self._coord_m(0.0, 20.0),
            self._coord_m(0.0, 0.0),
        ]
        plan = {
            "success": True, "name": "Brunnen", "map_name": "Brunnen",
            "sequence": [{
                "type": "contour", "segment_index": 0, "lane_index": 0,
                "coordinates": ring, "length_m": 80.0,
            }],
            "transitions": [], "rest_lanes": [], "lanes": [],
            "parameters": {"outer_margin_m": 0.0},
            "map": self._map_feature(-20.0, -20.0, 40.0, 40.0),
            "total_drive_length_m": 80.0,
        }

        executable = manager.executable_segments(
            plan,
            start_segment_index=0,
            start_pose=self._pose_m(-12.0, 14.0, 90.0),
        )

        approach = executable[0]["coordinates"]
        lane = executable[1]["coordinates"]
        arrival = manager._edge_bearing_deg(approach[-2], approach[-1])
        lane_bearing = manager._edge_bearing_deg(lane[0], lane[1])
        self.assertLess(
            manager._angle_error_deg(arrival, lane_bearing),
            manager.RING_START_HEADING_LIMIT_DEG,
            "Anfahrt endet quer zur Bahn",
        )

    def test_ring_sense_follows_the_approach_instead_of_forcing_a_loop(self):
        """Der Drehsinn wird beim Abfahren gewählt, nicht im Planer festgelegt.

        Ein geschlossener Ring wird in beide Richtungen vollständig gemäht.
        Fest verdrahtet zwang er das Fahrzeug in eine Schleife, nur um von der
        anderen Seite auf den ersten Ring zu kommen (real, 02.08.).
        """
        manager = MowingPlanManager("/tmp/maps")
        ring = {
            "type": "contour",
            "coordinates": [
                self._coord_m(0.0, 0.0), self._coord_m(20.0, 0.0),
                self._coord_m(20.0, 20.0), self._coord_m(0.0, 20.0),
                self._coord_m(0.0, 0.0),
            ],
        }
        target = self._coord_m(10.0, 0.0)

        # Anflug nach Osten: der gespeicherte Ring läuft dort ebenfalls nach
        # Osten, also unverändert fahren.
        self.assertFalse(manager._prefers_reversed_rings(ring, target, 90.0))
        # Anflug nach Westen: gespeichert liefe der Ring entgegen, also drehen.
        self.assertTrue(manager._prefers_reversed_rings(ring, target, 270.0))

    def test_route_signature_ignores_only_live_positioning_origin(self):
        base = [{
            "type": "positioning",
            "source_index": None,
            "mode": "track",
            "direction": "forward",
            "route_kind": "runtime_direct",
            "coordinates": [self._coord_m(0.0, 0.0), self._coord_m(5.0, 0.0)],
        }]
        moved_origin = [dict(base[0], coordinates=[
            self._coord_m(0.1, 0.0), self._coord_m(5.0, 0.0),
        ])]
        changed_direction = [dict(base[0], direction="reverse")]

        self.assertEqual(
            MowingPlanManager.route_signature(base),
            MowingPlanManager.route_signature(moved_origin),
        )
        self.assertNotEqual(
            MowingPlanManager.route_signature(base),
            MowingPlanManager.route_signature(changed_direction),
        )

    def test_selected_near_lane_end_drives_long_half_before_next_lane(self):
        manager = MowingPlanManager("/tmp/maps", lambda: self._pose_m(9.7, -2.0, 0.0))
        selected = self._coord_m(9.7, 0.0)
        first = {
            "type": "rest_lane",
            "segment_index": 0,
            "rest_index": 0,
            "rest_group": 0,
            "direction": "forward",
            "coordinates": [self._coord_m(0.0, 0.0), self._coord_m(10.0, 0.0)],
            "length_m": 10.0,
        }
        second = {
            "type": "rest_lane",
            "segment_index": 1,
            "rest_index": 1,
            "rest_group": 0,
            "direction": "reverse",
            "coordinates": [self._coord_m(10.0, 1.0), self._coord_m(0.0, 1.0)],
            "length_m": 10.0,
        }
        plan = {
            "success": True,
            "name": "Brunnen",
            "map_name": "Brunnen",
            "sequence": [first, second],
            "transitions": [],
            "rest_lanes": [first, second],
            "lanes": [],
            "parameters": {"outer_margin_m": 0.0},
            "map": self._map_feature(-5.0, -5.0, 15.0, 5.0),
            "total_drive_length_m": 20.0,
        }

        executable = manager.executable_segments(
            plan,
            start_segment_index=0,
            start_coordinate=selected,
            start_pose=self._pose_m(9.7, -2.0, 0.0),
        )

        self.assertEqual(
            ["positioning", "mow", "transition", "mow"],
            [item["type"] for item in executable],
        )
        first_track = executable[1]
        self.assertEqual(0, first_track["source_index"])
        # Der Startpunkt wird auf die Bahn projiziert; er liegt hier bereits
        # darauf, das Ergebnis ist bis auf Gleitkomma-Rundung identisch.
        self.assertAlmostEqual(selected[0], first_track["coordinates"][0][0], places=12)
        self.assertAlmostEqual(selected[1], first_track["coordinates"][0][1], places=12)
        self.assertAlmostEqual(self._coord_m(0.0, 0.0)[0], first_track["coordinates"][-1][0])
        self.assertGreater(first_track["length_m"], 9.0)
        self.assertEqual(first_track["coordinates"][-1], executable[2]["coordinates"][0])
        self.assertEqual(1, executable[-1]["source_index"])

    def test_opposite_transition_uses_arrival_heading_and_reverses(self):
        manager = MowingPlanManager("/tmp/maps")
        first = {
            "type": "rest_lane",
            "segment_index": 0,
            "rest_index": 0,
            "rest_group": 0,
            "direction": "forward",
            "coordinates": [self._coord_m(0.0, 0.0), self._coord_m(10.0, 0.0)],
            "length_m": 10.0,
        }
        second = {
            "type": "rest_lane",
            "segment_index": 1,
            "rest_index": 1,
            "rest_group": 0,
            "direction": "reverse",
            "coordinates": [self._coord_m(8.0, 1.0), self._coord_m(0.0, 1.0)],
            "length_m": 8.0,
        }
        plan = {
            "success": True,
            "name": "OppositeTransfer",
            "map_name": "OppositeTransfer",
            "sequence": [first, second],
            "transitions": [],
            "rest_lanes": [first, second],
            "lanes": [],
            "parameters": {"outer_margin_m": 0.0},
            "map": self._map_feature(-5.0, -5.0, 15.0, 5.0),
            "total_drive_length_m": 18.0,
        }

        executable = manager.executable_segments(
            plan,
            start_pose=self._pose_m(0.0, 0.0, 90.0),
        )

        self.assertEqual(["mow", "transition", "mow"], [item["type"] for item in executable])
        self.assertEqual("reverse", executable[1]["direction"])
        self.assertGreater(
            manager._route_heading_error(executable[1]["coordinates"], 90.0),
            manager.TRANSFER_REVERSE_THRESHOLD_DEG,
        )

    def test_short_direct_rest_lane_connector_is_absorbed_by_next_lane(self):
        manager = MowingPlanManager("/tmp/maps")
        first = {
            "type": "rest_lane",
            "segment_index": 0,
            "direction": "forward",
            "coordinates": [self._coord_m(0.0, 0.0), self._coord_m(10.0, 0.0)],
            "length_m": 10.0,
        }
        second = {
            "type": "rest_lane",
            "segment_index": 1,
            "direction": "reverse",
            "coordinates": [self._coord_m(10.0, 0.35), self._coord_m(0.0, 0.35)],
            "length_m": 10.0,
        }
        transition = {
            "type": "transition",
            "transition_index": 0,
            "from_segment_index": 0,
            "to_segment_index": 1,
            "from_type": "rest_lane",
            "to_type": "rest_lane",
            "coordinates": [first["coordinates"][-1], second["coordinates"][0]],
            "length_m": 0.35,
            "route_kind": "direct",
            "safe": True,
        }
        plan = {
            "success": True,
            "name": "StraightLanes",
            "map_name": "StraightLanes",
            "sequence": [first, second],
            "transitions": [transition],
            "rest_lanes": [first, second],
            "lanes": [],
            "parameters": {"outer_margin_m": 0.0},
            "map": self._map_feature(-5.0, -5.0, 15.0, 5.0),
        }

        executable = manager.executable_segments(
            plan,
            start_pose=self._pose_m(0.0, 0.0, 90.0),
        )

        self.assertEqual(["mow", "mow"], [item["type"] for item in executable])
        self.assertEqual(["forward", "reverse"], [item["direction"] for item in executable])
        self.assertAlmostEqual(
            0.35,
            manager._coord_distance_m(
                executable[0]["coordinates"][-1],
                executable[1]["coordinates"][0],
            ),
            delta=0.02,
        )

    def test_staggered_lane_ends_still_absorb_the_lateral_hop(self):
        """Regression for the real transition-55 block (26.07.2026, 61.3 deg).

        Towards a sub-zone the lanes shorten and their ends stagger, so the
        end-to-start step picks up a longitudinal component on top of the
        lateral spacing and grows past a flat 0.50 m while the neighbouring
        pairs stay below it. Driving such a half-metre hop as its own track
        made the vehicle turn 42-61 degrees for it and immediately the same
        amount back for the following lane - a detour the next lane's pure
        pursuit removes for free. The step here (0.35 m across, 0.40 m along
        = 0.53 m) mirrors the real geometry.
        """
        manager = MowingPlanManager("/tmp/maps")
        first = {
            "type": "rest_lane",
            "segment_index": 0,
            "direction": "forward",
            "coordinates": [self._coord_m(0.0, 0.0), self._coord_m(10.0, 0.0)],
            "length_m": 10.0,
        }
        second = {
            "type": "rest_lane",
            "segment_index": 1,
            "direction": "reverse",
            "coordinates": [self._coord_m(9.6, 0.35), self._coord_m(0.0, 0.35)],
            "length_m": 9.6,
        }
        transition = {
            "type": "transition",
            "transition_index": 0,
            "from_segment_index": 0,
            "to_segment_index": 1,
            "from_type": "rest_lane",
            "to_type": "rest_lane",
            "coordinates": [first["coordinates"][-1], second["coordinates"][0]],
            "length_m": 0.53,
            "route_kind": "direct",
            "safe": True,
        }
        plan = {
            "success": True,
            "name": "StraightLanes",
            "map_name": "StraightLanes",
            "sequence": [first, second],
            "transitions": [transition],
            "rest_lanes": [first, second],
            "lanes": [],
            "parameters": {"outer_margin_m": 0.0},
            "map": self._map_feature(-5.0, -5.0, 15.0, 5.0),
        }

        executable = manager.executable_segments(
            plan,
            start_pose=self._pose_m(0.0, 0.0, 90.0),
        )

        gap = manager._coord_distance_m(
            executable[0]["coordinates"][-1],
            executable[1]["coordinates"][0],
        )
        self.assertGreater(gap, 0.50, "fixture must exceed the original 0.50 m rule")
        self.assertEqual(["mow", "mow"], [item["type"] for item in executable])
        self.assertLess(gap, 1.0, "absorbed offset must stay inside track_cross_track_limit_m")

    def test_selected_start_coordinate_rotates_closed_ring_without_shortening_it(self):
        manager = MowingPlanManager("/tmp/maps", lambda: self._pose_m(-2.0, 0.0, 0.0))
        ring = [
            self._coord_m(0.0, 0.0),
            self._coord_m(10.0, 0.0),
            self._coord_m(10.0, 10.0),
            self._coord_m(0.0, 10.0),
            self._coord_m(0.0, 0.0),
        ]
        plan = {
            "success": True,
            "name": "Brunnen",
            "map_name": "Brunnen",
            "sequence": [{
                "type": "contour",
                "segment_index": 0,
                "lane_index": 0,
                "coordinates": ring,
                "length_m": 40.0,
            }],
            "transitions": [],
            "rest_lanes": [],
            "lanes": [],
            "parameters": {"outer_margin_m": 0.0},
            "map": self._map_feature(-5.0, -5.0, 15.0, 15.0),
            "total_drive_length_m": 40.0,
        }
        selected = self._coord_m(5.0, 0.0)

        executable = manager.executable_segments(
            plan,
            start_segment_index=0,
            start_coordinate=selected,
            start_pose=self._pose_m(-2.0, 0.0, 0.0),
        )

        self.assertEqual(["positioning", "mow"], [item["type"] for item in executable])
        for expected, actual in zip(
            self._coord_m(-2.0, 0.0), executable[0]["coordinates"][0]
        ):
            self.assertAlmostEqual(expected, actual, places=12)
        self.assertEqual(selected, executable[0]["coordinates"][-1])
        self.assertEqual(selected, executable[1]["coordinates"][0])
        self.assertEqual(selected, executable[1]["coordinates"][-1])
        self.assertAlmostEqual(40.0, executable[1]["length_m"], delta=0.1)

    def test_reverse_start_uses_nearest_lane_end_without_positioning_loop(self):
        manager = MowingPlanManager("/tmp/maps", lambda: self._pose_m(10.0, 0.0, 270.0))
        plan = self._reverse_transition_plan()

        executable = manager.executable_segments(
            plan,
            start_segment_index=1,
            start_pose=self._pose_m(10.0, 0.0, 270.0),
        )

        self.assertEqual(["mow"], [item["type"] for item in executable])
        # The lane is stored as coords=(10,0)->(0,0), i.e. due west, with
        # direction "reverse" as originally planned. The live arrival
        # heading here (270 degrees = due west) matches that path exactly,
        # so driving "forward" needs zero turn while "reverse" would need a
        # full 180 - the heading-based choice (mirrors
        # _select_transfer_direction for transitions) picks forward.
        self.assertEqual("forward", executable[0]["direction"])
        self.assertAlmostEqual(self._coord_m(10.0, 0.0)[0], executable[0]["coordinates"][0][0])
        self.assertAlmostEqual(self._coord_m(0.0, 0.0)[0], executable[0]["coordinates"][-1][0])

    def test_reverse_next_lane_orients_to_previous_end(self):
        manager = MowingPlanManager("/tmp/maps", lambda: {"latitude": 52.0, "longitude": 10.0, "rtk_status": "RTK FIXED"})
        plan = self._reverse_transition_plan()

        executable = manager.executable_segments(plan)

        self.assertEqual(["positioning", "mow", "mow"], [item["type"] for item in executable])
        # The rest lane is stored as coords=[(10,0),(0,0)] with direction
        # "reverse", i.e. nose east while backing from (10,0) towards (0,0)
        # (see test_reverse_start_uses_nearest_lane_end_without_positioning_loop,
        # which enters at (10,0) unreoriented and keeps "reverse"). Arriving
        # here from the contour instead lands exactly on (0,0), so
        # _oriented_track_coords flips the coordinate order to [(0,0),(10,0)]
        # for continuity. The physical nose target (east) must stay the same
        # regardless of which end the lane is entered from, so the direction
        # flag has to flip to "forward" here. Keeping it "reverse" would send
        # the nose target 180 degrees off - the real Brunnen segment-36 stall
        # on 25.07. (-52 degree heading error) was exactly this mismatch.
        self.assertEqual("forward", executable[-1]["direction"])
        self.assertEqual(plan["sequence"][0]["coordinates"][-1], executable[-1]["coordinates"][0])

    def test_resume_at_far_end_of_lane_keeps_heading_close_to_neighbours(self):
        """Regression for the real Brunnen segment-36 stall (25.07.2026).

        Coordinates are taken verbatim from
        raspberrycan/plans/Brunnen.plan.json, source segment 36, and the
        pose is the exact real pose logged at the moment of the stall
        (heading 302.8 degrees, -52 degree reported error). Resuming
        landed the vehicle close to the lane's stored EAST endpoint
        instead of its stored WEST start, so _oriented_track_coords
        reverses the coordinate order for path continuity.

        First fix attempt: flip the stored "forward" direction flag
        whenever the coordinates get reversed, to preserve the plan's
        original nose intent. That matched the neighbouring lanes'
        assumed ~90 degree bearing in isolation, but ignored the live
        heading entirely - on a real resume after this vehicle sat
        stationary for over an hour (heading unchanged at ~302-305
        degrees), it demanded a ~146 degree turn when driving "forward"
        only needed ~34-39 degrees. The correct rule, already used for
        transitions in _select_transfer_direction, is to pick whichever
        nose orientation needs the smaller turn from the live arrival
        heading - not to blindly preserve the plan's original intent.
        """
        manager = MowingPlanManager("/tmp/maps", lambda: None)
        plan = {
            "success": True,
            "map_name": "Brunnen",
            "sequence": [{
                "type": "rest_lane",
                "segment_index": 36,
                "direction": "forward",
                "coordinates": [
                    [11.078456601225982, 53.332558329029965],
                    [11.0786019219556, 53.332558329029965],
                ],
                "length_m": 9.66,
            }],
            "transitions": [],
            "rest_lanes": [],
            "lanes": [],
            "parameters": {"outer_margin_m": 0.0},
            "total_drive_length_m": 9.66,
        }
        start_pose = {
            "gps": {"latitude": 53.3325664, "longitude": 11.0785893},
            "heading": 302.8,
            "rtk_status": "RTK FIXED",
        }

        executable = manager.executable_segments(plan, start_segment_index=36, start_pose=start_pose)

        lane = executable[0]
        (lon1, lat1), (lon2, lat2) = lane["coordinates"][0], lane["coordinates"][1]
        path_bearing = self._bearing_deg(lat1, lon1, lat2, lon2)
        nose_bearing = (path_bearing + 180.0) % 360.0 if lane["direction"] == "reverse" else path_bearing
        live_heading = 302.8
        turn_needed = abs(((nose_bearing - live_heading + 540.0) % 360.0) - 180.0)

        self.assertEqual("forward", lane["direction"])
        self.assertLess(turn_needed, 45.0, f"nose bearing {nose_bearing:.1f} needs too big a turn from {live_heading}")

    def test_resumed_run_never_demands_a_turnaround_between_lanes(self):
        """Regression for the real lane-37 block (25.07.2026, 178.9 deg).

        Alternating boustrophedon lanes exist precisely so the vehicle never
        has to turn around: it drives one lane nose-first and backs up along
        the next, keeping the same heading throughout. A resume can invert
        the traversal sense of the lane it restarts on (the vehicle sits at
        that lane's far end). Every following lane must then be evaluated
        against the heading the vehicle physically ends up with, not against
        the plan's original assumption - otherwise lane N+1 inherits the
        inverted sense and demands a full 180 degree turnaround, which the
        controller rightly refuses to drive.

        Coordinates are the real segments 36-40 of Brunnen.plan.json; the
        pose is the real one logged after lane 36 completed westbound.
        """
        self._assert_shapely_available()
        manager = MowingPlanManager("/tmp/maps", lambda: None)
        lanes = [
            (36, "forward", [11.078456601225982, 53.332558329029965], [11.0786019219556, 53.332558329029965]),
            (37, "reverse", [11.078600625672586, 53.33256147311908], [11.078461441608367, 53.33256147311908]),
            (38, "forward", [11.078465477741368, 53.33256461720819], [11.078599242273375, 53.33256461720819]),
            (39, "reverse", [11.078597858874165, 53.332567761297305], [11.078469513874367, 53.332567761297305]),
            (40, "forward", [11.078473550007367, 53.33257090538642], [11.078595934717878, 53.33257090538642]),
        ]
        plan = {
            "success": True,
            "map_name": "Brunnen",
            "sequence": [
                {
                    "type": "rest_lane",
                    "segment_index": index,
                    "direction": direction,
                    "coordinates": [start, end],
                    "length_m": 9.0,
                }
                for index, direction, start, end in lanes
            ],
            "transitions": [],
            "rest_lanes": [],
            "lanes": [],
            "parameters": {"outer_margin_m": 0.0},
            "total_drive_length_m": 45.0,
            # A boundary comfortably around the lanes, so the runtime router
            # can connect the ~0.35 m lane-to-lane steps the same way it does
            # in production.
            "map": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {"type": "boundary"},
                    "geometry": {"type": "Polygon", "coordinates": [[
                        [11.07840, 53.33250],
                        [11.07866, 53.33250],
                        [11.07866, 53.33262],
                        [11.07840, 53.33262],
                        [11.07840, 53.33250],
                    ]]},
                }],
            },
        }
        start_pose = {
            "gps": {"latitude": 53.3325599, "longitude": 11.0784601},
            "heading": 258.36,
            "rtk_status": "RTK FIXED",
        }

        executable = manager.executable_segments(plan, start_segment_index=37, start_pose=start_pose)

        heading = 258.36
        for lane in [item for item in executable if item["type"] == "mow"]:
            coords = lane["coordinates"]
            (lon1, lat1), (lon2, lat2) = coords[0], coords[-1]
            path_bearing = self._bearing_deg(lat1, lon1, lat2, lon2)
            nose = (path_bearing + 180.0) % 360.0 if lane["direction"] == "reverse" else path_bearing
            turn_needed = abs(((nose - heading + 540.0) % 360.0) - 180.0)
            self.assertLess(
                turn_needed,
                45.0,
                f"lane {lane['source_index']} needs a {turn_needed:.1f} deg turn "
                f"from heading {heading:.1f}",
            )
            heading = nose

    @staticmethod
    def _bearing_deg(lat1, lon1, lat2, lon2):
        import math

        lat1_r = math.radians(lat1)
        lat2_r = math.radians(lat2)
        dlon = math.radians(lon2 - lon1)
        y = math.sin(dlon) * math.cos(lat2_r)
        x = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon)
        return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    def test_tiny_rest_lanes_block_legacy_plan_execution(self):
        manager = MowingPlanManager("/tmp/maps", lambda: {"latitude": 52.0, "longitude": 10.0, "rtk_status": "RTK FIXED"})
        plan = self._sample_plan(reverse=False, unsafe=False)
        tiny = dict(plan["rest_lanes"][0])
        tiny["length_m"] = 0.7
        plan["rest_lanes"] = [tiny]
        plan["sequence"] = [plan["lanes"][0], tiny]

        result = manager.check_plan("Brunnen", plan)

        self.assertFalse(result["success"])
        self.assertEqual(1, result["summary"]["short_rest_lane_count"])
        self.assertIn("sehr kurze Restbahn", result["errors"][0])

    def test_short_serpentine_links_do_not_block_execution(self):
        """Regression for the rejected Play on 28.07.

        Serpentine passes meet end to end, so a short one is a link in a run
        and not a leg of its own - and near a sub-zone the links get short by
        design. Judging them individually rejected an otherwise perfectly
        driveable plan with "Plan enthält 15 sehr kurze Restbahn(en)". Only a
        whole run below the minimum is worth refusing.
        """
        manager = MowingPlanManager("/tmp/maps", lambda: {"latitude": 52.0, "longitude": 10.0, "rtk_status": "RTK FIXED"})
        plan = self._sample_plan(reverse=False, unsafe=False)
        plan["parameters"] = dict(plan.get("parameters") or {}, rest_pattern="serpentine")
        links = []
        for index in range(4):
            link = dict(plan["rest_lanes"][0])
            link["segment_index"] = 10 + index
            link["rest_group"] = 0
            link["length_m"] = 1.2
            links.append(link)
        stray = dict(plan["rest_lanes"][0])
        stray["segment_index"] = 20
        stray["rest_group"] = 9
        stray["length_m"] = 0.7
        plan["rest_lanes"] = links + [stray]
        plan["sequence"] = [plan["lanes"][0]] + links + [stray]

        summary = manager.summarize_plan(plan)

        # The four 1.2 m links add up to 4.8 m and stay; the lone 0.7 m run
        # is still refused.
        self.assertEqual(1, summary["short_rest_lane_count"])

    def test_vehicle_parked_outside_the_area_still_drives_to_the_first_lane(self):
        """Regression for the silent Play on 28.07.

        The vehicle stood 12.3 m outside the boundary and the whole plan was
        rejected. Driving from wherever it is parked to the first lane is a
        normal part of the job, so the approach leg must not be confined to
        the mapped area - there is nothing mapped out there to check against
        anyway, and the runtime no-go monitor deliberately runs with
        enforce_outer_boundary=False for the same reason.
        """
        self._assert_shapely_available()
        manager = MowingPlanManager("/tmp/maps", lambda: None)
        plan = self._reverse_transition_plan()
        outside = self._pose_m(-25.0, 0.0, 90.0)

        executable = manager.executable_segments(plan, start_pose=outside)

        self.assertEqual("positioning", executable[0]["type"])
        for expected, actual in zip(self._coord_m(-25.0, 0.0), executable[0]["coordinates"][0]):
            self.assertAlmostEqual(expected, actual, places=12)
        self.assertGreater(executable[0]["length_m"], 20.0)

    def test_approach_routes_around_a_sub_zone_instead_of_through_it(self):
        """The outer boundary is not enforced on the approach, but real
        obstacles still are: a sub zone between the parking spot and the
        first lane must be driven around, never straight through."""
        LineString, Polygon = self._assert_shapely_available()
        manager = MowingPlanManager("/tmp/maps", lambda: None)
        plan = self._reverse_transition_plan()
        plan["map"] = self._map_feature(-30.0, -12.0, 20.0, 12.0)
        blocker = [
            self._coord_m(-16.0, -4.0),
            self._coord_m(-10.0, -4.0),
            self._coord_m(-10.0, 4.0),
            self._coord_m(-16.0, 4.0),
            self._coord_m(-16.0, -4.0),
        ]
        plan["exclusion_contours"] = [
            {"type": "sub_buffer_boundary", "coordinates": blocker}
        ]
        behind_the_blocker = self._pose_m(-25.0, 0.0, 90.0)

        executable = manager.executable_segments(plan, start_pose=behind_the_blocker)

        approach = executable[0]
        self.assertEqual("positioning", approach["type"])
        forbidden = Polygon([(c[0], c[1]) for c in blocker])
        self.assertFalse(
            LineString([(c[0], c[1]) for c in approach["coordinates"]]).intersects(forbidden),
            "the approach must not cut through the sub zone",
        )
        self.assertGreater(len(approach["coordinates"]), 2, "a detour needs waypoints")

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

    def test_nogo_monitor_default_allows_shallow_intrusion_as_warning(self):
        self._assert_shapely_available()
        monitor = NoGoZoneMonitor(self._sample_nogo_plan())

        shallow = monitor.check_pose(self._pose_m(-0.5, 1.0, 90.0))
        deep = monitor.check_pose(self._pose_m(-0.1, 1.0, 90.0))

        self.assertTrue(shallow["ok"])
        self.assertEqual("warning", shallow["state"])
        self.assertFalse(deep["ok"])
        self.assertEqual("stop", deep["state"])
        self.assertIn("35 cm", deep["reason"])

    def test_nogo_monitor_enforces_outer_map_boundary_without_sub_zones(self):
        self._assert_shapely_available()
        ring = [
            self._coord_m(-2.0, -2.0),
            self._coord_m(2.0, -2.0),
            self._coord_m(2.0, 2.0),
            self._coord_m(-2.0, 2.0),
            self._coord_m(-2.0, -2.0),
        ]
        plan = {
            "map": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {"type": "boundary"},
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }],
            },
            "parameters": {"outer_margin_m": 0.0},
        }
        monitor = NoGoZoneMonitor(plan, boundary_tolerance_m=0.35)

        inside = monitor.check_pose(self._pose_m(0.0, 0.0, 0.0))
        outside = monitor.check_pose(self._pose_m(2.8, 0.0, 0.0))

        self.assertTrue(inside["ok"])
        self.assertEqual("ok", inside["state"])
        self.assertFalse(outside["ok"])
        self.assertEqual("stop", outside["state"])
        self.assertIn("außerhalb der Mähbegrenzung", outside["reason"])

        runtime_monitor = NoGoZoneMonitor(plan, enforce_outer_boundary=False)
        runtime_result = runtime_monitor.check_pose(self._pose_m(2.8, 0.0, 0.0))

        self.assertTrue(runtime_result["ok"])
        self.assertEqual("disabled", runtime_result["state"])

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
            "length_m": 3.0,
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
            "strategy": "hybrid_contour_suboffset_rest_reverse",
            "parameters": {
                "cut_width_m": 0.45,
                "overlap_m": 0.1,
                "spacing_m": 0.35,
                "outer_margin_m": 0.0,
                "sub_margin_m": 0.25,
                "max_ring_turn_deg": 155.0,
                "sub_contour_count": 3,
            },
            "lane_count": 1,
            "rest_lane_count": 1,
            "transition_count": 1,
            "unsafe_transition_count": 1 if unsafe else 0,
            "total_drive_length_m": 5.0,
            "lanes": [contour],
            "rest_lanes": [rest],
            "sequence": [contour, rest],
            "transitions": [transition],
        }

    @classmethod
    def _reverse_transition_plan(cls):
        contour = {
            "type": "contour",
            "segment_index": 0,
            "lane_index": 0,
            "coordinates": [cls._coord_m(0.0, -1.0), cls._coord_m(0.0, 0.0)],
            "length_m": 1.0,
        }
        rest = {
            "type": "rest_lane",
            "segment_index": 1,
            "rest_index": 0,
            "rest_group": 0,
            "direction": "reverse",
            "coordinates": [cls._coord_m(10.0, 0.0), cls._coord_m(0.0, 0.0)],
            "length_m": 10.0,
        }
        transition = {
            "type": "transition",
            "transition_index": 0,
            "from_segment_index": 0,
            "to_segment_index": 1,
            "from_type": "contour",
            "to_type": "rest_lane",
            "safe": True,
            "reason": "ok",
            "route_kind": "direct",
            "coordinates": [cls._coord_m(0.0, 0.0), cls._coord_m(10.0, 0.0)],
            "length_m": 10.0,
        }
        return {
            "success": True,
            "name": "Brunnen",
            "map_name": "Brunnen",
            "sequence": [contour, rest],
            "transitions": [transition],
            "rest_lanes": [rest],
            "lanes": [contour],
            "parameters": {"outer_margin_m": 0.0},
            "map": cls._map_feature(-5.0, -5.0, 15.0, 5.0),
            "total_drive_length_m": 11.0,
        }

    @classmethod
    def _map_feature(cls, min_x, min_y, max_x, max_y):
        ring = [
            cls._coord_m(min_x, min_y),
            cls._coord_m(max_x, min_y),
            cls._coord_m(max_x, max_y),
            cls._coord_m(min_x, max_y),
            cls._coord_m(min_x, min_y),
        ]
        return {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"type": "boundary"},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }],
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
