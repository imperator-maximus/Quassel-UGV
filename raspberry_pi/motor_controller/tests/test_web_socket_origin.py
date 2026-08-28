"""Wer den Steuerkanal oeffnen darf.

Am 27.08.2026 stand das Fahrzeug 200 m entfernt, die Oberflaeche liess sich
ueber die alte Portfreigabe noch aufrufen - aber kein Fahrbefehl kam an. Der
Grund stand nur im Log des Fahrzeugs:

    engineio.server - ERROR - http://schloss.fdog.de:8080 is not an accepted origin.

Eine Liste erlaubter Herkuenfte **ersetzt** in engineio die Vorgabe "nur die
eigene Herkunft". Mit dem Eintrag fuer den neuen Reverse-Proxy fiel deshalb
stillschweigend jeder andere Weg zum Fahrzeug aus - und zwar so, dass die
Seite gesund aussah und nur der Joystick tot war.

Diese Tests halten beides fest: dass jeder Weg zum Fahrzeug selbst weiter
funktioniert, und dass fremde Seiten trotzdem draussen bleiben.
"""

import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.web.web_server import WebServer
from motor_controller.tests.web_test_support import web_config


def build_server(**config_overrides):
    dummy = SimpleNamespace()
    can = SimpleNamespace(
        get_sensor_data=lambda: {},
        get_status=lambda **_kwargs: {'online': True, 'age_s': 0.1, 'source': {}},
    )
    motor = SimpleNamespace(
        get_status=lambda: {'current_pwm': {'left': 1500, 'right': 1500}}
    )
    joystick = SimpleNamespace(get_status=lambda: {'enabled': False, 'max_speed': 100})
    return WebServer(web_config(**config_overrides), motor, joystick, can, dummy)


class SteuerkanalHerkunftTests(unittest.TestCase):
    def setUp(self):
        self.server = build_server(
            allowed_origins=['https://schloss.fdog.de:8443']
        )

    def erlaubt(self, origin, host):
        return self.server._socket_origin_allowed(origin, {'HTTP_HOST': host})

    def test_die_alte_portfreigabe_bleibt_bedienbar(self):
        """Der Rueckfall auf das alte Netz ist der Moment, in dem man das
        Fahrzeug am dringendsten steuern will."""
        self.assertTrue(
            self.erlaubt('http://schloss.fdog.de:8080', 'schloss.fdog.de:8080')
        )

    def test_der_reverse_proxy_ist_erlaubt(self):
        self.assertTrue(
            self.erlaubt('https://schloss.fdog.de:8443', 'schloss.fdog.de:8443')
        )

    def test_das_schema_darf_sich_unterscheiden(self):
        """Hinter einem TLS-Reverse-Proxy kommt die Anfrage unverschluesselt
        an; der Browser meldet trotzdem https."""
        self.assertTrue(
            self.erlaubt('https://raspberrycan', 'raspberrycan')
        )

    def test_zugang_im_heimnetz_ueber_die_ip(self):
        """Adressen aendern sich mit dem Netz - sie koennen nicht in einer
        Liste stehen, und muessen trotzdem funktionieren."""
        self.assertTrue(
            self.erlaubt('http://192.168.8.102', '192.168.8.102')
        )

    def test_konfigurierte_herkunft_gilt_auch_bei_umgeschriebenem_host(self):
        """Ein Reverse-Proxy darf den Host-Kopf auf sein eigenes Ziel setzen.
        Dann rettet nur der ausdrueckliche Eintrag den Steuerkanal."""
        self.assertTrue(
            self.erlaubt('https://schloss.fdog.de:8443', 'localhost:18080')
        )

    def test_fremde_seite_bleibt_draussen(self):
        """Der Browser haengt die Anmeldung auch an Anfragen, die eine fremde
        Seite ausloest. Ohne diese Pruefung koennte sie das Fahrzeug fahren."""
        self.assertFalse(
            self.erlaubt('https://boese.example', 'schloss.fdog.de:8080')
        )

    def test_ein_anderer_port_desselben_hosts_ist_fremd(self):
        """Port 8081 fuehrt zum SensorHub, nicht zum Fahrzeug - das sind
        verschiedene Dienste."""
        self.assertFalse(
            self.erlaubt('http://schloss.fdog.de:8081', 'schloss.fdog.de:8080')
        )

    def test_ohne_origin_entscheidet_die_anmeldung(self):
        """Nicht-Browser senden keinen Origin und koennen keine fremden
        Zugangsdaten mitbringen."""
        self.assertTrue(self.erlaubt('', 'schloss.fdog.de:8080'))
        self.assertTrue(self.server._socket_origin_allowed(None))

    def test_ohne_umgebung_bleibt_nur_die_liste(self):
        """engineio ruft die Funktion in aelteren Fassungen ohne environ auf."""
        self.assertTrue(
            self.server._socket_origin_allowed('https://schloss.fdog.de:8443')
        )
        self.assertFalse(
            self.server._socket_origin_allowed('http://schloss.fdog.de:8080')
        )


if __name__ == '__main__':
    unittest.main()
