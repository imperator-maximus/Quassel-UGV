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
    """Geprueft wird die Anlauflogik, nicht das Lesen der Achszustaende."""

    transport = 'usb'
    node_ids = [0, 1, 2]
    config = SimpleNamespace(heartbeat_timeout_s=1.0)

    def __init__(self, erfolg=True, fehler=None):
        self.enabled = True
        self.commanded_rpm = 0
        self.erfolg = erfolg
        self.fehler = dict(fehler or {})
        self.gestartet_mit = []

    def get_status(self, **_kwargs):
        return {
            'odrive_missing_heartbeats': [],
            'odrive_errors': {node_id: self.fehler.get(node_id, 0) for node_id in self.node_ids},
            'odrive_states': {node_id: 5 for node_id in self.node_ids},
            'odrive_heartbeat_ages': {node_id: 0.1 for node_id in self.node_ids},
            'odrive_currents': {},
        }

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
    pose = SimpleNamespace(
        get_sensor_data=lambda: {'rtk_status': 'RTK FIXED' if gesund else 'FLOAT'},
        get_status=lambda **_kwargs: {'online': True, 'age_s': 0.1, 'source': {}},
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
        web_config(**config_overrides), motor, joystick, pose, dummy,
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
        server = build_server(mower=FakeMower(fehler={2: 64}))

        self.assertIn('ODrive-Fehler', server._restart_health_problem())

    def test_fehlende_pose_verhindert_den_anlauf(self):
        server = build_server(mower=FakeMower())
        server.pose.get_status = lambda **_kwargs: {
            'online': False, 'age_s': None, 'source': {}
        }

        self.assertIn('GNSS', server._restart_health_problem())

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


class FortsetzpunktMerktDieDrehzahlTests(unittest.TestCase):
    """Die gespeicherte Drehzahl muss von *vor* dem Fehler stammen.

    Das Maehdeck raeumt sein ``commanded_rpm`` in ``emergency_stop`` und
    ``_request_system_stop`` sofort auf 0, und erst danach schreibt der
    Sicherheitsstopp den Fortsetzungspunkt. Wird an dieser Stelle die 0
    festgehalten, ueberspringt der automatische Anlauf das Deck stillschweigend
    (seine Bedingung lautet ``rpm > 0``) - das Fahrzeug faehrt weiter und maeht
    nicht. Genau so beobachtet am 31.08.2026.
    """

    def setUp(self):
        self.verzeichnis = tempfile.TemporaryDirectory()
        self.addCleanup(self.verzeichnis.cleanup)

    def bauen(self):
        mower = FakeMower()
        server = build_server(mower=mower)
        pfad = Path(self.verzeichnis.name) / 'Brunnen.resume.json'
        server._resume_path = lambda _name: pfad
        server._active_plan_map_name = 'Brunnen'
        server._active_executable_segments = [{'type': 'mow', 'source_index': 3}]
        server.get_plan_execution_status = lambda: {
            'active_index': 0,
            'current_segment': {'type': 'mow', 'source_index': 3},
        }
        return server, mower, pfad

    def maehen_dann_stoerung(self, server, mower, rpm=2850):
        server.mower_state = True
        mower.commanded_rpm = rpm
        server._save_resume_state(reason='running')
        # Der Fehler raeumt die Drehzahl, der Sicherheitsstopp kommt danach.
        mower.commanded_rpm = 0

    def test_drehzahl_ueberlebt_den_maehdeck_fehler(self):
        server, mower, pfad = self.bauen()
        self.maehen_dann_stoerung(server, mower)
        server._save_resume_state(reason='safety_stop', detail=USB_HAENGER)

        inhalt = json.loads(pfad.read_text(encoding='utf-8'))
        self.assertTrue(inhalt['mower_running'])
        self.assertEqual(inhalt['mower_rpm'], 2850)

    def test_das_deck_laeuft_danach_mit_alter_drehzahl_an(self):
        server, mower, pfad = self.bauen()
        self.maehen_dann_stoerung(server, mower)
        server._save_resume_state(reason='safety_stop', detail=USB_HAENGER)

        # Neustart: frisches Deck, der Fortsetzungspunkt ist alles, was bleibt.
        neues_deck = FakeMower()
        server.odrive_mower = neues_deck
        with patch.object(server, 'resume_plan_execution',
                          return_value={'success': True}):
            server._auto_resume_worker(
                'Brunnen', server._load_resume_state('Brunnen')
            )
        self.assertEqual(neues_deck.gestartet_mit, [2850])

    def test_bewusst_abgeschaltetes_deck_bleibt_aus(self):
        """Wer das Deck von Hand ausmacht, findet es nicht wieder laufend vor."""
        server, mower, pfad = self.bauen()
        self.maehen_dann_stoerung(server, mower)
        server.mower_state = False
        server._save_resume_state(reason='safety_stop', detail=USB_HAENGER)

        inhalt = json.loads(pfad.read_text(encoding='utf-8'))
        self.assertFalse(inhalt['mower_running'])
        self.assertEqual(inhalt['mower_rpm'], 0)

    def test_eine_neue_drehzahl_loest_die_alte_ab(self):
        server, mower, pfad = self.bauen()
        self.maehen_dann_stoerung(server, mower, rpm=2850)
        server.mower_state = True
        mower.commanded_rpm = 1900
        server._save_resume_state(reason='safety_stop', detail=USB_HAENGER)

        inhalt = json.loads(pfad.read_text(encoding='utf-8'))
        self.assertEqual(inhalt['mower_rpm'], 1900)


if __name__ == '__main__':
    unittest.main()
