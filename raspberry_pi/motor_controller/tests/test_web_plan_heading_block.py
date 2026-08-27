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

    def test_grosser_winkel_an_der_ersten_bahn_verhindert_den_start_nicht(self):
        """Bis zum 27.08.2026 wurde hier abgelehnt, weil der Regler nach drei
        Posen stoppte - ein Drittel einer Sekunde, kuerzer als jede Drehung.
        Er dreht jetzt ein und stoppt nur, wenn der Winkel dabei nicht kleiner
        wird. Das kann diese Pruefung aus geplanten Kursen nicht vorhersagen,
        also meldet sie es und laesst fahren."""
        segments = [
            lane(0, coord(0.0, 0.0), coord(0.0, 10.0)),
            lane(1, coord(0.0, 10.0), coord(10.0, 10.0)),
        ]
        result = self._result(segments)

        self.server._apply_heading_block_check(result, self.pose)

        self.assertTrue(result['success'])
        self.assertEqual([], result['errors'])
        self.assertEqual(1, len(result['warnings']))
        self.assertIn('Bahn 0', result['warnings'][0])
        self.assertIn('Einlenken', result['warnings'][0])

    def test_grosser_winkel_am_uebergang_verhindert_den_start_nicht(self):
        segments = [
            transfer(coord(0.0, 0.0), coord(0.0, 2.0)),
            lane(0, coord(0.0, 2.0), coord(0.0, 12.0)),
        ]
        result = self._result(segments)

        self.server._apply_heading_block_check(result, self.pose)

        self.assertTrue(result['success'])
        self.assertIn('Übergang zu Bahn 0', result['warnings'][0])

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


class ResumeCheckTargetsTheResumePointTests(unittest.TestCase):
    """Der Vorabcheck muss die Route pruefen, die auch gefahren wird.

    07.08.: Fahrzeug stand bei Bahn 65, "Fortsetzen" wurde zweimal abgelehnt
    mit "Anfahrt zu Bahn 0 +49.8 Grad" - der Check lief ueber den ganzen Plan
    ab Bahn 0, die Ausfuehrung waere ab Bahn 65 gefahren.
    """

    def setUp(self):
        config = SimpleNamespace(
            template_folder='.', static_folder='.', secret_key='test',
        )
        dummy = SimpleNamespace()
        self.server = WebServer(config, dummy, dummy, dummy, dummy)
        self.plan = {'sequence': [
            {'segment_index': 0, 'type': 'rest_lane'},
            {'segment_index': 65, 'type': 'rest_lane'},
            {'segment_index': 70, 'type': 'rest_lane'},
        ]}
        self.server.mapping = SimpleNamespace(
            load_plan=lambda name: {'success': True, 'plan': self.plan}
        )

    def test_resume_point_is_resolved_from_the_saved_state(self):
        self.server._load_resume_state = lambda name: {
            'source_segment_index': 65,
            'current_segment': {'type': 'mow'},
        }

        self.assertEqual(self.server._resume_start_segment_index('Wiese'), 65)

    def test_without_resume_state_nothing_is_forced(self):
        self.server._load_resume_state = lambda name: None

        self.assertIsNone(self.server._resume_start_segment_index('Wiese'))

    def test_transition_resume_advances_to_the_next_source_segment(self):
        """Denselben Uebergang erneut zu maehen waere eine wiederholte Bahn."""
        self.server._load_resume_state = lambda name: {
            'source_segment_index': 65,
            'current_segment': {'type': 'transition'},
        }

        self.assertEqual(self.server._resume_start_segment_index('Wiese'), 70)

    def test_frontend_tells_the_check_that_it_is_resuming(self):
        script = (
            Path(__file__).resolve().parents[2] / 'static' / 'js' / 'mapping_editor.js'
        ).read_text(encoding='utf-8')
        check_call = script[script.index('plan/check'):][:700]

        self.assertIn('resume: useResume === true', check_call)


