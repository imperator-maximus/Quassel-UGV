import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vehicle_geometry import build_local_footprint, build_visual_markers_local, load_vehicle_geometry


class VehicleGeometryTests(unittest.TestCase):
    def test_load_vehicle_geometry_reads_default_config(self):
        geometry = load_vehicle_geometry()

        self.assertEqual(geometry['reference_frame']['origin'], 'vehicle_center')
        self.assertAlmostEqual(geometry['dimensions_m']['length'], 1.15)
        self.assertAlmostEqual(geometry['dimensions_m']['width'], 0.79)
        self.assertAlmostEqual(geometry['gnss']['antenna_baseline_m'], 0.51)
        self.assertTrue(geometry['capabilities']['ride_on'])

    def test_build_local_footprint_matches_vehicle_dimensions(self):
        footprint = build_local_footprint({'dimensions_m': {'length': 1.15, 'width': 0.79}})

        self.assertEqual(len(footprint), 4)
        self.assertAlmostEqual(footprint[0]['x'], 0.575)
        self.assertAlmostEqual(footprint[0]['y'], -0.395)
        self.assertAlmostEqual(footprint[2]['x'], -0.575)
        self.assertAlmostEqual(footprint[2]['y'], 0.395)

    def test_build_visual_markers_local_uses_antenna_side_insets(self):
        geometry = load_vehicle_geometry()
        markers = build_visual_markers_local(geometry)

        self.assertAlmostEqual(markers['gps_primary']['point_local_m']['y'], -0.255)
        self.assertAlmostEqual(markers['gps_secondary']['point_local_m']['y'], 0.255)
        self.assertAlmostEqual(markers['mast']['point_local_m']['y'], -0.255)
        self.assertAlmostEqual(markers['imu']['point_local_m']['y'], -0.255)
        self.assertAlmostEqual(markers['gps_primary']['point_local_m']['x'], -0.475)
        self.assertAlmostEqual(markers['gps_secondary']['point_local_m']['x'], -0.475)



if __name__ == '__main__':
    unittest.main()