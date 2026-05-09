import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mapping import MappingRecorder


class MappingRecorderTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
