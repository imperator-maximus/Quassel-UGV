"""Der Max-Speed-Regler muss die manuelle Fahrt tatsaechlich begrenzen.

Die Kette Schieberegler -> WebSocket -> ``set_max_speed`` war vollstaendig
vorhanden, der Wert wurde gespeichert, geloggt und im Status gemeldet - nur
angewendet wurde er nie: ``update`` reichte die rohe Knueppelstellung an den
Antrieb weiter. Der Regler hatte damit keinerlei Wirkung.
"""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.control.joystick_handler import JoystickHandler


class FakeMotor:
    def __init__(self):
        self.commands = []
        self.stops = 0

    def set_joystick(self, x, y, use_ramping=False):
        self.commands.append((x, y, use_ramping))

    def emergency_stop(self):
        self.stops += 1


class FakeSafety:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.updates = 0

    def is_motion_allowed(self):
        return self.allowed

    def update_joystick_time(self):
        self.updates += 1


class JoystickMaxSpeedTests(unittest.TestCase):
    def setUp(self):
        self.motor = FakeMotor()
        self.safety = FakeSafety()

    def test_full_speed_passes_the_stick_through_unchanged(self):
        handler = JoystickHandler(self.motor, self.safety)

        handler.update(0.5, -1.0)

        self.assertEqual((0.5, -1.0, False), self.motor.commands[-1])

    def test_half_speed_halves_the_drive_command(self):
        handler = JoystickHandler(self.motor, self.safety)
        handler.set_max_speed(50)

        handler.update(0.8, -0.6)

        x, y, _ = self.motor.commands[-1]
        self.assertAlmostEqual(0.4, x)
        self.assertAlmostEqual(-0.3, y)

    def test_limit_applies_to_both_axes_including_turning(self):
        handler = JoystickHandler(self.motor, self.safety)
        handler.set_max_speed(25)

        handler.update(1.0, 1.0)

        x, y, _ = self.motor.commands[-1]
        self.assertAlmostEqual(0.25, x)
        self.assertAlmostEqual(0.25, y)

    def test_zero_percent_stops_the_vehicle(self):
        handler = JoystickHandler(self.motor, self.safety)
        handler.set_max_speed(0)

        handler.update(1.0, 1.0)

        self.assertEqual((0.0, 0.0, False), self.motor.commands[-1])

    def test_reported_position_stays_the_raw_stick(self):
        """Die Anzeige soll zeigen, wohin gezogen wurde - nicht das Ergebnis."""
        handler = JoystickHandler(self.motor, self.safety)
        handler.set_max_speed(40)

        handler.update(1.0, -1.0)

        self.assertEqual((1.0, -1.0), handler.get_position())
        self.assertEqual(40.0, handler.get_status()['max_speed'])

    def test_initial_limit_comes_from_the_configuration(self):
        """Regler und Fahrzeug muessen von Anfang an denselben Wert meinen."""
        handler = JoystickHandler(self.motor, self.safety, max_speed=20.0)

        handler.update(1.0, 1.0)

        x, y, _ = self.motor.commands[-1]
        self.assertAlmostEqual(0.2, x)
        self.assertAlmostEqual(0.2, y)
        self.assertEqual(20.0, handler.get_status()['max_speed'])

    def test_limit_is_clamped_to_the_valid_range(self):
        handler = JoystickHandler(self.motor, self.safety, max_speed=250.0)
        self.assertEqual(100.0, handler.get_status()['max_speed'])

        handler.set_max_speed(-10)
        self.assertEqual(0.0, handler.get_status()['max_speed'])

    def test_latched_safety_stop_still_wins_over_the_limit(self):
        handler = JoystickHandler(self.motor, FakeSafety(allowed=False))

        self.assertFalse(handler.update(1.0, 1.0))
        self.assertEqual([], self.motor.commands)


if __name__ == '__main__':
    unittest.main()
