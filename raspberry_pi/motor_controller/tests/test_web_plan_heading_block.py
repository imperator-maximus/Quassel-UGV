"""Vorabpruefung der Winkelsperre im Plan-Check.

Der Regler stoppt jede Bahn, deren Winkelfehler am Anfang
``track_heading_block_deg`` erreicht. Bis dahin lief Play an, das Fahrzeug
fuhr bis zur Stelle und blieb auf der Flaeche stehen. Die Pruefung sitzt im
Web-Server, weil nur dort Plan und Navigationskonfiguration zusammenliegen.
"""

import math
import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.mapping.plan_manager import MowingPlanManager
from motor_controller.web.web_server import WebServer

ORIGIN_LAT = 52.0
ORIGIN_LON = 10.0


def coord(east_m, north_m):
    """Lon/Lat aus Metern - derselbe Massstab wie in ``_offset_coord``."""
    return [
        ORIGIN_LON + east_m / (111320.0 * math.cos(math.radians(ORIGIN_LAT))),
        ORIGIN_LAT + north_m / 111320.0,
    ]


def lane(source_index, start, end, direction='forward'):
    return {
        'type': 'mow',
        'source_type': 'rest_lane',
        'source_index': source_index,
        'mode': 'track',
        'direction': direction,
        'coordinates': [start, end],
        'length_m': 10.0,
    }


def transfer(start, end):
    return {
        'type': 'transition',
        'source_index': None,
        'mode': 'track',
        'direction': 'forward',
        'route_kind': 'runtime_direct',
        'coordinates': [start, end],
        'length_m': 1.0,
    }


class FakeNavigation:
    def __init__(self, block_deg=45.0, lookahead_m=0.8):
        self.config = SimpleNamespace(track_lookahead_m=lookahead_m)
        self._block_deg = block_deg

    def get_status(self):
        # Der Regler clampt track_heading_block_deg auf 10..60 und meldet den
        # geclampten Wert unter 'limits'. Der Check muss diesen Wert nehmen,
        # nicht den rohen Konfigurationswert.
        return {'limits': {'track_heading_block_deg': self._block_deg}}


