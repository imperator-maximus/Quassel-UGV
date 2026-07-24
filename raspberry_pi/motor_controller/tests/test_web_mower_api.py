import unittest
import json
import tempfile
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.web.web_server import WebServer


class FakeODriveMower:
    enabled = True

    def __init__(self):
        self.running = False
        self.starting = False
        self.start_calls = []
        self.stop_calls = 0
        self.start_error = None

    def start(self, rpm=None):
        self.start_calls.append(rpm)
        if self.start_error:
            return self.get_status(success=False, error=self.start_error)
        self.running = True
        return self.get_status()

    def stop(self):
        self.stop_calls += 1
        self.running = False
        return self.get_status()

    def get_status(self, success=True, error=None):
        return {
            'success': success,
            'error': error,
            'enabled': True,
            'running': self.running,
            'command_running': self.running,
            'rpm': 500,
            'commanded_rpm': 500 if self.running else 0,
            'min_rpm': 500,
            'max_rpm': 5000,
            'default_rpm': 500,
            'ramp_rate_rpm_s': 300,
            'node_id': 0,
            'node_ids': [0, 1, 2],
            'axis_state': 5 if self.running else 1,
            'startup_status': {'active': self.starting},
        }


class MowerApiSafetyTests(unittest.TestCase):
    def setUp(self):
        config = SimpleNamespace(
            template_folder='.',
            static_folder='.',
            secret_key='test',
        )
        dummy = SimpleNamespace()
        self.server = WebServer(config, dummy, dummy, dummy, dummy)
        self.mower = FakeODriveMower()
        self.server.set_hardware_refs(None, None, None, self.mower)
        self.client = self.server.app.test_client()

    def test_missing_json_cannot_toggle_or_start_mower(self):
        response = self.client.post('/api/mower/toggle')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['success'])
        self.assertEqual(self.mower.start_calls, [])
        self.assertEqual(self.mower.stop_calls, 0)

    def test_malformed_json_cannot_toggle_or_start_mower(self):
        response = self.client.post(
            '/api/mower/toggle',
            data='{',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.mower.start_calls, [])
        self.assertEqual(self.mower.stop_calls, 0)

    def test_state_must_be_boolean(self):
        response = self.client.post('/api/mower/toggle', json={'state': 'false'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.mower.start_calls, [])
        self.assertEqual(self.mower.stop_calls, 0)

    def test_explicit_true_starts_and_explicit_false_stops(self):
        start_response = self.client.post(
            '/api/mower/toggle',
            json={'state': True, 'rpm': 500},
        )
        stop_response = self.client.post(
            '/api/mower/toggle',
            json={'state': False},
        )

        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(stop_response.status_code, 200)
        self.assertEqual(self.mower.start_calls, [500])
        self.assertEqual(self.mower.stop_calls, 1)
        self.assertFalse(stop_response.get_json()['mower_state'])

    def test_start_error_is_exposed_to_the_frontend(self):
        self.mower.start_error = 'Sicherheitsstopp ist verriegelt'

        response = self.client.post(
            '/api/mower/toggle',
            json={'state': True, 'rpm': 500},
        )

        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error'], self.mower.start_error)
        self.assertEqual(payload['mower_error'], self.mower.start_error)

    def test_pending_start_is_not_reported_as_mower_on(self):
        self.mower.running = True
        self.mower.starting = True

        payload = self.server._mower_api_status()

        self.assertFalse(payload['mower_state'])
        self.assertFalse(payload['mower_command_running'])
        self.assertTrue(payload['mower_starting'])

    def test_template_treats_all_odrive_transports_as_rpm_mode(self):
        template = Path(__file__).resolve().parents[2] / 'templates' / 'index.html'
        text = template.read_text(encoding='utf-8')

        self.assertIn("mowerMode.startsWith('odrive_')", text)
        self.assertIn('`ODrive ${odriveTransport}`', text)

    def test_resume_snapshot_is_compact_and_references_source_segment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            plans = SimpleNamespace(
                plans_dir=Path(temp_dir),
                _sanitize_name=lambda name: name,
            )
            self.server.mapping = SimpleNamespace(plans=plans)
            self.server.can = SimpleNamespace(
                get_sensor_data=lambda: {
                    'timestamp': 123.0,
                    'gps': {'lat': 52.0, 'lon': 10.0},
                }
            )
            self.server._active_plan_map_name = 'Test'
            self.server._active_plan_summary = {'map_name': 'Test'}
            self.server._active_executable_segments = [{
                'type': 'mow',
                'source_index': 7,
                'coordinates': [[10.0, 52.0]] * 10000,
            }]
            self.server._plan_status.update({
                'active_index': 0,
                'current_segment': {'type': 'mow', 'source_index': 7},
            })

            self.server._save_resume_state(reason='paused')

            path = Path(temp_dir) / 'Test.resume.json'
            payload = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(payload['schema'], 'raspberrycan.mowing_resume.v2')
            self.assertEqual(payload['source_segment_index'], 7)
            self.assertNotIn('executable_segments', payload)
            self.assertNotIn('plan', payload)
            self.assertLess(path.stat().st_size, 5000)


if __name__ == '__main__':
    unittest.main()
