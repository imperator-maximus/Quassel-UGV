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
    track_lookahead_m: float = 0.8
    min_inner_wheel_speed: float = 0.15


@dataclass
class FakePWMConfig:
    """Spiegelt PWMConfig-Felder, die NavigationController liest."""
    neutral_value: int = 1500
    forward_factor: float = 500.0
    turn_factor: float = 300.0


class FakeMotor:
    def __init__(self, pwm_config: FakePWMConfig = None):
        self.commands = []
        # NavigationController liest forward_factor/turn_factor für die
        # Innen-Rad-Garantie aus motor.pwm_config.
        self.pwm_config = pwm_config or FakePWMConfig()

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

    def test_inner_wheel_rolls_forward_at_moderate_heading_error(self):
        """Innen-Rad-Garantie: bei moderatem Heading-Fehler (hier 30°) muss
        das kurveninnere Skid-Rad vorwärts rollen (inner_pwm > neutral),
        damit kein Scrubbing entsteht."""
        motor = FakeMotor()
        # min_inner=0.50, max_joystick=0.30, ratio=0.6, distance_factor=1
        # err=30° → heading_factor = 1 - 30/90 = 0.667
        # inner_floor = 0.50·0.30·0.667 = 0.100
        # turn = clamp(30·0.02, ±0.30)·1 = 0.30 (saturiert)
        # required = 0.100 + 0.30·0.6 = 0.280 ≤ 0.30 → forward angehoben
        controller = NavigationController(
            motor,
            NavConfig(min_inner_wheel_speed=0.50, max_joystick=0.30),
        )
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0002}])  # WP weit östlich
        controller.start()
        try:
            # heading=60° (NO), WP nach O (bearing=90°) → err = +30°
            controller.on_pose_update({'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 60.0})
            x, y, _ = motor.commands[-1]
        finally:
            controller.shutdown()

        # forward >= required (Roll-Floor + No-Reverse), inner_pwm strikt > neutral
        inner_pwm = 1500 + y * 500.0 - abs(x) * 300.0
        self.assertGreater(inner_pwm, 1500.0,
                           f'Innen-Rad muss vorwärts rollen, ist {inner_pwm} μs')
        # Forward muss mindestens den No-Reverse-Schutz + Roll-Floor erfüllen
        self.assertGreaterEqual(y, 0.27, f'Forward zu klein: y={y}')

    def test_extreme_heading_error_keeps_inner_wheel_non_reverse(self):
        """Bei extremem Heading-Fehler (>=90°) wird der Roll-Floor auf 0
        zurückgenommen (heading_factor=0), damit der Wenderadius schrumpft.
        Der No-Reverse-Schutz (forward >= |turn|·ratio) bleibt aktiv:
        Innen-Rad ruht maximal in der ESC-Totzone (inner_pwm = neutral),
        läuft aber nicht rückwärts."""
        motor = FakeMotor()
        controller = NavigationController(
            motor,
            NavConfig(min_inner_wheel_speed=0.50, max_joystick=0.30),
        )
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0002}])
        controller.start()
        try:
            # heading=180° (S), WP O → err=-90°, heading_factor=0
            controller.on_pose_update({'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 180.0})
            x, y, _ = motor.commands[-1]
        finally:
            controller.shutdown()

        # Turn am Limit, Forward auf No-Reverse-Schutz reduziert (= |turn|·ratio)
        self.assertAlmostEqual(abs(x), 0.30, delta=0.001)
        self.assertAlmostEqual(y, 0.18, delta=0.001)
        # Innen-Rad genau auf Neutral (deadband, nicht rückwärts)
        inner_pwm = 1500 + y * 500.0 - abs(x) * 300.0
        self.assertGreaterEqual(inner_pwm, 1500.0 - 0.5,
                                f'Innen-Rad rückwärts (Scrubbing!), ist {inner_pwm} μs')
        # Forward ist reduziert ggü. err=0-Fall (0.30) → Wenderadius schrumpft
        self.assertLess(y, 0.30,
                        'Forward muss bei extremem Heading-Fehler reduziert sein')

    def test_zero_min_inner_wheel_speed_allows_legacy_pivot(self):
        """Mit min_inner_wheel_speed=0 ist die Innen-Rad-Garantie deaktiviert:
        bei |err|>=90° gibt es keinen Vorwärts-Schub (legacy Pivot-Verhalten)."""
        motor = FakeMotor()
        controller = NavigationController(
            motor,
            NavConfig(min_inner_wheel_speed=0.0, max_joystick=0.30),
        )
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0002}])
        controller.start()
        try:
            controller.on_pose_update({'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 180.0})
            _, y, _ = motor.commands[-1]
        finally:
            controller.shutdown()
        self.assertEqual(y, 0.0)

    def test_inner_wheel_guarantee_caps_turn_when_forward_would_exceed_limit(self):
        """Wenn die Innen-Rad-Garantie required_forward > limit erzwingen würde,
        muss stattdessen turn proportional zurückgenommen werden (forward bei limit).
        Sättigungsfenster mit heading-skaliertem inner_floor: bei min_inner=0.80
        und err=30° ist heading_factor=0.667 → inner_floor=0.160, |turn|=0.30
        saturiert → required=0.340 > limit → cap."""
        motor = FakeMotor()
        # min_inner=0.80, max_joystick=0.30, ratio=0.6
        # err=30° → heading_factor=0.667 → inner_floor=0.80·0.30·0.667=0.160
        # |turn|=0.30 (saturiert) → required=0.160+0.30·0.6=0.340 > 0.30 → cap
        # max_turn = (0.30 - 0.160) / 0.6 = 0.233
        controller = NavigationController(
            motor,
            NavConfig(min_inner_wheel_speed=0.80, max_joystick=0.30, turn_kp=0.02),
        )
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0002}])
        controller.start()
        try:
            # heading=60° (NO), WP O (bearing=90°) → err=+30°
            controller.on_pose_update({'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 60.0})
            x, y, _ = motor.commands[-1]
        finally:
            controller.shutdown()

        # forward am Limit, turn auf max_turn≈0.233 zurückgenommen
        self.assertAlmostEqual(y, 0.30, delta=0.001)
        self.assertAlmostEqual(abs(x), 0.233, delta=0.002)
        # Innen-Rad verifizieren: 1500 + 0.30·500 - 0.233·300 = 1580
        inner_pwm = 1500 + y * 500.0 - abs(x) * 300.0
        self.assertGreater(inner_pwm, 1500.0)

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
        des engagement_radius) und die Distanz danach mehrere Samples wieder
        wächst, muss der WP als erreicht gelten – auch ohne den Acceptance-
        Kreis zu unterschreiten."""
        motor = FakeMotor()
        # Acceptance 0.25m → engagement_radius = max(0.75, 1.5) = 1.5m
        controller = NavigationController(motor, NavConfig(acceptance_radius_m=0.25))
        # Wegpunkt direkt bei (52, 10); Fahrzeug nähert sich von Westen
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0}])
        controller.start()
        try:
            # Bei lat=52: 1° lon ≈ 68545 m → 1 m ≈ 1.459e-5 deg
            # Sequenz: ~0.34m → ~0.27m (min, < 1.5m engagement) → ~0.34m → ~0.41m
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
            # Annähern bis ~3m (über engagement_radius=1.5m), dann wieder weg
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

    def test_overshoot_advances_on_grazing_pass_within_15m(self):
        """Tangentialer Streiftreffer mit Min-Distanz ~0.6 m (außerhalb des
        Acceptance-Kreises, aber innerhalb des 1.5 m engagement_radius) muss
        den WP als erreicht markieren – Regression für das beobachtete
        Orbiting nach dem Roll-Bogen-Wenderadius."""
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig(acceptance_radius_m=0.25))
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0}])
        controller.start()
        try:
            # Min-Distanz ~0.6m (zwischen acceptance=0.25 und engagement=1.5),
            # danach monoton wachsend → Overshoot-Detector muss auslösen
            for offset_m in [1.2, 0.8, 0.6, 0.9, 1.4, 2.0]:
                controller.on_pose_update({
                    'latitude': 52.0,
                    'longitude': 10.0 - offset_m * 1.459e-5,
                    'heading_deg': 90.0,
                })
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertEqual(status['state'], 'completed')
        self.assertFalse(status['running'])

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

    def test_track_mode_generates_near_zero_turn_when_on_line(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig(track_lookahead_m=1.0))
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track')
        controller.start()
        try:
            controller.on_pose_update({'latitude': 52.0, 'longitude': 10.0001, 'heading_deg': 90.0})
            x, y, _ = motor.commands[-1]
        finally:
            controller.shutdown()

        self.assertAlmostEqual(x, 0.0, delta=0.03)
        self.assertGreater(y, 0.0)
        self.assertEqual(controller.get_status()['mode'], 'track')

    def test_track_mode_turns_back_toward_polyline_when_offset(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig(track_lookahead_m=1.0, min_inner_wheel_speed=0.0))
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track')
        controller.start()
        try:
            # Fahrzeug steht nördlich der Ost-West-Linie und fährt nach Osten:
            # Lookahead-Punkt liegt rechts/vorne-unten, also positiver Turn
            # in der bestehenden Joystick-X-Konvention.
            controller.on_pose_update({'latitude': 52.000003, 'longitude': 10.0001, 'heading_deg': 90.0})
            x, _, _ = motor.commands[-1]
        finally:
            controller.shutdown()

        self.assertGreater(x, 0.0)

    def test_track_mode_completes_after_end_projection(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig(track_lookahead_m=1.0))
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.0001},
        ], mode='track')
        controller.start()
        try:
            controller.on_pose_update({'latitude': 52.0, 'longitude': 10.00012, 'heading_deg': 90.0})
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertEqual(status['state'], 'completed')
        self.assertFalse(status['running'])

    def test_nav_set_waypoints_accepts_track_mode(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())

        result = controller.on_navigation_command({
            'cmd': 'nav_set_waypoints',
            'mode': 'track',
            'lookahead_m': 1.2,
            'waypoints': [
                {'latitude': 52.0, 'longitude': 10.0},
                {'latitude': 52.0, 'longitude': 10.001},
            ],
        })

        self.assertTrue(result['ok'])
        status = controller.get_status()
        self.assertEqual(status['mode'], 'track')
        self.assertAlmostEqual(status['limits']['track_lookahead_m'], 1.2)

    def test_track_mode_accepts_reverse_direction_and_drives_backward(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig(track_lookahead_m=1.0, min_inner_wheel_speed=0.0))
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track', direction='reverse')
        controller.start()
        try:
            controller.on_pose_update({'latitude': 52.0, 'longitude': 10.0001, 'heading_deg': 270.0})
            x, y, _ = motor.commands[-1]
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertEqual(status['direction'], 'reverse')
        self.assertAlmostEqual(x, 0.0, delta=0.03)
        self.assertLess(y, 0.0)

    def test_reverse_direction_is_rejected_for_goto(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())

        with self.assertRaises(ValueError):
            controller.set_waypoints([
                {'latitude': 52.0, 'longitude': 10.0},
            ], mode='goto', direction='reverse')


if __name__ == '__main__':
    unittest.main()
