"""Das Fahrsignal kommt jetzt als Soft-PWM aus pigpio.

Hardware-PWM gibt es auf dem Pi nur an GPIO 12/13/18/19, und diese Pins
werden anderweitig gebraucht. pigpio erzeugt die Servopulse per DMA und ist
dabei nicht an bestimmte Pins gebunden. Nach aussen bleibt alles beim Alten:
Der Wert ist eine Pulsbreite in Mikrosekunden.

Diese Tests halten fest, was dabei nicht verrutschen darf - dass wirklich
Servopulse gesendet werden, dass die Grenzen greifen und dass ein Wert, den
pigpio abweisen wuerde, gar nicht erst dort ankommt. Ein abgewiesener Puls
waere kein Stillstand, sondern ein Motor, der mit dem alten Wert weiterlaeuft.
"""

import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.hardware.pwm_controller import PWMController


def pwm_config(**overrides):
    config = dict(
        enabled=True,
        pins={'left': 19, 'right': 18},
        frequency=50,
        neutral_value=1500,
        min_value=1000,
        max_value=2000,
        forward_factor=500.0,
        turn_factor=300.0,
    )
    config.update(overrides)
    return SimpleNamespace(**config)


class FakePigpio:
    """Merkt sich die Pulse und faellt um, wenn pigpio es auch taete."""

    def __init__(self):
        self.pulses = []
        self.hardware_calls = []

    def set_servo_pulsewidth(self, pin, value):
        if value != 0 and not (500 <= value <= 2500):
            raise ValueError(f'pigpio weist {value} us ab')
        self.pulses.append((pin, value))

    def hardware_PWM(self, pin, frequency, duty):  # noqa: N802 - pigpio-Name
        self.hardware_calls.append((pin, frequency, duty))

    def last_for(self, pin):
        for got_pin, value in reversed(self.pulses):
            if got_pin == pin:
                return value
        return None


class FakeGpio:
    def __init__(self, pi):
        self._pi = pi

    def get_pigpio(self):
        return self._pi


def build(**overrides):
    pi = FakePigpio()
    return PWMController(pwm_config(**overrides), FakeGpio(pi)), pi


class StartingUpTests(unittest.TestCase):
    def test_both_sides_start_at_neutral(self):
        _controller, pi = build()
        self.assertEqual(pi.last_for(19), 1500)
        self.assertEqual(pi.last_for(18), 1500)

    def test_the_hardware_channels_stay_untouched(self):
        """Der ganze Zweck des Umbaus: keine Bindung an GPIO 12/13/18/19."""
        controller, pi = build()
        controller.set_motor_pwm_both(1400, 1600)
        self.assertEqual(pi.hardware_calls, [])

    def test_without_pigpio_the_motors_are_disabled(self):
        controller = PWMController(pwm_config(), FakeGpio(None))
        self.assertFalse(controller.motor_enabled)
        self.assertFalse(controller.set_motor_pwm('left', 1600))


class SendingValuesTests(unittest.TestCase):
    def test_a_value_reaches_the_pin_of_its_side(self):
        controller, pi = build()
        controller.set_motor_pwm_both(1400, 1600)
        self.assertEqual(pi.last_for(19), 1400)
        self.assertEqual(pi.last_for(18), 1600)
        self.assertEqual(controller.get_motor_pwm_both(), {'left': 1400, 'right': 1600})

    def test_values_beyond_the_configured_range_are_clamped(self):
        controller, pi = build()
        controller.set_motor_pwm('left', 2500)
        self.assertEqual(pi.last_for(19), 2000)
        controller.set_motor_pwm('left', 200)
        self.assertEqual(pi.last_for(19), 1000)

    def test_a_configuration_pigpio_would_refuse_is_caught_first(self):
        """Sonst weist pigpio den Puls ab - und der Motor liefe weiter."""
        controller, pi = build(min_value=200, max_value=3000)
        self.assertTrue(controller.set_motor_pwm('left', 200))
        self.assertEqual(pi.last_for(19), 500)
        self.assertTrue(controller.set_motor_pwm('left', 3000))
        self.assertEqual(pi.last_for(19), 2500)

    def test_an_unknown_side_is_refused(self):
        controller, _pi = build()
        self.assertFalse(controller.set_motor_pwm('mitte', 1500))


class StoppingTests(unittest.TestCase):
    def test_neutral_puts_both_sides_back(self):
        controller, pi = build()
        controller.set_motor_pwm_both(1400, 1600)
        controller.set_motor_neutral()
        self.assertEqual(pi.last_for(19), 1500)
        self.assertEqual(pi.last_for(18), 1500)

    def test_cleanup_leaves_the_vehicle_at_neutral(self):
        """Bewusst Neutral und nicht "Pulse aus": Was eine Endstufe ohne
        Signal tut, steht in ihrem Handbuch - und das gibt es zu dieser
        nicht. Ein Neutralpuls ist der Zustand, den wir kennen.
        """
        controller, pi = build()
        controller.set_motor_pwm_both(1700, 1700)
        controller.cleanup()
        self.assertEqual(pi.last_for(19), 1500)
        self.assertEqual(pi.last_for(18), 1500)


if __name__ == '__main__':
    unittest.main()
