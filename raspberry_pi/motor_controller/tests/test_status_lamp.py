"""Tests fuer die Lebenszeichen ueber das Lichtrelais.

Der Reiz liegt nicht im Blinken, sondern im Zusammenspiel mit der
Handbedienung. Ein Startsignal, das ein absichtlich eingeschaltetes Licht
wieder ausknipst, waere schlimmer als gar kein Signal.
"""

import logging
import sys
import threading
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# pyserial gibt es nur auf dem Fahrzeug. Der Netzwaechter-Test importiert
# main.py, und darueber haengt die GNSS-Kette am Import.
if 'serial' not in sys.modules:
    import types
    _serial = types.ModuleType('serial')
    _serial.Serial = object
    sys.modules['serial'] = _serial

from motor_controller.hardware.status_lamp import StatusLamp


@dataclass
class FakeLightConfig:
    enabled: bool = True
    pin: int = 22
    boot_signal_enabled: bool = True
    boot_on_s: float = 0.02
    network_signal_enabled: bool = True
    network_blinks: int = 2
    network_on_s: float = 0.02
    network_off_s: float = 0.02
    network_wait_timeout_s: float = 5.0
    network_poll_interval_s: float = 0.01


class FakeGPIO:
    """Merkt sich jede Schaltung mit Zeitstempel."""

    def __init__(self, fail_setup: bool = False, fail_output: bool = False):
        self.fail_setup = fail_setup
        self.fail_output = fail_output
        self.setup_calls: List[Tuple[int, int]] = []
        self.writes: List[Tuple[float, int, bool]] = []
        self._lock = threading.Lock()

    def setup_output(self, pin, initial_state=0):
        if self.fail_setup:
            raise RuntimeError('GPIO belegt')
        self.setup_calls.append((pin, initial_state))

    def output(self, pin, state):
        if self.fail_output:
            raise RuntimeError('Pin nicht schaltbar')
        with self._lock:
            self.writes.append((time.monotonic(), pin, bool(state)))

    @property
    def states(self) -> List[bool]:
        with self._lock:
            return [w[2] for w in self.writes]


def warte_auf_ruhe(lamp: StatusLamp, timeout: float = 3.0):
    """Wartet, bis die laufende Signalfolge fertig ist."""
    ende = time.monotonic() + timeout
    while time.monotonic() < ende:
        thread = lamp._thread
        if thread is None or not thread.is_alive():
            return True
        time.sleep(0.01)
    return False


class SignalTests(unittest.TestCase):
    def test_startsignal_geht_an_und_wieder_aus(self):
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        lamp.signal(blinks=1, on_s=0.02, reason='Test')
        self.assertTrue(warte_auf_ruhe(lamp))

        self.assertEqual(gpio.states, [True, False])
        self.assertFalse(lamp.state)

    def test_zweimal_blinken_schaltet_viermal(self):
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        lamp.signal(blinks=2, on_s=0.02, off_s=0.02, reason='Netz')
        self.assertTrue(warte_auf_ruhe(lamp))

        self.assertEqual(gpio.states, [True, False, True, False])

    def test_signal_haelt_den_aufrufer_nicht_auf(self):
        """Der Startvorgang darf nicht auf das Blinken warten."""
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        begonnen = time.monotonic()
        lamp.signal(blinks=3, on_s=0.3, off_s=0.3)
        gebraucht = time.monotonic() - begonnen

        self.assertLess(gebraucht, 0.2, 'signal() muss sofort zurueckkehren')
        lamp.stop()

    def test_pausen_liegen_zwischen_den_blinks(self):
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        lamp.signal(blinks=2, on_s=0.05, off_s=0.05)
        self.assertTrue(warte_auf_ruhe(lamp))

        zeiten = [w[0] for w in gpio.writes]
        self.assertGreaterEqual(zeiten[1] - zeiten[0], 0.04, 'Leuchtphase zu kurz')
        self.assertGreaterEqual(zeiten[2] - zeiten[1], 0.04, 'Pause zu kurz')


class HandbedienungTests(unittest.TestCase):
    def test_handbedienung_unterdrueckt_spaetere_signale(self):
        """Wer das Licht anmacht, will es anlassen."""
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        lamp.set(True)
        gestartet = lamp.signal(blinks=2, on_s=0.02, reason='Netz')

        self.assertFalse(gestartet, 'Nach Handbedienung darf kein Signal mehr laufen')
        self.assertTrue(lamp.state, 'Das Licht muss anbleiben')
        self.assertEqual(gpio.states, [True])

    def test_handbedienung_bricht_ein_laufendes_signal_ab(self):
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        lamp.signal(blinks=5, on_s=0.5, off_s=0.5, reason='lang')
        time.sleep(0.05)
        lamp.set(True)

        self.assertTrue(warte_auf_ruhe(lamp))
        self.assertTrue(lamp.state, 'Der Handzustand muss stehenbleiben')
        self.assertTrue(gpio.states[-1], 'Zuletzt muss eingeschaltet sein')

    def test_toggle_kehrt_um(self):
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        self.assertTrue(lamp.toggle())
        self.assertFalse(lamp.toggle())


