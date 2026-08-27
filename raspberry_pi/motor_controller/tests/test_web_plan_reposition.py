"""Neben der Bahn wird rangiert, nicht aufgegeben.

Am 27.08.2026 stand das Fahrzeug nach dem Ausrichtbogen parallel zu seiner
Bahn, aber 1,83 m daneben. Der Bahnregler kann seitlich heranziehen; mit 0,8 m
Vorausschau ist das aus knapp zwei Metern ein zaeher Fall, und er meldete
``cross_track_stop``. Ein Manoever, das genau dafuer da ist - meist rueckwaerts,
Sperrzonen beruecksichtigt - existiert seit langem, wurde aber nur beim
Zusammenstellen der Route benutzt und nie wieder danach.

Diese Tests halten fest, dass es jetzt auch waehrend der Fahrt greift, und wo
seine Grenzen liegen: Nach zwei Versuchen uebernimmt der Mensch, und ein Fehler,
der keine falsche Stellung beschreibt, wird nicht wegrangiert.
"""

import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.web.web_server import WebServer
from motor_controller.tests.web_test_support import web_config


class FakePlans:
    def __init__(self, anfahrt=None):
        self.anfahrt = anfahrt
        self.aufrufe = []

    @staticmethod
    def pose_rtk_ok(_pose):
        # Der Wartelauf prueft RTK; hier geht es um das Rangieren.
        return True

    def approach_segment_from_pose(self, plan, from_coord, target_coords, **kwargs):
        self.aufrufe.append({
            'from': from_coord,
            'ziel': target_coords[0] if target_coords else None,
            **kwargs,
        })
        return self.anfahrt


class FakeNavigation:
    def __init__(self):
        self.gefahren = []
        self.running = True

    def set_waypoints(self, waypoints, mode='goto', direction='forward'):
        self.gefahren.append((len(waypoints), mode, direction))
        return waypoints

    def start(self):
        return True

    def get_status(self):
        return {'running': False, 'state': 'completed', 'last_error': None}

    def stop(self, reason=None):
        self.running = False


ANFAHRT = {
    'type': 'positioning',
    'mode': 'track',
    'direction': 'reverse',
    'length_m': 2.4,
    'coordinates': [[11.0, 53.0], [11.0001, 53.0001]],
}

SEGMENT = {
    'type': 'mow',
    'source_index': 21,
    'direction': 'forward',
    'coordinates': [[11.001, 53.001], [11.002, 53.002]],
}


def build_server(anfahrt=None):
    dummy = SimpleNamespace()
    can = SimpleNamespace(
        get_sensor_data=lambda: {
            'gps': {'lat': 53.0, 'lon': 11.0}, 'heading': 42.0
        },
        get_status=lambda **_kwargs: {'odrives': {}, 'sensor_hub': {}},
    )
    motor = SimpleNamespace(
        get_status=lambda: {'current_pwm': {'left': 1500, 'right': 1500}}
    )
    joystick = SimpleNamespace(get_status=lambda: {'enabled': False, 'max_speed': 100})
    server = WebServer(web_config(), motor, joystick, can, dummy)
    server.mapping = SimpleNamespace(plans=FakePlans(anfahrt))
    server.navigation = FakeNavigation()
    return server


class RangierenTests(unittest.TestCase):
    def test_die_anfahrt_wird_aus_der_aktuellen_pose_gebaut(self):
        server = build_server(ANFAHRT)

        self.assertTrue(
            server._reposition_to_segment(SEGMENT, {}, None, 1)
        )

        aufruf = server.mapping.plans.aufrufe[0]
        self.assertEqual([11.0, 53.0], aufruf['from'])
        self.assertEqual(SEGMENT['coordinates'][0], aufruf['ziel'])
        self.assertEqual(42.0, aufruf['start_heading_deg'])
        self.assertEqual(21, aufruf['to_segment_index'])

    def test_der_rangierweg_wird_auch_gefahren(self):
        """Rueckwaerts ist dabei der Normalfall, nicht die Ausnahme."""
        server = build_server(ANFAHRT)

        server._reposition_to_segment(SEGMENT, {}, None, 1)

        self.assertEqual([(2, 'track', 'reverse')], server.navigation.gefahren)

    def test_ohne_konstruierbaren_weg_bleibt_der_fehler_stehen(self):
        """Lieber ehrlich melden als blind losfahren."""
        server = build_server(None)

        self.assertFalse(
            server._reposition_to_segment(SEGMENT, {}, None, 1)
        )
        self.assertEqual([], server.navigation.gefahren)

    def test_ohne_pose_wird_nicht_rangiert(self):
        server = build_server(ANFAHRT)
        server.can.get_sensor_data = lambda: {'gps': {}}

        self.assertFalse(
            server._reposition_to_segment(SEGMENT, {}, None, 1)
        )

    def test_nur_stellungsfehler_werden_wegrangiert(self):
        """Ein Mähdeckfehler oder eine Sperrzone ist keine falsche Stellung -
        da hilft kein Manoever."""
        self.assertIn('cross_track_stop', WebServer.PLAN_REPOSITION_STATES)
        self.assertIn('heading_block', WebServer.PLAN_REPOSITION_STATES)
        self.assertNotIn('nogo_stop', WebServer.PLAN_REPOSITION_STATES)
        self.assertNotIn('mower_fault', WebServer.PLAN_REPOSITION_STATES)
        self.assertNotIn('safety_stop', WebServer.PLAN_REPOSITION_STATES)

    def test_die_versuche_sind_begrenzt(self):
        """Ohne Grenze wuerde ein Fahrzeug, das den Bahnanfang nicht erreicht,
        endlos hin und her setzen."""
        self.assertGreaterEqual(WebServer.PLAN_REPOSITION_ATTEMPTS, 1)
        self.assertLessEqual(WebServer.PLAN_REPOSITION_ATTEMPTS, 3)

    def test_rangieren_ist_keine_stoerung(self):
        """Sonst kommt bei jedem Manoever eine Push-Meldung."""
        self.assertIn('repositioning', WebServer.QUIET_PLAN_STATES)


if __name__ == '__main__':
    unittest.main()
