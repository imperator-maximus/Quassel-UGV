"""Ein echter ODrive-Fehler braucht einen bewussten Ausweg.

Der Safety-Reset raeumt absichtlich nur Watchdog-Fehler weg - eine Maschine mit
Messern soll einen echten Fehler nicht stillschweigend wegwischen. Das war aber
eine Sackgasse: Der Reset verweigerte mit "Nicht-Watchdog-ODrive-Fehler aktiv",
und der einzige Ausweg war, zum Fahrzeug zu gehen und die Versorgung zu
trennen, denn die Fehler liegen im Arbeitsspeicher der Boards.

Diese Tests halten den bewussten Gegenweg fest: Er tut dasselbe wie der
Stromstoss, verlangt aber eine ausdrueckliche Bestaetigung und schreibt auf,
worueber hinweggegangen wurde.
"""

import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.web.web_server import WebServer
from motor_controller.tests.web_test_support import authenticated_client, web_config


class FakeMower:
    transport = 'usb'
    node_ids = [0, 1, 2]
    config = SimpleNamespace(heartbeat_timeout_s=1.0)

    def __init__(self, fehler=None, erfolg=True):
        self.enabled = True
        self.fehler = fehler if fehler is not None else {0: 0x40, 1: 0x40}
        self.erfolg = erfolg
        self.aufrufe = 0

    def clear_all_errors(self):
        self.aufrufe += 1
        if not self.erfolg:
            return False, 'ODrive USB-Fehler blieben aktiv', dict(self.fehler)
        geloescht = dict(self.fehler)
        self.fehler = {}
        return True, None, geloescht


class FakeNotifier:
    def __init__(self):
        self.meldungen = []

    def fault(self, event, title, message):
        self.meldungen.append(('fault', title, message))

    def recovery(self, event, title, message):
        self.meldungen.append(('recovery', title, message))


def build_server(mower=None, notifier=None):
    dummy = SimpleNamespace()
    can = SimpleNamespace(
        get_sensor_data=lambda: {},
        get_status=lambda **_kwargs: {'odrives': {}, 'sensor_hub': {}},
    )
    motor = SimpleNamespace(
        get_status=lambda: {'current_pwm': {'left': 1500, 'right': 1500}}
    )
    joystick = SimpleNamespace(get_status=lambda: {'enabled': False, 'max_speed': 100})
    server = WebServer(
        web_config(), motor, joystick, can, dummy, notifier=notifier
    )
    server.odrive_mower = mower
    return server


class OdriveFehlerLoeschenTests(unittest.TestCase):
    def test_mit_bestaetigung_werden_die_fehler_geloescht(self):
        mower = FakeMower()
        notifier = FakeNotifier()
        server = build_server(mower, notifier)
        client = authenticated_client(server)

        antwort = client.post('/api/odrive/clear-errors', json={'confirm': True})

        self.assertEqual(antwort.status_code, 200)
        daten = antwort.get_json()
        self.assertTrue(daten['success'])
        self.assertEqual(daten['cleared'], {'0': 64, '1': 64})
        self.assertIn('node 0=0x00000040', daten['cleared_text'])
        self.assertEqual(mower.aufrufe, 1)

    def test_ohne_bestaetigung_passiert_nichts(self):
        """Kein Standardwert und kein Umschalten: Wer Fehler an einer Maschine
        mit Messern wegraeumt, soll das gesagt haben."""
        mower = FakeMower()
        server = build_server(mower)
        client = authenticated_client(server)

        antwort = client.post('/api/odrive/clear-errors', json={})

        self.assertEqual(antwort.status_code, 400)
        self.assertEqual(mower.aufrufe, 0)

    def test_leerer_rumpf_loescht_nichts(self):
        mower = FakeMower()
        server = build_server(mower)
        client = authenticated_client(server)

        antwort = client.post('/api/odrive/clear-errors')

        self.assertEqual(antwort.status_code, 400)
        self.assertEqual(mower.aufrufe, 0)

    def test_das_geloeschte_wird_gemeldet(self):
        """Worueber hinweggegangen wurde, gehoert in die Meldung - sonst faellt
        ein Motor, der wirklich hin ist, niemandem auf."""
        notifier = FakeNotifier()
        server = build_server(FakeMower(), notifier)
        client = authenticated_client(server)

        client.post('/api/odrive/clear-errors', json={'confirm': True})

        self.assertEqual(len(notifier.meldungen), 1)
        art, _titel, text = notifier.meldungen[0]
        self.assertEqual(art, 'recovery')
        self.assertIn('0x00000040', text)

    def test_fehler_die_bleiben_werden_gemeldet(self):
        mower = FakeMower(erfolg=False)
        server = build_server(mower)
        client = authenticated_client(server)

        antwort = client.post('/api/odrive/clear-errors', json={'confirm': True})

        self.assertEqual(antwort.status_code, 409)
        self.assertFalse(antwort.get_json()['success'])

    def test_ohne_maehdeck_gibt_es_nichts_zu_loeschen(self):
        server = build_server(None)
        client = authenticated_client(server)

        antwort = client.post('/api/odrive/clear-errors', json={'confirm': True})

        self.assertEqual(antwort.status_code, 503)


if __name__ == '__main__':
    unittest.main()
