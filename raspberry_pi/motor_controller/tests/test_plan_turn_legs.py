"""Verdreht auf dem Bahnanfang: Das Fahrzeug muss sich drehen duerfen.

Am 27.08.2026 um 23:15 Uhr stand das Fahrzeug am Brunnen praktisch auf dem
Anfang seines ersten Segments, nur um 64° verdreht. Der Regler sperrte nach
drei Posen, die Planausfuehrung antwortete zweimal mit einer geraden Anfahrt
(3,24 m und 0,38 m) - und eine Gerade dreht keine Nase. Nach sieben Sekunden
stand der Plan, ohne dass sich das Fahrzeug einmal gedreht hatte.

Das vorhandene Rangiermanoever konnte hier nicht helfen: Es dreht *und* faehrt
danach den Bahnanfang an, und dieser Anfang ist der Punkt, auf dem das
Fahrzeug steht - nach jedem Zug liegt er hinter ihm (nachgerechnet: Anlauf des
Abschlusszuges 157°, in allen 24 Kombinationen abgelehnt).

Diese Tests halten das Drehen als eigenes Manoever fest, gerechnet auf dem
echten Plan Brunnen.
"""

import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.mapping.plan_manager import MowingPlanManager
from motor_controller.navigation.navigation_controller import NavigationController

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Standplatz vom 27.08., 23:15 Uhr, aus der Telemetrie des Fahrzeugs.
POSE_LON = 11.0785148
POSE_LAT = 53.3325307
# Der Regler sperrt ab 45°, mit 0,8 m Vorausschau.
BLOCK_DEG = 45.0
LOOKAHEAD_M = 0.8


class TurnLegsOnTheSpotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(
            (FIXTURES / "Brunnen.plan.json").read_text(encoding="utf-8")
        )

    def _first_segment(self, heading_deg):
        plans = MowingPlanManager(str(FIXTURES))
        segments = plans.executable_segments(
            self.plan,
            start_segment_index=22,
            start_pose={
                "longitude": POSE_LON,
                "latitude": POSE_LAT,
                "heading": heading_deg,
            },
            max_source_segments=8,
            allow_unsafe_plan=True,
        )
        return plans, segments[0]

    def _start_error(self, weg, heading_deg):
        return NavigationController.track_start_heading_error_deg(
            weg["coordinates"],
            heading_deg,
            direction=weg.get("direction", "forward"),
            lookahead_m=LOOKAHEAD_M,
        )

    def _turn(self, plans, segment, heading_deg):
        ziel = plans.segment_entry_heading(
            segment["coordinates"], segment.get("direction", "forward")
        )
        return plans.turn_legs_from_pose(
            self.plan, [POSE_LON, POSE_LAT], heading_deg, ziel
        )

    def test_der_fall_vom_27_august_dreht_sich_frei(self):
        plans, segment = self._first_segment(47.0)
        self.assertGreaterEqual(
            abs(self._start_error(segment, 47.0)), BLOCK_DEG,
            "Ausgangslage muss die Sperre ausloesen, sonst prueft der Test nichts",
        )

        zuege = self._turn(plans, segment, 47.0)

        self.assertTrue(zuege, "Ohne Zuege bleibt das Fahrzeug verdreht stehen")
        kurs = 47.0
        for zug in zuege:
            kurs = plans._segment_end_heading(zug, kurs)
        self.assertLess(abs(self._start_error(segment, kurs)), BLOCK_DEG)

    def test_aus_jeder_ausrichtung_heraus(self):
        """Die Nase steht, wie sie steht - jede Lage muss aufloesbar sein."""
        for heading in (5.0, 47.0, 160.0, 227.0, 320.0):
            with self.subTest(heading=heading):
                plans, segment = self._first_segment(heading)
                if abs(self._start_error(segment, heading)) < BLOCK_DEG:
                    continue
                zuege = self._turn(plans, segment, heading)
                self.assertTrue(zuege)
                kurs = heading
                for zug in zuege:
                    kurs = plans._segment_end_heading(zug, kurs)
                self.assertLess(abs(self._start_error(segment, kurs)), BLOCK_DEG)

    def test_zuege_gehen_vor_und_zurueck(self):
        """Auf der Stelle drehen kann dieses Fahrzeug nicht.

        Der Gegenlauf-Pivot laesst es unter Last stehen (real >4 min). Ein
        Manoever, das mehr als einen Zug braucht, muss deshalb die Richtung
        wechseln statt immer weiter in eine zu fahren.
        """
        plans, segment = self._first_segment(227.0)

        zuege = self._turn(plans, segment, 227.0)

        self.assertGreater(len(zuege), 1)
        richtungen = [zug.get("direction") for zug in zuege]
        for vorher, nachher in zip(richtungen, richtungen[1:]):
            self.assertNotEqual(vorher, nachher)

    def test_wer_schon_richtig_steht_dreht_nicht(self):
        plans, segment = self._first_segment(47.0)
        ziel = plans.segment_entry_heading(
            segment["coordinates"], segment.get("direction", "forward")
        )

        self.assertEqual(
            [],
            plans.turn_legs_from_pose(
                self.plan, [POSE_LON, POSE_LAT], ziel, ziel
            ),
        )


