import threading
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import motor_controller.hardware.odrive_mower as odrive_module
from motor_controller.hardware.odrive_mower import (
    CMD_GET_IQ,
    CMD_GET_SENSORLESS_ESTIMATES,
    CMD_SET_AXIS_STATE,
    CMD_SET_LIMITS,
    ODriveMowerController,
)
from motor_controller.hardware.safety_monitor import SafetyMonitor


@dataclass
class FakeODriveConfig:
    enabled: bool = True
    node_id: int = 0
    node_ids: list[int] = field(default_factory=lambda: [0, 1, 2])
    axis_state: int = 5
    min_rpm: int = 500
    max_rpm: int = 5000
    default_rpm: int = 500
    ramp_rate_rpm_s: int = 300
    command_interval_s: float = 0.1
    start_stagger_s: float = 0.0
    sequential_start_enabled: bool = True
    startup_timeout_s: float = 0.5
    startup_retries: int = 0
    startup_current_limit_a: float = 12.0
    startup_abort_current_a: float = 12.5
    startup_min_sensorless_rpm: float = 120.0
    startup_stable_duration_s: float = 0.05
    operating_current_limit_a: float = 30.0
    heartbeat_timeout_s: float = 1.0
    current_monitor_enabled: bool = True
    current_poll_interval_s: float = 0.1
    current_poll_while_idle: bool = False
    current_response_timeout_s: float = 2.0
    current_startup_grace_s: float = 2.0
    current_trip_a: float = 25.0
    current_trip_duration_s: float = 0.5
    current_critical_trip_a: float = 29.0
    current_critical_trip_duration_s: float = 0.1


@dataclass
class FakeSafetyConfig:
    pin: int = 17
    enabled: bool = False
    debounce_time: float = 0.2
    command_timeout: float = 100.0
    joystick_timeout: float = 100.0
    link_watchdog_enabled: bool = False
    link_watchdog_startup_grace_s: float = 0.0
    link_watchdog_interval_s: float = 0.02


class RecordingMower(ODriveMowerController):
    """Schreibt jeden abgesetzten Befehl mit, statt ihn zu uebertragen.

    Die Basisklasse kennt keinen Transport mehr; welche Achse welchen Befehl
    in welcher Reihenfolge bekommt, ist aber genau das, was die Ablauf- und
    Sicherheitslogik hier ausmacht.
    """

    def __init__(self, config):
        super().__init__(config)
        self.commands = []
        self.hook = None

    def _send(self, node_id, command_id, data=b""):
        self._record(int(node_id), int(command_id), bytes(data), False)

    def _send_rtr(self, node_id, command_id, dlc=8):
        self._record(int(node_id), int(command_id), b"", True)

    def _record(self, node_id, command_id, data, rtr):
        self.commands.append({
            'node_id': node_id,
            'command_id': command_id,
            'data': data,
            'rtr': rtr,
        })
        if self.hook:
            self.hook(node_id, command_id)


class ODriveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.controller = RecordingMower(FakeODriveConfig())

    def test_current_poll_asks_every_axis_once(self):
        self.controller._poll_currents()

        self.assertEqual(
            [(befehl['node_id'], befehl['command_id']) for befehl in self.controller.commands],
            [(0, CMD_GET_IQ), (1, CMD_GET_IQ), (2, CMD_GET_IQ)],
        )
        self.assertTrue(all(befehl['rtr'] for befehl in self.controller.commands))

    def test_runtime_current_polling_round_robins_nodes(self):
        polled = [self.controller._poll_next_current() for _ in range(5)]

        self.assertEqual(polled, [0, 1, 2, 0, 1])
        self.assertEqual(
            [befehl['node_id'] for befehl in self.controller.commands],
            [0, 1, 2, 0, 1],
        )

    def test_idle_monitor_does_not_poll_without_hardware_watchdog(self):
        self.controller.start_monitor()
        time.sleep(0.25)
        self.controller.stop_monitor()

        self.assertEqual(self.controller.commands, [])

    def test_startup_poll_requests_current_and_sensorless_estimate(self):
        self.controller._poll_node_startup(1)

        self.assertEqual(
            [(befehl['node_id'], befehl['command_id']) for befehl in self.controller.commands],
            [(1, CMD_GET_IQ), (1, CMD_GET_SENSORLESS_ESTIMATES)],
        )
        self.assertTrue(all(befehl['rtr'] for befehl in self.controller.commands))

    def test_sensorless_callback_records_rpm(self):
        self.controller.on_sensorless_estimates(0, 1.25, 10.0)

        sample = self.controller.odrive_sensorless[0]
        self.assertEqual(sample['position'], 1.25)
        self.assertEqual(sample['velocity'], 10.0)
        self.assertEqual(sample['rpm'], 600.0)
        self.assertGreater(sample['last_seen'], 0.0)

    def test_validated_start_uses_temporary_current_limit(self):
        self.controller.node_ids = [0]
        self.controller.running = True
        injected = threading.Event()

        def inject_measurements():
            while not self.controller.startup_status['active']:
                time.sleep(0.005)
            time.sleep(0.03)
            deadline = time.monotonic() + 0.25
            while time.monotonic() < deadline:
                self.controller.on_heartbeat(0, 0, 5)
                self.controller.on_iq(0, 5.0, 5.0)
                self.controller.on_sensorless_estimates(0, 0.0, 10.0)
                injected.set()
                time.sleep(0.01)

        worker = threading.Thread(target=inject_measurements, daemon=True)
        worker.start()
        success, error = self.controller._start_node_with_validation(0, [], 500)

        self.assertTrue(injected.is_set())
        self.assertTrue(success)
        self.assertIsNone(error)
        limits = [
            befehl for befehl in self.controller.commands
            if befehl['command_id'] == CMD_SET_LIMITS
        ]
        self.assertEqual(len(limits), 2)
        self.assertEqual(
            [round(odrive_module.struct.unpack('<ff', befehl['data'])[1], 1) for befehl in limits],
            [12.0, 30.0],
        )

    def test_startup_aborts_on_first_excessive_current_sample(self):
        self.controller.node_ids = [0]
        self.controller.running = True

        def inject_overcurrent():
            while not self.controller.startup_status['active']:
                time.sleep(0.005)
            time.sleep(0.03)
            self.controller.on_heartbeat(0, 0, 5)
            self.controller.on_iq(0, 20.0, 20.0)

        threading.Thread(target=inject_overcurrent, daemon=True).start()
        success, error = self.controller._start_node_with_validation(0, [], 500)

        self.assertFalse(success)
        self.assertIn('20.0 A', error)

    def test_sustained_high_current_requests_system_stop(self):
        stopped = threading.Event()
        reasons = []
        self.controller.set_system_stop_callback(
            lambda reason: (reasons.append(reason), stopped.set())
        )
        self.controller.running = True
        self.controller._run_started_monotonic = time.monotonic() - 10.0

        self.controller.on_iq(1, 26.0, 26.0)
        self.controller._overcurrent_since[1] = time.monotonic() - 0.6
        self.controller.on_iq(1, 26.0, 26.0)

        self.assertTrue(stopped.wait(1.0))
        self.assertFalse(self.controller.running)
        self.assertIn("node=1", reasons[0])
        self.assertIn("26.0 A", reasons[0])

    def test_short_current_spike_does_not_trip(self):
        stopped = threading.Event()
        self.controller.set_system_stop_callback(lambda _reason: stopped.set())
        self.controller.running = True
        self.controller._run_started_monotonic = time.monotonic() - 10.0

        self.controller.on_iq(0, 26.0, 26.0)
        self.controller.on_iq(0, 5.0, 5.0)

        self.assertFalse(stopped.wait(0.05))
        self.assertTrue(self.controller.running)

    def test_missing_current_response_is_fail_safe_after_grace(self):
        self.controller.running = True
        now = time.monotonic()
        self.controller._run_started_monotonic = now - 3.0
        for node_id in (0, 1):
            self.controller.odrive_iq[node_id]['last_seen'] = now

        error = self.controller._check_current_response_timeout(now)

        self.assertEqual(error, "ODrive GET_IQ timeout: nodes [2]")

    def test_status_reports_active_heartbeat_after_command_thread_stopped(self):
        self.controller.running = False
        self.controller.odrive_states[0] = self.controller.config.axis_state

        status = self.controller.get_status()

        self.assertTrue(status['running'])
        self.assertFalse(status['command_running'])
        self.assertEqual(status['active_axis_nodes'], [0])

    def test_emergency_stop_retries_until_heartbeats_confirm_idle(self):
        self.controller.running = True
        self.controller.odrive_states = {0: 5, 1: 5, 2: 5}
        idle_requests = {0: 0, 1: 0, 2: 0}

        def confirm_on_retry(node_id, command_id):
            if command_id != CMD_SET_AXIS_STATE:
                return
            idle_requests[node_id] += 1
            if idle_requests[node_id] >= 2:
                self.controller.on_heartbeat(node_id, 0, 1)

        self.controller.hook = confirm_on_retry
        status = self.controller.emergency_stop('test')

        self.assertTrue(status['success'])
        self.assertFalse(status['running'])
        self.assertEqual(status['active_axis_nodes'], [])
        self.assertEqual(idle_requests, {0: 2, 1: 2, 2: 2})


