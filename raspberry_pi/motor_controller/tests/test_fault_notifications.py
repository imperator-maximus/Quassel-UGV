"""Welche Zustaende eine Push-Meldung ausloesen - und welche nicht.

Ein Fehlerzustand faerbt die Oberflaeche rot, aber niemand sieht hin, waehrend
das Fahrzeug im Garten steht. Gemeldet wird deshalb die Flanke: der Uebergang
in einen Zustand, in dem die Fahrt ungewollt endet. Ein bewusst pausierter oder
fertiger Plan ist keine Stoerung, und derselbe Fehler darf nicht im Sekundentakt
wiederholt werden - ``_set_plan_status`` laeuft waehrend des RTK-Wartens einmal
pro Sekunde durch.
"""

import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.hardware.safety_monitor import SafetyMonitor
from motor_controller.web.web_server import WebServer


class FakeNotifier:
    """Nimmt Meldungen entgegen, statt sie zu senden."""

    def __init__(self):
        self.config = SimpleNamespace(motion_hold_after_s=0.05)
        self.faults = []
        self.recoveries = []
        self.infos = []

    def fault(self, event, title, message):
        self.faults.append((event, title, message))
        return True

    def recovery(self, event, title, message):
        self.recoveries.append((event, title, message))
        return True

    def info(self, event, title, message):
        self.infos.append((event, title, message))
        return True


def build_server(notifier):
    config = SimpleNamespace(template_folder='.', static_folder='.', secret_key='test')
    dummy = SimpleNamespace()
    server = WebServer(config, dummy, dummy, dummy, dummy, notifier=notifier)
    server.navigation = None
    server.mapping = None
    # Kein Wiederaufsetzpunkt auf der Platte soll den Test beeinflussen.
    server._stop_reason_restored = True
    return server


class PlanFaultNotificationTests(unittest.TestCase):
    def setUp(self):
        self.notifier = FakeNotifier()
        self.server = build_server(self.notifier)
        self.server._set_plan_status(running=True, state='running', total=3)
        self.notifier.recoveries.clear()

    def test_mower_fault_is_reported_with_its_reason(self):
        self.server._set_plan_status(
            running=False, state='mower_fault', last_error='Messer stehen still'
        )
        self.assertEqual(len(self.notifier.faults), 1)
        event, title, message = self.notifier.faults[0]
        self.assertEqual(event, 'plan')
        self.assertIn('Mähdeck', title)
        self.assertEqual(message, 'Messer stehen still')

    def test_every_stopping_fault_state_is_reported(self):
        for state in (
            'error', 'mower_fault', 'nogo_stop', 'rtk_lost', 'geofence',
            'divergence_stop', 'cross_track_stop', 'heading_block',
            'align_stall', 'track_stall', 'watchdog',
        ):
            with self.subTest(state=state):
                notifier = FakeNotifier()
                server = build_server(notifier)
                server._set_plan_status(running=True, state='running')
                server._set_plan_status(running=False, state=state, last_error='Grund')
                self.assertEqual(len(notifier.faults), 1)

    def test_unknown_fault_state_is_still_reported(self):
        """Ein spaeter hinzugekommener Fehlerzustand darf nicht durchrutschen."""
        self.server._set_plan_status(running=False, state='ganz_neuer_fehler')
        self.assertEqual(len(self.notifier.faults), 1)
        self.assertIn('ganz_neuer_fehler', self.notifier.faults[0][1])

    def test_fault_is_reported_even_if_running_stays_set(self):
        """Gemeldet wird der Zustand, nicht das running-Flag.

        Ein kuenftiger Fehlerzustand, der das Flag stehen laesst, waere sonst
        stumm - genau die Sorte Luecke, die eine Ausschlussliste vermeiden soll.
        """
        self.server._set_plan_status(running=True, state='neuer_fehler_im_lauf')
        self.assertEqual(len(self.notifier.faults), 1)

    def test_fault_before_the_plan_ever_ran_is_reported(self):
        notifier = FakeNotifier()
        server = build_server(notifier)  # bleibt auf 'idle'
        server._set_plan_status(running=False, state='error', last_error='Startfehler')
        self.assertEqual(len(notifier.faults), 1)
        self.assertEqual(notifier.faults[0][2], 'Startfehler')

    def test_deliberate_and_working_states_stay_quiet(self):
        """Die Ausschlussliste vollstaendig: nur diese Zustaende sind still."""
        for state in WebServer.QUIET_PLAN_STATES:
            with self.subTest(state=state):
                notifier = FakeNotifier()
                server = build_server(notifier)
                server._set_plan_status(running=True, state='running')
                server._set_plan_status(running=False, state=state)
                self.assertEqual(notifier.faults, [])

    def test_safety_stop_is_left_to_the_safety_monitor(self):
        """Sonst gibt es zwei Toene fuer denselben Vorgang."""
        self.server._set_plan_status(running=False, state='safety_stop')
        self.assertEqual(self.notifier.faults, [])

    def test_rtk_countdown_does_not_repeat_the_message(self):
        """rtk_wait aktualisiert sekuendlich denselben Zustand."""
        for remaining in (90, 89, 88):
            self.server._set_plan_status(
                running=True, state='rtk_wait',
                last_error=f'RTK verloren - noch {remaining}s',
            )
        self.assertEqual(self.notifier.faults, [])

        self.server._set_plan_status(
            running=False, state='rtk_lost', last_error='RTK zu lange weg'
        )
        self.assertEqual(len(self.notifier.faults), 1)

    def test_repeated_fault_state_is_reported_once(self):
        self.server._set_plan_status(running=False, state='track_stall', last_error='a')
        self.server._set_plan_status(running=False, state='track_stall', last_error='b')
        self.assertEqual(len(self.notifier.faults), 1)

    def test_resumed_plan_sends_an_all_clear(self):
        self.server._set_plan_status(running=False, state='rtk_lost', last_error='weg')
        self.server._set_plan_status(running=True, state='running')
        self.assertEqual(len(self.notifier.recoveries), 1)
        self.assertEqual(self.notifier.recoveries[0][0], 'plan')

    def test_completed_plan_sends_an_all_clear(self):
        self.server._set_plan_status(running=False, state='completed')
        self.assertEqual(len(self.notifier.recoveries), 1)

    def test_safety_pause_of_a_running_plan_is_not_double_reported(self):
        self.server.pause_plan_execution(reason='safety_stop')
        self.assertEqual(self.notifier.faults, [])

    def test_a_failing_notifier_never_breaks_the_plan_status(self):
        class BrokenNotifier(FakeNotifier):
            def fault(self, event, title, message):
                raise RuntimeError('kaputt')

        server = build_server(BrokenNotifier())
        server._set_plan_status(running=True, state='running')
        server._set_plan_status(running=False, state='error', last_error='Grund')
        self.assertEqual(server.get_plan_execution_status()['state'], 'error')

    def test_without_a_notifier_nothing_happens(self):
        server = build_server(None)
        server._set_plan_status(running=True, state='running')
        server._set_plan_status(running=False, state='error', last_error='Grund')
        self.assertEqual(server.get_plan_execution_status()['state'], 'error')


