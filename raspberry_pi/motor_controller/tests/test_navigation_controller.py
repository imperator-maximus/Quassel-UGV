import time
import unittest
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from navigation.navigation_controller import NavigationController, Waypoint


@dataclass
class NavConfig:
    watchdog_timeout_s: float = 1.0
    geofence_radius_m: float = 50.0
    max_joystick: float = 0.30
    acceptance_radius_m: float = 0.10
    slowdown_radius_m: float = 0.5
    turn_kp: float = 0.02


class FakeMotor:
    def __init__(self):
        self.commands = []

    def set_joystick(self, x, y, use_ramping=False):
        self.commands.append((x, y, use_ramping))


class NavigationControllerTests(unittest.TestCase):
    def test_bearing_and_heading_error_wrap(self):
        origin = Waypoint(52.0, 10.0)
        east = Waypoint(52.0, 10.001)

        self.assertAlmostEqual(NavigationController.bearing_deg(origin, east), 90.0, delta=1.0)
        self.assertEqual(NavigationController.heading_error_deg(10.0, 350.0), 20.0)
        self.assertEqual(NavigationController.heading_error_deg(350.0, 10.0), -20.0)

    def test_command_is_limited_to_30_percent_and_uses_ramping(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0002}])

        controller.start()
        try:
            controller.on_pose_update({'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 0.0})
        finally:
            controller.shutdown()

        x, y, use_ramping = motor.commands[-1]
        self.assertLessEqual(abs(x), 0.30)
        self.assertLessEqual(abs(y), 0.30)
        self.assertTrue(use_ramping)

    def test_on_pose_update_accepts_can_telemetry_payload(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0002}])

        controller.start()
        try:
            controller.on_pose_update({
                'timestamp': 123.0,
                'gps': {'lat': 52.0, 'lon': 10.0, 'altitude': 0.0},
                'rtk_status': 'RTK FIXED',
                'heading': 0.0,
            })
        finally:
            controller.shutdown()

        status = controller.get_status()
        self.assertIsNotNone(status['last_pose'])
        self.assertAlmostEqual(status['last_pose']['latitude'], 52.0)
        self.assertAlmostEqual(status['last_pose']['longitude'], 10.0)

    def test_on_pose_update_ignores_payload_without_pose(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.on_pose_update({'cmd': 'something_else'})
        self.assertIsNone(controller.get_status()['last_pose'])

    def test_geofence_stops_navigation(self):
        motor = FakeMotor()
        config = NavConfig(geofence_radius_m=5.0)
        controller = NavigationController(motor, config)
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0}])
        controller.start()
        try:
            controller.on_pose_update({'latitude': 52.001, 'longitude': 10.0, 'heading_deg': 0.0})
        finally:
            controller.shutdown()

        status = controller.get_status()
        self.assertFalse(status['running'])
        self.assertEqual(status['state'], 'geofence')

    def test_watchdog_stops_without_recent_pose(self):
        motor = FakeMotor()
        config = NavConfig(watchdog_timeout_s=0.01)
        controller = NavigationController(motor, config)
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0}])
        controller.start()
        try:
            time.sleep(0.02)
            controller._check_watchdog()

            status = controller.get_status()
            self.assertFalse(status['running'])
            self.assertEqual(status['state'], 'watchdog')
        finally:
            controller.shutdown()

    def test_overshoot_advances_when_distance_grows_after_close_approach(self):
        """Wenn das Fahrzeug knapp am WP vorbeifährt (Min-Distanz innerhalb
        2x acceptance) und die Distanz danach mehrere Samples wieder wächst,
        muss der WP als erreicht gelten – auch ohne den Acceptance-Kreis zu
        unterschreiten."""
        motor = FakeMotor()
        # Acceptance 0.25m → engagement_radius = max(0.5, 0.5) = 0.5m
        controller = NavigationController(motor, NavConfig(acceptance_radius_m=0.25))
        # Wegpunkt direkt bei (52, 10); Fahrzeug nähert sich von Westen
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0}])
        controller.start()
        try:
            # Bei lat=52: 1° lon ≈ 68545 m → 1 m ≈ 1.459e-5 deg
            # Sequenz: ~0.34m → ~0.27m (min, < 0.5m engagement) → ~0.34m → ~0.41m
            for offset_m in [0.34, 0.27, 0.34, 0.41]:
                controller.on_pose_update({
                    'latitude': 52.0,
                    'longitude': 10.0 - offset_m * 1.459e-5,
                    'heading_deg': 90.0,
                })
            status = controller.get_status()
        finally:
            controller.shutdown()

        # Einziger Wegpunkt → nach Overshoot-Advance ist Navigation completed
        self.assertEqual(status['state'], 'completed')
        self.assertFalse(status['running'])

    def test_overshoot_does_not_trigger_far_from_waypoint(self):
        """Wenn das Fahrzeug nie nah genug am WP war (außerhalb engagement_radius),
        darf wachsende Distanz keinen Advance auslösen."""
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig(acceptance_radius_m=0.10))
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0}])
        controller.start()
        try:
            # Annähern bis ~3m (über engagement_radius=0.5m), dann wieder weg
            for offset_m in [5.0, 4.0, 3.0, 4.0, 5.0, 6.0]:
                controller.on_pose_update({
                    'latitude': 52.0,
                    'longitude': 10.0 - offset_m * 1.459e-5,
                    'heading_deg': 90.0,
                })
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertEqual(status['state'], 'running')
        self.assertTrue(status['running'])

    def test_on_navigation_command_dispatches(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())

        result = controller.on_navigation_command({
            'cmd': 'nav_set_waypoints',
            'waypoints': [{'latitude': 52.0, 'longitude': 10.0}],
        })
        self.assertTrue(result['ok'])
        self.assertEqual(controller.get_status()['state'], 'ready')

        result = controller.on_navigation_command({'cmd': 'nav_start'})
        self.assertTrue(result['ok'])
        self.assertTrue(controller.get_status()['running'])

        controller.on_navigation_command({'cmd': 'nav_stop'})
        controller.shutdown()
        self.assertFalse(controller.get_status()['running'])


if __name__ == '__main__':
    unittest.main()
