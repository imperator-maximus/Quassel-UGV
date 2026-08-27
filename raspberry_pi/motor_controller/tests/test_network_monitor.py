"""Das Fahrzeug soll nicht mehr still ins alte WLAN zurueckfallen.

Am 27.08.2026 hing es zweimal unbemerkt am HaLow-Notweg statt am Mobilfunk.
Diese Tests halten fest, was der Netzwaechter dagegen leistet: Er liest den
tatsaechlichen Stand ueber NetworkManager, er erkennt, dass es nicht das
Wunschnetz ist, und sein Rueckweg sichert sich selbst ab - der Rueckfall ins
alte Netz wird vor dem Wechsel scharf gestellt und nur dann entschaerft, wenn
das Wunschnetz danach wirklich steht.
"""

import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.communication.network_monitor import NetworkMonitor, split_terse


DEVICE_ON_HUAWEI = (
    'GENERAL.CONNECTION:HUAWEI\n'
    'GENERAL.STATE:100 (verbunden)\n'
    'IP4.ADDRESS[1]:192.168.8.102/24\n'
)

DEVICE_ON_UGV = (
    'GENERAL.CONNECTION:UGV\n'
    'GENERAL.STATE:100 (verbunden)\n'
    'IP4.ADDRESS[1]:192.168.4.31/24\n'
)

WIFI_LIST_HUAWEI = (
    'no:HaLow-UGV:41\n'
    'yes:HUAWEI-E5180-E406:72\n'
)

WIFI_LIST_UGV = 'yes:UGV:58\n'

# So antwortet nmcli auf dem Fahrzeug: die Oberflaeche dort ist deutsch.
WIFI_LIST_GERMAN = 'ja:HUAWEI-E5180-E406:94\n'


def network_config(**overrides):
    config = dict(
        enabled=True,
        interface='wlan0',
        preferred_profile='HUAWEI',
        fallback_profile='UGV',
        poll_interval_s=10.0,
        command_timeout_s=10.0,
        switch_timeout_s=45.0,
        fallback_unit='ugv-netz-rueckfall',
        fallback_delay_min=10,
    )
    config.update(overrides)
    return SimpleNamespace(**config)


class FakeNmcli:
    """Spielt nmcli/systemctl und merkt sich, was aufgerufen wurde."""

    def __init__(self, device=DEVICE_ON_HUAWEI, wifi=WIFI_LIST_HUAWEI, switch_result=0):
        self.device = device
        self.wifi = wifi
        self.switch_result = switch_result
        self.calls = []
        # Womit das Geraet nach einem erfolgreichen Wechsel antwortet.
        self.device_after_switch = None
        self.wifi_after_switch = None

    def __call__(self, args, timeout):
        self.calls.append(list(args))
        if args[:2] == ['nmcli', '-t'] and 'device' in args and 'show' in args:
            return 0, self.device, ''
        if args[:2] == ['nmcli', '-t'] and 'wifi' in args:
            return 0, self.wifi, ''
        if args[:3] == ['nmcli', 'connection', 'up']:
            if self.switch_result == 0:
                if self.device_after_switch is not None:
                    self.device = self.device_after_switch
                if self.wifi_after_switch is not None:
                    self.wifi = self.wifi_after_switch
                return 0, 'Verbindung aktiviert\n', ''
            return self.switch_result, '', 'Error: unknown connection\n'
        if args[0] == 'systemd-run':
            return 0, '', ''
        if args[0] == 'systemctl':
            return 0, '', ''
        raise AssertionError(f'Unerwarteter Aufruf: {args}')

    def commands(self, program):
        return [call for call in self.calls if call[0] == program]


class TerseParsingTests(unittest.TestCase):
    def test_a_colon_in_the_value_stays_in_the_value(self):
        self.assertEqual(
            split_terse(r'GENERAL.HWADDR:B8\:27\:EB\:11\:22\:33'),
            ['GENERAL.HWADDR', 'B8:27:EB:11:22:33'],
        )