class TurningCloseToTheNoGoZoneTests(unittest.TestCase):
    """Am Brunnenrand ist fuer den grossen Zug kein Platz.

    Am 28.08.2026 um 00:33 Uhr stand das Fahrzeug 0,6 m von der Sperrzone und
    haette sich um 167,5 Grad drehen muessen. Ein 45-Grad-Zug traegt es 3,1 m
    weit - keine der vier Drehvarianten blieb dabei im erlaubten Bereich, und
    der Plan blieb stehen. Zum Brunnen hin kann man nicht rangieren, von ihm
    weg schon: Ein 15-Grad-Zug misst 1,05 m, und dort waren alle vier
    Varianten sicher.
    """

    # Standplatz und Zielkurs aus dem Vorfall.
    LON = 11.0783241
    LAT = 53.3325422
    ZIEL_DEG = 268.8

    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(
            (FIXTURES / "Brunnen.plan.json").read_text(encoding="utf-8")
        )

    def _plans(self):
        return MowingPlanManager(str(FIXTURES))

    def test_der_grosse_zug_findet_dort_keinen_platz(self):
        """Die Ausgangslage - sonst prueft der Test unten nichts."""
        plans = self._plans()
        router = plans._runtime_transition_router(self.plan)

        grob = plans._turn_legs_with_arc(
            router, [self.LON, self.LAT], 101.3, self.ZIEL_DEG, 20.0, 45.0, 6
        )

        self.assertIsNone(grob)

    def test_mit_feineren_zuegen_dreht_es_sich_doch(self):
        plans = self._plans()

        zuege = plans.turn_legs_from_pose(
            self.plan, [self.LON, self.LAT], 101.3, self.ZIEL_DEG
        )

        self.assertTrue(zuege)
        kurs = 101.3
        for zug in zuege:
            kurs = plans._segment_end_heading(zug, kurs)
        self.assertLessEqual(
            plans._angle_error_deg(kurs, self.ZIEL_DEG),
            plans.TURN_ALIGN_TOLERANCE_DEG,
        )

    def test_die_feinen_zuege_bleiben_kurz(self):
        """Sonst waere nichts gewonnen - die Laenge ist ja das Problem."""
        plans = self._plans()

        zuege = plans.turn_legs_from_pose(
            self.plan, [self.LON, self.LAT], 101.3, self.ZIEL_DEG
        )

        self.assertTrue(all(zug["length_m"] <= 2.2 for zug in zuege))

    def test_wo_der_grosse_zug_passt_bleibt_es_beim_grossen(self):
        """Fein gedreht wird nur, wo grob nicht geht: Jeder Zug kostet Zeit."""
        plans = self._plans()
        router = plans._runtime_transition_router(self.plan)

        grob = plans._turn_legs_with_arc(
            router, [self.LON, self.LAT], 160.0, self.ZIEL_DEG, 20.0, 45.0, 6
        )
        gestaffelt = plans.turn_legs_from_pose(
            self.plan, [self.LON, self.LAT], 160.0, self.ZIEL_DEG
        )

        self.assertTrue(grob)
        self.assertEqual(len(grob), len(gestaffelt))


if __name__ == "__main__":
    unittest.main()
