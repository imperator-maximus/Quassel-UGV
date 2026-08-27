import math
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
    pivot_heading_threshold_deg: float = 70.0
    goto_divergence_limit_m: float = 0.75
    goto_divergence_samples: int = 5
    track_cross_track_limit_m: float = 1.0
    track_cross_track_max_m: float = 8.0
    track_cross_track_recover_s: float = 10.0
    track_cross_track_progress_m: float = 0.1
    track_heading_block_deg: float = 25.0
    track_stall_timeout_s: float = 10.0
    track_stall_min_progress_m: float = 0.15
    min_inner_wheel_speed: float = 0.15
    turn_gain_left: float = 1.0


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
    def test_pause_resume_preserves_track_progress_and_waypoints(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track')
        controller.start()
        try:
            controller.on_pose_update({
                'latitude': 52.0,
                'longitude': 10.0002,
                'heading_deg': 90.0,
            })
            before = controller.get_status()

            self.assertTrue(controller.pause('sensor_pause'))
            paused = controller.get_status()
            self.assertTrue(paused['running'])
            self.assertTrue(paused['paused'])

            self.assertTrue(controller.resume())
            after = controller.get_status()
        finally:
            controller.shutdown()

        self.assertFalse(after['paused'])
        self.assertEqual(after['state'], 'running')
        self.assertEqual(after['waypoints'], before['waypoints'])
        self.assertEqual(
            after['limits']['track_progress_m'],
            before['limits']['track_progress_m'],
        )

    def test_practical_positioning_radius_accepts_26cm_target_distance(self):
        motor = FakeMotor()
        controller = NavigationController(
            motor, NavConfig(acceptance_radius_m=0.40)
        )
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0}])
        controller.start()
        try:
            controller.on_pose_update({
                'latitude': 52.0,
                'longitude': 10.0 - 0.26 * 1.459e-5,
                'heading_deg': 90.0,
            })
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertEqual(status['state'], 'completed')
        self.assertFalse(status['running'])

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
            controller.on_pose_update({'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 90.0})
            x, y, use_ramping = motor.commands[-1]
        finally:
            controller.shutdown()

        self.assertLessEqual(abs(x), 0.30)
        self.assertLessEqual(abs(y), 0.30)
        self.assertFalse(use_ramping)

    def _command_at_heading(self, config, heading_deg: float):
        """Ein Kommando fuer einen weit entfernten Wegpunkt im Osten."""
        motor = FakeMotor()
        controller = NavigationController(motor, config)
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0002}])
        controller.start()
        try:
            controller.on_pose_update({
                'latitude': 52.0, 'longitude': 10.0, 'heading_deg': heading_deg,
            })
            return motor.commands[-1]
        finally:
            controller.shutdown()

    def test_turn_gain_left_only_strengthens_the_weak_side(self):
        """Der Antrieb lenkt nach links schwaecher als nach rechts, ohne dass
        eine Rueckmeldung das verraet. ``turn_gain_left`` haelt genau diesen
        Unterschied vor - und nur ihn: rechts bleibt unveraendert."""
        config = NavConfig(turn_gain_left=2.0, max_joystick=0.30)
        # WP im Osten (bearing 90°). heading=95° → Fehler -5° (links),
        # heading=85° → Fehler +5° (rechts). turn_kp=0.02 → |turn|=0.10.
        left_x, _, _ = self._command_at_heading(config, 95.0)
        right_x, _, _ = self._command_at_heading(config, 85.0)

        self.assertAlmostEqual(right_x, 0.10, delta=0.005)
        self.assertAlmostEqual(left_x, -0.20, delta=0.005)

    def test_turn_gain_left_keeps_inner_wheel_rolling_forward(self):
        """Der Vorhalt greift vor der Innen-Rad-Garantie, damit deren
        PWM-Rechnung mit dem Wert arbeitet, der wirklich rausgeht. Sonst
        liefe das kurveninnere Rad unbemerkt rueckwaerts."""
        x, y, _ = self._command_at_heading(
            NavConfig(turn_gain_left=2.0, max_joystick=0.30, min_inner_wheel_speed=0.50),
            95.0,
        )

        self.assertLess(x, 0.0)
        inner_pwm = 1500 + y * 500.0 - abs(x) * 300.0
        self.assertGreater(inner_pwm, 1500.0,
                           f'Innen-Rad muss vorwärts rollen, ist {inner_pwm} μs')

    def test_turn_gain_left_saturates_at_full_joystick_on_pivot(self):
        """Beim Pivot steht der Drehanteil schon bei limit/ratio. Mit Vorhalt
        darf daraus kein Kommando jenseits des Knueppelanschlags werden."""
        # heading=180° (S), WP Osten → Fehler -90° → Pivot nach links.
        # pivot_turn = 0.30/0.6 = 0.50, mal 2.0 → auf 1.0 begrenzt.
        x, y, _ = self._command_at_heading(
            NavConfig(turn_gain_left=2.0, max_joystick=0.30), 180.0,
        )

        self.assertAlmostEqual(x, -1.0, delta=0.001)
        self.assertEqual(y, 0.0)

    def test_max_joystick_is_capped_by_the_absolute_backstop(self):
        """``max_joystick`` ist der Betriebspunkt, nicht die letzte Grenze:
        eine verrutschte Konfiguration darf das Fahrzeug nicht autonom auf
        Vollgas schicken."""
        # heading=90° = direkt auf den WP → kein Drehanteil, y am Deckel.
        _, y, _ = self._command_at_heading(NavConfig(max_joystick=0.90), 90.0)

        self.assertAlmostEqual(y, NavigationController.MAX_AUTONOMOUS_JOYSTICK, delta=0.001)

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

    def test_extreme_heading_error_pivots_without_forward_motion(self):
        """Bei großem Heading-Fehler darf kein fahrender U-Turn entstehen."""
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

        # turn_factor=300 ist kleiner als forward_factor=500. Deshalb wird
        # x auf 0.50 skaliert: 0.50*300 = 0.30*500 = 150 us PWM-Offset.
        self.assertAlmostEqual(abs(x), 0.50, delta=0.001)
        self.assertEqual(y, 0.0)

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

    def test_geofence_stops_navigation_when_pose_leaves_the_corridor(self):
        motor = FakeMotor()
        config = NavConfig(geofence_radius_m=5.0)
        controller = NavigationController(motor, config)
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0}])
        controller.start()
        try:
            # Erste Pose spannt den Korridor auf: von hier zum Zielwegpunkt.
            controller.on_pose_update({'latitude': 52.0, 'longitude': 10.001, 'heading_deg': 0.0})
            self.assertTrue(controller.get_status()['running'])
            # Rund 111 m seitlich neben dieser Linie.
            controller.on_pose_update({'latitude': 52.001, 'longitude': 10.001, 'heading_deg': 0.0})
        finally:
            controller.shutdown()

        status = controller.get_status()
        self.assertFalse(status['running'])
        self.assertEqual(status['state'], 'geofence')

    def test_geofence_allows_an_approach_longer_than_its_radius(self):
        """Regression 02.08.: Anfahrt zur ersten Bahn war 72 m lang.

        Der Geofence wurde zum ersten Wegpunkt gemessen und stoppte bei 50 m,
        obwohl das Fahrzeug exakt auf der geplanten Strecke fuhr. Er begrenzt
        die Abweichung vom Korridor, nicht die Länge der Fahrt.
        """
        motor = FakeMotor()
        config = NavConfig(geofence_radius_m=50.0)
        controller = NavigationController(motor, config)
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0018, 'longitude': 10.0},
        ], mode='track')
        controller.start()
        try:
            self.assertGreater(
                NavigationController.distance_m(
                    Waypoint(52.0, 10.0), Waypoint(52.0018, 10.0)
                ),
                config.geofence_radius_m,
            )
            for step in range(19):
                controller.on_pose_update({
                    'latitude': 52.0 + 0.0001 * step,
                    'longitude': 10.0,
                    'heading_deg': 0.0,
                })
                self.assertNotEqual('geofence', controller.get_status()['state'])
        finally:
            controller.shutdown()

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

    def test_goto_stops_when_aligned_vehicle_moves_away_from_target(self):
        motor = FakeMotor()
        controller = NavigationController(
            motor,
            NavConfig(goto_divergence_limit_m=0.5, goto_divergence_samples=3),
        )
        controller.set_waypoints([{'latitude': 52.0, 'longitude': 10.0002}])
        controller.start()
        try:
            # Ziel liegt östlich, Heading ist korrekt nach Osten, die Pose
            # bewegt sich aber wiederholt nach Westen und damit vom Ziel weg.
            for lon in [10.0, 9.999996, 9.999992, 9.999988, 9.999984]:
                controller.on_pose_update({
                    'latitude': 52.0,
                    'longitude': lon,
                    'heading_deg': 90.0,
                })
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertFalse(status['running'])
        self.assertEqual(status['state'], 'divergence_stop')
        self.assertIn('entfernt sich', status['last_error'])

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

    def _bahnregler(self, **grenzen):
        """Controller auf einer Ost-West-Bahn, Fahrzeug faehrt nach Osten."""
        motor = FakeMotor()
        controller = NavigationController(
            motor, NavConfig(track_lookahead_m=1.0, **grenzen)
        )
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track')
        controller.start()
        return controller

    @staticmethod
    def _pose_noerdlich(meter: float):
        """Pose um ``meter`` noerdlich der Bahn (0.00001 Grad ~ 1,11 m)."""
        return {
            'latitude': 52.0 + meter / 111_320.0,
            'longitude': 10.0001,
            'heading_deg': 90.0,
        }

    def test_eine_einzelne_zu_grosse_querabweichung_stoppt_nicht(self):
        """Am 27.08. hing ein USB-Aufruf des Maehdecks, der Dienst startete neu,
        und das Fahrzeug stand 1,42 m neben seiner Bahn. Die Navigation stieg
        50 ms nach dem Start aus, ohne einen Meter gefahren zu sein - obwohl der
        Fehler vom Maehdeck kam und mit dem Fahren nichts zu tun hatte.
        """
        controller = self._bahnregler(track_cross_track_limit_m=0.75)
        try:
            controller.on_pose_update(self._pose_noerdlich(2.2))
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertTrue(status['running'])
        self.assertNotEqual(status['state'], 'cross_track_stop')

    def test_annaeherung_haelt_die_navigation_am_leben(self):
        """Wer sich der Bahn naehert, tut genau das, was er soll - auch wenn er
        laenger als die Frist ueber der Grenze bleibt."""
        controller = self._bahnregler(
            track_cross_track_limit_m=0.75, track_cross_track_recover_s=1.0
        )
        try:
            for abstand in (3.0, 2.5, 2.0, 1.5, 1.2):
                controller.on_pose_update(self._pose_noerdlich(abstand))
                time.sleep(0.3)
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertTrue(status['running'])

    def test_stoppt_wenn_die_abweichung_nicht_kleiner_wird(self):
        """Ein Regler, der die Bahn wirklich verliert, muss weiterhin stoppen."""
        controller = self._bahnregler(
            track_cross_track_limit_m=0.75, track_cross_track_recover_s=1.0
        )
        try:
            for _ in range(5):
                controller.on_pose_update(self._pose_noerdlich(2.2))
                time.sleep(0.3)
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertFalse(status['running'])
        self.assertEqual(status['state'], 'cross_track_stop')
        self.assertIn('nicht naeher', status['last_error'])

    def test_weit_jenseits_der_grenze_wird_sofort_gestoppt(self):
        """Aus dieser Entfernung faengt sich nichts mehr ein: Zwischen Fahrzeug
        und Bahn koennen Sperrzonen liegen, von denen der Bahnregler nichts
        weiss."""
        controller = self._bahnregler(
            track_cross_track_limit_m=0.75, track_cross_track_max_m=5.0
        )
        try:
            controller.on_pose_update(self._pose_noerdlich(9.0))
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertFalse(status['running'])
        self.assertEqual(status['state'], 'cross_track_stop')
        self.assertIn('Pfad entfernt', status['last_error'])

    def test_forward_large_heading_error_blocks_instead_of_pivoting(self):
        """60° liegt jenseits dessen, was der Roll-Bogen sicher auffaengt
        (siehe test_failed_brunnen_pose_blocks_instead_of_pivoting_or_arcing);
        der Controller muss dort deterministisch stoppen statt zu rollen."""
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track')
        controller.start()
        try:
            # Die Sperre verlangt mehrere aufeinanderfolgende Posen; das reale
            # Fahrzeug liefert sie mit 5 Hz. Ein einzelner Ausreisser darf eine
            # laufende Mahd nicht mehr stoppen.
            for _ in range(3):
                controller.on_pose_update({
                    'latitude': 52.0,
                    'longitude': 10.0,
                    # Eastbound target, therefore a large +60 degree error.
                    'heading_deg': 30.0,
                })
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertFalse(status['running'])
        self.assertEqual(status['state'], 'heading_block')
        self.assertIn('Winkelfehler', status['last_error'])
        self.assertEqual((0.0, 0.0, True), motor.commands[-1])

    def test_track_heading_block_threshold_is_a_single_cutoff(self):
        """24 Grad Fehler bleibt unterhalb der (hier lokal auf 25 gesetzten)
        Blockgrenze und laeuft weiter (rollend ausgerichtet, da ueber
        track_alignment_enter_deg), 26 Grad stoppt sofort - ohne
        Zwischenstopp oder Ausnahme fuer die Blockgrenze selbst."""
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track')
        controller.start()
        try:
            for _ in range(3):
                controller.on_pose_update({'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 66.0})
            below_threshold = controller.get_status()
        finally:
            controller.shutdown()

        motor2 = FakeMotor()
        controller2 = NavigationController(motor2, NavConfig())
        controller2.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track')
        controller2.start()
        try:
            for _ in range(3):
                controller2.on_pose_update({'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 64.0})
            above_threshold = controller2.get_status()
        finally:
            controller2.shutdown()

        self.assertTrue(below_threshold['running'])
        self.assertNotEqual('heading_block', below_threshold['state'])
        self.assertFalse(above_threshold['running'])
        self.assertEqual('heading_block', above_threshold['state'])

    def test_failed_brunnen_pose_blocks_instead_of_pivoting_or_arcing(self):
        """Regression fuer den Realstopp vom 25.07.: -52 Grad am Bahnanfang.

        Der urspruengliche Roll-Bogen (x=-0.30, y=+0.18) lief real von der
        Bahn weg (Cross-Track 0.19 -> 1.01 m). Der als Ersatz eingefuehrte
        Gegenlauf-Pivot (x=-0.50, y=0.0) drehte das schwere Kettenfahrzeug
        auf Gras real über vier Minuten lang nicht. Beide Regelversuche sind
        also nicht zuverlaessig; der Controller muss bei so grossem
        Winkelfehler stattdessen deterministisch stoppen.
        """
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints([
            {'latitude': 53.3325664, 'longitude': 11.0785893},
            {'latitude': 53.3325583290, 'longitude': 11.0784566012},
        ], mode='track', direction='forward')
        controller.start()
        try:
            for _ in range(3):
                controller.on_pose_update({
                    'latitude': 53.3325664,
                    'longitude': 11.0785893,
                    'heading_deg': 302.8,
                })
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertFalse(status['running'])
        self.assertEqual(status['state'], 'heading_block')
        self.assertIn('Winkelfehler', status['last_error'])

    def test_reverse_large_heading_error_blocks_too(self):
        """Die Blockgrenze gilt richtungsunabhaengig - auch der fuer reverse
        real bewaehrte Roll-Bogen (29.7° -> 1.3° in 11s, 25.07.) faengt
        60° nicht mehr sicher auf."""
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track', direction='reverse')
        controller.start()
        try:
            # Eastbound reverse motion wants a west-facing body. The 60 degree
            # error mirrors the failed short Brunnen transition.
            for _ in range(3):
                controller.on_pose_update({
                    'latitude': 52.0,
                    'longitude': 10.0,
                    'heading_deg': 210.0,
                })
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertFalse(status['running'])
        self.assertEqual(status['state'], 'heading_block')
        self.assertIn('Winkelfehler', status['last_error'])

    def test_lateral_offset_at_the_lane_start_is_no_heading_error(self):
        """Regression fuer den Realstopp vom 07.08. mitten auf der Wiese.

        Das Fahrzeug stand parallel zur Bahn (Fehler zur Bahnrichtung 6.7
        Grad), aber am Segmentanfang praktisch auf dem Pure-Pursuit-Ziel. Der
        Ausrichtbogen schwenkte die GNSS-Antenne um wenige Zentimeter, und die
        Peilung zu diesem nahen Ziel sprang in einer Sekunde von 16.4 auf 48.4
        Grad - die Sperre stoppte den Plan bei 11 cm Querabstand.

        Hier derselbe Effekt in Reinform: exakt bahnparalleler Kurs, 0.8 m
        Querversatz, Ziel im Lookahead von 0.8 m. Gegen die Zielpeilung sind
        das 45 Grad, gegen die Bahnrichtung null.
        """
        east_per_deg = 111320.0 * math.cos(math.radians(52.0))
        offset_deg = 0.8 / east_per_deg
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0009, 'longitude': 10.0},
        ], mode='track')
        controller.start()
        try:
            for _ in range(5):
                controller.on_pose_update({
                    'latitude': 52.0,
                    'longitude': 10.0 + offset_deg,
                    'heading_deg': 0.0,
                })
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertNotEqual('heading_block', status['state'])
        self.assertTrue(status['running'])

    def test_single_outlier_pose_does_not_stop_the_plan(self):
        """Erst ein anhaltender Fehler stoppt - ein Ausreisser nicht."""
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track')
        controller.start()
        try:
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 30.0}
            )
            after_outlier = controller.get_status()
            # Kurs wieder in der Grenze: der Zaehler muss zurueckgesetzt sein.
            for _ in range(2):
                controller.on_pose_update(
                    {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 88.0}
                )
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 30.0}
            )
            after_recovery = controller.get_status()
        finally:
            controller.shutdown()

        self.assertTrue(after_outlier['running'])
        self.assertNotEqual('heading_block', after_outlier['state'])
        self.assertTrue(after_recovery['running'])
        self.assertNotEqual('heading_block', after_recovery['state'])

    def test_persistent_error_still_blocks_after_the_required_poses(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track')
        controller.start()
        try:
            states = []
            for _ in range(3):
                controller.on_pose_update(
                    {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 30.0}
                )
                states.append(controller.get_status()['state'])
        finally:
            controller.shutdown()

        self.assertNotEqual('heading_block', states[0])
        self.assertNotEqual('heading_block', states[1])
        self.assertEqual('heading_block', states[2])

    def _lane_north(self):
        return [
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0009, 'longitude': 10.0},
        ]

    def _east_offset_deg(self, meters):
        return meters / (111320.0 * math.cos(math.radians(52.0)))

    def test_alignment_needs_a_tracking_problem_not_only_a_lane_angle(self):
        """Realfall 07.08. 16:54: bahn 8.3 Grad, folge 1.0 Grad - kein Problem.

        Das Fahrzeug stand 10 cm seitlich versetzt und dabei 8 Grad gedreht -
        genau die Kombination, in der Pure Pursuit sauber auf die Linie
        faehrt. Der Bogen darf hier nicht anspringen; er nimmt sonst den
        Vorwaertsschub weg und das Fahrzeug steht ohne erkennbaren Grund.
        """
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints(self._lane_north(), mode='track')
        controller.start()
        try:
            for _ in range(4):
                controller.on_pose_update({
                    'latitude': 52.0,
                    'longitude': 10.0 + self._east_offset_deg(0.10),
                    'heading_deg': 352.0,
                })
            status = controller.get_status()
            x, y, _ = motor.commands[-1]
        finally:
            controller.shutdown()

        self.assertFalse(status['limits']['track_aligning'])
        self.assertTrue(status['running'])
        self.assertNotEqual('align_stall', status['state'])
        self.assertGreater(y, 0.0, 'Vorwaertsschub muss erhalten bleiben')

    def test_alignment_stops_once_the_nose_is_parallel(self):
        """Realfall 07.08. 16:30: folge -7 Grad, bahn 3.6 Grad.

        Der Rest ist reiner Querversatz - den baut nur Vorwaertsfahren ab.
        Der Bogen muss beenden, auch wenn der Verfolgungsfehler noch steht.
        """
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints(self._lane_north(), mode='track')
        controller.start()
        try:
            controller._track_aligning = True
            controller.on_pose_update({
                'latitude': 52.0,
                'longitude': 10.0 + self._east_offset_deg(0.15),
                'heading_deg': 357.0,
            })
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertFalse(status['limits']['track_aligning'])
        self.assertTrue(status['running'])

    def test_alignment_command_escalates_while_the_vehicle_does_not_turn(self):
        """Realfall 07.08. 16:54: x=0.220 bewegte das Fahrzeug 14 s nicht.

        Die Losbrechgrenze auf Gras ist nicht vorhersagbar. Bleibt der Kurs
        stehen, muss das Kommando bis zur Grenze hochlaufen, statt auf einem
        geratenen Wert zu verharren.
        """
        motor = FakeMotor()
        controller = self._aligning_controller(motor)
        try:
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 78.0}
            )
            first = abs(motor.commands[-1][0])
            controller._align_reference_time -= 4.0
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 78.0}
            )
            escalated = abs(motor.commands[-1][0])
        finally:
            controller.shutdown()

        self.assertGreater(escalated, first)
        self.assertAlmostEqual(escalated, 0.30, delta=0.001)

    def test_escalation_falls_back_when_the_vehicle_turns_again(self):
        motor = FakeMotor()
        controller = self._aligning_controller(motor)
        try:
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 78.0}
            )
            controller._align_reference_time -= 4.0
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 78.0}
            )
            escalated = abs(motor.commands[-1][0])
            # Kurs verbessert sich: die Eskalation muss zurueckfallen.
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 81.0}
            )
            relaxed = abs(motor.commands[-1][0])
        finally:
            controller.shutdown()

        self.assertLess(relaxed, escalated)

    def test_cross_track_offset_alone_does_not_start_an_alignment(self):
        """Ursache des Realstopps vom 07.08. mitten in der Bahn.

        Der Regelfehler der Bahnverfolgung ist Kursfehler plus
        Querversatz-Anteil: bei 0.15 m Versatz und 0.8 m Lookahead allein
        atan(0.15/0.8) = 10.6 Grad, also ueber der Eintrittsschwelle. Der
        Ausrichtbogen nimmt dann den Vorwaertsschub weg - und genau der waere
        noetig, um den Versatz abzubauen. Die Austrittsschwelle von 5 Grad
        blieb damit unerreichbar, obwohl das Fahrzeug exakt bahnparallel
        stand. Es muss stattdessen einfach normal weiterfahren.
        """
        north_per_deg = 111320.0
        offset_deg = 0.15 / (north_per_deg * math.cos(math.radians(52.0)))
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0009, 'longitude': 10.0},
        ], mode='track')
        controller.start()
        try:
            for _ in range(5):
                controller.on_pose_update({
                    'latitude': 52.0,
                    'longitude': 10.0 + offset_deg,
                    'heading_deg': 0.0,
                })
            status = controller.get_status()
            x, y, _ = motor.commands[-1]
        finally:
            controller.shutdown()

        self.assertFalse(status['limits']['track_aligning'])
        self.assertTrue(status['running'])
        self.assertNotEqual('align_stall', status['state'])
        # Vorwaertsschub bleibt: nur er baut den Querversatz ab.
        self.assertGreater(y, 0.0)

    def test_heading_error_toward_the_line_is_no_tracking_problem(self):
        """20 Grad Bahnwinkel koennen ein 9 Grad Verfolgungsfehler sein.

        Nase 20 Grad nach links bei 15 cm Versatz nach rechts heisst: das
        Fahrzeug faehrt auf die Linie zu. Pure Pursuit braucht dafuer nur
        9.4 Grad Korrektur - der Bogen waere hier ein Rueckschritt.
        """
        offset_deg = self._east_offset_deg(0.15)
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints(self._lane_north(), mode='track')
        controller.start()
        try:
            controller.on_pose_update({
                'latitude': 52.0,
                'longitude': 10.0 + offset_deg,
                'heading_deg': 340.0,
            })
            status = controller.get_status()
            _, y, _ = motor.commands[-1]
        finally:
            controller.shutdown()

        self.assertFalse(status['limits']['track_aligning'])
        self.assertGreater(y, 0.0)

    def _aligning_controller(self, motor, config=None):
        """Bahn nach Osten; 12 Grad Kursfehler starten den Roll-Bogen."""
        controller = NavigationController(motor, config or NavConfig())
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.001},
        ], mode='track')
        controller.start()
        return controller

    def test_alignment_that_never_turns_the_vehicle_is_stopped(self):
        """Regression fuer den Realstopp vom 07.08. ohne jede Fehlermeldung.

        Das Fahrzeug rollte im Ausrichtbogen bei 7 Grad Fehler, PWM 1405/1500 -
        zu wenig, um das beladene Kettenfahrzeug auf Gras zu drehen. Der
        Track-Fortschrittswaechter ruht in diesem Zweig bewusst, also lief er
        unbegrenzt: kein Fortschritt, kein Fehler, in der Oberflaeche alles
        gruen.
        """
        motor = FakeMotor()
        controller = self._aligning_controller(motor)
        try:
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 78.0}
            )
            self.assertTrue(controller.get_status()['limits']['track_aligning'])
            # Die Zeit vorspulen, ohne dass sich der Kurs bewegt.
            controller._align_reference_time -= 11.0
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 78.0}
            )
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertFalse(status['running'])
        self.assertEqual('align_stall', status['state'])
        self.assertIn('dreht nicht', status['last_error'])
        self.assertEqual((0.0, 0.0, True), motor.commands[-1])

    def test_slowly_converging_alignment_is_not_stopped(self):
        """Regression: der Waechter hat am 07.08. eine Drehung abgeschossen,
        die in 10 s um 1.7 Grad vorangekommen war - 1 Grad vor dem Ziel.
        Schrittweiten unter der alten 2-Grad-Granularitaet muessen zaehlen."""
        motor = FakeMotor()
        controller = self._aligning_controller(motor)
        try:
            for heading in (78.0, 78.8, 79.6, 80.4, 81.2):
                controller._align_reference_time -= 11.0
                controller.on_pose_update({
                    'latitude': 52.0,
                    'longitude': 10.0,
                    'heading_deg': heading,
                })
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertTrue(status['running'])
        self.assertNotEqual('align_stall', status['state'])

    def test_alignment_command_stays_above_the_breakaway_floor(self):
        """Unter der Losbrechgrenze dreht das Fahrzeug auf Gras nicht mehr.

        Am 07.08. lief die Ausrichtung mit x=0.125 bei 6 Grad Restfehler ins
        Leere: Kurs 10 s lang unveraendert, Austrittsschwelle 5 Grad nie
        erreicht. Proportional waeren 6 * 0.02 = 0.12.
        """
        motor = FakeMotor()
        controller = self._aligning_controller(motor)
        try:
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 78.0}
            )
            self.assertTrue(controller.get_status()['limits']['track_aligning'])
            # 84 Grad = 6 Grad Restfehler, genau der reale Fall.
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 84.0}
            )
            x, y, _ = motor.commands[-1]
        finally:
            controller.shutdown()

        self.assertGreaterEqual(abs(x), 0.22)
        self.assertGreater(abs(y), 0.0, 'Rollanteil folgt dem Drehanteil')

    def test_large_alignment_error_still_uses_the_proportional_command(self):
        """Die Schranke hebt nur an, sie ersetzt die Regelung nicht."""
        motor = FakeMotor()
        controller = self._aligning_controller(motor)
        try:
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 70.0}
            )
            x, _, _ = motor.commands[-1]
        finally:
            controller.shutdown()

        # 20 Grad * 0.02 = 0.40, begrenzt auf max_joystick 0.30.
        self.assertAlmostEqual(abs(x), 0.30, delta=0.001)

    def test_alignment_watchdog_resets_when_alignment_ends(self):
        motor = FakeMotor()
        controller = self._aligning_controller(motor)
        try:
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 78.0}
            )
            self.assertIsNotNone(controller._align_reference_error)
            # Kurs innerhalb der Austrittsschwelle: Ausrichtung beendet.
            controller.on_pose_update(
                {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 88.0}
            )
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertFalse(status['limits']['track_aligning'])
        self.assertIsNone(controller._align_reference_error)

    def test_track_speed_reduction_preserves_forward_wheel_directions(self):
        """Moderate heading correction must retain usable grass-load PWM."""
        motor = FakeMotor()
        controller = NavigationController(
            motor,
            NavConfig(
                track_lookahead_m=1.0,
                track_heading_block_deg=25.0,
                min_inner_wheel_speed=0.50,
            ),
        )
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.0001},
        ], mode='track', direction='forward')
        controller.start()
        try:
            # 8 degree error stays below track_alignment_enter_deg (10), so
            # this still exercises _calculate_command's normal driving mix
            # rather than the roll-alignment phase.
            controller.on_pose_update({
                'latitude': 52.0,
                'longitude': 10.0,
                'heading_deg': 98.0,
            })
            x, y, _ = motor.commands[-1]
        finally:
            controller.shutdown()

        ratio = motor.pwm_config.turn_factor / motor.pwm_config.forward_factor
        left_mix = y + x * ratio
        right_mix = y - x * ratio
        self.assertGreaterEqual(left_mix, -1e-9)
        self.assertGreaterEqual(right_mix, -1e-9)
        self.assertGreater(min(left_mix, right_mix) * 500.0, 50.0)

    def test_live_regression_23_degree_track_error_keeps_driving_track_out_of_deadband(self):
        """Regression for the real Brunnen stall at source segment 22.

        At about 23 degrees heading error the old post-processing multiplied
        the complete command by 0.20, yielding PWM 1511/1547. Both software
        states remained green although the heavy UGV could not move on grass.

        23 degrees now falls into the roll-alignment band (see
        track_alignment_enter_deg): one track is deliberately held near
        neutral as the pivot point while the other drives - that is the
        mechanism working as designed, not the silent-no-op bug this test
        guards against. What must still hold is that the driving track gets
        a real, usable PWM offset instead of another near-invisible 1511.
        """
        motor = FakeMotor()
        controller = NavigationController(
            motor,
            NavConfig(
                track_lookahead_m=0.8,
                track_heading_block_deg=25.0,
                min_inner_wheel_speed=0.50,
            ),
        )
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.0002},
        ], mode='track', direction='forward')
        controller.start()
        try:
            controller.on_pose_update({
                'latitude': 52.0,
                'longitude': 10.0,
                'heading_deg': 113.0,
            })
            x, y, _ = motor.commands[-1]
            status = controller.get_status()
        finally:
            controller.shutdown()

        ratio = motor.pwm_config.turn_factor / motor.pwm_config.forward_factor
        left_pwm_offset = (y + x * ratio) * motor.pwm_config.forward_factor
        right_pwm_offset = (y - x * ratio) * motor.pwm_config.forward_factor
        self.assertTrue(status['limits']['track_aligning'])
        self.assertGreater(max(left_pwm_offset, right_pwm_offset), 50.0)

    def test_track_stall_stops_and_reports_missing_progress(self):
        motor = FakeMotor()
        controller = NavigationController(
            motor,
            NavConfig(
                track_stall_timeout_s=3.0,
                track_stall_min_progress_m=0.15,
            ),
        )
        controller.set_waypoints([
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.0002},
        ], mode='track', direction='forward')
        controller.start()
        try:
            pose = {'latitude': 52.0, 'longitude': 10.0, 'heading_deg': 90.0}
            controller.on_pose_update(pose)
            controller._track_stall_reference_time -= 3.1
            controller.on_pose_update(pose)
            status = controller.get_status()
        finally:
            controller.shutdown()

        self.assertFalse(status['running'])
        self.assertEqual('track_stall', status['state'])
        self.assertIn('ohne Track-Fortschritt', status['last_error'])
        self.assertEqual((0.0, 0.0, True), motor.commands[-1])

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

    def test_closed_track_does_not_complete_at_selected_start_point(self):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig(track_lookahead_m=1.0))
        ring = [
            {'latitude': 52.0, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.0001},
            {'latitude': 52.0001, 'longitude': 10.0001},
            {'latitude': 52.0001, 'longitude': 10.0},
            {'latitude': 52.0, 'longitude': 10.0},
        ]
        controller.set_waypoints(ring, mode='track')
        controller.start()
        try:
            controller.on_pose_update({
                'latitude': 52.0,
                'longitude': 10.0,
                'heading_deg': 90.0,
            })
            status = controller.get_status()
            command = motor.commands[-1]
        finally:
            controller.shutdown()

        self.assertTrue(status['running'])
        self.assertEqual(status['state'], 'running')
        self.assertGreater(command[1], 0.0)
        self.assertLess(status['limits']['track_progress_m'], 1.0)

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