class StopReasonSurvivesARestartTests(unittest.TestCase):
    """Ein Sicherheitsstopp beendet den Prozess - der Grund darf nicht mitgehen.

    Real am 08.08., 21:06 und 21:18: der ODrive antwortete 5 s nicht auf USB,
    der Sicherheitswaechter stoppte, der Prozess beendete sich mit Status 70
    und systemd startete ihn neu. Danach stand das Fahrzeug, der Maeher war
    aus - und die Oberflaeche zeigte nichts an, weil der Planstatus nur im
    Prozess lebte. Der Wiederaufsetzpunkt lag die ganze Zeit auf der Platte.
    """

    def setUp(self):
        import json
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plans_dir = Path(self.tmp.name)
        self.json = json

        config = SimpleNamespace(
            template_folder='.', static_folder='.', secret_key='test'
        )
        dummy = SimpleNamespace()
        self.server = WebServer(config, dummy, dummy, dummy, dummy)
        self.server.mapping = SimpleNamespace(
            plans=SimpleNamespace(
                plans_dir=self.plans_dir,
                _sanitize_name=lambda name: name,
            )
        )

    def _write_resume(self, reason, timestamp=1786000000.0):
        (self.plans_dir / 'Brunnen.resume.json').write_text(
            self.json.dumps({
                'schema': 'raspberrycan.mowing_resume.v2',
                'map_name': 'Brunnen',
                'reason': reason,
                'timestamp': timestamp,
                'active_index': 3,
                'source_segment_index': 10,
            }),
            encoding='utf-8',
        )

    def test_a_safety_stop_is_reported_after_the_restart(self):
        self._write_resume('safety_stop')

        status = self.server.get_plan_execution_status()

        self.assertEqual('service_restart', status['state'])
        self.assertIn('safety_stop', status['last_error'])
        self.assertIn('Bahn 10', status['last_error'])
        self.assertEqual(3, status['active_index'])

    def test_the_resume_button_comes_back_after_the_restart(self):
        self._write_resume('safety_stop')

        self.assertTrue(
            self.server.get_plan_execution_status()['resume_available'],
            'Ohne resume_available fehlt in der Oberflaeche der Knopf',
        )

    def test_a_deliberate_pause_is_not_reported_as_a_fault(self):
        self._write_resume('paused')

        status = self.server.get_plan_execution_status()

        self.assertEqual('paused', status['state'])
        self.assertIsNone(status['last_error'])
        self.assertTrue(status['resume_available'])

    def test_without_a_resume_point_nothing_is_invented(self):
        status = self.server.get_plan_execution_status()

        self.assertEqual('idle', status['state'])
        self.assertIsNone(status['last_error'])

    def test_a_broken_resume_file_never_breaks_the_status(self):
        """Der Statusabruf haengt an jeder Anzeige - er darf nie scheitern."""
        (self.plans_dir / 'Brunnen.resume.json').write_text(
            '{kaputt', encoding='utf-8'
        )

        status = self.server.get_plan_execution_status()

        self.assertEqual('idle', status['state'])

    def test_a_mapping_without_a_plans_dir_is_survived(self):
        self.server.mapping = SimpleNamespace(plans=SimpleNamespace())

        self.assertEqual('idle', self.server.get_plan_execution_status()['state'])

    def test_a_running_plan_is_not_overwritten(self):
        """Der Nachtrag gilt nur beim Start, nicht mitten in der Fahrt."""
        self._write_resume('safety_stop')
        self.server._active_plan_map_name = 'Brunnen'
        self.server._plan_status.update(running=True, state='running')

        status = self.server.get_plan_execution_status()

        self.assertEqual('running', status['state'])
        self.assertIsNone(status['last_error'])


