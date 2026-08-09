"""Die echte Wiesenroute wird hier festgenagelt.

Am 08.08. sollte die Anfahrt zum Planbeginn repariert werden, weil sie beim
Brunnen rueckwaerts stiess und das Fahrzeug am Ziel entgegen der ersten Bahn
stehenliess. Die Anfahrt setzt aber den Kurs, aus dem der Planer die Richtung
*jeder* folgenden Bahn ableitet - eine unbedachte Aenderung dort schreibt die
komplette Route um. Genau das ist bei einem ersten Versuch passiert: 98 wurde
zu 97 Segmenten und saemtliche Bahnrichtungen drehten sich um.

Diese Tests rechnen deshalb mit dem echten gespeicherten Plan und der echten
Karte. Faellt einer davon aus, hat eine Aenderung die gefahrene Route
veraendert - das darf passieren, aber nie unbemerkt.
"""

import json
import math
import unittest
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.mapping.plan_manager import MowingPlanManager

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Gemessen am 08.08. mit dem gespeicherten Plan und einer Aufstellung, wie sie
# real gefahren wird: Fahrzeug 5 m vor dem Anfang der ersten Bahn, Nase entlang
# dieser Bahn.
EXPECTED_SEGMENTS = 96
EXPECTED_LENGTH_M = 2243.6
# Das eigentlich Schuetzenswerte ist nicht die Gesamtzahl, sondern was gemaeht
# wird - deshalb steht das hier daneben und wird mitgeprueft.
EXPECTED_MOW_LANES = 75
EXPECTED_MOW_LENGTH_M = 2149.9
# 09.08.: von 98/2245,0 auf 96/2243,6. Eine Restbahn von 0,64 m wird nicht
# mehr als eigene Bahn gefahren - unter MIN_DRIVEN_LANE_M hat ein Bahnstueck
# keine belastbare Richtung, und der Regler sperrte real vier solche Zwerge in
# Folge (0,61 bis 0,89 m, 50 bis 75 Grad Kursfehler). Es bleiben 0,6 m von
# 2150 m ungemaeht, zwischen Nachbarbahnen, deren Deck breiter ist als ihr
# Abstand.


class WieseRouteRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((FIXTURES / "Wiese.plan.json").read_text(encoding="utf-8"))

    def _first_lane(self):
        segments = [
            item for item in (self.plan.get("sequence") or [])
            if len(item.get("coordinates") or []) >= 2
        ]
        return min(segments, key=lambda item: item.get("segment_index", 0))

    def _aligned_start_pose(self, distance_m=5.0):
        """Fahrzeug ``distance_m`` vor der ersten Bahn, ausgerichtet auf sie."""
        coords = self._first_lane()["coordinates"]
        lat0 = math.radians(coords[0][1])
        east = (coords[1][0] - coords[0][0]) * 111320.0 * math.cos(lat0)
        north = (coords[1][1] - coords[0][1]) * 111320.0
        bearing = math.degrees(math.atan2(east, north)) % 360.0
        back = math.radians((bearing + 180.0) % 360.0)
        return {
            "timestamp": time.time(),
            "gps": {
                "lat": coords[0][1] + (distance_m * math.cos(back)) / 111320.0,
                "lon": coords[0][0]
                + (distance_m * math.sin(back)) / (111320.0 * math.cos(lat0)),
                "satellites": 25,
            },
            "heading": bearing,
            "heading_source": "dual_gnss",
            "rtk_status": "RTK FIXED",
        }

    def _route(self, pose):
        manager = MowingPlanManager(str(FIXTURES), lambda: pose)
        return manager.executable_segments(
            self.plan, start_segment_index=0, start_pose=pose
        )

    def test_route_from_an_aligned_start_is_unchanged(self):
        pose = self._aligned_start_pose()

        route = self._route(pose)

        self.assertEqual(EXPECTED_SEGMENTS, len(route))
        self.assertAlmostEqual(
            EXPECTED_LENGTH_M,
            sum(segment.get("length_m", 0.0) for segment in route),
            delta=0.5,
        )

    def test_what_gets_mown_never_changes(self):
        """Die eigentliche Zusage: dieselben Bahnen, dieselbe Flaeche.

        Die Gesamtzahl der Segmente darf sich bewegen - Verbindungsstuecke
        kommen und gehen. Was gemaeht wird, darf sich nicht bewegen.
        """
        route = self._route(self._aligned_start_pose())
        mow = [segment for segment in route if segment["type"] == "mow"]

        self.assertEqual(EXPECTED_MOW_LANES, len(mow))
        self.assertAlmostEqual(
            EXPECTED_MOW_LENGTH_M,
            sum(segment["length_m"] for segment in mow),
            delta=0.5,
        )

    def test_no_segment_starts_at_an_angle_the_controller_blocks(self):
        """Keine einzige Stelle, an der der Regler die Fahrt abbricht.

        Zwei reale Abbrueche vom 09.08. treffen sich hier. Um 11:48 zeigte ein
        0,97 m langer Uebergang 316 Grad, waehrend die Nase mit 268,7 Grad
        korrekt auf beiden Nachbarbahnen lag - 47,2 Grad, gesperrt. Um 12:55
        begann eine Bahn mit 0,56 m Querversatz, weil der Huepfer davor
        weggelassen worden war; rueckwaerts baut das Fahrzeug so viel nicht
        mehr ab (gemessen: 0,56 m am Anfang, 0,74 m am Ende), die naechste
        Bahn begann mit 1,42 m und brach ab.

        Beides loest derselbe Zug: der Uebergang zielt nicht mehr auf den
        Bahnanfang, sondern schert flach auf die Bahnlinie ein und laeuft
        gerade hinein. Kein schraeger Kurzhuepfer, kein Versatz am Bahnanfang.
        """
        pose = self._aligned_start_pose()
        manager = MowingPlanManager(str(FIXTURES), lambda: pose)
        route = manager.executable_segments(
            self.plan, start_segment_index=0, start_pose=pose
        )
        headings = manager.segment_start_headings(route, start_pose=pose)

        blocked = []
        for index, (segment, heading) in enumerate(zip(route, headings)):
            coords = segment.get("coordinates") or []
            if heading is None or len(coords) < 2 or segment.get("mode") == "goto":
                continue
            nose = MowingPlanManager._edge_bearing_deg(coords[0], coords[1])
            if nose is None:
                continue
            if segment.get("direction") == "reverse":
                nose = (nose + 180.0) % 360.0
            error = MowingPlanManager._angle_error_deg(nose, heading)
            if error >= 45.0:
                blocked.append((index, segment["type"],
                                round(segment["length_m"], 2), round(error, 1)))

        self.assertEqual(
            [], blocked,
            "Der Regler wuerde die Fahrt an diesen Stellen abbrechen",
        )

    def test_aligned_start_is_approached_forwards(self):
        """Steht das Fahrzeug richtig, gibt es nichts zu rangieren."""
        route = self._route(self._aligned_start_pose())

        self.assertEqual("positioning", route[0]["type"])
        self.assertEqual("forward", route[0]["direction"])

    def test_lane_directions_alternate_from_the_first_lane_forwards(self):
        """Die Serpentine haengt am Anfahrtskurs - hier wird sie festgehalten."""
        route = self._route(self._aligned_start_pose())
        mow = [s for s in route if s["type"] == "mow"][:4]

        self.assertEqual(
            ["forward", "reverse", "forward", "reverse"],
            [segment["direction"] for segment in mow],
        )


