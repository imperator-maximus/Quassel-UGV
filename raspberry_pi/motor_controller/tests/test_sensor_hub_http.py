import json
import time
import unittest
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
import socket

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.communication.sensor_hub_http import SensorHubHttpClient


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps(self.payload).encode('utf-8')


class FakeStreamResponse:
    status = 200

    def __init__(self, payloads, on_last_line):
        self.lines = [json.dumps(payload).encode('utf-8') + b'\n' for payload in payloads]
        self.on_last_line = on_last_line

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def readline(self, _limit):
        line = self.lines.pop(0)
        if not self.lines:
            self.on_last_line()
        return line


class SensorHubHttpClientTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            wifi_url='http://sensor/api/telemetry',
            poll_interval_s=0.1,
            request_timeout_s=0.2,
            pause_timeout_s=1.0,
            telemetry_timeout_s=1.0,
        )
        self.received = []
        self.client = SensorHubHttpClient(self.config, self.received.append)

    def valid_payload(self, timestamp=1.0):
        return {
            'timestamp': timestamp,
            'gps': {'lat': 53.0, 'lon': 11.0},
            'heading': 90.0,
            'rtk_status': 'RTK FIXED',
        }

    def test_valid_payload_is_forwarded_and_marks_client_online(self):
        with patch(
            'motor_controller.communication.sensor_hub_http.urlopen',
            return_value=FakeResponse(self.valid_payload()),
        ):
            self.assertTrue(self.client._poll_once())

        self.assertEqual(self.received, [self.valid_payload()])
        self.assertTrue(self.client.get_status()['online'])
        self.assertEqual(self.client.get_status()['packets_received'], 1)

    def test_stream_forwards_multiple_payloads_over_one_connection(self):
        response = FakeStreamResponse(
            [self.valid_payload(1.0), self.valid_payload(2.0)],
            self.client._stop_event.set,
        )
        with patch(
            'motor_controller.communication.sensor_hub_http.urlopen',
            return_value=response,
        ) as opener:
            self.assertTrue(self.client._stream_once())

        self.assertEqual(len(self.received), 2)
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, 'http://sensor/api/telemetry/stream')
        self.assertEqual(request.get_header('Connection'), 'keep-alive')

    def test_start_launches_two_staggered_stream_connections(self):
        threads = [Mock(), Mock()]
        for thread in threads:
            thread.is_alive.return_value = False

        with patch(
            'motor_controller.communication.sensor_hub_http.threading.Thread',
            side_effect=threads,
        ) as constructor:
            self.client.start()

        self.assertEqual(constructor.call_count, 2)
        self.assertEqual(constructor.call_args_list[0].kwargs['args'], (0.0,))
        self.assertEqual(constructor.call_args_list[1].kwargs['args'], (0.1,))
        threads[0].start.assert_called_once_with()
        threads[1].start.assert_called_once_with()

    def test_duplicate_timestamp_is_rejected(self):
        responses = [
            FakeResponse(self.valid_payload(2.0)),
            FakeResponse(self.valid_payload(2.0)),
        ]
        with patch(
            'motor_controller.communication.sensor_hub_http.urlopen',
            side_effect=responses,
        ):
            self.assertTrue(self.client._poll_once())
            self.assertFalse(self.client._poll_once())

        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.client.get_status()['stale_packets'], 1)

    def test_invalid_payload_does_not_refresh_watchdog(self):
        with patch(
            'motor_controller.communication.sensor_hub_http.urlopen',
            return_value=FakeResponse({'timestamp': time.time()}),
        ):
            self.assertFalse(self.client._poll_once())

        status = self.client.get_status()
        self.assertFalse(status['online'])
        self.assertIn('GPS-Pose fehlt', status['last_error'])

    def test_connection_error_only_counts_and_never_raises(self):
        with patch(
            'motor_controller.communication.sensor_hub_http.urlopen',
            side_effect=OSError('Verbindung fehlgeschlagen'),
        ):
            self.assertFalse(self.client._poll_once())
            self.assertFalse(self.client._poll_once())

        status = self.client.get_status()
        self.assertEqual(self.received, [])
        self.assertEqual(status['packets_received'], 0)
        self.assertEqual(status['error_count'], 2)
        self.assertEqual(status['consecutive_errors'], 2)
        self.assertFalse(status['online'])

    def test_dns_is_cached_as_numeric_request_target_with_original_host_header(self):
        with patch(
            'motor_controller.communication.sensor_hub_http.socket.getaddrinfo',
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('87.139.100.77', 8081)),
            ],
        ) as resolver:
            self.assertTrue(self.client._refresh_resolved_url())

        with patch(
            'motor_controller.communication.sensor_hub_http.urlopen',
            return_value=FakeResponse(self.valid_payload()),
        ) as opener:
            self.assertTrue(self.client._poll_once())

        resolver.assert_called_once()
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, 'http://87.139.100.77:80/api/telemetry')
        self.assertEqual(request.get_header('Host'), 'sensor')
        self.assertEqual(
            self.client.get_status()['resolved_url'],
            'http://87.139.100.77:80/api/telemetry',
        )

    def test_short_error_burst_does_not_trigger_dns_refresh(self):
        with patch(
            'motor_controller.communication.sensor_hub_http.urlopen',
            side_effect=OSError('kurze Netzstoerung'),
        ), patch.object(self.client, '_refresh_resolved_url') as resolver:
            for _ in range(9):
                self.assertFalse(self.client._poll_once())
            resolver.assert_not_called()
            self.assertFalse(self.client._poll_once())
            resolver.assert_called_once()


if __name__ == '__main__':
    unittest.main()
