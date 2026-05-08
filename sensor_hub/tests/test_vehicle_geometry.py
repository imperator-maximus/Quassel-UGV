import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vehicle_geometry import build_local_footprint, build_visual_markers_local, load_vehicle_geometry, select_heading_for_visualization


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

        self.assertAlmostEqual(markers['gps_primary']['point_local_m']['y'], 0.255)
        self.assertAlmostEqual(markers['gps_secondary']['point_local_m']['y'], -0.255)
        self.assertAlmostEqual(markers['mast']['point_local_m']['y'], 0.255)
        self.assertAlmostEqual(markers['imu']['point_local_m']['y'], 0.255)
        self.assertAlmostEqual(markers['gps_primary']['point_local_m']['x'], -0.475)
        self.assertAlmostEqual(markers['gps_secondary']['point_local_m']['x'], -0.475)

    def test_select_heading_for_visualization_prefers_imu_when_gps_heading_is_zero(self):
        selection = select_heading_for_visualization(
            gps_status={'heading': 0.0},
            orientation={'heading': 22.5, 'source': 'witmotion_native'},
        )

        self.assertAlmostEqual(selection['heading_deg'], 22.5)
        self.assertEqual(selection['heading_source'], 'witmotion_native_fallback')

    def test_select_heading_for_visualization_prefers_non_zero_gps_heading(self):
        selection = select_heading_for_visualization(
            gps_status={'heading': 181.2},
            orientation={'heading': 22.5, 'source': 'witmotion_native'},
        )

        self.assertAlmostEqual(selection['heading_deg'], 181.2)
        self.assertEqual(selection['heading_source'], 'dual_gnss')

    def test_select_heading_for_visualization_applies_gps_offset(self):
        selection = select_heading_for_visualization(
            gps_status={'heading': 220.0},
            orientation=None,
            gps_heading_offset_deg=-90.0,
        )

        self.assertAlmostEqual(selection['heading_deg'], 130.0)
        self.assertAlmostEqual(selection['heading_raw_deg'], 220.0)
        self.assertAlmostEqual(selection['heading_offset_deg'], -90.0)
        self.assertEqual(selection['heading_source'], 'dual_gnss')

    def test_select_heading_for_visualization_normalizes_offset_to_0_360(self):
        selection = select_heading_for_visualization(
            gps_status={'heading': 50.0},
            orientation=None,
            gps_heading_offset_deg=-90.0,
        )

        self.assertAlmostEqual(selection['heading_deg'], 320.0)

    def test_select_heading_for_visualization_offset_does_not_affect_imu_fallback(self):
        selection = select_heading_for_visualization(
            gps_status={'heading': 0.0},
            orientation={'heading': 22.5, 'source': 'witmotion_native'},
            gps_heading_offset_deg=-90.0,
        )

        self.assertAlmostEqual(selection['heading_deg'], 22.5)
        self.assertEqual(selection['heading_source'], 'witmotion_native_fallback')

    def test_select_heading_for_visualization_imu_calibrated_fallback(self):
        selection = select_heading_for_visualization(
            gps_status={'heading': 0.0},
            orientation={'heading': 22.5, 'source': 'witmotion_native'},
            imu_heading_offset_deg=287.7,
            imu_offset_source='live',
        )

        self.assertAlmostEqual(selection['heading_deg'], (22.5 + 287.7) % 360.0, places=4)
        self.assertEqual(selection['heading_source'], 'imu_calibrated_fallback')
        self.assertAlmostEqual(selection['heading_raw_deg'], 22.5)
        self.assertAlmostEqual(selection['imu_heading_offset_deg'], 287.7)
        self.assertEqual(selection['imu_offset_source'], 'live')

    def test_select_heading_for_visualization_imu_static_fallback(self):
        selection = select_heading_for_visualization(
            gps_status={'heading': 0.0},
            orientation={'heading': 22.5, 'source': 'witmotion_native'},
            imu_heading_offset_deg=180.0,
            imu_offset_source='static',
        )

        self.assertAlmostEqual(selection['heading_deg'], 202.5)
        self.assertEqual(selection['heading_source'], 'imu_static_fallback')
        self.assertAlmostEqual(selection['imu_heading_offset_deg'], 180.0)
        self.assertEqual(selection['imu_offset_source'], 'static')

    def test_select_heading_for_visualization_imu_offset_normalizes(self):
        selection = select_heading_for_visualization(
            gps_status={'heading': 0.0},
            orientation={'heading': 350.0, 'source': 'witmotion_native'},
            imu_heading_offset_deg=20.0,
            imu_offset_source='live',
        )

        self.assertAlmostEqual(selection['heading_deg'], 10.0, places=4)

    def test_select_heading_for_visualization_imu_offset_none_keeps_raw(self):
        selection = select_heading_for_visualization(
            gps_status={'heading': 0.0},
            orientation={'heading': 22.5, 'source': 'witmotion_native'},
            imu_heading_offset_deg=0.0,
            imu_offset_source='none',
        )

        self.assertAlmostEqual(selection['heading_deg'], 22.5)
        self.assertEqual(selection['heading_source'], 'witmotion_native_fallback')
        self.assertEqual(selection.get('imu_offset_source'), 'none')


if __name__ == '__main__':
    unittest.main()