class ApproachDirectionTests(unittest.TestCase):
    """Die Anfahrt darf nur rueckwaerts, wenn die Ankunft zur Bahn passt."""

    def test_reverse_arrival_against_the_lane_is_rejected(self):
        # Anfahrt nach Norden, folgende Bahn verlangt ebenfalls Norden.
        segment = {
            "mode": "track",
            "direction": "reverse",
            "coordinates": [[10.0, 52.0], [10.0, 52.0002]],
        }

        error = MowingPlanManager._arrival_error(segment, 0.0)

        # Rueckwaerts angekommen zeigt die Nase nach Sueden: 180 Grad daneben.
        self.assertAlmostEqual(180.0, error, delta=1.0)
        self.assertGreater(error, MowingPlanManager.ARRIVAL_ALIGNMENT_LIMIT_DEG)

    def test_reverse_arrival_matching_a_reverse_lane_is_fine(self):
        segment = {
            "mode": "track",
            "direction": "reverse",
            "coordinates": [[10.0, 52.0], [10.0, 52.0002]],
        }

        # Eine rueckwaerts gefahrene Bahn verlangt die Nase nach Sueden.
        error = MowingPlanManager._arrival_error(segment, 180.0)

        self.assertAlmostEqual(0.0, error, delta=1.0)
        self.assertLessEqual(error, MowingPlanManager.ARRIVAL_ALIGNMENT_LIMIT_DEG)

    def test_entry_heading_follows_the_lane_direction(self):
        coords = [[10.0, 52.0], [10.0, 52.0002]]

        self.assertAlmostEqual(
            0.0, MowingPlanManager._segment_entry_heading(coords, "forward"), delta=1.0
        )
        self.assertAlmostEqual(
            180.0, MowingPlanManager._segment_entry_heading(coords, "reverse"), delta=1.0
        )

    def test_the_arc_starts_where_the_nose_already_points(self):
        """Der Bogen beginnt in Fahrtrichtung - sonst greift der Regler nicht.

        Dieses Fahrzeug dreht nicht auf der Stelle. Beginnt der geplante Weg
        quer zur Nase, sperrt der Regler ihn am Kursfehler, bevor ein Meter
        gefahren ist. Die halbe Schrittweite kommt von der Abtastung: die erste
        Kante ist eine Sehne des Bogens.
        """
        goal = [11.0786425, 53.3324661]
        half_step = MowingPlanManager.MAX_TURN_STEP_DEG / 2.0 + 0.1
        for arrival in range(0, 360, 15):
            for heading in range(0, 360, 15):
                for east, north in ((0.0, 22.0), (17.0, -14.0), (-31.0, 2.0)):
                    start = MowingPlanManager._offset_coord(
                        goal,
                        math.degrees(math.atan2(east, north)),
                        math.hypot(east, north),
                    )
                    coords = MowingPlanManager._approach_arc_coords(
                        start, float(heading), goal, float(arrival)
                    )
                    if coords is None:
                        continue
                    with self.subTest(arrival=arrival, heading=heading,
                                      start=(east, north)):
                        self.assertLess(
                            MowingPlanManager._coord_distance_m(coords[-1], goal),
                            0.01,
                            "Die Anfahrt muss genau am gewaehlten Punkt enden",
                        )
                        self.assertLessEqual(
                            MowingPlanManager._angle_error_deg(
                                MowingPlanManager._edge_bearing_deg(
                                    coords[0], coords[1]
                                ),
                                float(heading),
                            ),
                            half_step,
                        )

    def test_approach_arc_has_no_kink_the_controller_blocks_on(self):
        """Bogen und Gerade haengen tangential aneinander."""
        goal = [11.0786425, 53.3324661]
        worst = 0.0
        for arrival in range(0, 360, 15):
            for heading in range(0, 360, 15):
                start = MowingPlanManager._offset_coord(goal, 20.0, 25.0)
                coords = MowingPlanManager._approach_arc_coords(
                    start, float(heading), goal, float(arrival)
                )
                if coords is None:
                    continue
                previous = None
                for first, second in zip(coords, coords[1:]):
                    bearing = MowingPlanManager._edge_bearing_deg(first, second)
                    if bearing is None:
                        continue
                    if previous is not None:
                        worst = max(
                            worst,
                            MowingPlanManager._angle_error_deg(bearing, previous),
                        )
                    previous = bearing

        self.assertLessEqual(worst, MowingPlanManager.MAX_TURN_STEP_DEG + 0.1)

    def test_the_arc_never_arrives_worse_than_driving_straight(self):
        """Ein Bogen muss die Ankunft verbessern, sonst gehoert er nicht hin.

        Der 08.08. hatte drei Stufen: erst fuhr das Fahrzeug 12,45 m am Marker
        vorbei, dann genau hin - aber schnurgerade, sodass am Bahnanfang sofort
        der Winkelfehler stand. Der Bogen loest das, aber nur, wenn er zur Bahn
        hin biegt. Beim ersten Versuch bog er teils von ihr weg und machte den
        Fehler groesser als die Gerade (Kurs 210 am Brunnen: 60,3 statt
        53,0 Grad). Deshalb ist die Gerade hier die Messlatte.

        Exakt auf der Bahnlinie zu enden ist der Idealfall und passiert oft -
        noetig ist es nicht. Der Regler verlangt nur, dass die Nase innerhalb
        von track_heading_block_deg steht.
        """
        goal = [11.0786425, 53.3324661]
        checked = 0
        exact = 0
        for arrival in range(0, 360, 15):
            for heading in range(0, 360, 15):
                for east, north in ((0.0, 25.0), (14.0, -9.0), (-31.0, 2.0)):
                    start = MowingPlanManager._offset_coord(
                        goal,
                        math.degrees(math.atan2(east, north)),
                        math.hypot(east, north),
                    )
                    coords = MowingPlanManager._approach_arc_coords(
                        start, float(heading), goal, float(arrival)
                    )
                    if coords is None:
                        continue
                    checked += 1
                    error = MowingPlanManager._angle_error_deg(
                        MowingPlanManager._edge_bearing_deg(
                            coords[-2], coords[-1]
                        ),
                        float(arrival),
                    )
                    if error < 1.0:
                        exact += 1
                    straight = MowingPlanManager._angle_error_deg(
                        MowingPlanManager._edge_bearing_deg(start, goal),
                        float(arrival),
                    )
                    with self.subTest(arrival=arrival, heading=heading,
                                      start=(east, north)):
                        self.assertLessEqual(
                            error, straight + 0.15,
                            "Der Bogen macht die Ankunft schlechter als die Gerade",
                        )

        self.assertGreater(checked, 100, "Zu wenige Faelle geprueft")
        self.assertGreater(
            exact, checked // 4,
            "Der exakte Einlauf auf die Bahnlinie muss der Regelfall bleiben",
        )

    def test_approach_never_loops_around_its_own_turning_circle(self):
        """Lieber keine Anfahrt als eine Schleife.

        Liegt der Marker seitlich und naeher als der Wendekreisdurchmesser,
        fuehrt der Beruehrpunkt fast einmal ganz um den Kreis: 40 bis 60 m fuer
        neun Meter Luftlinie (gemessen 08.08., Brunnen). Solche Loesungen
        werden verworfen; der Plan-Check meldet dann den Kursfehler.
        """
        goal = [11.0786425, 53.3324661]
        # Was die Konstruktion selbst zulaesst: ein Ausfahrbogen und ein
        # Einschwenkbogen, beide am oberen Ende ihrer Leiter. Gemessen bleibt
        # der Weg deutlich darunter - hoechstens das 2,1-fache der Luftlinie.
        budget = sum(
            math.radians(turn) * radius
            for radius, turn in (
                MowingPlanManager.APPROACH_TURN_ARCS[-1],
                MowingPlanManager.APPROACH_MERGE_ARCS[-1],
            )
        )
        for east, north in ((0.0, 25.0), (14.0, -9.0), (-31.0, 2.0)):
            start = MowingPlanManager._offset_coord(
                goal,
                math.degrees(math.atan2(east, north)),
                math.hypot(east, north),
            )
            direct = math.hypot(east, north)
            for heading in range(0, 360, 15):
                for arrival in range(0, 360, 15):
                    coords = MowingPlanManager._approach_arc_coords(
                        start, float(heading), goal, float(arrival)
                    )
                    if coords is None:
                        continue
                    with self.subTest(heading=heading, arrival=arrival,
                                      start=(east, north)):
                        self.assertLessEqual(
                            MowingPlanManager._polyline_length_m(coords),
                            direct + budget,
                        )

    def test_approach_arc_turns_tightly_enough_to_stay_put(self):
        """Der geplante Bogen darf nie enger sein als der gefahrene.

        Bis zum 08.08. stand hier das Gegenteil - der Radius wurde aus der
        Abtastschrittweite gerechnet (0,6 m je 20 Grad = 1,72 m) und der Test
        verlangte ausdruecklich unter 2 m. Beides beschrieb den Plan, nicht das
        Fahrzeug. Im Simulator faehrt der Regler einen 120-Grad-Bogen erst ab
        7 m; bei 5 m kriecht er, bei 2 m laeuft er aus dem Pfad. Genau das
        passierte real: cross_track_stop nach 10,9 von 13,1 m.
        """
        self.assertGreaterEqual(
            MowingPlanManager.POSITIONING_TURN_RADIUS_M,
            7.0,
            "Enger faehrt der Regler den vollen Eindrehwinkel nicht",
        )
        self.assertLessEqual(
            MowingPlanManager.MAX_TURN_STEP_DEG,
            45.0,
            "Ein Knick ueber der Reglergrenze macht den Bogen unfahrbar",
        )


