"""Das aktive WLAN muss die Oberflaeche auf beiden Wegen erreichen.

Wie beim Ladezustand wird der Browser zweimal gefuettert: einmal per
GET /api/status beim Laden, danach fortlaufend ueber den WebSocket-Strom. Ein
Feld in nur einem der beiden sieht nach dem Neuladen richtig aus und faellt
beim ersten Rundruf wieder weg - und dann steht die Statusleiste wieder ohne
Netzanzeige da, also genau dort, wo der Rueckfall unbemerkt blieb.
"""

import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.web.web_server import WebServer
from motor_controller.tests.web_test_support import authenticated_client, web_config


NETWORK_STATUS = {
    'enabled': True,
    'interface': 'wlan0',
    'profile': 'UGV',
    'ssid': 'UGV',
    'signal_percent': 58,
    'ipv4': '192.168.4.31',
    'preferred_profile': 'HUAWEI',
    'fallback_profile': 'UGV',
    'on_preferred': False,
    'switching': False,
    'last_switch': None,
    'error': None,
    'age_s': 1,
}


class FakeNetwork:
    def __init__(self, status, switch_result=None):
        self._status = status
        self._switch_result = switch_result or {'success': True, 'switching': True}
        self.switch_calls = 0

    def get_status(self):
        return dict(self._status)

    def switch_to_preferred(self):
        self.switch_calls += 1
        return dict(self._switch_result)


class RecordingSocketIO:
    def __init__(self):
        self.emitted = []

    def emit(self, event, payload=None, **_kwargs):
        self.emitted.append((event, payload))


def build_server(network=None):
    dummy = SimpleNamespace()
    can = SimpleNamespace(
        get_sensor_data=lambda: {},
        get_status=lambda **_kwargs: {'online': True, 'age_s': 0.1, 'source': {}},
    )
    motor = SimpleNamespace(get_status=lambda: {'current_pwm': {'left': 1500, 'right': 1500}})
    joystick = SimpleNamespace(get_status=lambda: {'enabled': False, 'max_speed': 100})
    return WebServer(web_config(), motor, joystick, can, dummy, network=network)


class NetworkStatusReachesTheBrowserTests(unittest.TestCase):
    def test_http_status_carries_the_network(self):
        server = build_server(FakeNetwork(NETWORK_STATUS))
        client = authenticated_client(server)

        payload = client.get('/api/status').get_json()

        self.assertEqual(payload['network_status']['ssid'], 'UGV')
        self.assertFalse(payload['network_status']['on_preferred'])

    def test_websocket_broadcast_carries_the_network(self):
        server = build_server(FakeNetwork(NETWORK_STATUS))
        server.socketio = RecordingSocketIO()

        server._emit_full_status()

        event, message = server.socketio.emitted[-1]
        self.assertEqual(event, 'status_update')
        self.assertEqual(message['status']['network_status']['ssid'], 'UGV')

    def test_both_paths_agree(self):
        server = build_server(FakeNetwork(NETWORK_STATUS))
        server.socketio = RecordingSocketIO()
        client = authenticated_client(server)

        http_payload = client.get('/api/status').get_json()
        server._emit_full_status()
        _event, message = server.socketio.emitted[-1]

        self.assertEqual(
            http_payload['network_status'], message['status']['network_status']
        )

    def test_without_a_monitor_both_paths_report_disabled(self):
        server = build_server(network=None)
        server.socketio = RecordingSocketIO()
        client = authenticated_client(server)

        http_payload = client.get('/api/status').get_json()
        server._emit_full_status()
        _event, message = server.socketio.emitted[-1]

        self.assertEqual(http_payload['network_status'], {'enabled': False})
        self.assertEqual(message['status']['network_status'], {'enabled': False})


class NudgeBackToThePreferredNetworkTests(unittest.TestCase):
    def test_the_button_starts_the_switch(self):
        network = FakeNetwork(NETWORK_STATUS)
        client = authenticated_client(build_server(network))

        response = client.post('/api/network/preferred')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(network.switch_calls, 1)
        self.assertTrue(response.get_json()['success'])

    def test_the_answer_carries_the_current_stand(self):
        client = authenticated_client(build_server(FakeNetwork(NETWORK_STATUS)))

        payload = client.post('/api/network/preferred').get_json()

        self.assertEqual(payload['network_status']['preferred_profile'], 'HUAWEI')

    def test_a_refused_switch_is_reported_as_such(self):
        network = FakeNetwork(
            NETWORK_STATUS,
            switch_result={'success': False, 'error': 'Ein Wechsel laeuft bereits'},
        )
        client = authenticated_client(build_server(network))

        response = client.post('/api/network/preferred')

        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.get_json()['success'])

    def test_without_a_monitor_the_button_says_so(self):
        client = authenticated_client(build_server(network=None))

        response = client.post('/api/network/preferred')

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.get_json()['success'])


if __name__ == '__main__':
    unittest.main()
