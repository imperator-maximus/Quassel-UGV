"""Welches Ereignis welche Ansage ausloest - und welches schweigt.

Die Ansagen haengen an denselben Flanken wie Licht und Push-Meldung. Was hier
falsch verdrahtet ist, faellt am Fahrzeug erst auf, wenn es darauf ankommt:
entweder bleibt es still, oder es redet im Sekundentakt.
"""

import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# pyserial gibt es nur auf dem Fahrzeug. Fuer den Import der NTRIP-Bruecke
# reicht der Platzhalter; angefasst wird die Schnittstelle hier nicht.
if 'serial' not in sys.modules:
    serial_stub = types.ModuleType('serial')
    serial_stub.Serial = object
    sys.modules['serial'] = serial_stub

from motor_controller.hardware.safety_monitor import SafetyMonitor
from motor_controller.web.web_server import WebServer


class FakeVoice:
    """Nimmt Ansagen entgegen, statt sie abzuspielen."""

    def __init__(self):
        self.gesagt = []

    def say(self, key, urgent=False, force=False):
        self.gesagt.append((key, urgent))
        return True

    @property
    def keys(self):
        return [k for k, _ in self.gesagt]


def make_safety():
    config = SimpleNamespace(
        enabled=False, pin=17, debounce_time=0.05,
        command_timeout=1.0, joystick_timeout=1.0,
        link_watchdog_enabled=False, watchdog_interval=0.05,
    )
    monitor = SafetyMonitor(config, SimpleNamespace())
    voice = FakeVoice()
    monitor.set_voice(voice)
    return monitor, voice


class SicherheitsAnsagenTest(unittest.TestCase):
    """Der Sicherheitsmonitor sagt seine Ursache an."""

    def test_sicherheitsstopp_ist_dringend(self):
        monitor, voice = make_safety()
        monitor.trigger_system_stop('Pose zu alt')
        self.assertEqual([('sicherheitsstopp', True)], voice.gesagt)

    def test_schalter_nennt_seine_eigene_ursache(self):
        """Sonst hoerte man nur "Sicherheitsstopp" und suchte am falschen Ende."""
        monitor, voice = make_safety()
        monitor.trigger_system_stop('Schalter', voice_key='sicherheitsschalter')
        self.assertEqual(['sicherheitsschalter'], voice.keys)

    def test_verriegelt_bleibt_verriegelt_und_still(self):
        """Ein zweiter Stopp auf demselben Zustand sagt nichts."""
        monitor, voice = make_safety()
        monitor.trigger_system_stop('erste Ursache')
        monitor.trigger_system_stop('zweite Ursache')
        self.assertEqual(['sicherheitsstopp'], voice.keys)

    def test_entriegeln_sagt_bescheid(self):
        monitor, voice = make_safety()
        monitor.trigger_system_stop('Pose zu alt')
        ok, _ = monitor.reset_system_stop()
        self.assertTrue(ok)
        self.assertEqual(['sicherheitsstopp', 'sicherheitsstopp_frei'], voice.keys)

    def test_ansage_laeuft_auch_ohne_push_ziel(self):
        """Ohne eingerichteten Push darf die Ansage nicht mit ausfallen."""
        monitor, voice = make_safety()
        self.assertIsNone(monitor.notifier)
        monitor.trigger_system_stop('Pose zu alt')
        self.assertEqual(['sicherheitsstopp'], voice.keys)

    def test_kurze_fahrpause_bleibt_still(self):
        """Eine Telemetrieluecke von Sekunden loest sich von selbst."""
        monitor, voice = make_safety()
        monitor._motion_hold_notify_after_s = 60.0
        monitor.trigger_motion_hold('Telemetrie unterbrochen')
        monitor._check_motion_hold_duration()
        self.assertEqual([], voice.keys)

    def test_anhaltende_fahrpause_wird_angesagt(self):
        monitor, voice = make_safety()
        monitor._motion_hold_notify_after_s = 0.0
        monitor.trigger_motion_hold('Telemetrie unterbrochen')
        monitor._check_motion_hold_duration()
        monitor.clear_motion_hold()
        self.assertEqual(['fahrpause', 'fahrpause_beendet'], voice.keys)


