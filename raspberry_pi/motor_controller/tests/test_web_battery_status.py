"""The battery reading must reach the browser on both status paths.

The frontend is fed twice: once by GET /api/status when the page loads, and
continuously by the WebSocket status stream. A field added to only one of
them looks correct right after a reload and then falls back to "Batterie aus"
on the first broadcast, which is exactly what happened when this was first
deployed.

The stream sends the full status only to a client that just connected; after
that it sends differences. These tests therefore ask for the full stand the
way a fresh browser does.
"""

import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.web.web_server import WebServer
from motor_controller.tests.web_test_support import authenticated_client, web_config


class FakeBattery:
    def __init__(self, status):
        self._status = status

    def get_status(self):
        return dict(self._status)


class RecordingSocketIO:
    def __init__(self):
        self.emitted = []

    def emit(self, event, payload=None, **_kwargs):
        self.emitted.append((event, payload))


BATTERY_STATUS = {
    'enabled': True,
    'connected': True,
    'fresh': True,
    'soc_percent': 98.4,
    'voltage_v': 26.51,
    'current_a': 0.4,
    'level': 'ok',
    'capacity_ah': 50.0,
}


def build_server(battery=None):
    dummy = SimpleNamespace()
    can = SimpleNamespace(
        get_sensor_data=lambda: {},
        get_status=lambda **_kwargs: {'online': True, 'age_s': 0.1, 'source': {}},
    )
    motor = SimpleNamespace(get_status=lambda: {'current_pwm': {'left': 1500, 'right': 1500}})
    joystick = SimpleNamespace(get_status=lambda: {'enabled': False, 'max_speed': 100})
    return WebServer(web_config(), motor, joystick, can, dummy, battery=battery)


class BatteryStatusReachesTheBrowserTests(unittest.TestCase):
    def test_http_status_carries_the_battery(self):
        server = build_server(FakeBattery(BATTERY_STATUS))
        client = authenticated_client(server)

        payload = client.get('/api/status').get_json()

        self.assertEqual(payload['battery_status']['soc_percent'], 98.4)
        self.assertTrue(payload['battery_status']['enabled'])

    def test_websocket_broadcast_carries_the_battery(self):
        server = build_server(FakeBattery(BATTERY_STATUS))
        server.socketio = RecordingSocketIO()

        server._emit_full_status()

        event, message = server.socketio.emitted[-1]
        self.assertEqual(event, 'status_update')
        payload = message['status']
        self.assertEqual(payload['battery_status']['soc_percent'], 98.4)
        self.assertTrue(payload['battery_status']['enabled'])

    def test_both_paths_agree(self):
        server = build_server(FakeBattery(BATTERY_STATUS))
        server.socketio = RecordingSocketIO()
        client = authenticated_client(server)

        http_payload = client.get('/api/status').get_json()
        server._emit_full_status()
        _event, message = server.socketio.emitted[-1]

        self.assertEqual(
            http_payload['battery_status'], message['status']['battery_status']
        )

    def test_without_a_monitor_both_paths_report_disabled(self):
        server = build_server(battery=None)
        server.socketio = RecordingSocketIO()
        client = authenticated_client(server)

        http_payload = client.get('/api/status').get_json()
        server._emit_full_status()
        _event, message = server.socketio.emitted[-1]

        self.assertEqual(http_payload['battery_status'], {'enabled': False})
        self.assertEqual(message['status']['battery_status'], {'enabled': False})


if __name__ == '__main__':
    unittest.main()