class TrackStartHeadingErrorTests(unittest.TestCase):
    """Die Vorabpruefung muss dieselbe Zahl liefern wie der laufende Regler.

    Sonst prueft der Plan-Check gegen etwas anderes als das, woran die Fahrt
    spaeter scheitert - genau der Fehler, den er verhindern soll.
    """

    LANE = [[10.0, 52.0], [10.001, 52.0]]

    def _live_state(self, heading_deg, direction='forward'):
        motor = FakeMotor()
        controller = NavigationController(motor, NavConfig())
        controller.set_waypoints(
            [{'latitude': coord[1], 'longitude': coord[0]} for coord in self.LANE],
            mode='track',
            direction=direction,
        )
        controller.start()
        try:
            for _ in range(3):
                controller.on_pose_update({
                    'latitude': self.LANE[0][1],
                    'longitude': self.LANE[0][0],
                    'heading_deg': heading_deg,
                })
            return controller.get_status()
        finally:
            controller.shutdown()

    def test_matches_the_live_controller_on_both_sides_of_the_block(self):
        # Dieselben Posen wie in
        # test_track_heading_block_threshold_is_a_single_cutoff: 66 Grad
        # bleibt knapp unter der lokal auf 25 gesetzten Grenze, 64 Grad
        # darueber.
        below = NavigationController.track_start_heading_error_deg(
            self.LANE, 66.0, lookahead_m=NavConfig().track_lookahead_m
        )
        above = NavigationController.track_start_heading_error_deg(
            self.LANE, 64.0, lookahead_m=NavConfig().track_lookahead_m
        )

        self.assertAlmostEqual(below, 24.0, delta=0.5)
        self.assertAlmostEqual(above, 26.0, delta=0.5)
        self.assertLess(abs(below), NavConfig().track_heading_block_deg)
        self.assertGreaterEqual(abs(above), NavConfig().track_heading_block_deg)
        self.assertNotEqual('heading_block', self._live_state(66.0)['state'])
        self.assertEqual('heading_block', self._live_state(64.0)['state'])

    def test_reverse_lane_is_measured_against_the_reversed_nose(self):
        """Rueckwaerts zeigt die Nase entgegen der Bahnrichtung.

        Ohne die 180-Grad-Drehung meldete die Pruefung genau bei den Posen
        eine Sperre, die der Regler problemlos faehrt - und umgekehrt.
        """
        error = NavigationController.track_start_heading_error_deg(
            self.LANE, 270.0, direction='reverse',
            lookahead_m=NavConfig().track_lookahead_m,
        )

        self.assertAlmostEqual(error, 0.0, delta=0.5)
        self.assertNotEqual(
            'heading_block', self._live_state(270.0, direction='reverse')['state']
        )

    def test_degenerate_lane_reports_nothing_instead_of_a_bearing(self):
        """Ohne Ausdehnung ist die Peilung Rauschen - keine erfundene Sperre."""
        self.assertIsNone(
            NavigationController.track_start_heading_error_deg([[10.0, 52.0]], 0.0)
        )
        self.assertIsNone(
            NavigationController.track_start_heading_error_deg(
                [[10.0, 52.0], [10.0, 52.0]], 0.0
            )
        )


if __name__ == '__main__':
    unittest.main()