class PlanAnsagenTest(unittest.TestCase):
    """Der Planzustand entscheidet, was gesagt wird."""

    def _server(self):
        server = WebServer.__new__(WebServer)
        server.logger = __import__('logging').getLogger('test-voice-plan')
        server.voice = FakeVoice()
        server.notifier = None
        return server

    def _uebergang(self, previous, current):
        server = self._server()
        server._announce_plan_state(previous, current)
        return server.voice

    def test_start_und_fortsetzung_klingen_verschieden(self):
        """Beides endet auf 'running' - der Unterschied ist der Anlass."""
        self.assertEqual(['plan_gestartet'], self._uebergang('idle', 'running').keys)
        self.assertEqual(['plan_fortgesetzt'], self._uebergang('rtk_lost', 'running').keys)

    def test_fertig_und_pausiert(self):
        self.assertEqual(['plan_fertig'], self._uebergang('running', 'completed').keys)
        self.assertEqual(['plan_pausiert'], self._uebergang('running', 'paused').keys)

    def test_stoerungen_nennen_ihre_ursache_und_draengeln_vor(self):
        for state, key in (
            ('nogo_stop', 'nogo_erreicht'),
            ('rtk_lost', 'rtk_verloren'),
            ('mower_fault', 'maehdeck_fehler'),
            ('geofence', 'rand_erreicht'),
        ):
            with self.subTest(state=state):
                self.assertEqual(
                    [(key, True)], self._uebergang('running', state).gesagt
                )

    def test_unbekannte_stoerung_bleibt_nicht_stumm(self):
        """Lieber allgemein als schweigend - wie bei den Betreffzeilen auch."""
        self.assertEqual(
            ['plan_fehler'], self._uebergang('running', 'track_stall').keys
        )

    def test_leise_zustaende(self):
        """Was der Benutzer selbst ausgeloest hat, braucht keine Ansage."""
        for state in ('idle', 'stopped', 'rtk_wait', 'shutdown', 'cleared'):
            with self.subTest(state=state):
                self.assertEqual([], self._uebergang('running', state).keys)

    def test_derselbe_zustand_wiederholt_sich_nicht(self):
        """``_set_plan_status`` laeuft im Sekundentakt durch."""
        self.assertEqual([], self._uebergang('running', 'running').keys)

    def test_sicherheitsstopp_sagt_der_safety_monitor(self):
        """Sonst kaeme die Ansage doppelt, einmal ohne die echte Ursache."""
        self.assertEqual([], self._uebergang('running', 'safety_stop').keys)

    def test_jeder_planzustand_hat_eine_datei(self):
        """Eine Zuordnung ohne Datei bliebe bis zum Ernstfall unbemerkt."""
        audio = Path(__file__).resolve().parents[1] / 'audio'
        vorhanden = {p.stem for p in audio.glob('*.wav')}
        erwartet = set(WebServer.PLAN_VOICE_STATES.values())
        erwartet |= {WebServer.PLAN_VOICE_DEFAULT, 'plan_gestartet'}
        self.assertEqual(set(), erwartet - vorhanden)


class KatalogTest(unittest.TestCase):
    """Katalog und Dateien duerfen nicht auseinanderlaufen."""

    def test_zu_jedem_katalogeintrag_gibt_es_eine_datei(self):
        wurzel = Path(__file__).resolve().parents[3]
        katalog = json.loads(
            (wurzel / 'tools' / 'voice' / 'announcements.json').read_text(
                encoding='utf-8'
            )
        )['announcements']
        audio = Path(__file__).resolve().parents[1] / 'audio'
        vorhanden = {p.stem for p in audio.glob('*.wav')}
        self.assertEqual(set(), set(katalog) - vorhanden)


class StartgeplapperTest(unittest.TestCase):
    """Der erste Befund nach dem Start ist kein Zustandswechsel.

    Ohne diese Unterscheidung meldet jeder Neustart eine Rueckkehr, die es nie
    gab: 'NO GPS' ist der Anfangswert der Bruecke, und der Netzwaechter kennt
    vor seiner ersten Messung ueberhaupt keine Adresse. Beides fiele in
    dieselben Sekunden wie die Startansage, die dasselbe schon sagt.
    """

    def _bridge(self):
        from motor_controller.sensors.gps_ntrip_bridge import GPSNTRIPBridge
        bridge = GPSNTRIPBridge.__new__(GPSNTRIPBridge)
        bridge.voice = FakeVoice()
        bridge._rtk_status_seen = False
        bridge.rtk_fix_count = 0
        bridge.rtk_float_count = 0
        return bridge

    def test_erster_fix_nach_dem_start_schweigt(self):
        bridge = self._bridge()
        bridge._on_rtk_status_changed('NO GPS', 'RTK FIXED')
        self.assertEqual([], bridge.voice.keys)

    def test_danach_wird_jeder_verlust_gemeldet(self):
        bridge = self._bridge()
        bridge._on_rtk_status_changed('NO GPS', 'RTK FIXED')
        bridge._on_rtk_status_changed('RTK FIXED', 'RTK FLOAT')
        bridge._on_rtk_status_changed('RTK FLOAT', 'RTK FIXED')
        self.assertEqual(['rtk_verloren', 'rtk_zurueck'], bridge.voice.keys)

    def _watcher(self):
        from motor_controller.communication.network_monitor import NetworkMonitor
        watcher = NetworkMonitor.__new__(NetworkMonitor)
        watcher.logger = __import__('logging').getLogger('test-voice-net')
        watcher.voice = FakeVoice()
        watcher._link_state_seen = False
        return watcher

    def test_erste_adresse_nach_dem_start_schweigt(self):
        watcher = self._watcher()
        watcher._announce_link_change(False, True)
        self.assertEqual([], watcher.voice.keys)

    def test_danach_wird_der_abriss_gemeldet(self):
        watcher = self._watcher()
        watcher._announce_link_change(False, True)
        watcher._announce_link_change(True, False)
        watcher._announce_link_change(False, True)
        self.assertEqual(['funk_verloren', 'funk_zurueck'], watcher.voice.keys)

    def test_gleicher_stand_sagt_nichts(self):
        """``refresh`` laeuft im Sekundentakt durch."""
        watcher = self._watcher()
        watcher._announce_link_change(True, True)   # erster Befund
        watcher._announce_link_change(True, True)
        self.assertEqual([], watcher.voice.keys)

if __name__ == '__main__':
    unittest.main()
