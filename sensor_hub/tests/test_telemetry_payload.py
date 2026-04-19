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

    def test_build_status_payload_preserves_telemetry_and_adds_meta(self):
        telemetry = {'timestamp': 1.23, 'gps': {'lat': 1.0, 'lon': 2.0, 'altitude': 3.0}}
        payload = build_status_payload(telemetry, {'source': 'sensor_hub_status', 'messages_sent': 7})

        self.assertEqual(payload['gps']['lat'], 1.0)
        self.assertEqual(payload['meta']['messages_sent'], 7)
        self.assertIn('"meta":', serialize_can_payload(payload))


if __name__ == '__main__':
    unittest.main()