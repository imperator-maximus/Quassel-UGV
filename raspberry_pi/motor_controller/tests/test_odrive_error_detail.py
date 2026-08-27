"""Ein Achsfehler soll sagen, woher er kommt.

``0x40`` ist auf Achsebene ``AXIS_ERROR_MOTOR_FAILED`` und damit ein
Sammelbegriff: Er heisst nur "das Motor-Objekt meldet einen Fehler", nicht
welchen. Am 27.08.2026 kam er mehrfach hintereinander, der Benutzer startete
jedes Mal neu, und die Frage nach dem Grund liess sich nicht beantworten - die
Ebene darunter wurde nie gelesen.

Gelesen wird sie nur, wenn ein Fehler anliegt: Jede Eigenschaft ist ein eigener
USB-Umlauf, und haengende Aufrufe sind an dieser Stelle das bekannte Problem.
"""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.hardware.odrive_mower import ODriveMowerController


class FehlerKlartextTests(unittest.TestCase):
    def test_ohne_einzelheiten_bleibt_die_meldung_wie_bisher(self):
        self.assertEqual(ODriveMowerController._format_error_detail(None), '')
        self.assertEqual(ODriveMowerController._format_error_detail({}), '')

    def test_nur_gesetzte_fehler_werden_genannt(self):
        """Nullen sind kein Befund und blaehen die Meldung nur auf."""
        text = ODriveMowerController._format_error_detail(
            {'motor': 0x1000, 'encoder': 0, 'sensorless': 0, 'board': None}
        )

        self.assertEqual(text, ' (motor=0x00001000)')

    def test_mehrere_ebenen_erscheinen_zusammen(self):
        text = ODriveMowerController._format_error_detail(
            {'motor': 0x10000, 'board': 0x02}
        )

        self.assertIn('motor=0x00010000', text)
        self.assertIn('board=0x00000002', text)


class HeartbeatMitEinzelheitenTests(unittest.TestCase):
    def _controller(self):
        from types import SimpleNamespace
        config = SimpleNamespace(
            enabled=True, node_id=0, node_ids=[0], default_rpm=500,
            min_rpm=500, max_rpm=5000, axis_state=5, ramp_rate_rpm_s=300,
            command_interval_s=0.1, heartbeat_timeout_s=1.0,
            transport='can',
        )
        return ODriveMowerController(config, can_handler=None)

    def test_einzelheiten_landen_im_klartext_des_fehlers(self):
        controller = self._controller()

        controller.on_heartbeat(0, 0x40, 1, {'motor': 0x1000})

        self.assertIn('motor=0x00001000', controller.last_error)
        self.assertEqual(
            controller.odrive_error_details[0], {'motor': 0x1000}
        )

    def test_ohne_fehler_bleibt_nichts_stehen(self):
        """Sonst haengt der Grund von gestern noch an der Anzeige von heute."""
        controller = self._controller()
        controller.on_heartbeat(0, 0x40, 1, {'motor': 0x1000})

        controller.on_heartbeat(0, 0, 1)

        self.assertNotIn(0, controller.odrive_error_details)

    def test_alter_aufruf_ohne_einzelheiten_funktioniert_weiter(self):
        """Der CAN-Weg liefert sie nicht - er darf davon nichts merken."""
        controller = self._controller()

        controller.on_heartbeat(0, 0x40, 1)

        self.assertIn('error=0x00000040', controller.last_error)
        self.assertEqual(controller.odrive_error_details[0], {})


if __name__ == '__main__':
    unittest.main()
