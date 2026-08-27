"""Nach einem USB-Haenger am Maehdeck faehrt das Fahrzeug von allein weiter.

Ein haengender ``libfibre``-Aufruf ist bekannt und harmlos: Der Prozess beendet
sich selbst, weil sich der Aufruf intern nicht abbrechen laesst, und systemd
startet ihn neu. Danach stand das Fahrzeug bisher mitten auf der Wiese und
wartete auf einen Menschen - bei einem Fehler, der regelmaessig auftritt und
mit dem Maehen nichts zu tun hat.

Automatisch angelaufen wird ausschliesslich dieser eine Fall, nur bei gesunden
Verhaeltnissen und nur einige Male hintereinander. Genau das halten diese Tests
fest - besonders die Grenzen, denn hier laufen Messer an, ohne dass jemand
hingesehen hat.
"""

import json
import unittest
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.web.web_server import WebServer
from motor_controller.tests.web_test_support import web_config

USB_HAENGER = 'ODrive USB haengt: USB-Aufruf ohne Antwort seit 5.1s (node 2)'


class FakeMower:
    # transport='can' laesst _can_api_status den Knotenzustand direkt aus
    # can.get_status uebernehmen. Geprueft wird hier die Anlauflogik, nicht der
    # Weg, auf dem die Knotendaten zusammenkommen.
    transport = 'can'
    node_ids = [0, 1, 2]
    config = SimpleNamespace(heartbeat_timeout_s=1.0)

    def __init__(self, erfolg=True):
        self.enabled = True
        self.commanded_rpm = 0
        self.erfolg = erfolg
        self.gestartet_mit = []

    def start(self, rpm=None):
        self.gestartet_mit.append(rpm)
        if not self.erfolg:
            return {'success': False, 'error': 'Transport haengt weiter'}
        self.commanded_rpm = int(rpm or 0)
        return {'success': True, 'running': True}


class FakeNotifier:
    def __init__(self):
        self.meldungen = []

    def fault(self, event, title, message):
        self.meldungen.append(('fault', event, title, message))

    def recovery(self, event, title, message):
        self.meldungen.append(('recovery', event, title, message))


def build_server(gesund=True, mower=None, notifier=None, **config_overrides):
    dummy = SimpleNamespace()
    can = SimpleNamespace(
        get_sensor_data=lambda: {'rtk_status': 'RTK FIXED' if gesund else 'FLOAT'},
        get_status=lambda **_kwargs: {
            'odrives': {'all_online': True, 'nodes': {'0': {'error': 0}}},
            'sensor_hub': {'online': True},
        },
    )
    motor = SimpleNamespace(
        get_status=lambda: {'current_pwm': {'left': 1500, 'right': 1500}}
    )
    joystick = SimpleNamespace(get_status=lambda: {'enabled': False, 'max_speed': 100})
    safety = SimpleNamespace(
        get_status=lambda: {
            'system_stop_latched': False, 'motion_hold_active': False
        }
    )
    server = WebServer(
        web_config(**config_overrides), motor, joystick, can, dummy,
        safety_monitor=safety, notifier=notifier,
    )
    server.odrive_mower = mower
    # Der Wartelauf bricht ab, sobald der Server nicht mehr laeuft. In start()
    # steht das Flag vor dem Anlauf; hier muss es von Hand gesetzt werden.
    server.running = True
    return server