class HeadingBlockCheckTests(unittest.TestCase):
    def setUp(self):
        config = SimpleNamespace(template_folder='.', static_folder='.', secret_key='test')
        dummy = SimpleNamespace()
        self.server = WebServer(config, dummy, dummy, dummy, dummy)
        self.server.navigation = FakeNavigation()
        self.server.mapping = SimpleNamespace(plans=MowingPlanManager('/tmp/maps'))
        # Fahrzeug steht am Anfang der ersten Bahn und schaut nach Osten.
        self.pose = {'latitude': ORIGIN_LAT, 'longitude': ORIGIN_LON, 'heading_deg': 90.0}

    def _result(self, segments):
        return {'success': True, 'errors': [], 'warnings': [], 'executable_segments': segments}

    def test_aligned_route_produces_neither_error_nor_warning(self):
        segments = [
            lane(0, coord(0.0, 0.0), coord(10.0, 0.0)),
            lane(1, coord(10.0, 0.0), coord(20.0, 0.0)),
        ]
        result = self._result(segments)

        self.server._apply_heading_block_check(result, self.pose)

        self.assertTrue(result['success'])
        self.assertEqual([], result['errors'])
        self.assertEqual([], result['warnings'])
        self.assertNotIn('heading_blocks', result)

    def test_block_after_the_first_lane_warns_and_names_segment_and_angle(self):
        """Ein Plan, der weitgehend faehrt, darf nicht komplett gesperrt sein.

        Brunnen hat mehrere solcher Stellen bei sonst intakter Route - ein
        harter Fehler pro Stelle haette den ganzen Plan unstartbar gemacht.
        """
        segments = [
            lane(0, coord(0.0, 0.0), coord(10.0, 0.0)),
            # Bahn 1 laeuft nach Norden, das Fahrzeug kommt nach Osten an: 90°.
            lane(1, coord(10.0, 0.0), coord(10.0, 10.0)),
        ]
        result = self._result(segments)

        self.server._apply_heading_block_check(result, self.pose)

        self.assertTrue(result['success'])
        self.assertEqual([], result['errors'])
        self.assertEqual(1, len(result['warnings']))
        warning = result['warnings'][0]
        self.assertIn('Bahn 1', warning)
        self.assertIn('45', warning)
        # Vorzeichen wie beim Regler: nach Norden abknickend, Fahrzeug nach
        # Osten - das ist eine Drehung nach links.
        self.assertIn('-90.0°', warning)
        self.assertEqual([1], [item['route_index'] for item in result['heading_blocks']])

    def test_block_at_the_first_lane_rejects_play(self):
        """Sperrt schon die erste Bahn, bringt der Start nichts - 0 statt 95%."""
        segments = [
            lane(0, coord(0.0, 0.0), coord(0.0, 10.0)),
            lane(1, coord(0.0, 10.0), coord(10.0, 10.0)),
        ]
        result = self._result(segments)

        self.server._apply_heading_block_check(result, self.pose)

        self.assertFalse(result['success'])
        self.assertEqual([], result['warnings'])
        self.assertEqual(1, len(result['errors']))
        self.assertIn('vor der ersten', result['errors'][0])
        self.assertIn('Bahn 0', result['errors'][0])

    def test_blocked_transfer_before_the_first_lane_rejects_play(self):
        segments = [
            transfer(coord(0.0, 0.0), coord(0.0, 2.0)),
            lane(0, coord(0.0, 2.0), coord(0.0, 12.0)),
        ]
        result = self._result(segments)

        self.server._apply_heading_block_check(result, self.pose)

        self.assertFalse(result['success'])
        self.assertIn('Übergang zu Bahn 0', result['errors'][0])

    def test_goto_segments_are_not_checked(self):
        """Die Sperre sitzt hinter der Verzweigung auf mode == 'track'."""
        segments = [
            {
                'type': 'positioning',
                'source_type': 'rest_lane',
                'source_index': None,
                'mode': 'goto',
                'direction': 'forward',
                'coordinates': [coord(0.0, 5.0)],
                'length_m': 0.0,
            },
            lane(0, coord(0.0, 5.0), coord(10.0, 5.0)),
        ]
        result = self._result(segments)

        self.server._apply_heading_block_check(result, self.pose)

        self.assertTrue(result['success'])
        self.assertEqual([], result['warnings'])

    def test_reverse_lane_is_judged_by_the_nose_not_the_lane_direction(self):
        """Die Bahn laeuft nach Westen, gefahren wird sie rueckwaerts.

        Die Nase bleibt damit nach Osten gerichtet - kein Winkelfehler. Ohne
        die 180-Grad-Drehung haette der Check hier 180° gemeldet und jeden
        Serpentinenplan gesperrt.
        """
        segments = [
            lane(0, coord(10.0, 0.0), coord(0.0, 0.0), direction='reverse'),
        ]
        result = self._result(segments)

        self.server._apply_heading_block_check(result, self.pose)

        self.assertTrue(result['success'])
        self.assertEqual([], result['warnings'])

    def test_limit_follows_the_controller_configuration(self):
        """Nicht 45 als Konstante: geprueft wird gegen den Wert des Reglers."""
        segments = [
            lane(0, coord(0.0, 0.0), coord(10.0, 0.0)),
            # 30° Knick - unter 45, aber ueber einer engeren Reglergrenze.
            lane(1, coord(10.0, 0.0), coord(18.66, 5.0)),
        ]

        default_limit = self._result([dict(item) for item in segments])
        self.server._apply_heading_block_check(default_limit, self.pose)
        self.assertEqual([], default_limit['warnings'])

        self.server.navigation = FakeNavigation(block_deg=25.0)
        tight_limit = self._result([dict(item) for item in segments])
        self.server._apply_heading_block_check(tight_limit, self.pose)
        self.assertEqual(1, len(tight_limit['warnings']))
        self.assertIn('25', tight_limit['warnings'][0])

    def test_missing_navigation_leaves_the_result_untouched(self):
        self.server.navigation = None
        result = self._result([lane(0, coord(0.0, 0.0), coord(0.0, 10.0))])

        self.server._apply_heading_block_check(result, self.pose)

        self.assertTrue(result['success'])
        self.assertEqual([], result['errors'])
        self.assertEqual([], result['warnings'])

    def test_already_failed_check_is_not_overwritten(self):
        result = self._result([lane(0, coord(0.0, 0.0), coord(0.0, 10.0))])
        result['success'] = False
        result['errors'] = ['RTK nicht verfügbar: unbekannt']

        self.server._apply_heading_block_check(result, self.pose)

        self.assertEqual(['RTK nicht verfügbar: unbekannt'], result['errors'])

    def test_pose_without_heading_reports_nothing(self):
        """Ohne gemessenen Kurs fehlt das erste Glied der Kette."""
        result = self._result([lane(0, coord(0.0, 0.0), coord(0.0, 10.0))])

        self.server._apply_heading_block_check(
            result, {'latitude': ORIGIN_LAT, 'longitude': ORIGIN_LON}
        )

        self.assertTrue(result['success'])
        self.assertEqual([], result['warnings'])


if __name__ == '__main__':
    unittest.main()