class BrunnenSelectedStartTests(unittest.TestCase):
    """Der Realfall vom 08.08.: Konturring, Startpunkt aus der Karte gewaehlt.

    Das Fahrzeug stand quer zum Ring. Die Anfahrt konnte damals nur geradeaus
    ankommen, also wanderte stattdessen der Ringanfang 12,45 m weiter - der
    Marker in der Karte blieb stehen und das Fahrzeug fuhr woandershin.
    """

    POSE = {
        "gps": {"lat": 53.3325422, "lon": 11.0786776, "satellites": 25},
        "heading": 183.7,
        "heading_source": "dual_gnss",
        "rtk_status": "RTK FIXED",
    }
    SELECTED_START = [11.0786425, 53.3324661]
    # navigation.track_heading_block_deg: darueber lehnt der Regler die Bahn ab.
    BLOCK_DEG = 45.0

    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(
            (FIXTURES / "Brunnen.plan.json").read_text(encoding="utf-8")
        )

    def _route(self, heading_deg):
        pose = dict(self.POSE, heading=float(heading_deg), timestamp=time.time())
        manager = MowingPlanManager(str(FIXTURES), lambda: pose)
        return manager.executable_segments(
            self.plan,
            start_segment_index=0,
            start_coordinate=self.SELECTED_START,
            start_pose=pose,
        )

    def test_the_ring_starts_at_the_point_the_user_picked(self):
        for heading in range(0, 360, 30):
            with self.subTest(heading=heading):
                route = self._route(heading)
                first_lane = next(s for s in route if s["type"] != "positioning")
                self.assertLess(
                    MowingPlanManager._coord_distance_m(
                        first_lane["coordinates"][0], self.SELECTED_START
                    ),
                    0.05,
                )

    def test_a_bad_arrival_is_reported_and_never_papered_over(self):
        """Entweder es passt, oder der Kursfehler steht sichtbar im Plan.

        Der Wendekreis des Fahrzeugs ist groesser als der Abstand zum Marker,
        deshalb gibt es fuer viele Aufstellungen keinen kurzen Bogen, der in
        Bahnrichtung ankommt. Das darf passieren - es darf nur nicht versteckt
        werden. Frueher rollte hier ein Ersatzbogen den Kursfehler auf 20 Grad
        klein; der Plan-Check sah damit nichts mehr und liess eine Fahrt zu,
        die der Regler nach zweieinhalb Metern abbrach (08.08.).

        Geprueft wird deshalb nicht, dass alles passt, sondern dass der Plan
        die Wahrheit sagt: der Kursfehler an der Nahtstelle ist entweder klein
        genug zum Fahren oder gross genug, dass ihn der Check meldet.
        """
        reported = 0
        for heading in range(0, 360, 30):
            with self.subTest(heading=heading):
                route = self._route(heading)
                approach = route[0]
                self.assertEqual("positioning", approach["type"])
                first_lane = next(s for s in route if s["type"] != "positioning")
                entry = MowingPlanManager._segment_entry_heading(
                    first_lane["coordinates"], first_lane.get("direction")
                )
                error = MowingPlanManager._angle_error_deg(
                    MowingPlanManager._segment_end_heading(approach), entry
                )
                # Ein Wert dicht unter der Sperre waere der gefaehrliche Fall:
                # der Check laesst ihn durch, der Regler nicht.
                self.assertFalse(
                    self.BLOCK_DEG - 8.0 <= error < self.BLOCK_DEG,
                    f"Kursfehler {error:.1f} Grad liegt genau auf der Sperre",
                )
                if error >= self.BLOCK_DEG:
                    reported += 1

        self.assertGreater(
            reported, 0,
            "An diesem Stellplatz muss der Check mindestens einmal anschlagen",
        )

    def test_the_approach_itself_stays_drivable(self):
        """Kein Knick, an dem der Regler unterwegs abbricht."""
        for heading in range(0, 360, 30):
            route = self._route(heading)
            coords = route[0]["coordinates"]
            previous = None
            for first, second in zip(coords, coords[1:]):
                bearing = MowingPlanManager._edge_bearing_deg(first, second)
                if bearing is None:
                    continue
                if previous is not None:
                    with self.subTest(heading=heading):
                        self.assertLessEqual(
                            MowingPlanManager._angle_error_deg(bearing, previous),
                            MowingPlanManager.MAX_TURN_STEP_DEG + 0.1,
                        )
                previous = bearing