class AnlaufNachUsbHaengerTests(unittest.TestCase):
    def setUp(self):
        self.verzeichnis = tempfile.TemporaryDirectory()
        self.addCleanup(self.verzeichnis.cleanup)

    def ruestung(self, server, **felder):
        """Legt einen Wiederaufsetzpunkt an, wie ihn der Stopp hinterlaesst."""
        pfad = Path(self.verzeichnis.name) / 'Brunnen.resume.json'
        inhalt = {
            'schema': 'raspberrycan.mowing_resume.v2',
            'map_name': 'Brunnen',
            'reason': 'safety_stop',
            'detail': USB_HAENGER,
            'mower_rpm': 700,
            'mower_running': True,
            'auto_resume_count': 0,
            'active_index': 3,
        }
        inhalt.update(felder)
        pfad.write_text(json.dumps(inhalt), encoding='utf-8')
        server._active_plan_map_name = 'Brunnen'
        server._resume_path = lambda _name: pfad
        return pfad

    def test_usb_haenger_laeuft_von_allein_wieder_an(self):
        mower = FakeMower()
        notifier = FakeNotifier()
        server = build_server(mower=mower, notifier=notifier)
        self.ruestung(server)
        with patch.object(server, 'resume_plan_execution',
                          return_value={'success': True}) as fortsetzen,                 patch('motor_controller.web.web_server.threading.Thread') as thread:
            # Der Anlauf laeuft im Hintergrund; hier soll er nachvollziehbar
            # sein statt nebenlaeufig.
            server._maybe_auto_resume_after_usb_stall()
            self.assertTrue(thread.called, 'Der Anlauf haette starten muessen')
            server._auto_resume_worker('Brunnen', server._load_resume_state('Brunnen'))

        fortsetzen.assert_called_once_with('Brunnen')
        self.assertEqual(server._auto_resume_count, 1)
        self.assertEqual(mower.gestartet_mit, [700])
        self.assertEqual(
            [m[0] for m in notifier.meldungen], ['recovery'],
            'Jeder Anlauf gehoert gemeldet - er passiert unbeobachtet',
        )

    def test_anderer_sicherheitsstopp_laeuft_nicht_von_allein_an(self):
        """Ein Stopp mit anderer Ursache wartet weiter auf einen Menschen."""
        mower = FakeMower()
        server = build_server(mower=mower)
        self.ruestung(server, detail='Maehdeck-Kommandoschleife ohne Lebenszeichen')
        with patch.object(server, 'resume_plan_execution') as fortsetzen:
            server._maybe_auto_resume_after_usb_stall()

        fortsetzen.assert_not_called()
        self.assertEqual(mower.gestartet_mit, [])

    def test_ohne_klartext_laeuft_nichts_an(self):
        """Alte Wiederaufsetzpunkte kennen das Feld nicht."""
        server = build_server(mower=FakeMower())
        self.ruestung(server, detail=None)
        with patch.object(server, 'resume_plan_execution') as fortsetzen:
            server._maybe_auto_resume_after_usb_stall()

        fortsetzen.assert_not_called()

    def test_nach_zu_vielen_anlaeufen_uebernimmt_der_mensch(self):
        """Haengt der Transport wirklich fest, waere die Kette sonst Neustart,
        Messer an, Haenger, Neustart - ohne Ende."""
        mower = FakeMower()
        notifier = FakeNotifier()
        server = build_server(
            mower=mower, notifier=notifier, auto_resume_max_attempts=3
        )
        self.ruestung(server, auto_resume_count=3)
        with patch.object(server, 'resume_plan_execution') as fortsetzen:
            server._maybe_auto_resume_after_usb_stall()

        fortsetzen.assert_not_called()
        self.assertEqual(mower.gestartet_mit, [])
        self.assertEqual([m[0] for m in notifier.meldungen], ['fault'])

    def test_abgeschaltet_laeuft_nichts_an(self):
        server = build_server(
            mower=FakeMower(), auto_resume_after_usb_stall=False
        )
        self.ruestung(server)
        with patch.object(server, 'resume_plan_execution') as fortsetzen:
            server._maybe_auto_resume_after_usb_stall()

        fortsetzen.assert_not_called()

    def test_ohne_rtk_fix_wird_nicht_angelaufen(self):
        """Auf einer FLOAT-Loesung faehrt das Fahrzeug ohnehin nicht."""
        server = build_server(gesund=False, mower=FakeMower())

        self.assertIn('RTK', server._restart_health_problem())

    def test_odrive_fehler_verhindert_den_anlauf(self):
        server = build_server(mower=FakeMower())
        server.can.get_status = lambda **_kwargs: {
            'odrives': {'all_online': True, 'nodes': {'2': {'error': 64}}},
            'sensor_hub': {'online': True},
        }

        self.assertIn('ODrive-Fehler', server._restart_health_problem())

    def test_fehlende_pose_verhindert_den_anlauf(self):
        server = build_server(mower=FakeMower())
        server.can.get_status = lambda **_kwargs: {
            'odrives': {'all_online': True, 'nodes': {}},
            'sensor_hub': {'online': False},
        }

        self.assertIn('SensorHub', server._restart_health_problem())

    def test_gesunder_zustand_meldet_kein_hindernis(self):
        server = build_server(mower=FakeMower())

        self.assertIsNone(server._restart_health_problem())

    def test_maehdeck_das_nicht_anlaeuft_stoppt_den_anlauf(self):
        """Faehrt das Fahrzeug ohne Messer weiter, maeht es nichts und der
        Fehler faellt erst am Ende der Bahn auf."""
        mower = FakeMower(erfolg=False)
        notifier = FakeNotifier()
        server = build_server(mower=mower, notifier=notifier)
        self.ruestung(server)
        with patch.object(server, 'resume_plan_execution') as fortsetzen:
            server._auto_resume_worker(
                'Brunnen', server._load_resume_state('Brunnen')
            )

        fortsetzen.assert_not_called()
        self.assertEqual([m[0] for m in notifier.meldungen], ['fault'])


if __name__ == '__main__':
    unittest.main()
