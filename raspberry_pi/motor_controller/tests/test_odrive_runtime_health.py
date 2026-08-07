"""Laufzeitueberwachung des Maehdecks ausserhalb des Kommando-Threads.

Hintergrund: ein synchroner USB/Fibre-Aufruf blockiert den aufrufenden Thread
ohne Timeout. Jede Pruefung, die *innerhalb* des Kommando-Threads lebt, faellt
mit ihm aus. ``runtime_health`` arbeitet deshalb ausschliesslich auf
gespeicherten Werten und wird vom zentralen Safety-Watchdog gerufen.
"""

import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.hardware.odrive_mower import ODriveMowerController


@dataclass
class HealthConfig:
    enabled: bool = True
    node_id: int = 0
    node_ids: list[int] = field(default_factory=lambda: [0, 1, 2])
    axis_state: int = 5
    min_rpm: int = 500
    max_rpm: int = 5000
    default_rpm: int = 500
    ramp_rate_rpm_s: int = 300
    command_interval_s: float = 0.1
    heartbeat_timeout_s: float = 1.0
    current_startup_grace_s: float = 2.0
    command_loop_timeout_s: float = 2.0
    runtime_rpm_monitor_enabled: bool = True
    runtime_sensorless_poll_interval_s: float = 0.5
    runtime_sensorless_timeout_s: float = 3.0
    runtime_min_rpm: float = 150.0
    runtime_rpm_fault_duration_s: float = 1.5