class RobustheitTests(unittest.TestCase):
    def test_abgeschaltetes_licht_schaltet_nichts(self):
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(enabled=False), gpio)

        self.assertFalse(lamp.initialize())
        self.assertFalse(lamp.signal(blinks=2))
        self.assertEqual(gpio.writes, [])

    def test_nicht_einrichtbarer_pin_schaltet_die_lampe_ab(self):
        """Ein belegter Pin darf den Dienst nicht am Starten hindern."""
        gpio = FakeGPIO(fail_setup=True)
        lamp = StatusLamp(FakeLightConfig(), gpio)

        self.assertFalse(lamp.initialize())
        self.assertFalse(lamp.enabled)
        self.assertFalse(lamp.signal(blinks=1))

    def test_schaltfehler_reisst_den_signalthread_nicht_ab(self):
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()
        gpio.fail_output = True

        lamp.signal(blinks=2, on_s=0.02, off_s=0.02)
        self.assertTrue(warte_auf_ruhe(lamp), 'Thread muss trotz Fehler enden')

    def test_stop_beendet_ein_laufendes_signal(self):
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        lamp.signal(blinks=10, on_s=1.0, off_s=1.0)
        time.sleep(0.05)
        begonnen = time.monotonic()
        lamp.stop()

        self.assertLess(time.monotonic() - begonnen, 2.5)
        self.assertFalse(lamp.state, 'Nach dem Stoppen muss das Licht aus sein')

    def test_zweites_signal_loest_das_erste_ab(self):
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        lamp.signal(blinks=10, on_s=0.5, off_s=0.5, reason='erst')
        time.sleep(0.05)
        lamp.signal(blinks=1, on_s=0.02, reason='dann')
        self.assertTrue(warte_auf_ruhe(lamp))

        self.assertFalse(lamp.state)



class NetzwaechterTests(unittest.TestCase):
    """Der Teil, der entscheidet, wann "Netz da" gilt.

    Geprueft wird auf die IPv4-Adresse. Eine Verbindung mit SSID, aber ohne
    Adresse ist noch nicht erreichbar - das Signal soll heissen "du kommst
    jetzt drauf", nicht "das Funkmodul hat sich eingebucht".
    """

    def _app(self, lamp, netz_status, timeout_s=5.0):
        from motor_controller.main import MotorControllerApp
        app = SimpleNamespace()
        app.running = True
        app.lamp = lamp
        app.logger = logging.getLogger('test')
        app.config = SimpleNamespace(
            light=FakeLightConfig(network_wait_timeout_s=timeout_s)
        )
        app.network = SimpleNamespace(get_status=netz_status)
        app._await_network_signal = (
            MotorControllerApp._await_network_signal.__get__(app, SimpleNamespace)
        )
        return app

    def test_blinkt_erst_wenn_eine_adresse_da_ist(self):
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        aufrufe = {'n': 0}

        def status():
            aufrufe['n'] += 1
            if aufrufe['n'] < 3:
                # Verbunden, aber noch ohne Adresse.
                return {'ssid': 'HUAWEI-E5180', 'ipv4': None}
            return {'ssid': 'HUAWEI-E5180', 'ipv4': '192.168.8.101/24'}

        app = self._app(lamp, status)
        app._await_network_signal()
        self.assertTrue(warte_auf_ruhe(lamp))

        self.assertGreaterEqual(aufrufe['n'], 3, 'Ohne Adresse darf nicht geblinkt werden')
        self.assertEqual(gpio.states, [True, False, True, False])

    def test_ohne_netz_bleibt_es_still(self):
        """Ohne Zeitfenster koennte es Stunden spaeter im Maehen losblinken."""
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        app = self._app(lamp, lambda: {'ssid': None, 'ipv4': None}, timeout_s=0.1)
        begonnen = time.monotonic()
        app._await_network_signal()

        self.assertLess(time.monotonic() - begonnen, 2.0, 'Warten muss enden')
        self.assertEqual(gpio.writes, [], 'Kein Netz, kein Signal')

    def test_fehler_im_netzstatus_beendet_das_warten_nicht(self):
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        aufrufe = {'n': 0}

        def status():
            aufrufe['n'] += 1
            if aufrufe['n'] < 3:
                raise RuntimeError('nmcli antwortet nicht')
            return {'ssid': 'UGV', 'ipv4': '192.168.178.55/24'}

        app = self._app(lamp, status)
        app._await_network_signal()
        self.assertTrue(warte_auf_ruhe(lamp))

        self.assertEqual(gpio.states, [True, False, True, False])

    def test_abschaltung_beendet_das_warten(self):
        """Beim Herunterfahren darf kein Thread weiterlaufen."""
        gpio = FakeGPIO()
        lamp = StatusLamp(FakeLightConfig(), gpio)
        lamp.initialize()

        app = self._app(lamp, lambda: {'ipv4': None}, timeout_s=30.0)
        app.running = False
        begonnen = time.monotonic()
        app._await_network_signal()

        self.assertLess(time.monotonic() - begonnen, 1.0)
        self.assertEqual(gpio.writes, [])



if __name__ == '__main__':
    unittest.main()
