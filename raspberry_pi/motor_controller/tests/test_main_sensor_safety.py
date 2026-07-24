import unittest
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.main import MotorControllerApp


class FakeCan:
    def __init__(self, sensor_online=False):
        self.sensor_online = sensor_online

    def get_status(self, **_kwargs):
        return {
            'interface_online': True,
            'sensor_hub': {'online': self.sensor_online, 'transport': 'wifi'},
            'odrives': {
                'nodes': {
                    '0': {'online': True},
                    '1': {'online': True},
                    '2': {'online': True},
                },
                'error_node_ids': [],
            },
        }


class FakeUSBMower:
    transport = 'usb'
    node_ids = [0, 1, 2]
    config = SimpleNamespace(heartbeat_timeout_s=1.0)

    def __init__(self, *, running=False, missing=None, errors=None, startup=False):
        self.running = running
        self._status = {
            'mower_command_running': running,
            'mower_startup_status': {'active': startup},
            'odrive_missing_heartbeats': list(missing or []),
            'odrive_errors': dict(errors or {}),
        }

    def get_status(self):
        return dict(self._status)


class SensorSafetyScopeTests(unittest.TestCase):
    def _app(self, *, sensor_online=False, joystick_active=False, navigation_running=False):
        app = MotorControllerApp.__new__(MotorControllerApp)
        app.config = SimpleNamespace(
            sensor_hub=SimpleNamespace(
                telemetry_timeout_s=10.0,
                pause_timeout_s=1.0,
                resume_stable_s=2.0,
            )
        )
        app.odrive_mower = SimpleNamespace(
            node_ids=[0, 1, 2],
            config=SimpleNamespace(heartbeat_timeout_s=1.0),
        )
        app.can = FakeCan(sensor_online=sensor_online)
        app.web = None
        app.navigation = SimpleNamespace(
            get_status=lambda: {'running': navigation_running}
        )
        app.safety = SimpleNamespace(
            get_status=lambda: {'joystick_active': joystick_active}
        )
        app._sensor_pause_resume_mode = None
        app._sensor_recovery_started_monotonic = None
        return app

    def test_offline_sensor_does_not_latch_idle_system_at_boot(self):
        app = self._app(sensor_online=False)

        self.assertEqual(app._sensor_motion_health_check(), (True, None))
        self.assertEqual(app._can_health_check(), (True, None))

    def test_offline_sensor_does_not_stop_manual_motion(self):
        app = self._app(sensor_online=False, joystick_active=True)

        self.assertEqual(app._sensor_motion_health_check(), (True, None))
        self.assertEqual(app._can_health_check(), (True, None))

    def test_offline_sensor_stops_autonomous_motion(self):
        app = self._app(sensor_online=False, navigation_running=True)

        self.assertFalse(app._sensor_motion_health_check()[0])
        self.assertFalse(app._can_health_check()[0])

    def test_sensor_pause_remains_monitored_until_resume(self):
        app = self._app(sensor_online=False)
        app._sensor_pause_resume_mode = 'plan'

        self.assertFalse(app._sensor_motion_health_check()[0])
        self.assertFalse(app._can_health_check()[0])

    def test_sensor_must_be_stable_before_paused_plan_resumes(self):
        app = self._app(sensor_online=True)
        app._sensor_pause_resume_mode = 'plan'

        healthy, reason = app._sensor_motion_health_check()
        self.assertFalse(healthy)
        self.assertIn('stabilisiert', reason)

        app._sensor_recovery_started_monotonic -= 2.1
        self.assertEqual(app._sensor_motion_health_check(), (True, None))

    def test_idle_usb_poll_gap_does_not_latch_vehicle(self):
        app = self._app(sensor_online=True)
        app.odrive_mower = FakeUSBMower(missing=[1, 2])

        self.assertEqual(app._can_health_check(), (True, None))

    def test_running_usb_poll_gap_stops_vehicle(self):
        app = self._app(sensor_online=True)
        app.odrive_mower = FakeUSBMower(running=True, missing=[1, 2])

        healthy, reason = app._can_health_check()

        self.assertFalse(healthy)
        self.assertEqual(reason, "ODrive USB-Timeout: nodes [1, 2]")

    def test_usb_startup_owns_its_axis_validation(self):
        app = self._app(sensor_online=True)
        app.odrive_mower = FakeUSBMower(
            running=True,
            missing=[2],
            startup=True,
        )

        self.assertEqual(app._can_health_check(), (True, None))

    def test_stuck_usb_start_is_detected_independently_of_fibre_thread(self):
        app = self._app(sensor_online=True)
        mower = FakeUSBMower(running=True, startup=True)
        mower.config = SimpleNamespace(
            heartbeat_timeout_s=1.0,
            usb_startup_hang_timeout_s=8.0,
        )
        mower._status['startup_status'] = {
            'active': True,
            'phase': 'node',
            'node_id': 1,
            'node_started_monotonic': time.monotonic() - 9.0,
        }
        app.odrive_mower = mower

        reason = app._odrive_usb_startup_hang_reason()

        self.assertIn('node=1', reason)
        self.assertIn('Limit 8.0s', reason)


if __name__ == '__main__':
    unittest.main()
