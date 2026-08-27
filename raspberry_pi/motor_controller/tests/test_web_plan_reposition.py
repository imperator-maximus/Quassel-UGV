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

from motor_controller.mapping.plan_manager import MowingPlanManager
from motor_controller.web.web_server import WebServer
from motor_controller.tests.web_test_support import web_config


class FakePlans:
    def __init__(self, anfahrt=None, manoever=None):
        self.anfahrt = anfahrt
        self.manoever = manoever
        self.aufrufe = []
        self.manoever_aufrufe = []

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

    def turn_legs_from_pose(self, plan, from_coord, start_heading_deg, target_heading_deg):
        self.manoever_aufrufe.append({
            'from': from_coord,
            'heading': start_heading_deg,
            'ziel': target_heading_deg,
        })
        return self.manoever

    # Der Zielkurs wird nicht nachgebaut: Wonach gedreht wird, entscheidet
    # dieselbe Rechnung wie im Betrieb.
    segment_entry_heading = staticmethod(MowingPlanManager.segment_entry_heading)


class FakeNavigation:
    def __init__(self):
        self.gefahren = []
        self.running = True
        # Dieselbe Sperre, die der Regler fährt. Ohne sie kann der Webserver
        # nicht vorab wissen, welcher Zug gar nicht erst anläuft.
        self.config = SimpleNamespace(track_lookahead_m=0.8)

    def set_waypoints(self, waypoints, mode='goto', direction='forward'):
        self.gefahren.append((len(waypoints), mode, direction))
        return waypoints

    def start(self):
        return True

    def get_status(self):
        return {
            'running': False,
            'state': 'completed',
            'last_error': None,
            'limits': {'track_heading_block_deg': 45.0},
        }

    def stop(self, reason=None):
        self.running = False


# Rueckwaerts an den Bahnanfang. Der Weg fuehrt nach Suedwesten, das Fahrzeug
# steht mit der Nase auf 42° - so faehrt es rueckwaerts geradeaus, und der
# Kursfehler zur Bahn bleibt bei -14°. Vorher stand hier ein Weg nach
# Nordosten: den haette der Regler mit 169° sofort gesperrt, was der Test
# nicht bemerkte, weil er die Sperre gar nicht kannte.
ANFAHRT = {
    'type': 'positioning',
    'mode': 'track',
    'direction': 'reverse',
    'length_m': 2.4,
    'coordinates': [[11.0, 53.0], [10.99993, 52.99992]],
}

# Eine Anfahrt, die genau in die Gegenrichtung losfaehrt: 164,6° Kursfehler
# bei einem Fahrzeugkurs von 42°. Der Regler sperrt sie nach drei Posen.
ANFAHRT_GESPERRT = {
    'type': 'positioning',
    'mode': 'track',
    'direction': 'forward',
    'length_m': 0.38,
    'coordinates': [[11.0, 53.0], [10.9999, 52.99988]],
}

# Vor und zurueck, bis die Nase passt.
MANOEVER = [
    {
        'type': 'transition',
        'mode': 'track',
        'direction': 'forward',
        'route_kind': 'shunt_turn',
        'length_m': 3.14,
        'coordinates': [[11.0, 53.0], [11.00005, 53.00006]],
    },
    {
        'type': 'transition',
        'mode': 'track',
        'direction': 'reverse',
        'route_kind': 'shunt_turn',
        'length_m': 3.14,
        'coordinates': [[11.00005, 53.00006], [11.0001, 53.0001]],
    },
]

SEGMENT = {
    'type': 'mow',
    'source_index': 21,
    'direction': 'forward',
    'coordinates': [[11.001, 53.001], [11.002, 53.002]],
}


def build_server(anfahrt=None, manoever=None):
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
    server.mapping = SimpleNamespace(plans=FakePlans(anfahrt, manoever))
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

    def test_eine_gesperrte_anfahrt_wird_zum_wendemanoever(self):
        """Der Fall vom 27.08., 23:15 Uhr.

        Das Fahrzeug stand auf dem Bahnanfang, nur um 160° verdreht. Es bekam
        zweimal eine gerade Anfahrt, die der Regler nach je drei Posen wieder
        sperrte - gedreht hat sich dabei nichts, und danach stand der Plan.
        Eine Anfahrt, die der Regler sofort sperrt, ist kein Rangierweg.
        """
        server = build_server(ANFAHRT_GESPERRT, MANOEVER)

        self.assertTrue(server._reposition_to_segment(SEGMENT, {}, None, 1))

        self.assertEqual(
            [(2, 'track', 'forward'), (2, 'track', 'reverse')],
            server.navigation.gefahren,
        )
        self.assertEqual(42.0, server.mapping.plans.manoever_aufrufe[0]['heading'])

    def test_eine_anfahrt_ohne_laenge_ist_kein_rangierweg(self):
        """Der zweite Anlauf vom 27.08.: 0,38 m vom Standpunkt zum Standpunkt.

        Steht das Fahrzeug auf dem Bahnanfang, fuehrt die gebaute Anfahrt von
        diesem Punkt zu diesem Punkt. Gefahren aendert sie nichts, und der
        naechste Anlauf laeuft in dieselbe Sperre - so wurden aus zwei
        Versuchen zwei verlorene.
        """
        nullweg = dict(ANFAHRT, length_m=0.38)
        server = build_server(nullweg, MANOEVER)

        self.assertTrue(server._reposition_to_segment(SEGMENT, {}, None, 1))

        self.assertEqual(
            [(2, 'track', 'forward'), (2, 'track', 'reverse')],
            server.navigation.gefahren,
        )

    def test_ohne_anfahrt_wird_auf_die_bahn_gedreht(self):
        """Ohne Anfahrt gibt das Segment selbst den Zielkurs vor."""
        server = build_server(None, MANOEVER)

        self.assertTrue(server._reposition_to_segment(SEGMENT, {}, None, 1))

        ziel = server.mapping.plans.manoever_aufrufe[0]['ziel']
        self.assertAlmostEqual(
            MowingPlanManager.segment_entry_heading(
                SEGMENT['coordinates'], SEGMENT['direction']
            ),
            ziel,
        )

    def test_eine_fahrbare_anfahrt_bleibt_die_anfahrt(self):
        """Rangiert wird nur, wo es noetig ist - sonst kostet es nur Weg."""
        server = build_server(ANFAHRT, MANOEVER)

        self.assertTrue(server._reposition_to_segment(SEGMENT, {}, None, 1))

        self.assertEqual([(2, 'track', 'reverse')], server.navigation.gefahren)
        self.assertEqual([], server.mapping.plans.manoever_aufrufe)

    def test_ohne_manoever_wird_die_gesperrte_anfahrt_nicht_gefahren(self):
        """Sie noch einmal zu fahren hiesse, denselben Abbruch zu erzeugen."""
        server = build_server(ANFAHRT_GESPERRT, None)

        self.assertFalse(server._reposition_to_segment(SEGMENT, {}, None, 1))
        self.assertEqual([], server.navigation.gefahren)

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
