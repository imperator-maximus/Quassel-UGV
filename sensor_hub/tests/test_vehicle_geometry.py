import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import math

from vehicle_geometry import (
    METERS_PER_DEG_LAT,
    build_local_footprint,
    build_visual_markers_local,
    correct_to_vehicle_center,
    gps_primary_offset_m,
    load_vehicle_geometry,
    select_heading_for_visualization,
)


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

    def test_gps_primary_offset_uses_default_geometry(self):
        offset = gps_primary_offset_m(load_vehicle_geometry())

        self.assertIsNotNone(offset)
        # length=1.15, rear_inset=0.10 → x = -(0.575 - 0.10) = -0.475
        # width=0.79,  side_inset=0.14 → y = +(0.395 - 0.14) = +0.255 (rear_right)
        self.assertAlmostEqual(offset[0], -0.475, places=3)
        self.assertAlmostEqual(offset[1], +0.255, places=3)

    def test_correct_to_vehicle_center_heading_north_moves_lever_to_north(self):
        # Heading 0° (Nord): Antenne hinten-rechts → Zentrum liegt 0.475 m
        # nördlich und 0.255 m westlich der Antenne.
        geometry = load_vehicle_geometry()
        center_lat, center_lon = correct_to_vehicle_center(
            antenna_latitude=53.33231900,
            antenna_longitude=11.07874300,
            heading_deg=0.0,
            geometry=geometry,
        )

        delta_lat_m = (center_lat - 53.33231900) * METERS_PER_DEG_LAT
        delta_lon_m = (center_lon - 11.07874300) * (
            METERS_PER_DEG_LAT * math.cos(math.radians(53.33231900))
        )
        self.assertAlmostEqual(delta_lat_m, +0.475, places=2)
        self.assertAlmostEqual(delta_lon_m, -0.255, places=2)

    def test_correct_to_vehicle_center_heading_east_swaps_axes(self):
        # Heading 90° (Ost): Fahrzeug-vorwärts zeigt nach Osten, Fahrzeug-rechts
        # zeigt nach Süden. Antenne hinten-rechts (-0.475, +0.255) → Zentrum
        # liegt 0.255 m nördlich und 0.475 m östlich.
        geometry = load_vehicle_geometry()
        center_lat, center_lon = correct_to_vehicle_center(
            antenna_latitude=53.0,
            antenna_longitude=11.0,
            heading_deg=90.0,
            geometry=geometry,
        )
        delta_lat_m = (center_lat - 53.0) * METERS_PER_DEG_LAT
        delta_lon_m = (center_lon - 11.0) * (METERS_PER_DEG_LAT * math.cos(math.radians(53.0)))
        self.assertAlmostEqual(delta_lat_m, +0.255, places=2)
        self.assertAlmostEqual(delta_lon_m, +0.475, places=2)

    def test_correct_to_vehicle_center_returns_input_without_heading(self):
        center = correct_to_vehicle_center(
            antenna_latitude=53.0,
            antenna_longitude=11.0,
            heading_deg=None,
            geometry=load_vehicle_geometry(),
        )
        self.assertEqual(center, (53.0, 11.0))

    def test_correct_to_vehicle_center_returns_input_without_geometry(self):
        center = correct_to_vehicle_center(
            antenna_latitude=53.0,
            antenna_longitude=11.0,
            heading_deg=42.0,
            geometry=None,
        )
        self.assertEqual(center, (53.0, 11.0))

    def test_correct_to_vehicle_center_lever_arm_magnitude_is_invariant(self):
        # Drehung darf die Distanz Antenne ↔ Fahrzeugzentrum nicht ändern.
        geometry = load_vehicle_geometry()
        ant_lat, ant_lon = 53.33, 11.08
        magnitudes = []
        for hdg in (0.0, 45.0, 137.0, 209.0, 307.0):
            c_lat, c_lon = correct_to_vehicle_center(ant_lat, ant_lon, hdg, geometry)
            d_lat_m = (c_lat - ant_lat) * METERS_PER_DEG_LAT
            d_lon_m = (c_lon - ant_lon) * (METERS_PER_DEG_LAT * math.cos(math.radians(ant_lat)))
            magnitudes.append(math.hypot(d_lat_m, d_lon_m))
        expected = math.hypot(0.475, 0.255)  # ≈ 0.539 m
        for m in magnitudes:
            self.assertAlmostEqual(m, expected, places=2)


if __name__ == '__main__':
    unittest.main()