class SimulationWithoutRtkTests(unittest.TestCase):
    """Rechnen darf man immer, losfahren nur mit RTK FIXED.

    Die Simulation bewegt nichts, hing aber am selben RTK-Fix wie die echte
    Fahrt. Damit liess sich eine Anfahrt ausgerechnet dann nicht durchrechnen,
    wenn das Fahrzeug wegen fehlendem Fix ohnehin stand (08.08., Status
    "RTK GPS Fix" statt "RTK FIXED").
    """

    def setUp(self):
        self.script = (
            Path(__file__).resolve().parents[2] / 'static' / 'js' / 'mapping_editor.js'
        ).read_text(encoding='utf-8')

    def _simulate_function(self):
        start = self.script.index('function simulateLanePlan(')
        return self.script[start:start + 1400]

    def test_simulation_only_needs_a_position(self):
        body = self._simulate_function()
        guard = body[body.index('useCurrentPose &&'):][:120]

        self.assertIn('latestVehiclePose === null', guard)
        self.assertNotIn('rtkAvailable', guard)

    def test_a_missing_fix_is_named_in_the_status_line(self):
        """Ohne Fix ist die Startposition ungenau - das muss dastehen."""
        body = self._simulate_function()

        self.assertIn('OHNE RTK-Fix', body)

    def test_driving_still_requires_a_fix(self):
        self.assertIn(
            "if (!rtkAvailable) return {ready: false, reason: 'RTK FIXED ist erforderlich'};",
            self.script,
        )


class PlanAlertVisibilityTests(unittest.TestCase):
    """Ein gestoppter Plan muss ohne Suchen sichtbar sein.

    Am 07.08. stand das Fahrzeug mit ``heading_block`` mitten auf der Flaeche
    und meldete scheinbar nichts: die Statuszeile dafuer liegt in einem
    zugeklappten <details> auf der Kartenseite, waehrend der Benutzer auf der
    Steuerungsseite war. Auch die Ablehnung von "Fortsetzen" landete dort.
    """

    def setUp(self):
        root = Path(__file__).resolve().parents[2]
        self.template = (root / 'templates' / 'index.html').read_text(encoding='utf-8')
        self.script = (
            root / 'static' / 'js' / 'mapping_editor.js'
        ).read_text(encoding='utf-8')

    def test_alert_element_exists_outside_every_screen(self):
        self.assertIn('id="planAlert"', self.template)
        banner_at = self.template.index('id="planAlert"')
        first_screen_at = self.template.index('class="screen active"')
        self.assertLess(
            banner_at,
            first_screen_at,
            'Banner steht in einem Screen und ist dann nur dort sichtbar',
        )

    def test_alert_is_not_hidden_inside_the_collapsed_plan_details(self):
        # Bewusst die Markup-Stelle, nicht die CSS-Regel weiter oben.
        details_at = self.template.index('<details class="plan-info-disclosure">')
        self.assertLess(
            self.template.index('id="planAlert"'),
            details_at,
            'Banner darf nicht im zugeklappten Bereich liegen',
        )

    def test_status_update_feeds_the_alert(self):
        self.assertIn('setPlanAlert(planAlertText(plan, planState))', self.script)
        self.assertIn('function planAlertText(', self.script)

    def test_blocking_states_reach_the_alert(self):
        """Zustaende ohne Fehlertext-Ausnahme muessen das Banner ausloesen."""
        start = self.script.index('function planAlertText(')
        body = self.script[start:start + 800]
        # Nur diese Zustaende gelten als unauffaellig; alles andere - darunter
        # heading_block, nogo_stop, error und mower_fault - meldet sich.
        self.assertIn("['', 'idle', 'running', 'completed'].includes(planState)", body)
        self.assertIn('plan.last_error', body)

    def test_rejected_resume_shows_immediately(self):
        self.assertIn('setPlanAlert(planBlockedMessage)', self.script)

    def test_alert_can_be_dismissed_and_returns_for_a_new_message(self):
        self.assertIn('function dismissPlanAlert(', self.script)
        self.assertIn('planAlertDismissed = el.textContent', self.script)
        self.assertIn('dismissPlanAlert,', self.script)
        self.assertIn('dismissPlanAlert()', self.template)


if __name__ == '__main__':
    unittest.main()