class SafetyLatchTests(unittest.TestCase):
    def setUp(self):
        self.monitor = SafetyMonitor(FakeSafetyConfig(), SimpleNamespace())

    def tearDown(self):
        self.monitor.cleanup()

    def test_system_stop_latches_until_healthy_manual_reset(self):
        reasons = []
        self.monitor.set_system_stop_callback(reasons.append)
        self.monitor.trigger_system_stop("CAN verloren")

        self.assertFalse(self.monitor.is_motion_allowed())
        self.assertEqual(reasons, ["CAN verloren"])

        self.monitor.set_link_health_check(lambda: (False, "Node 2 fehlt"))
        success, error = self.monitor.reset_system_stop()
        self.assertFalse(success)
        self.assertEqual(error, "Node 2 fehlt")

        self.monitor.set_link_health_check(lambda: (True, None))
        success, error = self.monitor.reset_system_stop()
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertTrue(self.monitor.is_motion_allowed())

    def test_command_timeout_only_runs_while_navigation_commands_are_active(self):
        self.monitor.last_command_time = time.time() - 100.0
        self.assertFalse(self.monitor.check_command_timeout())

        self.monitor.update_command_time()
        self.monitor.last_command_time = time.time() - 100.0
        self.assertTrue(self.monitor.check_command_timeout())

        self.monitor.deactivate_command_watchdog()
        self.assertFalse(self.monitor.check_command_timeout())

    def test_motion_hold_stops_driving_without_latching_and_clears(self):
        pauses = []
        resumes = []
        self.monitor.set_motion_hold_callback(pauses.append)
        self.monitor.set_motion_resume_callback(lambda: resumes.append(True))

        self.monitor.trigger_motion_hold("SensorHub WIFI kurzzeitig unterbrochen")
        self.monitor.trigger_motion_hold("wird nicht doppelt ausgeloest")

        status = self.monitor.get_status()
        self.assertEqual(pauses, ["SensorHub WIFI kurzzeitig unterbrochen"])
        self.assertTrue(status['motion_hold_active'])
        self.assertFalse(status['system_stop_latched'])
        self.assertFalse(self.monitor.is_motion_allowed())

        self.monitor.clear_motion_hold()

        self.assertFalse(self.monitor.get_status()['motion_hold_active'])
        self.assertTrue(self.monitor.is_motion_allowed())
        self.assertEqual(resumes, [True])

    def test_motion_hold_does_not_prevent_escalation_to_full_stop(self):
        full_stops = []
        resumes = []
        self.monitor.set_motion_hold_callback(lambda _reason: None)
        self.monitor.set_motion_resume_callback(lambda: resumes.append(True))
        self.monitor.set_system_stop_callback(full_stops.append)
        self.monitor.trigger_motion_hold("kurze Luecke")

        self.monitor.trigger_system_stop("SensorHub WIFI-Timeout")

        self.assertEqual(full_stops, ["SensorHub WIFI-Timeout"])
        self.assertTrue(self.monitor.get_status()['system_stop_latched'])
        self.assertFalse(self.monitor.is_motion_allowed())

        self.monitor.clear_motion_hold()
        self.assertEqual(resumes, [])

if __name__ == "__main__":
    unittest.main()