class ResumeOnAContourRingTests(unittest.TestCase):
    """Fortsetzen nach einem Abbruch, auf einem Konturring.

    Real am 08.08.: die Planfahrt stoppte mit RTK-Verlust auf Ring 0, danach
    liess sich nicht mehr fortsetzen. Der Check meldete "Bahn 0 -158.8 Grad".
    Ursache war nicht die Pose, sondern eine Fallunterscheidung: die
    Durchlaufrichtung wurde aus dem gemessenen Kurs nur fuer rest_lane neu
    entschieden. Ein Plan aus Konturringen bekam stur die gespeicherte
    Reihenfolge - auch wenn die Nase andersherum stand, was nach einem
    Abbruch der Normalfall ist.

    Geloest wird das *nicht* dadurch, dass der Ring rueckwaerts gemaeht wird.
    Ein Ring wird andersherum durchfahren: dieselbe Flaeche, dasselbe Ende,
    aber die Nase bleibt vorn.
    """

    POSE = {
        "gps": {"lat": 53.3324479, "lon": 11.0784765, "satellites": 28},
        "heading": 259.76,
        "heading_source": "dual_gnss",
        "rtk_status": "RTK FIXED",
    }
    BLOCK_DEG = 45.0

    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(
            (FIXTURES / "Brunnen.plan.json").read_text(encoding="utf-8")
        )

    def _resume_route(self, heading_deg):
        pose = dict(self.POSE, heading=float(heading_deg), timestamp=time.time())
        manager = MowingPlanManager(str(FIXTURES), lambda: pose)
        route = manager.executable_segments(
            self.plan, start_segment_index=0, start_pose=pose
        )
        return manager, pose, route

    def test_the_ring_is_driven_towards_the_nose_not_against_it(self):
        manager, pose, route = self._resume_route(self.POSE["heading"])
        first_lane = next(item for item in route if item["type"] == "mow")

        nose = MowingPlanManager._edge_bearing_deg(
            first_lane["coordinates"][0], first_lane["coordinates"][1]
        )
        if first_lane["direction"] == "reverse":
            nose = (nose + 180.0) % 360.0

        self.assertLess(
            MowingPlanManager._angle_error_deg(nose, self.POSE["heading"]),
            self.BLOCK_DEG,
            "Der Regler wuerde die Bahn am Kursfehler sperren",
        )

    def test_the_chosen_side_is_never_the_worse_one(self):
        """Quer zur Bahn bleibt quer - das loest keine Richtungswahl auf.

        Zugesagt ist deshalb kein fester Winkel, sondern nur: von den beiden
        Seiten, die ein Ring hat, wird nie die schlechtere genommen. Frueher
        stand hier eine Schwelle ("umdrehen ab 90 Grad"); die taugte nicht,
        weil das Umdrehen einen anderen Stuetzpunkt als Anfang sucht und der
        Vergleich damit nicht mehr stimmt (bei Kurs 180 kamen 95,9 Grad
        heraus, obwohl 45,9 moeglich waren).
        """
        segment = min(
            (
                item for item in self.plan["sequence"]
                if len(item.get("coordinates") or []) >= 2
            ),
            key=lambda item: item.get("segment_index", 0),
        )
        for heading in range(0, 360, 30):
            manager, pose, route = self._resume_route(heading)
            vehicle = MowingPlanManager._pose_coord(pose)
            errors = []
            for reversed_ring in (False, True):
                candidate = dict(
                    segment,
                    coordinates=list(reversed(MowingPlanManager._coords(segment)))
                    if reversed_ring else list(MowingPlanManager._coords(segment)),
                )
                errors.append(abs(MowingPlanManager._route_heading_error(
                    manager._oriented_track_coords(
                        candidate, vehicle, float(heading), vehicle=vehicle
                    ),
                    float(heading),
                )))
            first_lane = next(item for item in route if item["type"] == "mow")
            chosen = abs(MowingPlanManager._route_heading_error(
                first_lane["coordinates"], float(heading)
            ))

            with self.subTest(heading=heading):
                self.assertLessEqual(
                    chosen, min(errors) + 0.1,
                    "Es wird nie die schlechtere der beiden Seiten gefahren",
                )
                self.assertLess(
                    MowingPlanManager._coord_distance_m(
                        first_lane["coordinates"][0], first_lane["coordinates"][-1]
                    ),
                    0.05,
                    "Der Ring muss geschlossen bleiben, sonst gilt er dem "
                    "Regler als beendet, sobald das Fahrzeug am Ende steht",
                )

    def test_standing_on_the_ring_needs_no_approach_at_all(self):
        """Kein Anfahrtssegment, wenn das Fahrzeug auf der Bahn steht.

        Real am 08.08., 20:22 Uhr: Ring 9, Fahrzeug 0,01 m neben der
        Bahnlinie - aber 0,99 m vom naechsten Stuetzpunkt. Nach dem
        Stuetzpunkt gemessen entstand daraus eine 0,98 m lange "Anfahrt". Bei
        so kurzen Stuecken ist die Richtung fast beliebig; der Regler sperrte
        sie 1,8 s nach dem Start mit 63,9 Grad. Der Plan-Check hatte vorher
        gruenes Licht gegeben - die schlechteste Kombination.
        """
        pose = {
            "gps": {"lat": 53.3326738, "lon": 11.0785199, "satellites": 28},
            "heading": 122.91,
            "heading_source": "dual_gnss",
            "rtk_status": "RTK FIXED",
            "timestamp": time.time(),
        }
        manager = MowingPlanManager(str(FIXTURES), lambda: pose)
        route = manager.executable_segments(
            self.plan, start_segment_index=9, start_pose=pose
        )

        self.assertEqual(
            "mow", route[0]["type"],
            "Auf der Bahn stehend braucht es keine Anfahrt",
        )
        self.assertLess(
            abs(MowingPlanManager._route_heading_error(
                route[0]["coordinates"], pose["heading"]
            )),
            45.0,
            "Der Regler wuerde die Bahn sonst sperren",
        )

    def test_the_handover_to_the_next_ring_stays_short(self):
        """Andersherum faehrt der ganze Plan, nicht nur der erste Ring.

        Nur den ersten umzudrehen stiess ihn gegen den naechsten: aus einem
        1,55-m-Uebergang wurde ein 25,8-m-Eindrehmanoever, waehrend alle
        folgenden Uebergaenge kurz blieben - der Hinweis, dass die Ursache
        die Nahtstelle war und nicht der Uebergang selbst (08.08.).
        """
        manager, pose, route = self._resume_route(self.POSE["heading"])
        transitions = [item for item in route if item["type"] == "transition"]

        self.assertTrue(transitions)
        self.assertEqual(
            [], [item for item in transitions[:2]
                 if str(item.get("route_kind", "")).startswith("turn_in")],
            "Ein Eindrehmanoever direkt nach dem Wiederaufsetzen heisst, "
            "dass die Ringe gegeneinander laufen",
        )
        self.assertLess(transitions[0]["length_m"], 5.0)

    def test_a_ring_is_never_mown_backwards(self):
        """Der Ring wird andersherum durchfahren, nicht rueckwaerts gemaeht."""
        for heading in range(0, 360, 30):
            manager, pose, route = self._resume_route(heading)
            rings = [
                item for item in route
                if item["type"] == "mow" and item.get("source_type") == "contour"
            ]
            with self.subTest(heading=heading):
                self.assertTrue(rings, "Keine Konturbahn in der Route")
                self.assertEqual(
                    [], [item for item in rings if item["direction"] == "reverse"],
                    "Ein Konturring darf nie rueckwaerts gefahren werden",
                )

    def test_the_reversed_ring_starts_with_a_real_edge(self):
        """Kein Doppelpunkt am neuen Anfang.

        Ein geschlossener Ring traegt seinen Anfangspunkt am Ende noch einmal.
        Umgedreht stand er vorne, die erste Kante hatte keine Richtung, und
        der Plan-Check las das als 180 Grad Kursfehler - also genau die
        Sperre, die eigentlich verschwinden sollte.
        """
        manager, pose, route = self._resume_route(self.POSE["heading"])
        first_lane = next(item for item in route if item["type"] == "mow")

        self.assertIsNotNone(
            MowingPlanManager._edge_bearing_deg(
                first_lane["coordinates"][0], first_lane["coordinates"][1]
            )
        )


