import threading
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import motor_controller.hardware.odrive_mower as odrive_module
from motor_controller.hardware.odrive_mower import CMD_GET_IQ, ODriveMowerController
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
    heartbeat_timeout_s: float = 1.0
    current_monitor_enabled: bool = True
    current_poll_interval_s: float = 0.1
    current_poll_while_idle: bool = False
    current_response_timeout_s: float = 0.75
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
    can_watchdog_enabled: bool = False
    can_watchdog_startup_grace_s: float = 0.0
    can_watchdog_interval_s: float = 0.02


class FakeMessage:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeBus:
    def __init__(self):
        self.messages = []

    def send(self, message, timeout=None):
        self.messages.append((message, timeout))


class ODriveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.controller = ODriveMowerController(
            FakeODriveConfig(),
            SimpleNamespace(can_bus=self.bus),
        )

    def test_get_iq_uses_classical_can_rtr_with_dlc_8(self):
        fake_can = SimpleNamespace(Message=FakeMessage)
        with patch.object(odrive_module, "CAN_AVAILABLE", True), patch.object(
            odrive_module, "can", fake_can, create=True
        ):
            self.controller._poll_currents()

        self.assertEqual(len(self.bus.messages), 3)
        ids = [entry[0].arbitration_id for entry in self.bus.messages]
        self.assertEqual(ids, [0x14, 0x34, 0x54])
        for message, _timeout in self.bus.messages:
            self.assertTrue(message.is_remote_frame)
            self.assertFalse(message.is_extended_id)
            self.assertEqual(message.dlc, 8)
            self.assertEqual(message.arbitration_id & 0x1F, CMD_GET_IQ)

    def test_idle_monitor_does_not_poll_without_hardware_watchdog(self):
        fake_can = SimpleNamespace(Message=FakeMessage)
        with patch.object(odrive_module, "CAN_AVAILABLE", True), patch.object(
            odrive_module, "can", fake_can, create=True
        ):
            self.controller.start_monitor()
            time.sleep(0.25)
            self.controller.stop_monitor()

        self.assertEqual(self.bus.messages, [])

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

        self.monitor.set_can_health_check(lambda: (False, "Node 2 fehlt"))
        success, error = self.monitor.reset_system_stop()
        self.assertFalse(success)
        self.assertEqual(error, "Node 2 fehlt")

        self.monitor.set_can_health_check(lambda: (True, None))
        success, error = self.monitor.reset_system_stop()
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertTrue(self.monitor.is_motion_allowed())


if __name__ == "__main__":
    unittest.main()