class RuntimeHealthTests(unittest.TestCase):
    def setUp(self):
        self.controller = ODriveMowerController(HealthConfig(), can_handler=None)

    def _mark_running(self, *, rpm=3000.0, run_age_s=10.0):
        """Versetzt den Controller in einen gesunden Laufzustand."""
        now = time.monotonic()
        controller = self.controller
        controller.running = True
        controller.commanded_rpm = 3000
        controller._run_started_monotonic = now - run_age_s
        controller._loop_alive_monotonic = now
        controller._command_loop_expected = True
        for node_id in controller.node_ids:
            controller.odrive_last_seen[node_id] = now
            controller.odrive_states[node_id] = 5
            controller.odrive_errors[node_id] = 0
            controller.odrive_sensorless[node_id] = {
                'position': 0.0,
                'velocity': rpm / 60.0,
                'rpm': rpm,
                'last_seen': now,
            }

    def test_healthy_run_passes(self):
        self._mark_running()

        self.assertEqual(self.controller.runtime_health(), (True, None))

    def test_idle_deck_is_healthy(self):
        # Im Stillstand werden die ODrives fuer den Fahrantrieb nicht gebraucht;
        # ein Transportproblem darf das manuelle Rangieren nicht verriegeln.
        self.controller.odrive_last_seen = {
            node_id: 0.0 for node_id in self.controller.node_ids
        }

        self.assertEqual(self.controller.runtime_health(), (True, None))

    def test_startup_owns_its_own_validation(self):
        self._mark_running()
        self.controller.startup_status['active'] = True
        self.controller._loop_alive_monotonic = time.monotonic() - 30.0

        self.assertEqual(self.controller.runtime_health(), (True, None))

    def test_frozen_command_loop_stops_the_vehicle(self):
        """Der eigentliche Ausfall: der Kommando-Thread haengt im Transport."""
        self._mark_running()
        self.controller._loop_alive_monotonic = time.monotonic() - 5.0

        healthy, reason = self.controller.runtime_health()

        self.assertFalse(healthy)
        self.assertIn('Kommandoschleife', reason)

    def test_failed_start_keeps_its_own_reason(self):
        """Ein gescheiterter Start darf nicht ueberschrieben werden.

        Real 07.08.: node 0 kam wegen blockiertem Messer nicht hoch. Waehrend
        seiner Validierung veralten die beiden anderen Achsen zwangslaeufig -
        im Abbruchfenster meldete die Laufzeitpruefung dann ausgerechnet die
        beiden intakten Motoren ("nodes [1, 2]") statt des echten Grundes.
        """
        self._mark_running()
        # Zustand nach dem Fehlschlag: Startvorgang abgemeldet, Kommando-Thread
        # nie gestartet, uebrige Achsen seit Sekunden nicht abgefragt.
        self.controller._command_loop_expected = False
        self.controller.startup_status['active'] = False
        self.controller.startup_status['last_result'] = 'failed'
        stale = time.monotonic() - 30.0
        self.controller.odrive_last_seen[1] = stale
        self.controller.odrive_last_seen[2] = stale

        self.assertEqual(self.controller.runtime_health(), (True, None))

    def test_sequential_start_is_no_missing_sign_of_life(self):
        """Der Anlauf dauert Sekunden - das ist kein toter Kommando-Thread.

        Zustand direkt nach der Achsvalidierung: das Deck gilt als laufend, der
        Kommando-Thread existiert aber noch nicht, und der zuerst validierte
        Node wurde seit Sekunden nicht mehr abgefragt.
        """
        self._mark_running()
        self.controller._command_loop_expected = False
        self.controller.startup_status.update({'active': True, 'phase': 'finalize'})
        self.controller._loop_alive_monotonic = time.monotonic() - 8.0
        self.controller.odrive_last_seen[0] = time.monotonic() - 8.0

        self.assertEqual(self.controller.runtime_health(), (True, None))

    def test_successful_sequential_start_stays_marked_as_starting(self):
        """Erst der laufende Kommando-Thread beendet den Start."""
        self.controller._start_node_with_validation = (
            lambda node_id, already_running, rpm: (True, None)
        )
        self.controller._set_axis_state = lambda *args, **kwargs: None
        self.controller._send_all = lambda *args, **kwargs: None

        success, error = self.controller._start_sequentially(3000)

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertTrue(self.controller.startup_status['active'])
        self.assertEqual(self.controller.startup_status['phase'], 'finalize')
        self.assertIsNotNone(self.controller.startup_status['node_started_monotonic'])

    def test_failed_sequential_start_is_not_marked_as_starting(self):
        self.controller._start_node_with_validation = (
            lambda node_id, already_running, rpm: (False, 'Anlauf fehlgeschlagen')
        )
        self.controller._set_axis_state = lambda *args, **kwargs: None
        self.controller._send_all = lambda *args, **kwargs: None
        self.controller._set_node_axis_state = lambda *args, **kwargs: None
        self.controller._set_node_limits = lambda *args, **kwargs: None

        success, error = self.controller._start_sequentially(3000)

        self.assertFalse(success)
        self.assertEqual(error, 'Anlauf fehlgeschlagen')
        self.assertFalse(self.controller.startup_status['active'])
        self.assertEqual(self.controller.startup_status['last_result'], 'failed')

    def test_stopping_clears_the_command_loop_expectation(self):
        self._mark_running()
        self.controller._send = lambda *args, **kwargs: None
        self.controller.odrive_states = {node_id: 1 for node_id in self.controller.node_ids}

        self.controller.stop()

        self.assertFalse(self.controller._command_loop_expected)
        self.assertEqual(self.controller.runtime_health(), (True, None))

    def test_stale_status_stops_the_vehicle(self):
        self._mark_running()
        self.controller.odrive_last_seen[2] = time.monotonic() - 30.0

        healthy, reason = self.controller.runtime_health()

        self.assertFalse(healthy)
        self.assertIn('[2]', reason)

    def test_odrive_error_during_run_stops_the_vehicle(self):
        self._mark_running()
        self.controller.odrive_errors[1] = 0x800

        healthy, reason = self.controller.runtime_health()

        self.assertFalse(healthy)
        self.assertIn('0x00000800', reason)

    def test_axis_dropping_out_of_closed_loop_stops_the_vehicle(self):
        """Ein entwaffneter Achszustand meldet keinen Fehler - nur IDLE."""
        self._mark_running()
        self.controller.odrive_states[0] = 1

        healthy, reason = self.controller.runtime_health()

        self.assertFalse(healthy)
        self.assertIn('nodes [0]', reason)

    def test_standing_blade_stops_the_vehicle(self):
        self._mark_running(rpm=5.0)

        healthy, reason = self.controller.runtime_health()
        self.assertTrue(healthy, 'kurzer Drehzahleinbruch darf nicht sofort stoppen')

        self.controller._low_rpm_since = {
            node_id: time.monotonic() - 2.0 for node_id in self.controller.node_ids
        }
        healthy, reason = self.controller.runtime_health()

        self.assertFalse(healthy)
        self.assertIn('dreht nicht', reason)

    def test_blade_fault_names_the_current_that_tells_the_cause_apart(self):
        """Blockiert oder abgerissen - das entscheidet der Strom, nicht die Drehzahl.

        Real 07.08.: node 0 stand bei 31 rpm und zog dabei 24.3 A bei einem
        Sollstrom von 30 A. Ohne diese Zahl in der Meldung ist von aussen
        nicht zu unterscheiden, ob das Messer blockiert oder der Antrieb weg
        ist.
        """
        self._mark_running(rpm=31.0)
        now = time.monotonic()
        self.controller.odrive_iq[0] = {
            'setpoint_a': 29.99,
            'measured_a': 24.26,
            'last_seen': now,
        }
        self.controller._low_rpm_since = {
            node_id: now - 2.0 for node_id in self.controller.node_ids
        }

        healthy, reason = self.controller.runtime_health()

        self.assertFalse(healthy)
        self.assertIn('node=0', reason)
        self.assertIn('24.3 A', reason)
        self.assertIn('30.0 A', reason)

    def test_recovering_rpm_clears_the_pending_fault(self):
        self._mark_running(rpm=5.0)
        self.controller.runtime_health()
        self.assertIsNotNone(self.controller._low_rpm_since[0])

        self._mark_running(rpm=3000.0)

        self.assertEqual(self.controller.runtime_health(), (True, None))
        self.assertIsNone(self.controller._low_rpm_since[0])

    def test_stale_rpm_sample_gives_no_verdict(self):
        """Eine unbeantwortete Drehzahlabfrage ist kein stehendes Messer."""
        self._mark_running(rpm=5.0)
        stale = time.monotonic() - 30.0
        for node_id in self.controller.node_ids:
            self.controller.odrive_sensorless[node_id]['last_seen'] = stale
        self.controller._low_rpm_since = {
            node_id: time.monotonic() - 5.0 for node_id in self.controller.node_ids
        }

        self.assertEqual(self.controller.runtime_health(), (True, None))

    def test_rpm_check_respects_startup_grace(self):
        self._mark_running(rpm=5.0, run_age_s=0.5)
        self.controller._low_rpm_since = {
            node_id: time.monotonic() - 5.0 for node_id in self.controller.node_ids
        }

        self.assertEqual(self.controller.runtime_health(), (True, None))

    def test_transport_stall_stops_the_vehicle(self):
        self._mark_running()
        self.controller.transport_stall_reason = lambda: 'USB-Aufruf ohne Antwort seit 4.0s'

        healthy, reason = self.controller.runtime_health()

        self.assertFalse(healthy)
        self.assertIn('USB-Aufruf ohne Antwort', reason)

    def test_status_exposes_command_loop_age(self):
        self._mark_running()
        self.controller._loop_alive_monotonic = time.monotonic() - 1.0

        status = self.controller.get_status()

        self.assertGreaterEqual(status['command_loop_age_s'], 1.0)
        self.assertIsNone(status['transport_stall'])

    def test_status_contract_used_by_the_safety_watchdog(self):
        """Sichert genau die Schluessel, deren Vertipper den Watchdog blendete."""
        status = self.controller.get_status()

        for key in (
            'command_running',
            'startup_status',
            'odrive_missing_heartbeats',
            'odrive_errors',
            'command_loop_age_s',
            'transport_stall',
        ):
            self.assertIn(key, status)


if __name__ == '__main__':
    unittest.main()