class SafetyMonitorNotificationTests(unittest.TestCase):
    def setUp(self):
        self.notifier = FakeNotifier()
        config = SimpleNamespace(
            pin=17, enabled=False, debounce_time=0.2,
            command_timeout=2.0, joystick_timeout=1.0,
            can_watchdog_enabled=False, can_watchdog_startup_grace_s=0.0,
            can_watchdog_interval_s=0.02,
        )
        self.safety = SafetyMonitor(config, SimpleNamespace())
        self.safety.set_notifier(self.notifier)

    def test_system_stop_is_reported_with_its_cause(self):
        self.safety.trigger_system_stop('ODrive Fehler: nodes [1]')
        self.assertEqual(len(self.notifier.faults), 1)
        event, title, message = self.notifier.faults[0]
        self.assertEqual(event, 'system_stop')
        self.assertEqual(message, 'ODrive Fehler: nodes [1]')

    def test_latched_system_stop_is_reported_only_once(self):
        self.safety.trigger_system_stop('erster Grund')
        self.safety.trigger_system_stop('zweiter Grund')
        self.assertEqual(len(self.notifier.faults), 1)

    def test_reset_sends_an_all_clear(self):
        self.safety.trigger_system_stop('Grund')
        ok, _ = self.safety.reset_system_stop()
        self.assertTrue(ok)
        self.assertEqual(len(self.notifier.recoveries), 1)

    def test_short_motion_hold_stays_quiet(self):
        """Eine kurze WLAN-Luecke pausiert staendig und loest sich von selbst."""
        self.safety.trigger_motion_hold('SensorHub kurz weg')
        self.safety._check_motion_hold_duration()
        self.assertEqual(self.notifier.faults, [])

    def test_persistent_motion_hold_is_reported_once(self):
        self.safety.trigger_motion_hold('SensorHub weg')
        time.sleep(0.08)  # laenger als motion_hold_after_s des FakeNotifier
        self.safety._check_motion_hold_duration()
        self.safety._check_motion_hold_duration()
        self.assertEqual(len(self.notifier.faults), 1)
        self.assertEqual(self.notifier.faults[0][0], 'motion_hold')

    def test_recovery_only_after_a_reported_hold(self):
        self.safety.trigger_motion_hold('SensorHub weg')
        self.safety.clear_motion_hold()
        self.assertEqual(self.notifier.recoveries, [])

        self.safety.trigger_motion_hold('SensorHub weg')
        time.sleep(0.08)
        self.safety._check_motion_hold_duration()
        self.safety.clear_motion_hold()
        self.assertEqual(len(self.notifier.recoveries), 1)

    def test_a_failing_notifier_never_breaks_the_safety_stop(self):
        class BrokenNotifier(FakeNotifier):
            def fault(self, event, title, message):
                raise RuntimeError('kaputt')

        self.safety.set_notifier(BrokenNotifier())
        self.safety.trigger_system_stop('Grund')
        self.assertTrue(self.safety.system_stop_latched)
        self.assertFalse(self.safety.is_motion_allowed())


if __name__ == '__main__':
    unittest.main()