class ReadingTheCurrentNetworkTests(unittest.TestCase):
    def test_the_preferred_network_is_reported_as_such(self):
        monitor = NetworkMonitor(network_config(), runner=FakeNmcli())

        status = monitor.refresh()

        self.assertEqual(status['profile'], 'HUAWEI')
        self.assertEqual(status['ssid'], 'HUAWEI-E5180-E406')
        self.assertEqual(status['ipv4'], '192.168.8.102')
        self.assertEqual(status['signal_percent'], 72)
        self.assertTrue(status['on_preferred'])

    def test_the_old_network_is_flagged(self):
        monitor = NetworkMonitor(
            network_config(),
            runner=FakeNmcli(device=DEVICE_ON_UGV, wifi=WIFI_LIST_UGV),
        )

        status = monitor.refresh()

        self.assertEqual(status['profile'], 'UGV')
        self.assertFalse(status['on_preferred'])

    def test_the_display_never_triggers_a_scan(self):
        # Ein Suchlauf legt die Verbindung kurz lahm. Eine Anzeige darf das
        # nicht ausloesen, sonst reisst das Hinsehen die Fahrt ab.
        runner = FakeNmcli()
        NetworkMonitor(network_config(), runner=runner).refresh()

        wifi_call = [call for call in runner.calls if 'wifi' in call][0]
        self.assertIn('--rescan', wifi_call)
        self.assertEqual(wifi_call[wifi_call.index('--rescan') + 1], 'no')

    def test_a_german_nmcli_is_understood_too(self):
        # Auf dem Fahrzeug antwortet nmcli deutsch: In der Spalte ACTIVE steht
        # "ja". Wird das nicht erkannt, bleibt der Netzname leer und die
        # Statusleiste zeigt wieder nichts.
        monitor = NetworkMonitor(
            network_config(),
            runner=FakeNmcli(wifi=WIFI_LIST_GERMAN),
        )

        status = monitor.refresh()

        self.assertEqual(status['ssid'], 'HUAWEI-E5180-E406')
        self.assertEqual(status['signal_percent'], 94)

    def test_a_broken_nmcli_shows_up_instead_of_a_wrong_network(self):
        def failing(args, timeout):
            return 127, '', 'nmcli nicht gefunden'

        monitor = NetworkMonitor(network_config(), runner=failing)

        status = monitor.refresh()

        self.assertIsNone(status['profile'])
        self.assertFalse(status['on_preferred'])
        self.assertIn('nicht gefunden', status['error'])


class SwitchingBackTests(unittest.TestCase):
    def _run_switch(self, monitor):
        monitor.switch_to_preferred()
        monitor._switch_thread.join(timeout=5)

    def test_a_successful_switch_disarms_the_fallback(self):
        runner = FakeNmcli(device=DEVICE_ON_UGV, wifi=WIFI_LIST_UGV)
        runner.device_after_switch = DEVICE_ON_HUAWEI
        runner.wifi_after_switch = WIFI_LIST_HUAWEI
        monitor = NetworkMonitor(network_config(), runner=runner)

        self._run_switch(monitor)

        status = monitor.get_status()
        self.assertTrue(status['on_preferred'])
        self.assertFalse(status['switching'])
        self.assertTrue(status['last_switch']['success'])
        self.assertFalse(status['last_switch']['fallback_armed'])
        # Der Rueckfall stand vor dem Wechsel bereit und wurde danach entschaerft.
        self.assertTrue(runner.commands('systemd-run'))
        self.assertTrue(runner.commands('systemctl'))

    def test_the_fallback_is_armed_before_the_switch_is_attempted(self):
        runner = FakeNmcli(device=DEVICE_ON_UGV, wifi=WIFI_LIST_UGV)
        runner.device_after_switch = DEVICE_ON_HUAWEI
        runner.wifi_after_switch = WIFI_LIST_HUAWEI
        monitor = NetworkMonitor(network_config(), runner=runner)

        self._run_switch(monitor)

        programme = [call[0] for call in runner.calls]
        arm = programme.index('systemd-run')
        wechsel = next(
            index for index, call in enumerate(runner.calls)
            if call[:3] == ['nmcli', 'connection', 'up']
        )
        self.assertLess(arm, wechsel)

    def test_a_failed_switch_leaves_the_fallback_armed(self):
        runner = FakeNmcli(device=DEVICE_ON_UGV, wifi=WIFI_LIST_UGV, switch_result=4)
        monitor = NetworkMonitor(network_config(), runner=runner)

        self._run_switch(monitor)

        status = monitor.get_status()
        self.assertFalse(status['on_preferred'])
        self.assertFalse(status['last_switch']['success'])
        self.assertTrue(status['last_switch']['fallback_armed'])
        self.assertIn('unknown connection', status['last_switch']['error'])

    def test_a_switch_that_silently_stays_put_counts_as_failure(self):
        # nmcli meldet Erfolg, das Fahrzeug haengt aber weiter im alten Netz -
        # genau die Sorte Wechsel, die am 27.08. niemand bemerkt hat.
        runner = FakeNmcli(device=DEVICE_ON_UGV, wifi=WIFI_LIST_UGV)
        monitor = NetworkMonitor(network_config(), runner=runner)

        self._run_switch(monitor)

        status = monitor.get_status()
        self.assertFalse(status['last_switch']['success'])
        self.assertTrue(status['last_switch']['fallback_armed'])

    def test_a_second_nudge_while_switching_is_refused(self):
        monitor = NetworkMonitor(network_config(), runner=FakeNmcli())
        monitor._switching = True

        result = monitor.switch_to_preferred()

        self.assertFalse(result['success'])
        self.assertIn('laeuft bereits', result['error'])


if __name__ == '__main__':
    unittest.main()
