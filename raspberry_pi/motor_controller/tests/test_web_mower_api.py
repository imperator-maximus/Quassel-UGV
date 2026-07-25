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

    def test_template_exposes_controller_simulation_in_requested_order(self):
        template = Path(__file__).resolve().parents[2] / 'templates' / 'index.html'
        script = Path(__file__).resolve().parents[2] / 'static' / 'js' / 'mapping_editor.js'
        template_text = template.read_text(encoding='utf-8')
        script_text = script.read_text(encoding='utf-8')

        self.assertIn('id="planSimulateBtn"', template_text)
        self.assertIn('id="planSimulationStatus"', template_text)
        self.assertIn('id="simulationUseCurrentPose"', template_text)
        self.assertIn('id="activePlanLabel"', template_text)
        self.assertIn('id="simulationSpeed"', template_text)
        self.assertIn('id="simulationScope"', template_text)
        self.assertIn('<option value="3" selected>3 Plansegmente</option>', template_text)
        self.assertIn('id="planSimulationPauseBtn"', template_text)
        self.assertIn('id="planSimulationStopBtn"', template_text)
        self.assertIn('id="planLoadBtn"', template_text)
        self.assertIn('id="planPlayStatus"', template_text)
        self.assertNotIn('id="planSelect" onchange=', template_text)
        self.assertIn('id="planSimulationControls" hidden', template_text)
        self.assertIn('Berechnete Reglerspur:', template_text)
        self.assertIn('Gesamter Restplan', template_text)
        self.assertLess(template_text.index('id="laneProgressSlider"'), template_text.index('id="simulationUseCurrentPose"'))
        self.assertLess(template_text.index('id="simulationUseCurrentPose"'), template_text.index('id="planSimulateBtn"'))
        self.assertNotIn('id="canStatus"', template_text)
        self.assertIn('id="rtkInfoStatus"', template_text)
        self.assertIn('<details class="plan-info-disclosure">', template_text)
        self.assertIn('function simulateLanePlan()', script_text)
        self.assertIn('function planPlayAvailability()', script_text)
        self.assertIn('function parseJsonResponse(response)', script_text)
        self.assertIn('/plan/simulate', script_text)
        self.assertNotIn('max_source_segments: 3', script_text)
        self.assertIn('max_steps: 120000', script_text)
        self.assertIn('/plan/simulate/status', script_text)
        self.assertIn('/plan/simulate/cancel', script_text)
        self.assertIn('requestPayload.max_source_segments = maxSourceSegments', script_text)
        self.assertIn('function pollLaneSimulationStatus()', script_text)
        self.assertIn('result.trajectory', script_text)
        self.assertIn('function animateLaneSimulation(timestamp)', script_text)
        self.assertIn('function footprintLatLngs(', script_text)
        self.assertIn('simulationControls.hidden = !lanePreviewPlan', script_text)
        self.assertIn("loadBtn.textContent = planLoadRunning ? 'Plan wird geladen…' : 'Plan laden'", script_text)
        self.assertIn('Berechnete Fahrzeugspur', script_text)
        self.assertIn("laneSimulationRunning ? 'Simulation läuft…'", script_text)
        self.assertIn('remaining < segmentLength || segment === sequence[sequence.length - 1]', script_text)
        self.assertIn('sourceIndex !== null', script_text)
        self.assertIn('const insideOffset = Math.min(0.05', script_text)
        self.assertNotIn('expected_route_signature', script_text)
        self.assertIn('function cancelLaneSimulationForPlanStart()', script_text)
        self.assertIn('Plan ist startbereit · Simulation optional', script_text)
        self.assertIn("playBtn.disabled = !playAvailability.ready", script_text)
        self.assertIn("playAvailability.ready ? 'Play bereit' : 'Play gesperrt'", script_text)
        self.assertIn('function invalidateLaneSimulationSelection()', script_text)
        self.assertIn('invalidateLaneSimulationSelection()', template_text)

    def test_saved_resume_survives_idle_status_updates_after_restart(self):
        script = Path(__file__).resolve().parents[2] / 'static' / 'js' / 'mapping_editor.js'
        script_text = script.read_text(encoding='utf-8')

        self.assertIn('function savedPlanHasResume(mapName)', script_text)
        self.assertIn('(!planIsRunning && savedPlanHasResume(activeMapName))', script_text)
        self.assertIn("['stopped', 'completed'].includes(planState)", script_text)

    def test_route_binding_rejects_changed_execution_prefix(self):
        self.server.mapping = SimpleNamespace(
            plans=SimpleNamespace(route_signature=lambda _segments: 'actual-route')
        )
        result = {
            'success': True,
            'errors': [],
            'executable_segments': [{'type': 'transition'}],
        }

        self.server._bind_expected_route(result, {
            'expected_route_signature': 'simulated-route',
            'expected_route_segment_count': 1,
        })

        self.assertFalse(result['success'])
        self.assertEqual('actual-route', result['route_signature'])
        self.assertIn('erneut simulieren', result['errors'][0])

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

    def test_resume_snapshot_during_transition_references_next_mowing_lane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            plans = SimpleNamespace(
                plans_dir=Path(temp_dir),
                _sanitize_name=lambda name: name,
            )
            self.server.mapping = SimpleNamespace(plans=plans)
            self.server.can = SimpleNamespace(get_sensor_data=lambda: {
                'timestamp': 123.0,
                'gps': {'lat': 52.0, 'lon': 10.0},
            })
            self.server._active_plan_map_name = 'Test'
            self.server._active_plan_summary = {'map_name': 'Test'}
            self.server._active_executable_segments = [
                {'type': 'mow', 'source_index': 31},
                {'type': 'transition', 'source_index': 31},
                {'type': 'mow', 'source_index': 32},
            ]
            self.server._plan_status.update({
                'active_index': 1,
                'current_segment': {'type': 'transition', 'source_index': 31},
            })

            self.server._save_resume_state(reason='paused')

            payload = json.loads(
                (Path(temp_dir) / 'Test.resume.json').read_text(encoding='utf-8')
            )
            self.assertEqual(32, payload['source_segment_index'])

    def test_legacy_transition_resume_advances_to_next_plan_lane(self):
        plan = {'sequence': [
            {'segment_index': 31},
            {'segment_index': 32},
            {'segment_index': 33},
        ]}
        resume = {
            'source_segment_index': 31,
            'current_segment': {'type': 'transition', 'source_index': 31},
        }

        self.assertEqual(32, self.server._resume_source_index(plan, resume))


if __name__ == '__main__':
    unittest.main()
