"""Was die Sprachansage darf und was sie niemals darf.

Ansagen sind Beiwerk. Sie laufen neben Steuerung und Sicherheit her und muessen
sich entsprechend benehmen: nie blockieren, nie eine Ausnahme nach oben geben,
und einer dringenden Ansage nie im Weg stehen, nur weil gerade der fertige
Maehplan verkuendet wird.
"""

import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.hardware.voice_announcer import VoiceAnnouncer


def make_config(audio_dir, **overrides):
    values = dict(
        enabled=True,
        device='plughw:CARD=Device,DEV=0',
        player='aplay',
        audio_dir=str(audio_dir),
        queue_size=8,
        min_interval_s=0.0,
        timeout_s=5.0,
        boot_announcements=True,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class VoiceAnnouncerTest(unittest.TestCase):
    """Der Ansager mit eingespeistem Abspieler - ohne Soundkarte."""

    def setUp(self):
        self.audio_dir = Path(__file__).resolve().parent / 'fixtures' / 'audio'
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        for name in ('system_bereit', 'notaus', 'plan_fertig', 'faehrt_an'):
            (self.audio_dir / f'{name}.wav').write_bytes(b'RIFF')

        self.played = []
        self.play_gate = threading.Event()
        self.announcer = None

    def tearDown(self):
        if self.announcer:
            self.play_gate.set()
            self.announcer.stop()

    def _start(self, **overrides):
        def player(path):
            self.played.append(Path(path).stem)

        self.announcer = VoiceAnnouncer(
            make_config(self.audio_dir, **overrides), player=player
        )
        self.announcer.start()
        return self.announcer

    def _wait_for(self, count, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.played) >= count:
                return True
            time.sleep(0.01)
        return False

    def test_ansage_wird_abgespielt(self):
        voice = self._start()
        self.assertTrue(voice.say('system_bereit'))
        self.assertTrue(self._wait_for(1), 'Ansage wurde nicht abgespielt')
        self.assertEqual(['system_bereit'], self.played)

    def test_fehlende_datei_ist_kein_absturz(self):
        """Eine fehlende Datei darf den Aufrufer nicht stoeren."""
        voice = self._start()
        self.assertFalse(voice.say('gibt_es_nicht'))
        self.assertEqual(['gibt_es_nicht'], voice.get_status()['missing'])

    def test_wiederholsperre(self):
        """Ein dauerhaft anliegender Anlass darf nicht im Takt plappern."""
        voice = self._start(min_interval_s=60.0)
        self.assertTrue(voice.say('faehrt_an'))
        self.assertFalse(voice.say('faehrt_an'))
        self.assertTrue(voice.say('faehrt_an', force=True))

    def test_dringende_ansage_verdraengt_die_warteschlange(self):
        """Der Not-Aus wartet nicht, bis der Maehplan fertig verkuendet ist."""
        started = threading.Event()

        def blocking_player(path):
            name = Path(path).stem
            if name == 'plan_fertig':
                started.set()
                self.play_gate.wait(timeout=3.0)
            self.played.append(name)

        self.announcer = VoiceAnnouncer(
            make_config(self.audio_dir), player=blocking_player
        )
        self.announcer.start()

        self.announcer.say('plan_fertig')
        self.assertTrue(started.wait(timeout=3.0), 'erste Ansage lief nicht an')
        self.announcer.say('faehrt_an')          # steht in der Schlange
        self.announcer.say('notaus', urgent=True)  # raeumt sie ab
        self.play_gate.set()

        self.assertTrue(self._wait_for(2), 'Not-Aus kam nicht durch')
        time.sleep(0.2)
        self.assertIn('notaus', self.played)
        self.assertNotIn('faehrt_an', self.played)

    def test_dringende_ansage_schneidet_sich_nicht_selbst_ab(self):
        """Das Abbruchsignal galt der vorigen Ansage, nicht dieser."""
        voice = self._start()
        voice.say('notaus', urgent=True)
        self.assertTrue(self._wait_for(1), 'dringende Ansage kam nicht')
        self.assertEqual(['notaus'], self.played)

    def test_abspielfehler_bleibt_im_ansager(self):
        """Ein defektes aplay darf den Ansagethread nicht beenden."""
        def failing_player(path):
            if Path(path).stem == 'notaus':
                raise RuntimeError('kein Audiogeraet')
            self.played.append(Path(path).stem)

        self.announcer = VoiceAnnouncer(
            make_config(self.audio_dir), player=failing_player
        )
        self.announcer.start()
        self.announcer.say('notaus')
        self.announcer.say('system_bereit')

        # Die zweite Ansage kommt durch: der Thread hat den Fehler ueberlebt.
        # ``last_error`` steht hier schon wieder auf None - ein Erfolg loescht
        # ihn, wie beim PushNotifier auch.
        self.assertTrue(self._wait_for(1), 'Ansager ist am Fehler gestorben')
        self.assertEqual(['system_bereit'], self.played)

    def test_abgeschaltet_sagt_nichts(self):
        voice = self._start(enabled=False)
        self.assertFalse(voice.say('system_bereit'))
        self.assertEqual([], self.played)

    def test_volle_warteschlange_verwirft_das_aelteste(self):
        """Die juengste Lage zaehlt mehr als die aelteste Ansage."""
        self.announcer = VoiceAnnouncer(
            make_config(self.audio_dir, queue_size=2), player=lambda p: None
        )
        # Ohne laufenden Thread bleibt alles in der Schlange liegen.
        for _ in range(5):
            self.announcer._put_dropping_oldest({'key': 'x', 'path': 'x'})
        self.assertEqual(2, self.announcer.get_status()['queued'])
        self.assertEqual(3, self.announcer.get_status()['dropped'])


if __name__ == '__main__':
    unittest.main()
