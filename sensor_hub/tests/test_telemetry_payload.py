import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telemetry_payload import build_status_payload, build_telemetry_payload, serialize_can_payload


class TelemetryPayloadTests(unittest.TestCase):
    def test_build_telemetry_payload_rounds_values(self):
        payload = build_telemetry_payload(
            gps_status={
                'latitude': 53.33227380466667,
                'longitude': 11.079006669333333,
                'altitude': 19.3277,
                'heading': 12.3456,
                'rtk_status': 'GPS FIX'
            },
            timestamp=1776599841.86649,
        )

        self.assertEqual(payload['timestamp'], 1776599841.866)
        self.assertEqual(payload['gps']['lat'], 53.3322738)
        self.assertEqual(payload['gps']['lon'], 11.0790067)
        self.assertEqual(payload['gps']['altitude'], 19.33)
        self.assertEqual(payload['heading'], 12.35)

    def test_satellite_count_travels_with_the_pose(self):
        """Der Motor-Controller sieht sonst nur rtk_status, nicht die Satelliten."""
        payload = build_telemetry_payload(
            gps_status={
                'latitude': 53.33, 'longitude': 11.08, 'altitude': 15.0,
                'heading': 0.0, 'rtk_status': 'RTK FIXED', 'satellites': 24,
            },
        )

        self.assertEqual(payload['gps']['satellites'], 24)

    def test_missing_satellite_count_falls_back_to_zero(self):
        payload = build_telemetry_payload(
            gps_status={
                'latitude': 1.0, 'longitude': 2.0, 'altitude': 3.0,
                'rtk_status': 'NO GPS',
            },
        )

        self.assertEqual(payload['gps']['satellites'], 0)

    def test_build_status_payload_preserves_telemetry_and_adds_meta(self):
        telemetry = {'timestamp': 1.23, 'gps': {'lat': 1.0, 'lon': 2.0, 'altitude': 3.0}}
        payload = build_status_payload(telemetry, {'source': 'sensor_hub_status', 'messages_sent': 7})

        self.assertEqual(payload['gps']['lat'], 1.0)
        self.assertEqual(payload['meta']['messages_sent'], 7)
        self.assertIn('"meta":', serialize_can_payload(payload))

    def test_gps_heading_takes_precedence_over_imu(self):
        """GPS dual-antenna heading muss IMU-yaw schlagen, wenn beides vorhanden ist."""
        payload = build_telemetry_payload(
            gps_status={
                'latitude': 53.33, 'longitude': 11.08, 'altitude': 15.0,
                'heading': 209.92, 'rtk_status': 'RTK FIXED',
            },
            orientation={'roll': 0.0, 'pitch': 0.0, 'yaw': 25.6, 'heading': 25.6},
            imu_data={'is_calibrated': True},
        )

        self.assertEqual(payload['heading'], 209.92)
        self.assertEqual(payload['heading_source'], 'dual_gnss')
        self.assertEqual(payload['imu']['heading'], 25.6)
        self.assertEqual(payload['gps']['heading'], 209.92)

    def test_imu_used_only_when_gps_heading_unavailable(self):
        """Ohne GPS-Heading (=0.0) fällt das Top-Level-Heading auf IMU zurück."""
        payload = build_telemetry_payload(
            gps_status={
                'latitude': 53.33, 'longitude': 11.08, 'altitude': 15.0,
                'heading': 0.0, 'rtk_status': 'GPS FIX',
            },
            orientation={'roll': 0.0, 'pitch': 0.0, 'yaw': 42.7, 'heading': 42.7},
            imu_data={'is_calibrated': True},
        )

        self.assertEqual(payload['heading'], 42.7)
        self.assertEqual(payload['heading_source'], 'imu_fallback')

    def test_heading_info_overrides_raw_sources(self):
        """Übergebenes heading_info (mit Offset-Korrektur) hat Vorrang."""
        payload = build_telemetry_payload(
            gps_status={
                'latitude': 53.33, 'longitude': 11.08, 'altitude': 15.0,
                'heading': 209.92, 'rtk_status': 'RTK FIXED',
            },
            orientation={'roll': 0.0, 'pitch': 0.0, 'yaw': 25.6, 'heading': 25.6},
            imu_data={'is_calibrated': True},
            heading_info={
                'heading_deg': 307.05,
                'heading_source': 'dual_gnss',
                'heading_raw_deg': 209.92,
                'heading_offset_deg': 97.13,
            },
        )

        self.assertEqual(payload['heading'], 307.05)
        self.assertEqual(payload['heading_source'], 'dual_gnss')
        # Rohwerte bleiben für Diagnose erhalten
        self.assertEqual(payload['gps']['heading'], 209.92)
        self.assertEqual(payload['imu']['heading'], 25.6)


if __name__ == '__main__':
    unittest.main()