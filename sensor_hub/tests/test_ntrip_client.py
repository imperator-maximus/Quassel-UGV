"""Tests fuer die Stillstandserkennung des NTRIP-Clients.

Der Caster laesst den Socket bei einem Ausfall minutenlang offen, ohne Daten zu
senden. Ohne Erkennung bliebe ``connected`` True und RTK hinge auf GPS FIX, bis
der Server endlich das FIN schickt (~7 min beobachtet, 08.08.2026). Die Tests
sichern ab, dass ein stehender Strom als Trennung behandelt wird und ein frisch
fliessender Strom nicht faelschlich getrennt wird.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ntrip_client import NTRIPClient


def _make_client(stale_timeout=10.0):
    return NTRIPClient(
        host='example.invalid', port=2101, mountpoint='mp',
        username='u', password='p', stale_timeout=stale_timeout,
    )


class _FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class NTRIPStallDetectionTest(unittest.TestCase):
    def test_fresh_stream_is_not_stale(self):
        client = _make_client(stale_timeout=10.0)
        client.connected = True
        client.last_data_time = time.time()
        self.assertFalse(client.data_is_stale())
        self.assertFalse(client.check_stalled_stream())

    def test_stalled_stream_forces_disconnect(self):
        client = _make_client(stale_timeout=10.0)
        sock = _FakeSocket()
        client.socket = sock
        client.connected = True
        # Letzte Daten liegen deutlich ueber der Schwelle zurueck.
        client.last_data_time = time.time() - 25.0

        self.assertTrue(client.data_is_stale())
        self.assertTrue(client.check_stalled_stream())
        # Verbindung gilt jetzt als getrennt, Socket ist geschlossen.
        self.assertFalse(client.connected)
        self.assertTrue(sock.closed)
        # Nach der Trennung ist nichts mehr "stale" (kein Doppel-Reconnect).
        self.assertFalse(client.data_is_stale())
        self.assertFalse(client.check_stalled_stream())

    def test_disconnected_client_is_never_stale(self):
        client = _make_client(stale_timeout=10.0)
        client.connected = False
        client.last_data_time = time.time() - 999.0
        self.assertIsNone(client.seconds_since_data())
        self.assertFalse(client.data_is_stale())

    def test_connected_without_data_yet_is_not_stale(self):
        # last_data_time == 0 (nie Daten) darf keinen Stillstand melden, solange
        # connect() nicht gelaufen ist; connect() seedet last_data_time selbst.
        client = _make_client(stale_timeout=10.0)
        client.connected = True
        client.last_data_time = 0.0
        self.assertIsNone(client.seconds_since_data())
        self.assertFalse(client.data_is_stale())

    def test_stale_timeout_zero_disables_check(self):
        client = _make_client(stale_timeout=0.0)
        client.connected = True
        client.last_data_time = time.time() - 3600.0
        self.assertFalse(client.data_is_stale())
        self.assertFalse(client.check_stalled_stream())

    def test_status_exposes_stall_fields(self):
        client = _make_client(stale_timeout=10.0)
        client.connected = True
        client.last_data_time = time.time() - 2.0
        status = client.get_status()
        self.assertIn('seconds_since_data', status)
        self.assertIn('stale', status)
        self.assertFalse(status['stale'])
        self.assertGreaterEqual(status['seconds_since_data'], 1.5)


if __name__ == '__main__':
    unittest.main()