if __name__ == "__main__":
    unittest.main()


class EveryLaneCanBeAStartTests(unittest.TestCase):
    """Ein Marker auf irgendeiner Bahn muss ein gueltiger Start sein.

    Am 09.08. blockierte Play mit "Gewaehlte Abfahrposition liegt nicht auf
    dem gewaehlten Pfad". Ursache waren zwei eigene Regeln, die Bahnen aus
    dem Plan nehmen: die eine wirft Zwergbahnen weg, die andere ueberspringt
    kurze Bahnen, die quer liegen. Traf es die *erste* Bahn, suchte die
    naechste den Marker bei sich und fand ihn nicht - aus einem Winkelfehler
    wurde ein kompletter Startabbruch, also schlimmer als das Problem.

    Die erste Bahn ist deshalb von beiden Regeln ausgenommen.
    """

    def _plan(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def _start_on(self, plan, segment):
        coords = MowingPlanManager._coords(segment)
        middle = coords[len(coords) // 2]
        pose = {
            "timestamp": time.time(),
            "gps": {"lat": middle[1] + 0.00002, "lon": middle[0],
                    "satellites": 28},
            "heading": 90.0, "heading_source": "dual_gnss",
            "rtk_status": "RTK FIXED",
        }
        manager = MowingPlanManager(str(FIXTURES), lambda: pose)
        manager.executable_segments(
            plan,
            start_segment_index=segment.get("segment_index"),
            start_coordinate=list(middle),
            start_pose=pose,
        )

    def test_no_lane_is_rejected_as_a_start_position(self):
        for name in ("Wiese.plan.json", "Brunnen.plan.json"):
            plan = self._plan(name)
            for segment in plan["sequence"]:
                if len(segment.get("coordinates") or []) < 2:
                    continue
                length = MowingPlanManager._polyline_length_m(
                    MowingPlanManager._coords(segment)
                )
                with self.subTest(plan=name, lane=segment.get("segment_index"),
                                  length=round(length, 2)):
                    try:
                        self._start_on(plan, segment)
                    except ValueError as exc:
                        # Ein Weg, der durch eine Sperrzone fuehrt, ist ein
                        # echter Grund - der gewaehlte Punkt selbst nie.
                        self.assertNotIn("Abfahrposition", str(exc))


class LanesBehindTheWellTests(unittest.TestCase):
    """Die Bahnen links vom Brunnen werden von oben angefahren.

    Der Planer legt sie von unten nach oben, ohne zu wissen, dass der Brunnen
    dazwischen liegt. Das Fahrzeug kommt aber oben rechts an, und der Weg zum
    unteren Ende fuehrt einmal um den halben Brunnen herum: 19,2 m als
    ``around_sub``, also entlang der Grenze der Sperrzone. Die hat 23
    Stuetzpunkte auf 40 m Umfang mit Ecken von 43 bis 53 Grad - Wenderadien
    von 1,4 bis 3,5 m, waehrend das Fahrzeug fuer eine anhaltende Drehung rund
    7 m braucht.

    Real am 09.08. zweimal belegt: voller Lenkausschlag (x = -0,900), der
    Kursfehler zur Bahn schrumpft, die Querabweichung waechst trotzdem von
    0,49 auf 0,91 m, dann cross_track_stop. Im Simulator lief derselbe
    Uebergang 207 s lang und wurde nicht fertig.

    Vom oberen Ende her sind es 5,2 m mit einer einzigen Ecke von 26 Grad, und
    der Weg laeuft nordlich am Brunnen vorbei statt um ihn herum.
    """

    POSE = {
        "gps": {"lat": 53.3325422, "lon": 11.0786776, "satellites": 25},
        "heading": 183.7,
        "heading_source": "dual_gnss",
        "rtk_status": "RTK FIXED",
    }
    SELECTED_START = [11.0786425, 53.3324661]
    # Die Bahnen links vom Brunnen, in der Reihenfolge des Planers.
    FIRST_LANE_LEFT = 68
    LAST_LANE_LEFT = 101

    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(
            (FIXTURES / "Brunnen.plan.json").read_text(encoding="utf-8")
        )

    def _route(self):
        pose = dict(self.POSE, timestamp=time.time())
        manager = MowingPlanManager(str(FIXTURES), lambda: pose)
        route = manager.executable_segments(
            self.plan,
            start_segment_index=0,
            start_coordinate=self.SELECTED_START,
            start_pose=pose,
        )
        return manager, pose, route

    def _left_lanes(self, route):
        return [
            segment for segment in route
            if segment["type"] == "mow"
            and self.FIRST_LANE_LEFT <= (segment.get("source_index") or -1)
            <= self.LAST_LANE_LEFT
        ]

    def test_the_left_lanes_are_worked_from_the_top_down(self):
        left = self._left_lanes(self._route()[2])

        self.assertTrue(left, "Keine Bahn links vom Brunnen in der Route")
        indices = [segment["source_index"] for segment in left]
        self.assertEqual(
            sorted(indices, reverse=True), indices,
            "Der Block links vom Brunnen muss oben beginnen",
        )

    def test_no_route_wraps_around_the_well(self):
        """Kein Uebergang legt sich mehr an die Grenze der Sperrzone.

        Ein kurzes Stueck um die Nordseite herum bleibt uebrig - die gerade
        Verbindung streift dort die Ecke der Sperrzone. Das ist etwas anderes
        als eine Umfahrung: drei Stuetzpunkte statt sechzehn, eine Ecke statt
        vierzehn.
        """
        route = self._route()[2]
        around = [
            segment for segment in route
            if str(segment.get("route_kind", "")).endswith("around_sub")
        ]

        for segment in around:
            with self.subTest(length=segment["length_m"]):
                self.assertLess(
                    segment["length_m"], 8.0,
                    "So lang kann der Weg nur sein, wenn er um den Brunnen "
                    "herum fuehrt",
                )
                self.assertLessEqual(
                    self._sharpest_corner_deg(segment["coordinates"]),
                    MowingPlanManager.MAX_TURN_STEP_DEG + 10.0,
                    "Ein Weg entlang der Sperrzonengrenze knickt schaerfer, "
                    "als das Fahrzeug fahren kann",
                )

    def test_nothing_starts_at_an_angle_the_controller_blocks(self):
        """Dieselbe Zusage wie fuer die Wiese, jetzt auch fuer den Brunnen.

        Vor der Umkehrung stand das Fahrzeug nach der Umfahrung 86,3 Grad quer
        zur ersten Bahn links - der Regler haette dort gesperrt.
        """
        manager, pose, route = self._route()
        headings = manager.segment_start_headings(route, start_pose=pose)

        blocked = []
        for index, (segment, heading) in enumerate(zip(route, headings)):
            coords = segment.get("coordinates") or []
            if heading is None or len(coords) < 2 or segment.get("mode") == "goto":
                continue
            nose = MowingPlanManager._edge_bearing_deg(coords[0], coords[1])
            if nose is None:
                continue
            if segment.get("direction") == "reverse":
                nose = (nose + 180.0) % 360.0
            error = MowingPlanManager._angle_error_deg(nose, heading)
            if error >= 45.0:
                blocked.append((index, segment["type"], round(error, 1)))

        self.assertEqual([], blocked)

    def test_reordering_only_touches_blocks_behind_an_exclusion_zone(self):
        """Ohne Sperrzone im Weg bleibt die Reihenfolge des Planers stehen.

        Die festgenagelte Wiesenroute haengt daran: sie enthaelt keinen
        einzigen Uebergang, der um etwas herum muss, und darf sich durch diese
        Regel deshalb nicht um eine Bahn bewegen.
        """
        plan = json.loads((FIXTURES / "Wiese.plan.json").read_text(encoding="utf-8"))
        manager = MowingPlanManager(str(FIXTURES))
        sequence = [
            item for item in plan["sequence"]
            if len(item.get("coordinates") or []) >= 2
        ]
        router = MowingPlanManager._runtime_transition_router(plan)

        reordered = manager._blocks_entered_from_the_near_end(sequence, router)

        self.assertEqual(
            [item.get("segment_index") for item in sequence],
            [item.get("segment_index") for item in reordered],
        )

    @staticmethod
    def _sharpest_corner_deg(coords):
        worst = 0.0
        previous = None
        for first, second in zip(coords, coords[1:]):
            bearing = MowingPlanManager._edge_bearing_deg(first, second)
            if bearing is None:
                continue
            if previous is not None:
                worst = max(
                    worst, MowingPlanManager._angle_error_deg(bearing, previous)
                )
            previous = bearing
        return worst
