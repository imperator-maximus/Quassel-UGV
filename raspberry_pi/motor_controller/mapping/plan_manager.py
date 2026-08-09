"""Persistence and execution preparation for mowing plans."""

import json
import hashlib
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .geometry import distance_m, lonlat_to_xy
from .transition_router import TransitionRouter


class MowingPlanManager:
    """Stores generated mowing plans and converts them into executable steps."""

    SCHEMA = "raspberrycan.mowing_plan.v1"
    MIN_PLANNED_REST_LANE_M = 2.0
    # Kuerzeste Bahn, die noch als eigene Bahn gefahren wird. Gemessen an den
    # realen Abbruechen vom 09.08.: 0,61 m ergab 75,2 Grad, 0,75 m ergab
    # 62,7 Grad, 0,89 m ergab 50,9 Grad, 1,04 m noch 42,7 Grad - und erst ab
    # 1,43 m war der Kursfehler null. 1,20 m trennt die unbrauchbaren von den
    # brauchbaren, ohne die guten mitzunehmen.
    MIN_DRIVEN_LANE_M = 1.20
    # Bis hierhin wird eine Bahn lieber uebersprungen als mit einem Manoever
    # erzwungen. Drei Meter Bahn rechtfertigen keine zwanzig Meter Rangieren -
    # und die Nachbarbahnen ueberlappen ohnehin.
    SKIPPABLE_LANE_M = 3.0
    # Ausprobiert und verworfen: am Routenanfang grosszuegiger auslassen
    # (6 m statt 3 m). Klingt harmlos - dort ist noch nichts gefahren -, macht
    # es aber schlimmer, weil nach mehreren ausgelassenen Bahnen das Fahrzeug
    # irgendwo steht, wo die folgenden nicht mehr passen: 16 Sperrstellen
    # statt 1 (gemessen 09.08.). Dasselbe bei 3,5 m durchgehend: 20 statt 3.
    # Diese Kette vertraegt keine grosszuegigeren Schwellen.
    TRANSFER_REVERSE_THRESHOLD_DEG = 100.0
    # The rest-lane spacing is smaller than the vehicle and the navigation
    # acceptance radius. Treating this tiny lateral connector as a separate
    # track makes a skid-steer oscillate between two impossible headings.
    # The following long lane naturally absorbs the small cross-track offset.
    #
    # 0.60 rather than the original 0.50: as the lanes shorten towards a
    # sub-zone their ends stagger, so the end-to-start step grows past a flat
    # 0.50 for some pairs while its neighbours stay below it. Measured over
    # the real Brunnen plan the steps cluster at <=0.53 m (65 of 73) and then
    # jump to >=0.79 m, so 0.60 sits in an empty band: it absorbs the whole
    # lateral-hop family and still leaves the genuine repositioning moves as
    # real transitions. Driving one of those hops as its own track demanded a
    # 42-61 degree turn for half a metre and then the same turn back (real,
    # 26.07., transition 55/56/58) - pure detour the following lane's pure
    # pursuit removes for free. The absorbed offset also stays well inside
    # track_cross_track_limit_m (1.0 m).
    ABSORBED_REST_LANE_TRANSFER_M = 0.60
    # Zweites Kriterium neben der reinen Laenge: wie weit der Huepfer quer zur
    # naechsten Bahn liegt - denn genau das bleibt als Querversatz stehen,
    # wenn er nicht gefahren wird.
    #
    # Die Zahl stammt aus dem Fahrtprotokoll vom 09.08., nicht aus der
    # Reglergrenze. Gemessen ueber drei aufeinanderfolgende Bahnen:
    #     Start 0,27 m rueckwaerts -> Ende 0,07 m   (baut ab)
    #     Start 0,72 m vorwaerts   -> Ende 0,12 m   (baut ab)
    #     Start 0,56 m rueckwaerts -> Ende 0,74 m   (waechst!)
    # Rueckwaerts baut der Regler ab etwa einem halben Meter nichts mehr ab.
    # Der Versatz wurde von Bahn zu Bahn weitergereicht - 0,12 auf 0,56 auf
    # 0,74 - bis die naechste mit 1,42 m begann und abbrach. 0,30 m liegt im
    # Bereich, der nachweislich zulaeuft.
    ABSORBED_REST_LANE_CROSS_M = 0.30
    ABSORBED_REST_LANE_STEP_M = 1.50
    # Einscheren auf die Bahnlinie: flacher Winkel, damit der Regler den
    # Uebergang aufnimmt und die Bahn danach ohne Versatz beginnt. 20 Grad
    # liegt weit unter der Sperre von 45 und ist der Winkel, bei dem das
    # Fahrzeug im Protokoll sauber folgt.
    # Bis hierhin gilt ein Schritt zwischen zwei Bahnen als Huepfer, dessen
    # Richtung nichts bedeutet. Real gesperrt wurden 0,97 m und 1,19 m; die
    # naechstgroesseren echten Standortwechsel im Brunnen-Plan liegen bei
    # ueber 5 m, dazwischen ist Luft.
    SIDEWAYS_LANE_HOP_M = 2.50
    # Und "quer" heisst: mehr als das neben beiden Bahnrichtungen. Ein Schritt
    # entlang der Bahn ist harmlos, der wird normal gefahren.
    SIDEWAYS_LANE_HOP_ANGLE_DEG = 25.0
    JOIN_LANE_ANGLE_DEG = 20.0
    MIN_JOIN_LANE_RUN_M = 1.50
    # Laenger als das ist kein Einscheren mehr, sondern ein Umweg durch die
    # Nachbarbahnen.
    MAX_JOIN_LANE_RUN_M = 6.0
    # Wie gross die Luecke zwischen Anfang und Ende eines Rings hoechstens
    # sein darf, damit sie als Teil des Rings geschlossen wird. Sie entsteht
    # beim Zuschneiden auf die Fahrzeugposition und ist real wenige Dezimeter
    # (gemessen 0,61 m beim Fortsetzen auf Ring 0). Groesser heisst: das ist
    # keine Naht, sondern ein echtes Stueck Weg, und der wird nicht erfunden.
    # Wie weit das Fahrzeug beim Fortsetzen vom Bahnanfang entfernt stehen
    # darf, ohne dass daraus eine eigene Anfahrt gebaut wird. Bleibt bewusst
    # unter navigation.track_cross_track_limit_m (1,0 m): so viel gleicht der
    # Regler beim Aufnehmen der Bahn ohnehin aus.
    RESUME_ON_TRACK_M = 0.9
    # Wie schief die Nase am Ende der Anfahrt zur ersten Bahn stehen darf.
    # Spiegelt navigation.track_heading_block_deg: darueber lehnt der Regler
    # die folgende Bahn ab, und eine Anfahrt darf das Fahrzeug nicht so
    # abstellen. Entscheidet nur noch ueber die eine Anfahrt, die geradeaus
    # rueckwaerts an den Bahnanfang stoesst - reicht die dabei erreichte
    # Ausrichtung nicht, wird stattdessen vorwaerts eingeschwenkt (real
    # 08.08., Brunnen: 3,7 m rueckwaerts, danach 128 Grad Winkelfehler und
    # Stopp).
    ARRIVAL_ALIGNMENT_LIMIT_DEG = 45.0
    # Ein geschlossener Ring kann an jedem seiner Stützpunkte begonnen werden.
    # Rein nach Abstand gewählt landet der Start regelmäßig auf einer Ecke,
    # deren Tangente quer zur Ankunftsrichtung steht: Ring endet mit Kurs
    # 90.4°, nächster Ring startet mit 157.6° - 67° Drehung auf einem 0,42 m
    # langen Übergang, den der Regler (Grenze 45°) zu Recht ablehnt (real,
    # 02.08., Wiese, nach dem Vereinheitlichen des Drehsinns). Deshalb unter
    # den nahe gelegenen Stützpunkten denjenigen bevorzugen, dessen Tangente
    # zur Ankunftsrichtung passt. 40° lässt Reserve zur 45°-Reglergrenze.
    RING_START_HEADING_LIMIT_DEG = 40.0
    # Wie weit der Start dafür vom nächstgelegenen Punkt abweichen darf. Bei
    # konzentrischen Ringen liegt der passende Punkt wenige Meter weiter auf
    # demselben Ring; mehr Umweg wäre kein besserer Startpunkt mehr, sondern
    # eine Anfahrt quer über die Fläche.
    RING_START_MAX_DETOUR_M = 6.0
    # Abtastweite entlang der Ringkanten. Nur die Stützpunkte zu prüfen reicht
    # nicht: im 6-m-Fenster lag auf der Wiese genau ein einziger.
    RING_START_SAMPLE_M = 1.0
    # Unterhalb dieses Abstands gilt das Fahrzeug als schon auf der Bahn
    # stehend; die Peilung dorthin ist dann nur noch Rauschen.
    ON_TRACK_DISTANCE_M = 2.0
    # Rollender Anfahrbogen: Kursänderung pro Stützpunkt und Schrittlänge.
    # 20° bleibt klar unter der 45°-Sperre des Reglers, 1,5 m entspricht dem
    # Wenderadius, den die Innen-Rad-Garantie zulässt (~1 m).
    MAX_TURN_STEP_DEG = 20.0
    TURN_STEP_M = 1.5
    MAX_TURN_STEPS = 12
    # Schrittweite der Rueckfallebene _rolling_turn_coords, die nur noch
    # Uebergaenge zwischen Segmenten betrifft.
    POSITIONING_TURN_STEP_M = 0.6
    # Wie eng ein geplanter Bogen sein darf, haengt davon ab, wie weit er
    # dreht - ein kurzer enger Bogen ist fahrbar, eine anhaltende enge Drehung
    # nicht. Im Simulator gegen reine Kreisboegen gemessen (08.08.):
    #
    #     Radius   20 Grad  30 Grad  45 Grad  60 Grad  90 Grad  120 Grad
    #     2,0 m    faehrt   faehrt   faehrt   faehrt   raus     -
    #     3,0 m    faehrt   faehrt   faehrt   kriecht  kriecht  -
    #     4,0 m    faehrt   faehrt   faehrt   kriecht  kriecht  -
    #     6,0 m    faehrt   faehrt   faehrt   faehrt   faehrt   kriecht
    #     7,0 m    faehrt   faehrt   faehrt   faehrt   faehrt   faehrt
    #
    # "kriecht" heisst: das Fahrzeug bleibt auf dem Pfad, faellt aber in den
    # Ausrichtmodus und braucht ein Vielfaches der Zeit; "raus" heisst, es
    # verlaesst ihn. Beides ist unbrauchbar. Die Tabelle passt zur Physik:
    # 0,35 m/s Radgeschwindigkeit, davon 10 % Gierrate (gemessen 02.08.),
    # gegen navigation.max_joystick = 0,30 bleiben rund 1,9 Grad/s.
    #
    # Dass kurze enge Boegen wirklich gehen, zeigen die Konturringe selbst:
    # ihre engsten Stellen liegen bei 2,0 m und werden gemaeht.
    #
    # Daraus die beiden Leitern - je Radius der groesste Winkel, den er noch
    # traegt. Der engste Bogen wird zuerst probiert, weil er den kuerzesten
    # Weg ergibt.
    APPROACH_MERGE_ARCS = ((4.0, 45.0), (6.0, 90.0))
    APPROACH_TURN_ARCS = ((4.0, 45.0), (6.0, 90.0), (7.0, 120.0))
    # Engster Radius, der eine anhaltende Drehung traegt. Frueher standen hier
    # 1,72 m - die Zahl kam aus 0,6 m Sehne je 20 Grad, also aus der Abtastung
    # des Plans, und beschrieb nie, was das Fahrzeug fahren kann. Die damit
    # geplante Anfahrt brach in der Simulation nach 10,9 von 13,1 m mit
    # cross_track_stop ab (08.08., Brunnen).
    POSITIONING_TURN_RADIUS_M = APPROACH_TURN_ARCS[-1][0]
    MAX_APPROACH_TURN_DEG = APPROACH_TURN_ARCS[-1][1]
    # Wie weit vor dem Marker die Nahtstelle spaetestens liegt. Weiter draussen
    # wuerde der Einlauf laenger als die Anfahrt selbst.
    MAX_APPROACH_MERGE_LEAD_M = 25.0
    # Eindrehmanöver: wie weit in die Zielbahn hineingefahren wird, bevor das
    # Fahrzeug an deren Anfang zurückstößt. Aus dem Drehwinkel gerechnet
    # (~13°/m gemessen) plus Reserve; genau diese Strecke wird doppelt
    # befahren.
    TURN_IN_RESERVE_M = 2.0
    MIN_TURN_IN_M = 4.0
    MAX_TURN_IN_M = 20.0
    # Wie viel Weg die umgedrehte Bahnfolge sparen muss, damit sie umgedreht
    # wird. Eine Bahnreihenfolge ist nichts, was man fuer einen halben Meter
    # anfasst; gemessen am Brunnen spart die Umkehrung 12,1 m (5,2 statt
    # 17,3 m Anfahrt) und liegt damit weit ueber dieser Schwelle.
    BLOCK_REVERSAL_GAIN_M = 2.0
    # Ab wie vielen Bahnen ein Stueck Plan als eigener Block gilt. Zwei
    # genuegen: weniger ist keine Reihenfolge, die man umdrehen koennte.
    MIN_REORDERED_BLOCK_LANES = 2

    def __init__(self, maps_dir: str, pose_provider: Optional[Callable[[], Dict[str, Any]]] = None):
        self.maps_dir = Path(maps_dir).expanduser()
        self.plans_dir = self.maps_dir.parent / "plans"
        self.pose_provider = pose_provider
        self.reverse_track_supported = True

    def list_plans(self) -> List[Dict[str, Any]]:
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        plans = []
        for path in sorted(self.plans_dir.glob("*.plan.json")):
            try:
                payload = self._read_json(path)
                plans.append({
                    "name": path.name[:-10],
                    "map_name": payload.get("map_name", path.name[:-10]),
                    "path": str(path),
                    "created_at": payload.get("created_at"),
                    "resume_available": (self.plans_dir / f"{path.name[:-10]}.resume.json").exists(),
                    "segment_count": len(payload.get("sequence") or []),
                    "unsafe_transition_count": self._unsafe_transition_count(payload),
                    "reverse_segment_count": self._reverse_segment_count(payload),
                    "total_drive_length_m": payload.get("total_drive_length_m", 0.0),
                })
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return plans

    def save_plan(self, map_name: str, plan: Dict[str, Any]) -> Dict[str, Any]:
        clean_name = self._sanitize_name(map_name or plan.get("name", ""))
        if not clean_name:
            return {"success": False, "error": "Kartenname erforderlich"}
        if not isinstance(plan, dict) or plan.get("success") is False:
            return {"success": False, "error": "Gültiger Plan erforderlich"}
        if plan.get("name") and self._sanitize_name(plan.get("name")) != clean_name:
            return {"success": False, "error": "Plan passt nicht zur gewählten Karte"}

        payload = self._persisted_payload(clean_name, plan)
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        path = self._plan_path(clean_name)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"success": True, "path": str(path), "plan": payload, "summary": self.summarize_plan(payload)}

    def load_plan(self, map_name: str) -> Dict[str, Any]:
        path = self._plan_path(map_name)
        if not path.exists():
            return {"success": False, "error": "Plan nicht gefunden"}
        payload = self._read_json(path)
        if payload.get("schema") != self.SCHEMA:
            return {"success": False, "error": "Unbekanntes Planformat"}
        return {"success": True, "path": str(path), "plan": payload, "summary": self.summarize_plan(payload)}

    def check_plan(
        self,
        map_name: str,
        plan: Optional[Dict[str, Any]] = None,
        start_segment_index: Optional[int] = None,
        start_coordinate: Optional[List[float]] = None,
        start_pose: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        loaded = {"plan": plan} if plan is not None else self.load_plan(map_name)
        if loaded.get("success") is False:
            return loaded
        payload = loaded["plan"]
        summary = self.summarize_plan(payload)
        errors = []
        warnings = []

        if self._sanitize_name(payload.get("map_name", payload.get("name", ""))) != self._sanitize_name(map_name):
            errors.append("Plan passt nicht zur aktuell gewählten Karte")
        if summary["unsafe_transition_count"] > 0:
            errors.append("Plan enthält unsichere Übergänge")
        if summary["reverse_segment_count"] > 0 and not self.reverse_track_supported:
            errors.append("Plan enthält Rückwärtssegmente, Ausführung noch nicht unterstützt")
        if summary["short_rest_lane_count"] > 0:
            errors.append(
                f"Plan enthält {summary['short_rest_lane_count']} sehr kurze Restbahn(en); bitte neu planen"
            )

        pose = self._current_pose()
        if pose is None:
            errors.append("Keine aktuelle RTK/GPS-Pose vorhanden")
        else:
            timestamp = pose.get("timestamp")
            if timestamp is not None:
                try:
                    if time.time() - float(timestamp) > 2.0:
                        errors.append("RTK/GPS-Pose ist nicht aktuell")
                except (TypeError, ValueError):
                    warnings.append("RTK/GPS-Zeitstempel ist ungültig")
            rtk_status = self.rtk_status_from_pose(pose)
            if not self.is_rtk_fixed(rtk_status):
                errors.append(f"RTK nicht verfügbar: {rtk_status or 'unbekannt'}")

        executable = []
        if not errors:
            try:
                executable = self.executable_segments(
                    payload,
                    start_segment_index=start_segment_index,
                    start_coordinate=start_coordinate,
                    start_pose=start_pose or pose,
                )
            except ValueError as exc:
                errors.append(str(exc))

        return {
            "success": len(errors) == 0,
            "summary": summary,
            "errors": errors,
            "warnings": warnings,
            "capabilities": {"reverse_track_supported": self.reverse_track_supported},
            "executable_segments": executable,
            "route_signature": self.route_signature(executable) if executable else None,
            "route_signature_segment_count": len(executable),
        }

    @staticmethod
    def route_signature(segments: List[Dict[str, Any]]) -> str:
        """Stable signature for binding a preview to the route being run.

        The live RTK coordinate at the beginning of a positioning leg is
        intentionally excluded: centimetre noise between preview and Play
        must not invalidate an otherwise identical route. Direction, target,
        routed geometry and all following segments remain covered.
        """
        canonical = []
        for segment in segments:
            coords = list(segment.get("coordinates") or [])
            if segment.get("type") == "positioning" and len(coords) > 1:
                coords = coords[1:]
            canonical.append({
                "type": segment.get("type"),
                "source_index": segment.get("source_index"),
                "mode": segment.get("mode"),
                "direction": segment.get("direction"),
                "route_kind": segment.get("route_kind"),
                "coordinates": [
                    [round(float(coord[0]), 7), round(float(coord[1]), 7)]
                    for coord in coords
                ],
            })
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    def executable_segments(
        self,
        plan: Dict[str, Any],
        start_segment_index: Optional[int] = None,
        start_coordinate: Optional[List[float]] = None,
        start_pose: Optional[Dict[str, Any]] = None,
        max_source_segments: Optional[int] = None,
        allow_unsafe_plan: bool = False,
    ) -> List[Dict[str, Any]]:
        if self._unsafe_transition_count(plan) > 0 and not allow_unsafe_plan:
            raise ValueError("Unsafe transitions blockieren die Ausführung")

        sequence = [
            item for item in plan.get("sequence") or []
            if self._coords(item)
        ]
        if start_segment_index is not None:
            try:
                start_index = int(start_segment_index)
            except (TypeError, ValueError):
                raise ValueError("start_segment_index muss eine Zahl sein")
            sequence = [
                item for item in sequence
                if int(item.get("segment_index", -1)) >= start_index
            ]
            if not sequence:
                raise ValueError("Startsegment liegt außerhalb des Plans")
        # Zwergbahnen gar nicht erst als eigene Bahn ausgeben. Unter einem
        # guten Meter hat ein Bahnstueck keine belastbare Richtung mehr, der
        # Regler verlangt sie aber trotzdem und sperrt: real am 09.08. vier
        # Abbrueche in Folge auf Bahnen von 0,61 bis 0,89 m Laenge, mit 50 bis
        # 75 Grad Kursfehler. Nur Restbahnen - ein Konturring ist nie ein
        # Fragment. Was liegen bleibt, sind 3,7 m von 2260 m (0,16 %),
        # zwischen Nachbarbahnen, deren Maehdeck breiter ist als ihr Abstand.
        #
        # Die erste Bahn bleibt immer stehen, auch wenn sie ein Zwerg ist:
        # auf ihr liegt der vom Benutzer gewaehlte Startpunkt. Ohne diese
        # Ausnahme fand er seine Bahn nicht mehr und Play brach ab mit
        # "Gewaehlte Abfahrposition liegt nicht auf dem gewaehlten Pfad"
        # (real 09.08.) - schlimmer als der Winkelfehler, den die Regel
        # verhindern sollte.
        drivable = [
            item for item in sequence
            if item.get("type") != "rest_lane"
            or self._polyline_length_m(self._coords(item)) >= self.MIN_DRIVEN_LANE_M
        ]
        if drivable and drivable[0] is not sequence[0]:
            # Der gewaehlte Startpunkt liegt auf einer Zwergbahn. Sie zu
            # behalten hilft nicht: real am 09.08. war die gewaehlte Bahn 67
            # nur 0,73 m lang und lief 111 Grad quer zum stehenden Fahrzeug -
            # eindrehen laesst sich das auf 73 Zentimetern nicht. Also
            # beginnt der Plan bei der naechsten richtigen Bahn, und der
            # Marker wird fallengelassen: er gehoert zu einer Bahn, die nicht
            # gefahren wird.
            logging.getLogger(__name__).info(
                "Startbahn %r ist nur %.2f m lang - Plan beginnt bei Bahn %r",
                sequence[0].get("segment_index"),
                self._polyline_length_m(self._coords(sequence[0])),
                drivable[0].get("segment_index"),
            )
            start_coordinate = None
        sequence = drivable
        if max_source_segments is not None:
            try:
                source_limit = int(max_source_segments)
            except (TypeError, ValueError):
                raise ValueError("max_source_segments muss eine Zahl sein")
            if source_limit < 1:
                raise ValueError("max_source_segments muss mindestens 1 sein")
            sequence = sequence[:source_limit]
        runtime_router = self._runtime_transition_router(plan)
        sequence = self._blocks_entered_from_the_near_end(sequence, runtime_router)
        transitions_by_pair = {
            (item.get("from_segment_index"), item.get("to_segment_index")): item
            for item in plan.get("transitions") or []
        }
        executable: List[Dict[str, Any]] = []
        current_end = None
        previous_index = None
        previous_segment = None
        start_coord = self._pose_coord(start_pose)
        start_heading_deg = self._pose_heading(start_pose)
        current_heading_deg = start_heading_deg
        selected_start = self._validated_coord(start_coordinate)

        # Ein geschlossener Ring wird in beide Richtungen vollständig gemäht.
        # Welche richtig ist, hängt davon ab, woher das Fahrzeug kommt - das
        # weiß der Planer nicht, deshalb wird es hier einmal für die ganze
        # Route entschieden. Fest im Planer verdrahtet zwang der Drehsinn das
        # Fahrzeug sonst in eine Schleife, nur um von der falschen Seite auf
        # den ersten Ring zu kommen (real, 02.08.).
        # Bezugspunkt ist die Stelle der ersten Bahn, an der das Fahrzeug
        # tatsächlich ankommt - nicht deren gespeicherter erster Stützpunkt.
        # Gegen den verglichen betrachtete die Drehsinn-Wahl einen ganz
        # anderen Abschnitt des Rings als die anschließende Startpunktwahl.
        approach_reference = selected_start
        if approach_reference is None and sequence and start_coord is not None:
            approach_reference = min(
                self._coords(sequence[0]),
                key=lambda coord: self._coord_distance_m(coord, start_coord),
            )
        approach_bearing = self._approach_bearing(
            start_coord, approach_reference, start_heading_deg
        )
        reverse_rings = self._prefers_reversed_rings(
            sequence[0] if sequence else None,
            approach_reference if selected_start is not None else start_coord,
            approach_bearing,
            vehicle=start_coord,
        )
        if selected_start is not None and sequence and start_coord is not None:
            # Ein geschlossener Ring wird in beide Richtungen vollständig
            # gemäht. Welche davon gefahren wird, entscheidet ab hier die
            # Anfahrt: das Fahrzeug faehrt keinen engeren Bogen als
            # POSITIONING_TURN_RADIUS_M, also liegt die Richtung, in der es am
            # Marker ankommen kann, weitgehend fest - der Ring hat dagegen die
            # freie Wahl. Andersherum gerechnet musste frueher der Ringanfang
            # vom Marker weglaufen, bis er zur Anfahrt passte.
            reverse_rings = self._ring_sense_for_selected_start(
                sequence[0],
                selected_start,
                start_coord,
                start_heading_deg,
                default=reverse_rings,
            )
        elif (
            sequence
            and start_coord is not None
            and start_heading_deg is not None
            and self._is_closed(self._coords(sequence[0]))
            and min(
                self._coord_distance_m(start_coord, point)
                for point in self._coords(sequence[0])
            ) <= self.ON_TRACK_DISTANCE_M
        ):
            # Fortsetzen: das Fahrzeug steht schon auf dem ersten Ring. Ein
            # Ring wird nie rueckwaerts gemaeht, sondern andersherum
            # durchfahren - und zwar der ganze Plan, nicht nur dieser eine.
            # Nur den ersten umzudrehen stiess ihn gegen den naechsten: aus
            # einem 1,55-m-Uebergang wurde ein 25,8-m-Eindrehmanoever
            # (08.08.), waehrend alle folgenden Uebergaenge kurz blieben.
            reverse_rings = self._ring_sense_for_resume(
                sequence[0], start_coord, start_heading_deg, default=reverse_rings
            )

        for segment in sequence:
            if reverse_rings:
                segment = dict(segment, coordinates=list(reversed(self._coords(segment))))
            if current_end is None and selected_start is not None:
                # Ohne Anflugrichtung: die Bahn beginnt am gewählten Punkt,
                # und die Anfahrt kommt dort in Bahnrichtung an, egal wie das
                # Fahrzeug steht. Welchen Drehsinn der Ring bekommt, ist damit
                # schon oben entschieden.
                coords = self._coords_from_selected_start(segment, selected_start)
            else:
                # Vor der ersten Bahn steht normalerweise die Anfahrt, die auf
                # die Bahn einschwenkt - dort zählt die Anflugrichtung, nicht
                # der Kurs am Stellplatz.
                #
                # Beim Fortsetzen steht das Fahrzeug aber schon auf dieser
                # Bahn. Dann gibt es keine Anfahrt, und die Anflugrichtung ist
                # die Peilung auf einen Punkt direkt unter dem Fahrzeug, also
                # beliebig. Damit gewählt begann der Ring an einem Stützpunkt,
                # der 91,3° zur Nase stand, obwohl 45,9° möglich waren
                # (08.08.). Hier zählt der gemessene Kurs.
                orientation = (
                    approach_bearing if current_end is None else current_heading_deg
                )
                if (
                    current_end is None
                    and selected_start is None
                    and start_coord is not None
                    and start_heading_deg is not None
                    and min(
                        self._coord_distance_m(start_coord, point)
                        for point in self._coords(segment)
                    ) <= self.ON_TRACK_DISTANCE_M
                ):
                    orientation = start_heading_deg
                coords = self._oriented_track_coords(
                    segment,
                    current_end or start_coord,
                    orientation,
                    vehicle=start_coord if current_end is None else None,
                )
            if current_end is None and selected_start is None and start_coord is not None:
                if self._is_closed(self._coords(segment)):
                    # Ein Ring wird nicht zugeschnitten. _oriented_track_coords
                    # hat ihn schon auf den Stuetzpunkt beim Fahrzeug gedreht,
                    # und zwar geschlossen - der Regler erkennt eine Bahn nur
                    # dann als Ring, wenn Anfang und Ende auf 5 cm
                    # zusammenfallen. Zugeschnitten klaffte dort eine kleine
                    # Luecke; die Bahn galt dann als beendet, sobald das
                    # Fahrzeug in der Naehe des letzten Stuetzpunkts stand.
                    pass
                else:
                    trimmed = self._trim_coords_from_point(coords, start_coord, max_distance_m=1.5)
                    if trimmed is not None:
                        coords = trimmed
            start = coords[0]
            emitted_before = len(executable)
            end_before = current_end
            heading_before = current_heading_deg
            if current_end is None:
                already_on_track = (
                    start_coord is not None
                    and selected_start is None
                    and self._distance_to_polyline_m(start_coord, coords)
                    <= self.RESUME_ON_TRACK_M
                )
                # Beim Fortsetzen steht das Fahrzeug auf seiner Bahn - gemessen
                # wird deshalb der Abstand zur Bahnlinie, nicht der zum
                # naechsten Stuetzpunkt. Der ist eine ganz andere Groesse: bei
                # Ring 9 lag der naechste Stuetzpunkt 0,99 m entfernt, die
                # Bahnlinie selbst aber 0,01 m. Nach dem Stuetzpunkt gemessen
                # entstand daraus eine 0,98 m lange "Anfahrt", und bei so
                # kurzen Stuecken ist die Richtung fast beliebig: der Regler
                # sperrte sie mit 63,9 Grad, 1,8 s nach dem Start (08.08.,
                # 20:22 Uhr). Der Rest ist Querabweichung, die der Regler beim
                # Aufnehmen der Bahn selbst ausgleicht - sie bleibt klar unter
                # track_cross_track_limit_m.
                if not already_on_track and (
                    start_coord is None
                    or self._coord_distance_m(start_coord, start) > 0.05
                ):
                    if start_coord is None:
                        # Direct callers may inspect a plan without a live pose.
                        # Production check_plan always supplies the current RTK
                        # pose, allowing the positioning leg to be routed below.
                        executable.append({
                            "type": "positioning",
                            "source_type": segment.get("type"),
                            "mode": "goto",
                            "direction": "forward",
                            "coordinates": [start],
                            "length_m": 0.0,
                            "route_kind": "pose_required",
                        })
                    else:
                        positioning = self._routed_positioning_segment(
                            runtime_router,
                            start_coord,
                            start,
                            source_type=segment.get("type", "positioning"),
                            to_segment_index=segment.get("segment_index"),
                            start_heading_deg=start_heading_deg,
                            arrival_heading_deg=self._segment_entry_heading(
                                coords, segment.get("direction")
                            ),
                        )
                        executable.append(positioning)
                        current_heading_deg = self._segment_end_heading(
                            positioning,
                            current_heading_deg,
                        )
            elif self._coord_distance_m(current_end, start) > 0.05:
                def build_transfer(target):
                    return self._transfer_segment(
                        transitions_by_pair.get(
                            (previous_index, segment.get("segment_index"))
                        ),
                        current_end,
                        target,
                        runtime_router=runtime_router,
                        previous_segment=previous_segment,
                        next_segment=segment,
                        start_heading_deg=current_heading_deg,
                    )

                # Hier waere der Platz, die Restbahn vom anderen Ende her
                # anzufangen - beide Enden sind erlaubt, und beim Fall vom
                # 08.08. stuende die Nase dort 27,1 statt 85,6 Grad zur Bahn.
                # Ausprobiert und wieder entfernt: es verschiebt die
                # festgenagelte Wiesenroute um 68 m (2245,0 -> 2313,0) und
                # loeste den Fall trotzdem nicht (74,7 Grad blieben). Die
                # Wahl gehoert in _oriented_track_coords und braucht eine
                # eigene Runde am Pruefstand.
                transfer = build_transfer(start)
                if not self._absorbs_short_rest_lane_transfer(
                    transfer,
                    previous_segment,
                    segment,
                    current_end,
                    start,
                ):
                    # Sperrt der Regler diesen Übergang am Winkel, wird
                    # stattdessen in die Fläche hinein eingedreht und an den
                    # Bahnanfang zurückgestoßen. Das gilt für beide Enden:
                    # ein Übergang, in den das Fahrzeug gut hineinkommt, kann
                    # es trotzdem quer zur nächsten Bahn abstellen. Real am
                    # 08.08. um 22:16: der Übergang selbst lag bei 41,3° und
                    # galt damit als fahrbar, nach seinen 14,7 m rückwärts
                    # stand das Fahrzeug aber 85,6° quer zur Restbahn - und
                    # dort sperrte der Regler. Geprüft wurde nur die Einfahrt.
                    manoeuvre = None
                    # Ein kurzer Huepfer zwischen zwei Bahnen wird immer
                    # eingeschert - unabhaengig vom Kurs, den die Route an
                    # dieser Stelle vorhersagt. Genau hier weicht der
                    # modellierte Kurs vom echten ab: das Stueck ist zu kurz,
                    # um eine belastbare Richtung zu haben. Am 09.08. lief
                    # deshalb ein 1,19-m-Uebergang durch die Vorabpruefung und
                    # wurde beim Fahren mit 47,2 Grad gesperrt - zweimal, mit
                    # denselben Zahlen. Vorhergesagt braucht es dafuer nichts:
                    # dass die Richtung eines Meterstuecks nicht zur Bahn
                    # passt, steht schon im Plan.
                    if self._is_sideways_lane_hop(
                        transfer, previous_segment, segment, coords
                    ):
                        joined = self._joined_transfer(
                            current_end, coords, runtime_router,
                            current_heading_deg,
                        )
                        if joined is not None and not self._blocks_on_heading(
                            joined, current_heading_deg
                        ):
                            manoeuvre = [joined]
                    if manoeuvre is None and (
                        self._blocks_on_heading(
                            transfer, current_heading_deg
                        ) or self._leaves_vehicle_across_lane(
                            transfer, segment, coords, current_heading_deg
                        )
                    ):
                        # Sonst dasselbe Mittel, aber am Kurs entschieden.
                        joined = self._joined_transfer(
                            current_end, coords, runtime_router,
                            current_heading_deg,
                        )
                        if joined is not None and not self._blocks_on_heading(
                            joined, current_heading_deg
                        ):
                            manoeuvre = [joined]
                    if manoeuvre is None and (
                        self._blocks_on_heading(transfer, current_heading_deg)
                        or self._leaves_vehicle_across_lane(
                            transfer, segment, coords, current_heading_deg
                        )
                    ):
                        manoeuvre = self._turn_in_transfer(
                            current_end, current_heading_deg, coords, runtime_router
                        )
                        if manoeuvre is None:
                            # Das Eindrehmanoever faehrt in die Zielbahn hinein
                            # und stoesst zurueck - dafuer muss die Bahn lang
                            # genug sein. Bei 14,6 m seitlichem Versatz
                            # verlangte es 20 m Tiefe in einer 4,64 m langen
                            # Restbahn und kam nicht zustande (08.08.). Dann
                            # der Bogen, der auch die Anfahrt zum Planbeginn
                            # baut: der braucht die Bahn nicht als Platz.
                            manoeuvre = self._arc_transfer(
                                current_end,
                                current_heading_deg,
                                segment,
                                coords,
                                runtime_router,
                            )
                    for item in manoeuvre or [transfer]:
                        executable.append(item)
                        current_heading_deg = self._segment_end_heading(
                            item,
                            current_heading_deg,
                        )

            # Eine kurze Bahn, die das Fahrzeug von hier aus nicht aufnehmen
            # kann, wird uebersprungen statt unfahrbar ausgegeben. Geprueft
            # wird erst hier, weil der Uebergang davor den Kurs noch dreht.
            # Laenger als SKIPPABLE_LANE_M lohnt ein Manoever; darunter kostet
            # es mehr Weg, als die Bahn lang ist. Real am 09.08.: eine
            # 1,41-m-Bahn nach einem 17-m-Umweg um die Sperrzone, 68,4 Grad
            # quer - der Regler haette dort gestoppt und die restlichen
            # 2000 m waeren liegengeblieben.
            if (
                # Die erste Bahn nur dann, wenn kein Marker daran haengt:
                # uebersprungen suchte ihn sonst die naechste Bahn bei sich
                # und fand ihn nicht - Play brach ab mit "Gewaehlte
                # Abfahrposition liegt nicht auf dem gewaehlten Pfad"
                # (real 09.08.).
                (current_end is not None or selected_start is None)
                and segment.get("type") == "rest_lane"
                and self._polyline_length_m(coords) <= self.SKIPPABLE_LANE_M
                and self._lane_entry_error(coords, current_heading_deg)
                > self.RING_START_HEADING_LIMIT_DEG
            ):
                # Auch den Weg dorthin zuruecknehmen: ein Uebergang zu einer
                # Bahn, die gar nicht gemaeht wird, ist reine Fahrerei. Ohne
                # das standen vier 0,70-m-Uebergaenge zu uebersprungenen
                # Bahnen in der Route (gemessen 09.08.).
                del executable[emitted_before:]
                current_end = end_before
                current_heading_deg = heading_before
                continue

            track = self._track_segment(
                segment,
                coordinates=coords,
                # current_heading_deg is the heading the vehicle physically
                # ends the previous segment with (live RTK pose for the first
                # one, then _segment_end_heading of what was actually
                # compiled). Every lane must be evaluated against it, not
                # just the first: on an uninterrupted run the plan's own
                # alternating directions already match it, so this is a
                # no-op there. After a resume or skip the traversal sense of
                # one lane can be inverted, and only this check keeps the
                # following lanes from demanding a 180 degree turnaround
                # (real, 25.07.: lane 37 asked for 178.9 deg after lane 36
                # had been resumed east-to-west).
                heading_deg=current_heading_deg,
            )
            executable.append(track)
            current_heading_deg = self._segment_end_heading(
                track,
                current_heading_deg,
            )
            current_end = coords[-1]
            previous_index = segment.get("segment_index")
            previous_segment = segment

        return executable

    def _blocks_entered_from_the_near_end(
        self,
        sequence: List[Dict[str, Any]],
        runtime_router,
    ) -> List[Dict[str, Any]]:
        """Bahnbloecke hinter einer Sperrzone am naeheren Ende beginnen.

        Der Planer legt die Bahnreihenfolge fest, ohne zu wissen, dass eine
        Sperrzone dazwischen liegt. Am Brunnen fuehrt das dazu, dass die
        Bahnen links davon an ihrem *unteren* Ende begonnen werden: das
        Fahrzeug kommt oben rechts an und muss einmal um den halben Brunnen
        herum, um dort hinzukommen.

        Dieser Weg ist nicht fahrbar. Er entsteht als ``around_sub`` und legt
        sich damit an die Grenze der Sperrzone - 23 Stuetzpunkte auf 40 m
        Umfang, Ecken von 43 bis 53 Grad, also Wenderadien von 1,4 bis 3,5 m.
        Das Fahrzeug braucht fuer eine anhaltende Drehung rund 7 m. Real am
        09.08. zweimal belegt: voller Lenkausschlag, der Kursfehler zur Bahn
        schrumpft, die Querabweichung waechst trotzdem von 0,49 auf 0,91 m,
        dann cross_track_stop. Im Simulator lief derselbe Uebergang - 13,8 m
        auf 16 Stuetzpunkten - 207 s lang und wurde nicht fertig; die Bahn
        danach begann mit 86,3 Grad Kursfehler.

        Ein Bahnblock hat aber zwei Enden, und beide sind erlaubte Anfaenge -
        welches genommen wird, entscheidet nur, in welcher Richtung er
        abgearbeitet wird. Vom oberen Ende her kostet der Wechsel 5,2 statt
        17,3 m und laeuft nordlich am Brunnen vorbei statt um ihn herum: drei
        Stuetzpunkte, eine Ecke von 26 Grad.

        Angefasst wird ausschliesslich die Reihenfolge *innerhalb* eines
        Blocks, dessen Anfahrt eine Sperrzone umgehen muss. Steht keine
        Sperrzone im Weg, bleibt der Plan Bahn fuer Bahn so, wie der Planer
        ihn gelegt hat - die Wiesenroute enthaelt keinen einzigen solchen
        Uebergang und aendert sich dadurch nicht.
        """
        if runtime_router is None or len(sequence) < 3:
            return sequence
        result = list(sequence)
        index = 1
        while index < len(result):
            block_end = self._lane_block_behind_a_sub(runtime_router, result, index)
            if block_end is None:
                index += 1
                continue
            if self._block_is_shorter_reversed(runtime_router, result, index, block_end):
                logging.getLogger(__name__).info(
                    "Bahnen %r bis %r werden vom anderen Ende her gefahren - "
                    "sonst fuehrt die Anfahrt um eine Sperrzone herum",
                    result[index].get("segment_index"),
                    result[block_end - 1].get("segment_index"),
                )
                result[index:block_end] = list(reversed(result[index:block_end]))
            index = block_end
        return result

    def _lane_block_behind_a_sub(
        self,
        runtime_router,
        sequence: List[Dict[str, Any]],
        index: int,
    ) -> Optional[int]:
        """Ende des Blocks, dessen Anfahrt um eine Sperrzone herum fuehrt.

        ``None``, wenn an dieser Stelle keine Sperrzone im Weg steht oder das
        Stueck dahinter zu kurz ist, um eine Reihenfolge zu haben - dann gibt
        es nichts umzuordnen.

        Der Block reicht so weit, wie seine Bahnen ohne Umweg aneinander
        haengen. Die erste Bahn, die selbst wieder um etwas herum angefahren
        werden muss, gehoert schon zum naechsten Block und wird gesondert
        betrachtet.
        """
        previous = sequence[index - 1]
        segment = sequence[index]
        if previous.get("type") != "rest_lane" or segment.get("type") != "rest_lane":
            return None
        entry = self._block_link(
            runtime_router, self._coords(previous)[-1], self._coords(segment)[0]
        )
        if entry is None or entry[1] != "around_sub":
            return None
        end = index + 1
        while end < len(sequence) and sequence[end].get("type") == "rest_lane":
            step = self._block_link(
                runtime_router,
                self._coords(sequence[end - 1])[-1],
                self._coords(sequence[end])[0],
            )
            if step is None or step[1] != "direct":
                break
            end += 1
        if end - index < self.MIN_REORDERED_BLOCK_LANES:
            return None
        return end

    def _block_is_shorter_reversed(
        self,
        runtime_router,
        sequence: List[Dict[str, Any]],
        index: int,
        block_end: int,
    ) -> bool:
        """Lohnt es, den Block von hinten nach vorn zu fahren?

        Gerechnet wird der ganze Preis, nicht nur die Anfahrt: ein umgedrehter
        Block endet am anderen Ende, und der Weg von dort zum naechsten Block
        gehoert dazu. Steht kein naechster Block mehr an - wie am Brunnen, wo
        die linken Bahnen den Plan beschliessen -, kostet das Ende nichts.
        """
        arrival = self._coords(sequence[index - 1])[-1]
        first = self._coords(sequence[index])[0]
        last = self._coords(sequence[block_end - 1])[-1]
        departure = (
            self._coords(sequence[block_end])[0]
            if block_end < len(sequence) else None
        )
        planned = self._block_cost_m(runtime_router, arrival, first, last, departure)
        turned = self._block_cost_m(runtime_router, arrival, last, first, departure)
        if turned is None:
            return False
        if planned is None:
            # Der geplante Weg ist ueberhaupt nicht sicher zu routen, der
            # andere schon - dann ist die Wahl keine Abwaegung mehr.
            return True
        return planned - turned > self.BLOCK_REVERSAL_GAIN_M

    def _block_cost_m(
        self,
        runtime_router,
        arrival: List[float],
        entry: List[float],
        exit_point: List[float],
        departure: Optional[List[float]],
    ) -> Optional[float]:
        """Weg zum Block hin und von ihm weg, ohne die Bahnen selbst."""
        link = self._block_link(runtime_router, arrival, entry)
        if link is None:
            return None
        total = link[0]
        if departure is not None:
            onward = self._block_link(runtime_router, exit_point, departure)
            if onward is None:
                return None
            total += onward[0]
        return total

    @staticmethod
    def _block_link(
        runtime_router,
        from_coord: List[float],
        to_coord: List[float],
    ) -> Optional[Tuple[float, str]]:
        """Laenge und Art des Wegs zwischen zwei Bahnenden.

        ``None``, wenn es keinen sicheren Weg gibt.
        """
        routed = runtime_router.plan_between(
            from_coord,
            to_coord,
            from_type="rest_lane",
            to_type="rest_lane",
        )
        if not routed.safe:
            return None
        return float(routed.length_m), str(routed.route_kind)

    def _absorbs_short_rest_lane_transfer(
        self,
        transfer: Dict[str, Any],
        previous_segment: Optional[Dict[str, Any]],
        next_segment: Optional[Dict[str, Any]],
        from_coord: List[float],
        to_coord: List[float],
    ) -> bool:
        if (previous_segment or {}).get("type") != "rest_lane":
            return False
        if (next_segment or {}).get("type") != "rest_lane":
            return False
        if str(transfer.get("route_kind", "")).split("_")[-1] != "direct":
            return False
        step_m = self._coord_distance_m(from_coord, to_coord)
        if step_m <= self.ABSORBED_REST_LANE_TRANSFER_M:
            return True
        # Entscheidend ist nicht, wie lang der Huepfer ist, sondern wie weit
        # er quer zur naechsten Bahn liegt - denn nur das muss der Regler
        # ausgleichen. Ein Schritt, der groesstenteils in Bahnrichtung geht,
        # ist als eigener Track sogar schaedlich: bei 0,97 m Laenge zeigte er
        # 316 Grad, waehrend die Nase mit 268,7 Grad korrekt auf beiden Bahnen
        # lag - 47,5 Grad Differenz, und der Regler sperrte (real 09.08.,
        # 11:48 Uhr). Bei so kurzen Stuecken ist die Richtung Rauschen.
        if step_m > self.ABSORBED_REST_LANE_STEP_M:
            return False
        return (
            self._distance_to_polyline_m(from_coord, self._coords(next_segment))
            <= self.ABSORBED_REST_LANE_CROSS_M
        )

    def _transfer_segment(
        self,
        transition: Optional[Dict[str, Any]],
        from_coord: List[float],
        to_coord: List[float],
        runtime_router=None,
        previous_segment: Optional[Dict[str, Any]] = None,
        next_segment: Optional[Dict[str, Any]] = None,
        start_heading_deg: Optional[float] = None,
    ) -> Dict[str, Any]:
        if runtime_router is None:
            if transition is not None:
                segment = self._transition_segment(
                    transition,
                    from_coord=from_coord,
                    to_coord=to_coord,
                )
                if segment is not None:
                    return self._select_transfer_direction(segment, start_heading_deg)
            raise ValueError(
                "Übergang passt nach Bahnorientierung nicht und kann ohne "
                "Kartengeometrie nicht sicher neu geroutet werden"
            )
        previous_segment = previous_segment or {}
        next_segment = next_segment or {}
        routed = runtime_router.plan_between(
            from_coord,
            to_coord,
            transition_index=int((transition or {}).get("transition_index", -1)),
            from_segment_index=int(previous_segment.get("segment_index", -1)),
            to_segment_index=int(next_segment.get("segment_index", -1)),
            from_type=str(previous_segment.get("type", "unknown")),
            to_type=str(next_segment.get("type", "unknown")),
        ).to_dict()
        segment = self._transition_segment(routed, from_coord=from_coord, to_coord=to_coord)
        if segment is None:
            raise ValueError("Neu berechneter Übergang passt nicht zu den ausführbaren Bahnenden")
        segment["route_kind"] = f"runtime_{segment['route_kind']}"
        segment = self._select_transfer_direction(segment, start_heading_deg)
        return self._rolled_into_direction(segment, start_heading_deg, runtime_router)

    @classmethod
    def _blocks_on_heading(
        cls, segment: Dict[str, Any], heading_deg: Optional[float]
    ) -> bool:
        """Würde der Regler dieses Segment am Winkel ablehnen?"""
        if heading_deg is None:
            return False
        coords = segment.get("coordinates") or []
        if len(coords) < 2:
            return False
        nose = cls._edge_bearing_deg(coords[0], coords[1])
        if nose is None:
            return False
        if segment.get("direction") == "reverse":
            nose = (nose + 180.0) % 360.0
        return cls._angle_error_deg(nose, heading_deg) > cls.RING_START_HEADING_LIMIT_DEG

    def _lane_entry_error(
        self,
        lane_coords: List[List[float]],
        heading_deg: Optional[float],
    ) -> float:
        """Wie schief die Nase zu dieser Bahn steht - guenstigere Seite zaehlt.

        Eine Restbahn darf in beide Richtungen gefahren werden; entscheidend
        ist die, zu der weniger gedreht werden muss.
        """
        if heading_deg is None or len(lane_coords) < 2:
            return 0.0
        tangent = self._segment_entry_heading(lane_coords, "forward")
        if tangent is None:
            return 0.0
        return min(
            self._angle_error_deg(tangent, heading_deg),
            self._angle_error_deg((tangent + 180.0) % 360.0, heading_deg),
        )

    def _leaves_vehicle_across_lane(
        self,
        transfer: Dict[str, Any],
        segment: Dict[str, Any],
        lane_coords: List[List[float]],
        heading_deg: Optional[float],
    ) -> bool:
        """Stellt dieser Uebergang das Fahrzeug quer zur naechsten Bahn ab?

        Gegenstueck zu _blocks_on_heading, das nur die Einfahrt prueft. Ein
        langer Uebergang dreht das Fahrzeug unterwegs; entscheidend fuer die
        folgende Bahn ist, wie die Nase am *Ende* steht.

        Eine Restbahn darf in beide Richtungen gefahren werden, also zaehlt
        die guenstigere der beiden. Ein geschlossener Ring wird immer vorwaerts
        gefahren - dort gibt es nur eine.
        """
        return (
            self._lane_arrival_error(transfer, segment, lane_coords, heading_deg)
            > self.RING_START_HEADING_LIMIT_DEG
        )

    def _lane_arrival_error(
        self,
        transfer: Dict[str, Any],
        segment: Dict[str, Any],
        lane_coords: List[List[float]],
        heading_deg: Optional[float],
    ) -> float:
        """Wie schief die Nase am Ende des Uebergangs zur Bahn steht."""
        if heading_deg is None or len(lane_coords) < 2:
            return 0.0
        arrival = self._segment_end_heading(transfer, heading_deg)
        tangent = self._segment_entry_heading(lane_coords, "forward")
        if arrival is None or tangent is None:
            return 0.0
        error = self._angle_error_deg(tangent, arrival)
        if segment.get("type") == "rest_lane" and self.reverse_track_supported:
            error = min(
                error,
                self._angle_error_deg((tangent + 180.0) % 360.0, arrival),
            )
        return error

    def _is_sideways_lane_hop(
        self,
        transfer: Dict[str, Any],
        previous_segment: Optional[Dict[str, Any]],
        next_segment: Optional[Dict[str, Any]],
        lane_coords: List[List[float]],
    ) -> bool:
        """Kurzer Schritt zwischen zwei Bahnen, der quer zu ihnen zeigt.

        Er ueberbrueckt Bahnabstand und Endenversatz zugleich und zeigt
        dadurch in eine Richtung, die zu keiner der beiden Bahnen gehoert.
        Ihn als eigene Bahn zu fahren geht schief, sobald der reale Kurs auch
        nur wenig vom vorhergesagten abweicht - und bei einem Meter Laenge
        weicht er immer ab. Gemessen 09.08.: 1,19 m Uebergang, 47,2 Grad,
        zweimal gesperrt, waehrend die Nase auf beiden Nachbarbahnen sauber
        lag.

        Bewusst ohne jeden Kursvergleich: die Entscheidung faellt allein aus
        der Geometrie des Plans und ist damit unabhaengig davon, wie gut die
        Kursvorhersage an dieser Stelle ist.
        """
        if (previous_segment or {}).get("type") != "rest_lane":
            return False
        if (next_segment or {}).get("type") != "rest_lane":
            return False
        if len(lane_coords) < 2:
            return False
        if transfer.get("length_m", 0.0) > self.SIDEWAYS_LANE_HOP_M:
            return False
        coords = transfer.get("coordinates") or []
        if len(coords) < 2:
            return False
        step = self._edge_bearing_deg(coords[0], coords[-1])
        tangent = self._segment_entry_heading(lane_coords, "forward")
        if step is None or tangent is None:
            return False
        # Quer heisst: weder in noch gegen die Bahnrichtung.
        across = min(
            self._angle_error_deg(step, tangent),
            self._angle_error_deg(step, (tangent + 180.0) % 360.0),
        )
        return across > self.SIDEWAYS_LANE_HOP_ANGLE_DEG

    def _joined_transfer(
        self,
        from_coord: List[float],
        lane_coords: List[List[float]],
        runtime_router,
        start_heading_deg: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Uebergang, der auf die Bahnlinie einschert statt quer anzukommen.

        Ein kurzer Huepfer von einer Bahn zur naechsten laeuft diagonal: er
        ueberbrueckt den Bahnabstand und den Versatz der Bahnenden zugleich.
        Als eigene Bahn gefahren zeigt er dadurch in eine Richtung, die mit
        keiner der beiden Bahnen etwas zu tun hat - real am 09.08. 47,2 Grad
        auf 0,97 m, vom Regler gesperrt. Weggelassen bleibt stattdessen der
        Querversatz stehen, und den baut das Fahrzeug rueckwaerts ab einem
        halben Meter nicht mehr ab (gemessen 09.08.: 0,56 m am Bahnanfang,
        0,74 m am Ende, danach 1,42 m und Abbruch).

        Beides vermeidet dieser Weg: der Uebergang zielt nicht auf den
        Bahnanfang, sondern auf einen Punkt auf der *Verlaengerung* der Bahn
        davor. Von dort laeuft er gerade in den Bahnanfang. Das Fahrzeug
        schert flach ein und beginnt die Bahn auf der Linie - ohne Versatz und
        ohne Knick. Die Verlaengerung liegt im schon gemaehten Bereich neben
        der Bahn, kostet also nichts.
        """
        if runtime_router is None or len(lane_coords) < 2:
            return None
        tangent = self._segment_entry_heading(lane_coords, "forward")
        if tangent is None:
            return None
        lateral = self._distance_to_polyline_m(from_coord, lane_coords)
        if lateral <= 0.05:
            return None
        # Flach einscheren: der Anlauf ist so lang, dass der Winkel zur Bahn
        # unter JOIN_LANE_ANGLE_DEG bleibt.
        run_m = max(
            self.MIN_JOIN_LANE_RUN_M,
            lateral / math.tan(math.radians(self.JOIN_LANE_ANGLE_DEG)),
        )
        if run_m > self.MAX_JOIN_LANE_RUN_M:
            return None
        entry = self._offset_coord(
            lane_coords[0], (tangent + 180.0) % 360.0, run_m
        )
        coords = [list(from_coord), entry, list(lane_coords[0])]
        if self._coord_distance_m(coords[0], coords[1]) < 0.05:
            return None
        # Das Eck am Einscherpunkt ausrunden. Als scharfer Knick gefahren
        # faellt der Regler dort in den Ausrichtmodus und kriecht: der
        # Simulator kam 2,97 von 4,76 m weit und lief in die
        # Zeitueberschreitung (09.08.). Mit einem Bogen, dessen Radius die
        # Messtabelle traegt, laeuft er durch.
        if start_heading_deg is not None:
            smooth = self._merge_onto_lane_coords(
                from_coord, start_heading_deg, lane_coords[0], tangent
            )
            if smooth is not None and runtime_router.is_polyline_safe(smooth):
                coords = smooth
        if not runtime_router.is_polyline_safe(coords):
            return None
        joined = {
            "type": "transition",
            "source_index": None,
            "mode": "track",
            "direction": "forward",
            "route_kind": "join_lane",
            "coordinates": coords,
            "length_m": round(self._polyline_length_m(coords), 2),
        }
        joined = self._select_transfer_direction(joined, start_heading_deg)
        if joined.get("direction") == "reverse":
            # Rueckwaerts eingeschert bricht der Regler am Knick ab: der
            # Simulator kam 4,06 von 4,52 m weit und stieg mit
            # cross_track_stop aus (09.08.). Kommt das Fahrzeug von einer
            # rueckwaerts gemaehten Bahn, bleibt es beim geraden Uebergang -
            # lieber die alte Loesung als eine neue, die nicht faehrt.
            return None
        return joined

    def _arc_transfer(
        self,
        from_coord: List[float],
        start_heading_deg: Optional[float],
        segment: Dict[str, Any],
        lane_coords: List[List[float]],
        runtime_router,
    ) -> Optional[List[Dict[str, Any]]]:
        """Uebergang als Bogen, der in Bahnrichtung am Bahnanfang ankommt.

        Letzte Moeglichkeit, wenn der gerade Uebergang das Fahrzeug quer
        abstellt und das Eindrehmanoever nicht in die Zielbahn passt. Benutzt
        dieselbe Konstruktion wie die Anfahrt zum Planbeginn - Radien, die der
        Regler nachweislich haelt, und ein Einlauf in Bahnrichtung.

        Eine Restbahn darf in beide Richtungen gefahren werden; genommen wird
        die, zu der weniger gedreht werden muss.
        """
        if start_heading_deg is None or runtime_router is None:
            return None
        tangent = self._segment_entry_heading(lane_coords, "forward")
        if tangent is None:
            return None
        targets = [tangent]
        if segment.get("type") == "rest_lane" and self.reverse_track_supported:
            targets.append((tangent + 180.0) % 360.0)
        targets.sort(key=lambda value: self._angle_error_deg(value, start_heading_deg))

        # Bewusst die Bauer direkt und nicht _approach_arc_coords: das misst
        # jeden Bogen gegen die gerade Verbindung und verwirft ihn, wenn die
        # nicht schlechter ankommt. Fuer die Anfahrt stimmt das - dort ist die
        # Gerade die Alternative. Hier ist sie es nicht: sie ist unbrauchbar,
        # weil das Fahrzeug quer zu ihr steht, und genau deshalb sind wir hier.
        for target in targets:
            for build in (
                self._merge_onto_lane_coords, self._bend_onto_marker_coords
            ):
                coords = build(
                    from_coord, start_heading_deg, lane_coords[0], target
                )
                if coords is None or len(coords) < 2:
                    continue
                if self._route_heading_error(coords, start_heading_deg) > (
                    self.RING_START_HEADING_LIMIT_DEG
                ):
                    # Der Regler muss den Bogen auch aufnehmen koennen.
                    continue
                arrival = self._edge_bearing_deg(coords[-2], coords[-1])
                if self._angle_error_deg(arrival, target) > (
                    self.RING_START_HEADING_LIMIT_DEG
                ):
                    continue
                if not runtime_router.is_polyline_safe(coords):
                    continue
                return [{
                    "type": "transition",
                    "source_index": None,
                    "mode": "track",
                    "direction": "forward",
                    "route_kind": "arc_transfer",
                    "coordinates": coords,
                    "length_m": round(self._polyline_length_m(coords), 2),
                }]
        return None

    def _turn_in_transfer(
        self,
        from_coord: List[float],
        start_heading_deg: Optional[float],
        lane_coords: List[List[float]],
        runtime_router,
    ) -> Optional[List[Dict[str, Any]]]:
        """Übergang als Eindrehmanöver in der Fläche statt als Knick am Rand.

        Scheitert ein Übergang am Winkel, wird die Zielbahn nicht an ihrem
        Anfang angefahren, sondern ein Stück weiter innen - dort ist Platz zum
        rollenden Eindrehen. Von dort stößt das Fahrzeug rückwärts an den
        Bahnanfang zurück; die Nase zeigt dabei schon in Bahnrichtung, sodass
        die Bahn selbst mit null Winkelfehler beginnt.

        Der doppelt befahrene Abschnitt ist genau die Rückstoßstrecke. Ohne
        dieses Manöver blieb der Mäher am Wechsel zwischen den Planhälften
        stehen: 72,9° auf 5,92 m, vom Regler zu Recht gesperrt, und die halbe
        Wiese blieb ungemäht (real, 06.08.).
        """
        if start_heading_deg is None or runtime_router is None or len(lane_coords) < 2:
            return None
        tangent = self._edge_bearing_deg(lane_coords[0], lane_coords[1])
        if tangent is None:
            return None
        # Zwei Gründe, warum ein Übergang scheitert, und beide bestimmen, wie
        # weit hineingefahren werden muss:
        # der Drehwinkel (~13°/m gemessen) ...
        turn = self._angle_error_deg(tangent, start_heading_deg)
        depth = turn / (self.MAX_TURN_STEP_DEG / self.TURN_STEP_M)
        # ... und der seitliche Versatz. Der war der eigentliche Fall auf der
        # Wiese: die Zielbahn lief mit 158° praktisch parallel zum Kurs von
        # 159,7°, lag aber 5,92 m daneben. Ein Spurwechsel um d bei Wenderadius
        # r braucht rund 2*sqrt(2*r*d) Länge - aus dem Winkel allein gerechnet
        # kamen 4 m heraus, nötig sind 16.
        radius = self.TURN_STEP_M / math.radians(self.MAX_TURN_STEP_DEG)
        lateral = self._point_to_line_distance_m(from_coord, lane_coords[0], lane_coords[1])
        if lateral > 0.05:
            depth = max(depth, 2.0 * math.sqrt(2.0 * radius * lateral))
        depth = max(self.MIN_TURN_IN_M, min(self.MAX_TURN_IN_M, depth + self.TURN_IN_RESERVE_M))
        entry = self._point_along_polyline(lane_coords, depth)
        if entry is None or self._coord_distance_m(entry, lane_coords[0]) < self.MIN_TURN_IN_M / 2.0:
            return None

        # ACHTUNG: dieser Bogen beschreibt einen 4,3-m-Kreis (TURN_STEP_M je
        # MAX_TURN_STEP_DEG). Gemessen haelt der Regler eine anhaltende
        # Drehung erst ab 7 m, und in der Simulation laeuft das Manoever
        # deshalb aus dem Pfad (08.08., Brunnen, Uebergang nach dem
        # Fortsetzen). Der Ersatz durch _approach_arc_coords ist der richtige
        # Weg, aendert aber die festgenagelte Wiesenroute (2245,0 -> 2252,5 m)
        # und braucht eine eigene Runde am Pruefstand.
        approach = self._rolling_turn_coords(from_coord, start_heading_deg, [entry])
        if len(approach) < 2 or not runtime_router.is_polyline_safe(approach):
            return None
        first = self._edge_bearing_deg(approach[0], approach[1])
        if self._angle_error_deg(first, start_heading_deg) > self.RING_START_HEADING_LIMIT_DEG:
            return None
        arrival = self._edge_bearing_deg(approach[-2], approach[-1])
        if self._angle_error_deg(arrival, tangent) > self.RING_START_HEADING_LIMIT_DEG:
            return None

        back = [list(entry), list(lane_coords[0])]
        if not runtime_router.is_polyline_safe(back):
            return None
        return [
            {
                "type": "transition",
                "source_index": None,
                "mode": "track",
                "direction": "forward",
                "route_kind": "turn_in_approach",
                "coordinates": approach,
                "length_m": round(self._polyline_length_m(approach), 2),
            },
            {
                # Rückwärts: die Nase bleibt in Bahnrichtung stehen, deshalb
                # beginnt die Bahn danach ohne Winkelfehler.
                "type": "transition",
                "source_index": None,
                "mode": "track",
                "direction": "reverse",
                "route_kind": "turn_in_backup",
                "coordinates": back,
                "length_m": round(self._polyline_length_m(back), 2),
            },
        ]

    @classmethod
    def _point_along_polyline(
        cls, coords: List[List[float]], distance_m: float
    ) -> Optional[List[float]]:
        walked = 0.0
        for start, end in zip(coords, coords[1:]):
            span = cls._coord_distance_m(start, end)
            if span <= 1e-9:
                continue
            if walked + span >= distance_m:
                fraction = (distance_m - walked) / span
                return [
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                ]
            walked += span
        return None

    def _rolled_into_direction(
        self,
        segment: Dict[str, Any],
        start_heading_deg: Optional[float],
        runtime_router,
    ) -> Dict[str, Any]:
        """Übergang mit rollendem Bogen beginnen, wenn er quer zur Fahrt liegt.

        Der Regler lehnt jede Bahn ab, deren Winkelfehler *am Anfang* über 45°
        liegt - unabhängig davon, wie lang sie ist. Die Regel "Strecke reicht
        zum Drehen" genügt also nicht: der Wechsel zwischen den beiden
        Planhälften war 5,92 m lang und verlangte 70,8°, rückwärts 109°.
        Beides gesperrt, der Mäher blieb nach der ersten Hälfte stehen und die
        zweite wurde nie gefahren (real, 06.08.). Mit eingebautem Bogen
        beginnt der Übergang in Fahrtrichtung und dreht sich unterwegs ein.
        """
        if start_heading_deg is None or runtime_router is None:
            return segment
        coords = list(segment.get("coordinates") or [])
        if len(coords) < 2:
            return segment
        nose = self._edge_bearing_deg(coords[0], coords[1])
        if nose is not None and segment.get("direction") == "reverse":
            nose = (nose + 180.0) % 360.0
        if self._angle_error_deg(nose, start_heading_deg) <= self.RING_START_HEADING_LIMIT_DEG:
            return segment
        # Beide Drehrichtungen prüfen: die geometrisch kürzere führt am
        # Flächenrand regelmäßig nach außen und wird verworfen, während
        # nach innen Platz wäre (real, 06.08.: 21 m Bogen, ausserhalb).
        for clockwise in (None, True, False):
            turned = self._rolling_turn_coords(
                coords[0], start_heading_deg, coords[1:], clockwise=clockwise
            )
            if len(turned) <= len(coords):
                continue
            # Der Bogen stammt nicht vom Router: er darf nur gefahren werden,
            # wenn er die Mähfläche nicht verlässt und keine Sperrzone berührt.
            if not runtime_router.is_polyline_safe(turned):
                continue
            entry = self._edge_bearing_deg(turned[0], turned[1])
            if self._angle_error_deg(entry, start_heading_deg) > self.RING_START_HEADING_LIMIT_DEG:
                continue
            segment["coordinates"] = turned
            segment["length_m"] = round(self._polyline_length_m(turned), 2)
            segment["direction"] = "forward"
            return segment
        return segment

    def _routed_positioning_segment(
        self,
        runtime_router,
        from_coord: List[float],
        to_coord: List[float],
        *,
        source_type: str,
        to_segment_index: Optional[int],
        start_heading_deg: Optional[float] = None,
        arrival_heading_deg: Optional[float] = None,
    ) -> Dict[str, Any]:
        if runtime_router is None:
            raise ValueError("Startposition kann ohne Kartengeometrie nicht sicher geroutet werden")
        routed = runtime_router.plan_between(
            from_coord,
            to_coord,
            transition_index=-1,
            from_segment_index=-1,
            to_segment_index=int(to_segment_index if to_segment_index is not None else -1),
            from_type="start_pose",
            to_type=source_type,
            # The vehicle is parked wherever it is parked - a shed, a path,
            # the driveway - and driving from there to the first lane is a
            # normal part of the job. Requiring this leg to stay inside the
            # mapped area rejected the whole plan for a vehicle standing
            # 12.3 m outside it (real, 28.07.). Sub zones and the vehicle
            # clearance are still enforced below; only the outer boundary is
            # not, because there is nothing mapped out there to check.
            confine_to_mow_area=False,
        ).to_dict()
        if routed.get("safe") is not True:
            raise ValueError(
                "Startposition kann nicht sicher angefahren werden: der Weg zur ersten "
                "Bahn führt durch eine Sperrzone. Bitte das Fahrzeug umstellen."
            )
        segment = self._transition_segment(routed, from_coord=from_coord, to_coord=to_coord)
        if segment is None:
            raise ValueError("Startpositionierung passt nicht zum berechneten sicheren Pfad")
        segment.update({
            "type": "positioning",
            "source_type": source_type,
            "source_index": None,
            "route_kind": f"runtime_{segment['route_kind']}",
        })
        coordinates = list(segment["coordinates"])
        segment["length_m"] = round(self._polyline_length_m(coordinates), 2)
        segment = self._select_transfer_direction(segment, start_heading_deg)
        if segment.get("direction") == "reverse":
            # Rueckwaerts wird nur geradeaus zurueckgestossen, nie im Bogen:
            # ein aus dem Nasenkurs gerechneter Bogen liefe spiegelverkehrt zur
            # tatsaechlichen Bewegung. Dafuer muss das Fahrzeug aber an beiden
            # Enden passen - am Ziel richtig herum ankommen UND am Stellplatz
            # schon annaehernd auf der Linie stehen. Nur die Ankunft zu pruefen
            # liess Anfahrten stehen, die der Regler sofort am Kursfehler
            # sperrte, weil die Nase 60 bis 75 Grad quer zur Linie stand
            # (gemessen 08.08., Brunnen, Kurs 90 und 315).
            entry_error = (
                0.0 if start_heading_deg is None
                else self._route_heading_error(
                    coordinates, (float(start_heading_deg) + 180.0) % 360.0
                )
            )
            if entry_error <= self.ARRIVAL_ALIGNMENT_LIMIT_DEG and (
                arrival_heading_deg is None
                or self._arrival_error(segment, arrival_heading_deg)
                <= self.ARRIVAL_ALIGNMENT_LIMIT_DEG
            ):
                return segment
            # Sonst zeigt die Nase am Ziel entgegen der ersten Bahn - dann
            # lieber vorwaerts einschwenken.
            segment["direction"] = "forward"
        if start_heading_deg is not None and arrival_heading_deg is not None:
            # Nicht nur den Punkt treffen, sondern dort in Bahnrichtung
            # ankommen. Der Bogen stammt nicht vom Router, deshalb gilt fuer
            # ihn dieselbe Pruefung wie fuer die gerade Verbindung - sonst
            # bleibt es beim geraden Weg darunter.
            curved = self._approach_arc_coords(
                from_coord, start_heading_deg, to_coord, arrival_heading_deg
            )
            if curved is not None and runtime_router.is_polyline_safe(
                curved, confine_to_mow_area=False
            ):
                segment["coordinates"] = curved
                segment["length_m"] = round(self._polyline_length_m(curved), 2)
                return segment
        # Kein Bogen moeglich: der Marker liegt seitlich und naeher als der
        # Wendekreis, dorthin fuehrt in einem Zug kein kurzer Weg. Hier stand
        # frueher ein eingerollter Ersatzbogen. Der sah fahrbar aus - 20 Grad
        # Knick je Stuetzpunkt -, war es aber nie: mit 0,6 m Schrittweite
        # beschreibt er einen 1,7-m-Kreis, und der Regler haelt erst 6 m. In
        # der Simulation lief das Fahrzeug nach zweieinhalb Metern aus dem
        # Pfad (08.08.). Vor allem verdeckte er den wahren Kursfehler: der
        # Plan-Check sah 20 Grad statt der tatsaechlichen 75 und liess eine
        # Fahrt zu, die der Regler sofort abbrach. Die gerade Verbindung sagt
        # die Wahrheit - der Check lehnt sie ab und nennt den Winkel.
        return segment

    @classmethod
    def _rolling_turn_coords(
        cls,
        start: List[float],
        heading_deg: float,
        waypoints: List[List[float]],
        clockwise: Optional[bool] = None,
        step_m: Optional[float] = None,
    ) -> List[List[float]]:
        """Anfahrt als rollender Bogen statt als Knick.

        Dieses Fahrzeug dreht nicht auf der Stelle: der Gegenlauf-Pivot lässt
        es unter Last stehen (real, >4 min), und ein Track mit mehr als 45°
        Knick lehnt der Regler ab. Ein quer geparktes Fahrzeug hatte damit
        keine fahrbare Anfahrt - als Goto stand es 161 s und kam 17,9 m weit
        (real, 02.08.). Deshalb den Kurs schrittweise auf das Ziel
        einschwenken: pro Schritt höchstens MAX_TURN_STEP_DEG, das bleibt
        unter der Reglergrenze und ist genau die Bewegung, die das UGV kann.
        """
        path = [list(start)]
        heading = float(heading_deg) % 360.0
        position = list(start)
        step_length = float(cls.TURN_STEP_M if step_m is None else step_m)
        for waypoint in waypoints:
            for _ in range(cls.MAX_TURN_STEPS):
                bearing = cls._edge_bearing_deg(position, waypoint)
                if bearing is None:
                    break
                error = (bearing - heading + 540.0) % 360.0 - 180.0
                if abs(error) <= cls.MAX_TURN_STEP_DEG:
                    break
                remaining = cls._coord_distance_m(position, waypoint)
                if remaining <= step_length:
                    break
                # ``clockwise`` erzwingt die Drehrichtung. Ohne Vorgabe wird
                # die kürzere genommen; die führt am Flächenrand aber
                # regelmäßig nach außen, wo der Bogen verworfen wird.
                if clockwise is None:
                    step = math.copysign(cls.MAX_TURN_STEP_DEG, error)
                else:
                    step = cls.MAX_TURN_STEP_DEG if clockwise else -cls.MAX_TURN_STEP_DEG
                    if abs(error) <= cls.MAX_TURN_STEP_DEG:
                        step = error
                heading = (heading + step) % 360.0
                position = cls._offset_coord(position, heading, step_length)
                path.append(list(position))
            # Der Wegpunkt wurde bisher immer angehaengt - auch dann, wenn die
            # Nase nach dem Bogen noch quer zu ihm stand. Dann klaffte
            # zwischen Bogenende und Wegpunkt ein Sprung, und der Knick dort
            # war beliebig gross. Zwei Ausstiege der Schleife fuehren dahin:
            # das Ziel liegt *innerhalb* des Wendekreises, dann dreht sich der
            # Bogen einmal aussen herum, ohne je darauf zu zeigen
            # (MAX_TURN_STEPS erschoepft); oder er ist naeher als eine
            # Schrittweite, aber in der falschen Richtung.
            #
            # Real am 09.08. am Brunnen, Abfahrposition 95,1 %: 12 Schritte im
            # Kreis (220 Grad auf 4,3 m Radius), dann 5,01 m Sprung und 0,15 m
            # zurueck - eine Kehre von 174,6 Grad mitten im Uebergang, die den
            # Regler nach 0,08 m stoppte. Die Vorabpruefung sah davon nichts:
            # Anfang und Ende des Uebergangs waren in Ordnung, der Knick lag
            # dazwischen.
            #
            # Fuer die Anfahrt ist derselbe Fall seit dem 08.08. verboten
            # (test_approach_never_loops_around_its_own_turning_circle), fuer
            # diesen Bogen fehlte die Bremse. Kein Bogen ist besser als ein
            # gesprungener: die Aufrufer pruefen die Laenge und nehmen dann
            # den Weg ohne Bogen, darueber greift die Manoeverleiter in
            # executable_segments.
            bearing = cls._edge_bearing_deg(position, waypoint)
            if (
                bearing is not None
                and cls._angle_error_deg(bearing, heading) > cls.MAX_TURN_STEP_DEG
            ):
                return []
            heading = bearing if bearing is not None else heading
            position = list(waypoint)
            path.append(list(waypoint))
        return path

    @staticmethod
    def _offset_coord(coord: List[float], heading_deg: float, distance_m: float) -> List[float]:
        # Bewusst derselbe Maßstab für Nord und Ost wie in _edge_bearing_deg:
        # mit getrennten Konstanten weicht die tatsächlich erreichte Peilung
        # um knapp 0,1° von der gewünschten ab, und die Zusage "höchstens
        # MAX_TURN_STEP_DEG pro Schritt" gälte nicht mehr exakt.
        latitude = math.radians(float(coord[1]))
        north = math.cos(math.radians(heading_deg)) * distance_m
        east = math.sin(math.radians(heading_deg)) * distance_m
        return [
            float(coord[0]) + east / (111320.0 * max(0.01, math.cos(latitude))),
            float(coord[1]) + north / 111320.0,
        ]

    def _ring_sense_for_selected_start(
        self,
        segment: Dict[str, Any],
        selected_start: List[float],
        start_coord: List[float],
        start_heading_deg: Optional[float],
        default: bool,
    ) -> bool:
        """Drehsinn des Rings so waehlen, dass die Anfahrt dazu passt.

        Gefahren wird derselbe geschlossene Ring, nur herum. Verglichen wird,
        wie schief die Nase am Marker steht - einmal fuer die gespeicherte
        Reihenfolge, einmal fuer die umgekehrte. Bei offenen Bahnen gibt es
        nichts zu waehlen, dort bleibt es bei ``default``.
        """
        coords = self._coords(segment)
        if start_heading_deg is None or not self._is_closed(coords):
            return default

        best = default
        best_error = None
        for reversed_ring in (False, True):
            candidate = dict(
                segment,
                coordinates=list(reversed(coords)) if reversed_ring else list(coords),
            )
            try:
                oriented = self._coords_from_selected_start(candidate, selected_start)
            except ValueError:
                continue
            entry = self._segment_entry_heading(oriented, candidate.get("direction"))
            if entry is None:
                continue
            # Dieselben Moeglichkeiten durchspielen, die spaeter auch
            # _routed_positioning_segment hat - sonst waehlt die Drehrichtung
            # gegen eine Anfahrt, die so nie gebaut wird. Genau daran ging es
            # einmal schief: nur die vorwaerts gefahrene Gerade betrachtet,
            # verlor der Drehsinn die drei Aufstellungen, die rueckwaerts
            # sauber ankamen.
            straight = self._edge_bearing_deg(start_coord, oriented[0])
            if straight is None:
                continue
            options = []
            approach = self._approach_arc_coords(
                start_coord, start_heading_deg, oriented[0], entry
            )
            if approach is not None and len(approach) >= 2:
                options.append(self._edge_bearing_deg(approach[-2], approach[-1]))
            else:
                options.append(straight)
            if (
                self._angle_error_deg(
                    (straight + 180.0) % 360.0, start_heading_deg
                )
                <= self.ARRIVAL_ALIGNMENT_LIMIT_DEG
            ):
                # Rueckwaerts zurueckgestossen zeigt die Nase entgegen der
                # Fahrtrichtung; erlaubt ist das nur, wenn das Fahrzeug schon
                # annaehernd so steht.
                options.append((straight + 180.0) % 360.0)
            error = min(
                self._angle_error_deg(arrival, entry)
                for arrival in options
                if arrival is not None
            )
            if best_error is None or error < best_error:
                best_error = error
                best = reversed_ring
        return best

    @classmethod
    def _merge_onto_lane_coords(
        cls,
        from_coord: List[float],
        start_heading_deg: float,
        to_coord: List[float],
        arrival_heading_deg: Optional[float] = None,
    ) -> Optional[List[List[float]]]:
        """Bogen raus, Gerade, Bogen auf die Bahn.

        Der Zielpunkt allein reicht nicht: kommt das Fahrzeug quer an, sperrt
        der Regler die erste Bahn am Kursfehler. Es dreht aber nicht auf der
        Stelle, also muessen beide Drehungen in den Weg - die aus dem
        Stellplatz heraus und die auf die Bahn hinein.

        Gebaut wird von hinten her. Auf der Bahnlinie, ein Stueck vor dem
        Marker, liegt die Nahtstelle. Dorthin fuehrt eine Gerade, die
        tangential am Wendekreis des Stellplatzes anliegt; an der Nahtstelle
        legt ein zweiter Bogen sie an die Bahnlinie an, und die letzten Meter
        laufen genau in Bahnrichtung in den Marker. Alles haengt tangential
        aneinander, es gibt also nirgends einen Knick.

        Die beiden Boegen duerfen unterschiedlich eng sein, weil sie
        unterschiedlich lang sind. Gemessen (08.08., Simulator gegen reine
        Kreisboegen): eine anhaltende Drehung haelt der Regler erst ab 7 m,
        ein kurzes Einschwenken bis 45 Grad aber schon mit 4 m und bis
        90 Grad mit 6 m. Dass kurze enge Boegen fahrbar sind, zeigen auch die
        Konturringe selbst - ihre engsten Stellen liegen bei 2,0 m.

        Gibt ``None`` zurueck, wenn keine Nahtstelle passt; dann bleibt es bei
        der geraden Verbindung, deren Kursfehler der Plan-Check meldet.
        """
        if arrival_heading_deg is None:
            return None
        lat_scale = 111320.0
        lon_scale = 111320.0 * max(0.01, math.cos(math.radians(float(to_coord[1]))))

        def unit(bearing_deg):
            angle = math.radians(bearing_deg)
            return (math.sin(angle), math.cos(angle))

        start_xy = (
            (float(from_coord[0]) - float(to_coord[0])) * lon_scale,
            (float(from_coord[1]) - float(to_coord[1])) * lat_scale,
        )
        start_heading = float(start_heading_deg) % 360.0
        arrival = float(arrival_heading_deg) % 360.0
        along = unit(arrival)

        # Wendekreise am Stellplatz: links und rechts, und je Seite in allen
        # Weiten, die die Messung traegt. Ein enger Kreis versperrt weniger
        # Flaeche und erreicht Nahtstellen, an denen ein weiter Kreis schon
        # vorbeigelaufen ist - solange die noetige Drehung klein bleibt.
        circles = []
        for left in (True, False):
            side = unit(start_heading - 90.0 if left else start_heading + 90.0)
            for out_radius, out_limit in cls.APPROACH_TURN_ARCS:
                circles.append((
                    left,
                    (start_xy[0] + side[0] * out_radius,
                     start_xy[1] + side[1] * out_radius),
                    out_radius,
                    out_limit,
                ))

        best = None
        steps = int(round((cls.MAX_APPROACH_MERGE_LEAD_M - 1.5) / 0.5))
        for step in range(steps + 1):
            lead = 1.5 + 0.5 * step
            corner = (-along[0] * lead, -along[1] * lead)
            for left, centre, out_radius, out_limit in circles:
                reach_e = corner[0] - centre[0]
                reach_n = corner[1] - centre[1]
                reach = math.hypot(reach_e, reach_n)
                if reach <= out_radius:
                    # Die Nahtstelle liegt im Wendekreis - dorthin fuehrt von
                    # dieser Seite keine Gerade.
                    continue
                towards = math.degrees(math.atan2(reach_e, reach_n)) % 360.0
                opening = math.degrees(
                    math.acos(max(-1.0, min(1.0, out_radius / reach)))
                )
                run = math.sqrt(reach * reach - out_radius * out_radius)
                for spoke in (towards - opening, towards + opening):
                    # Nur an einem der beiden Beruehrpunkte laeuft der Bogen in
                    # die Gerade hinein statt aus ihr heraus.
                    leaving = (
                        (spoke - 90.0) % 360.0 if left else (spoke + 90.0) % 360.0
                    )
                    contact = (
                        centre[0] + unit(spoke)[0] * out_radius,
                        centre[1] + unit(spoke)[1] * out_radius,
                    )
                    heading_to_corner = math.degrees(
                        math.atan2(corner[0] - contact[0], corner[1] - contact[1])
                    ) % 360.0
                    if abs(
                        (leaving - heading_to_corner + 180.0) % 360.0 - 180.0
                    ) > 0.5:
                        continue
                    out_turn = (
                        (start_heading - leaving) % 360.0 if left
                        else (leaving - start_heading) % 360.0
                    )
                    if out_turn > out_limit:
                        continue
                    signed = (arrival - leaving + 540.0) % 360.0 - 180.0
                    merge_turn = abs(signed)
                    for merge_radius, turn_limit in cls.APPROACH_MERGE_ARCS:
                        if merge_turn > turn_limit:
                            continue
                        tangent_m = merge_radius * math.tan(
                            math.radians(merge_turn) / 2.0
                        )
                        if tangent_m > (lead - 0.5) or tangent_m > (run - 0.5):
                            # Der Einschwenkbogen wuerde ueber den Marker
                            # hinaus oder in den Wendekreis zurueckreichen.
                            continue
                        total = (
                            math.radians(out_turn) * out_radius
                            + (run - tangent_m)
                            + math.radians(merge_turn) * merge_radius
                            + (lead - tangent_m)
                        )
                        if best is None or total < best[0]:
                            best = (
                                total, centre, left, out_turn, out_radius,
                                leaving, signed, merge_turn, tangent_m,
                                merge_radius, corner,
                            )
                        break

        if best is None:
            return None
        (
            _total, centre, left, out_turn, out_radius, leaving, signed,
            merge_turn, tangent_m, merge_radius, corner,
        ) = best

        def arc(centre_xy, radius, from_heading, turn_deg, turns_left):
            points = []
            count = max(1, int(math.ceil(turn_deg / cls.MAX_TURN_STEP_DEG)))
            for index in range(1, count + 1):
                travelled = turn_deg * index / count
                heading = (
                    from_heading - travelled if turns_left
                    else from_heading + travelled
                )
                spoke = unit(heading + 90.0 if turns_left else heading - 90.0)
                points.append((
                    centre_xy[0] + spoke[0] * radius,
                    centre_xy[1] + spoke[1] * radius,
                ))
            return points

        path = [start_xy]
        path.extend(arc(centre, out_radius, start_heading, out_turn, left))
        entry = unit(leaving)
        merge_start = (
            corner[0] - entry[0] * tangent_m,
            corner[1] - entry[1] * tangent_m,
        )
        path.append(merge_start)
        merge_left = signed < 0.0
        merge_dir = unit(leaving - 90.0 if merge_left else leaving + 90.0)
        merge_centre = (
            merge_start[0] + merge_dir[0] * merge_radius,
            merge_start[1] + merge_dir[1] * merge_radius,
        )
        path.extend(
            arc(merge_centre, merge_radius, leaving, merge_turn, merge_left)
        )
        path.append((0.0, 0.0))

        coords = [
            [
                float(to_coord[0]) + east / lon_scale,
                float(to_coord[1]) + north / lat_scale,
            ]
            for east, north in path
        ]
        deduplicated = [coords[0]]
        for coord in coords[1:]:
            if cls._coord_distance_m(deduplicated[-1], coord) > 0.02:
                deduplicated.append(coord)
        # Der Zielpunkt ist gesetzt, nicht gerechnet: die erste Bahn beginnt
        # exakt dort, und schon zwei Zentimeter daneben zaehlen als eigener
        # Uebergang.
        deduplicated[-1] = [float(to_coord[0]), float(to_coord[1])]
        if len(deduplicated) < 2:
            return None
        return deduplicated

    @classmethod
    def _required_turn_radius_m(cls, turn_deg: float) -> Optional[float]:
        """Engster Radius, mit dem der Regler ``turn_deg`` noch sauber faehrt."""
        for radius, limit in cls.APPROACH_TURN_ARCS:
            if turn_deg <= limit:
                return radius
        return None

    @classmethod
    def _bend_onto_marker_coords(
        cls,
        from_coord: List[float],
        start_heading_deg: float,
        to_coord: List[float],
        arrival_heading_deg: float,
    ) -> Optional[List[List[float]]]:
        """Ein Bogen, der im Marker endet - so schief wie noetig, nicht exakt.

        Der Regler verlangt keine exakte Bahnrichtung, sondern nur, dass die
        Nase am Bahnanfang innerhalb von track_heading_block_deg steht. Genau
        das macht diese Konstruktion moeglich, wo ein exakter Einlauf nicht
        hinpasst: durch Marker und Fahrzeug laeuft genau ein Kreis, der den
        aktuellen Kurs aufnimmt, und der biegt die Ankunft schon um den
        doppelten Winkel zwischen Kurs und Sehne.

        Real am Brunnen: 8,78 m Luftlinie, das Fahrzeug 14,2 Grad neben der
        Sehne. Der Bogen dreht 28,4 Grad, hat 17,9 m Radius, ist 8,87 m lang -
        neun Zentimeter mehr als die Gerade - und senkt den Winkelfehler zur
        ersten Bahn von 50,5 auf 36,3 Grad. Damit faehrt der Plan, waehrend
        die Gerade gesperrt wurde.

        Ueber die Laenge der Geraden davor laesst sich der Ankunftskurs
        einstellen: je weiter geradeaus vorgefahren wird, desto schaerfer
        biegt der Rest ein.
        """
        lat_scale = 111320.0
        lon_scale = 111320.0 * max(0.01, math.cos(math.radians(float(to_coord[1]))))

        def unit(bearing_deg):
            angle = math.radians(bearing_deg)
            return (math.sin(angle), math.cos(angle))

        start_xy = (
            (float(from_coord[0]) - float(to_coord[0])) * lon_scale,
            (float(from_coord[1]) - float(to_coord[1])) * lat_scale,
        )
        start_heading = float(start_heading_deg) % 360.0
        arrival = float(arrival_heading_deg) % 360.0
        ahead = unit(start_heading)
        span = math.hypot(*start_xy)

        best = None
        steps = int(max(0.0, span - 1.0) / 0.5)
        for step in range(steps + 1):
            run = 0.5 * step
            begin = (
                start_xy[0] + ahead[0] * run,
                start_xy[1] + ahead[1] * run,
            )
            reach_e = -begin[0]
            reach_n = -begin[1]
            reach = math.hypot(reach_e, reach_n)
            if reach < 0.5:
                continue
            chord = math.degrees(math.atan2(reach_e, reach_n)) % 360.0
            offset = (chord - start_heading + 540.0) % 360.0 - 180.0
            turn = 2.0 * abs(offset)
            if abs(offset) < 0.25:
                # Der Marker liegt genau voraus: nichts zu biegen.
                radius = None
                total = run + reach
                lands = start_heading
            else:
                if turn > cls.MAX_APPROACH_TURN_DEG:
                    continue
                needed = cls._required_turn_radius_m(turn)
                radius = reach / (2.0 * math.sin(math.radians(abs(offset))))
                if needed is None or radius < needed:
                    # Enger als der Regler halten kann.
                    continue
                total = run + math.radians(turn) * radius
                lands = (start_heading + 2.0 * offset) % 360.0
            error = cls._angle_error_deg(lands, arrival)
            rank = (round(error, 1), round(total, 2))
            if best is None or rank < best[0]:
                best = (rank, run, begin, offset, turn, radius)

        if best is None:
            return None
        _rank, run, begin, offset, turn, radius = best

        path = [start_xy]
        if run > 0.02:
            path.append(begin)
        if radius is not None:
            left = offset < 0.0
            side = unit(start_heading - 90.0 if left else start_heading + 90.0)
            centre = (begin[0] + side[0] * radius, begin[1] + side[1] * radius)
            count = max(1, int(math.ceil(turn / cls.MAX_TURN_STEP_DEG)))
            for index in range(1, count + 1):
                travelled = turn * index / count
                heading = (
                    start_heading - travelled if left
                    else start_heading + travelled
                )
                spoke = unit(heading + 90.0 if left else heading - 90.0)
                path.append((
                    centre[0] + spoke[0] * radius,
                    centre[1] + spoke[1] * radius,
                ))
        path.append((0.0, 0.0))

        coords = [
            [
                float(to_coord[0]) + east / lon_scale,
                float(to_coord[1]) + north / lat_scale,
            ]
            for east, north in path
        ]
        deduplicated = [coords[0]]
        for coord in coords[1:]:
            if cls._coord_distance_m(deduplicated[-1], coord) > 0.02:
                deduplicated.append(coord)
        deduplicated[-1] = [float(to_coord[0]), float(to_coord[1])]
        if len(deduplicated) < 2:
            return None
        return deduplicated

    @classmethod
    def _approach_arc_coords(
        cls,
        from_coord: List[float],
        start_heading_deg: float,
        to_coord: List[float],
        arrival_heading_deg: Optional[float] = None,
    ) -> Optional[List[List[float]]]:
        """Die Anfahrt, die am Marker am besten zur ersten Bahn passt.

        Zwei Bauarten stehen zur Wahl, und sie ergaenzen sich:

        ``_merge_onto_lane_coords`` legt den Weg exakt auf die Bahnlinie -
        null Grad Fehler, aber es braucht Platz, um sich anzulegen: der
        Einschwenkbogen muss vor dem Marker auf die Bahnlinie passen.

        ``_bend_onto_marker_coords`` biegt bloss auf den Marker zu und nimmt
        den Restfehler in Kauf. Das kostet fast nichts an Weg und geht auch
        dann, wenn kein Platz zum Anlegen da ist.

        Genommen wird, was am Ziel weniger schief steht; bei gleichem Winkel
        der kuerzere Weg. Der Regler verlangt nicht mehr als
        track_heading_block_deg - eine Anfahrt, die diese Grenze einhaelt,
        ist gut genug, auch wenn sie nicht exakt auf der Bahn endet. Das war
        der Denkfehler vom 08.08.: nur die exakte Loesung gesucht und, wo sie
        nicht hinpasste, gar keinen Bogen gebaut - obwohl ein flacher Bogen
        den Fehler am realen Stellplatz von 50,5 auf 36,3 Grad gedrueckt und
        damit die Fahrt freigegeben haette.
        """
        if arrival_heading_deg is None:
            return None

        # Messlatte ist die gerade Verbindung, die sonst gefahren wuerde. Ein
        # Bogen wird nur gebaut, wenn er die Ankunft wirklich verbessert -
        # sonst biegt er im Zweifel von der Bahn weg statt zu ihr hin (bei
        # Kurs 210 am Brunnen gemessen: 60,3 statt 53,0 Grad).
        straight = cls._edge_bearing_deg(from_coord, to_coord)
        best = None
        if straight is not None:
            best = (
                (round(cls._angle_error_deg(straight, arrival_heading_deg), 1),
                 round(cls._coord_distance_m(from_coord, to_coord), 2)),
                None,
            )
        for build in (cls._merge_onto_lane_coords, cls._bend_onto_marker_coords):
            coords = build(
                from_coord, start_heading_deg, to_coord, arrival_heading_deg
            )
            if coords is None or len(coords) < 2:
                continue
            arrival = cls._edge_bearing_deg(coords[-2], coords[-1])
            if arrival is None:
                continue
            rank = (
                round(cls._angle_error_deg(arrival, arrival_heading_deg), 1),
                round(cls._polyline_length_m(coords), 2),
            )
            if best is None or rank < best[0]:
                best = (rank, coords)
        return None if best is None else best[1]

    @classmethod
    def _segment_entry_heading(
        cls,
        coords: List[List[float]],
        direction: Optional[str],
    ) -> Optional[float]:
        """Kurs, den die Nase am Anfang dieses Segments haben muss."""
        for start, end in zip(coords, coords[1:]):
            if cls._coord_distance_m(start, end) <= 0.02:
                continue
            bearing = cls._edge_bearing_deg(start, end)
            if bearing is None:
                continue
            return (bearing + 180.0) % 360.0 if direction == "reverse" else bearing
        return None

    @classmethod
    def _arrival_error(
        cls,
        segment: Dict[str, Any],
        arrival_heading_deg: float,
    ) -> float:
        """Wie schief die Nase am Ende dieser Anfahrt zur naechsten Bahn steht."""
        end = cls._segment_end_heading(segment)
        if end is None:
            return 0.0
        return abs((end - float(arrival_heading_deg) + 180.0) % 360.0 - 180.0)

    def _select_transfer_direction(
        self,
        segment: Dict[str, Any],
        start_heading_deg: Optional[float],
    ) -> Dict[str, Any]:
        """Choose the drive direction from the physical arrival heading.

        Transitions are separate controller tracks.  Starting a short one in
        the opposite direction as ``forward`` makes the rolling alignment
        leave the track before the UGV has turned.  Use reverse whenever the
        vehicle already faces substantially closer to the reverse heading.
        This applies to every transfer, not just the first RTK approach.
        """
        if (
            self.reverse_track_supported
            and start_heading_deg is not None
            and segment.get("mode") == "track"
            and self._route_heading_error(segment.get("coordinates") or [], start_heading_deg)
            > self.TRANSFER_REVERSE_THRESHOLD_DEG
        ):
            segment["direction"] = "reverse"
        return segment

    @classmethod
    def _polyline_length_m(cls, coords: List[List[float]]) -> float:
        return sum(
            cls._coord_distance_m(coords[index], coords[index + 1])
            for index in range(len(coords) - 1)
        )

    @staticmethod
    def _edge_bearing_deg(start: List[float], end: List[float]) -> Optional[float]:
        import math

        latitude = math.radians((float(start[1]) + float(end[1])) / 2.0)
        east = (float(end[0]) - float(start[0])) * math.cos(latitude)
        north = float(end[1]) - float(start[1])
        if abs(east) < 1e-12 and abs(north) < 1e-12:
            return None
        return (math.degrees(math.atan2(east, north)) + 360.0) % 360.0

    @staticmethod
    def _angle_error_deg(bearing_deg: Optional[float], heading_deg: float) -> float:
        if bearing_deg is None:
            return 180.0
        return abs((float(bearing_deg) - float(heading_deg) + 180.0) % 360.0 - 180.0)

    @classmethod
    def _route_heading_error(cls, coords: List[List[float]], heading_deg: float) -> float:
        import math

        for start, end in zip(coords, coords[1:]):
            if cls._coord_distance_m(start, end) <= 0.02:
                continue
            latitude = math.radians((float(start[1]) + float(end[1])) / 2.0)
            east = (float(end[0]) - float(start[0])) * math.cos(latitude)
            north = float(end[1]) - float(start[1])
            bearing = (math.degrees(math.atan2(east, north)) + 360.0) % 360.0
            return abs((bearing - float(heading_deg) + 180.0) % 360.0 - 180.0)
        return 0.0

    @classmethod
    def _segment_end_heading(
        cls,
        segment: Dict[str, Any],
        fallback: Optional[float] = None,
    ) -> Optional[float]:
        coords = segment.get("coordinates") or []
        for start, end in reversed(list(zip(coords, coords[1:]))):
            if cls._coord_distance_m(start, end) <= 0.02:
                continue
            import math

            latitude = math.radians((float(start[1]) + float(end[1])) / 2.0)
            east = (float(end[0]) - float(start[0])) * math.cos(latitude)
            north = float(end[1]) - float(start[1])
            heading = (math.degrees(math.atan2(east, north)) + 360.0) % 360.0
            if segment.get("direction") == "reverse":
                heading = (heading + 180.0) % 360.0
            return heading
        return fallback

    def segment_start_headings(
        self,
        segments: List[Dict[str, Any]],
        start_pose: Optional[Dict[str, Any]] = None,
    ) -> List[Optional[float]]:
        """Kurs, mit dem das Fahrzeug jedes kompilierte Segment beginnt.

        Fuer das erste Segment ist das der gemessene Kurs aus der Pose, danach
        der Kurs am Ende des Vorgaengers - dieselbe Kette, aus der
        ``executable_segments`` die Fahrtrichtungen und Eindrehmanoever
        ableitet.

        Nur das erste Glied ist gemessen; alle weiteren sind modelliert. Real
        weicht der Kurs davon ab (RTK-Rauschen, Regelverhalten, Untergrund),
        deshalb taugt das Ergebnis fuer eine Vorabpruefung, nicht als Zusage
        ueber das, was der Regler unterwegs tatsaechlich sieht.
        """
        heading = self._pose_heading(start_pose)
        headings: List[Optional[float]] = []
        for segment in segments:
            headings.append(heading)
            heading = self._segment_end_heading(segment, heading)
        return headings

    def summarize_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "map_name": plan.get("map_name", plan.get("name")),
            "segment_count": len(plan.get("sequence") or []),
            "transition_count": len(plan.get("transitions") or []),
            "unsafe_transition_count": self._unsafe_transition_count(plan),
            "reverse_segment_count": self._reverse_segment_count(plan),
            "short_rest_lane_count": self._short_rest_lane_count(plan),
            "total_drive_length_m": round(float(plan.get("total_drive_length_m", plan.get("total_length_m", 0.0)) or 0.0), 2),
        }

    def _track_segment(
        self,
        segment: Dict[str, Any],
        coordinates: Optional[List[List[float]]] = None,
        heading_deg: Optional[float] = None,
    ) -> Dict[str, Any]:
        track_coords = coordinates or self._coords(segment)
        direction = "forward"
        if segment.get("type") == "rest_lane":
            direction = segment.get("direction", "forward")
            if self.reverse_track_supported and heading_deg is not None:
                # One rule for the drive direction: take whichever nose
                # orientation needs the smaller turn from the heading the
                # vehicle actually has here - exactly what
                # _select_transfer_direction already does for transitions.
                #
                # On an uninterrupted run this simply reproduces the plan's
                # own alternating forward/reverse pattern, because that
                # pattern exists precisely so the nose never has to turn.
                # After a resume or skip the traversal sense of a lane can
                # be inverted, and only this rule keeps the vehicle from
                # being asked for a 180 degree turnaround it cannot drive
                # (real, 25.07.: -52° on lane 36, then 178.9° on lane 37).
                forward_error = abs(self._route_heading_error(track_coords, heading_deg))
                direction = "forward" if forward_error <= self.TRANSFER_REVERSE_THRESHOLD_DEG else "reverse"
        if direction == "reverse" and not self.reverse_track_supported:
            raise ValueError("Plan enthält Rückwärtssegmente, Ausführung noch nicht unterstützt")
        return {
            "type": "mow",
            "source_type": segment.get("type"),
            "source_index": segment.get("segment_index"),
            "mode": "track",
            "direction": direction,
            "coordinates": track_coords,
            "length_m": sum(
                self._coord_distance_m(track_coords[index], track_coords[index + 1])
                for index in range(len(track_coords) - 1)
            ),
        }

    def _ring_sense_for_resume(
        self,
        segment: Dict[str, Any],
        start_coord: List[float],
        start_heading_deg: float,
        default: bool,
    ) -> bool:
        """Drehsinn beim Fortsetzen: der, in den die Nase schon zeigt.

        Gebaut werden beide Moeglichkeiten genau so, wie sie die Route spaeter
        auch baut, und verglichen wird der Kursfehler am Bahnanfang. Eine
        Schwelle taugt dafuer nicht: das Umdrehen sucht sich einen anderen
        Stuetzpunkt als Anfang, dort verlaeuft der Ring anders, und ein
        vorher gerechneter Winkel stimmt nicht mehr.
        """
        best = default
        best_error = None
        for reversed_ring in (False, True):
            candidate = dict(
                segment,
                coordinates=list(reversed(self._coords(segment)))
                if reversed_ring else list(self._coords(segment)),
            )
            oriented = self._oriented_track_coords(
                candidate, start_coord, start_heading_deg, vehicle=start_coord
            )
            if len(oriented) < 2:
                continue
            error = abs(self._route_heading_error(oriented, start_heading_deg))
            if best_error is None or error < best_error:
                best_error = error
                best = reversed_ring
        return best

    def _transition_segment(
        self,
        transition: Dict[str, Any],
        from_coord: Optional[List[float]] = None,
        to_coord: Optional[List[float]] = None,
    ) -> Optional[Dict[str, Any]]:
        if transition.get("safe") is not True:
            # Diese Meldung traf früher zwei völlig verschiedene Fälle: ein
            # altes safe:false aus dem gespeicherten Plan und einen gerade
            # neu berechneten Übergang, den der Runtime-Router verworfen hat.
            # Im zweiten Fall steht der Grund im Ergebnis - den zu verschweigen
            # kostete eine komplette Fehlersuche (real, 02.08.).
            raise ValueError(self._transition_rejection_message(transition))
        route_kind = transition.get("route_kind", "direct")
        if route_kind not in ("direct", "around_sub", "inside_boundary"):
            raise ValueError(f"Unbekannte Transition-Route: {route_kind}")
        coords = self._coords(transition)
        if from_coord is not None and to_coord is not None and len(coords) >= 2:
            direct = self._coord_distance_m(coords[0], from_coord) + self._coord_distance_m(coords[-1], to_coord)
            reverse = self._coord_distance_m(coords[-1], from_coord) + self._coord_distance_m(coords[0], to_coord)
            if reverse < direct:
                coords = list(reversed(coords))
                direct = reverse
            if direct > 1.0:
                return None
        return {
            "type": "transition",
            "source_index": transition.get("transition_index"),
            "mode": "track" if len(coords) >= 2 else "goto",
            "direction": "forward",
            "route_kind": route_kind,
            "coordinates": coords,
            "length_m": float(transition.get("length_m", 0.0) or 0.0),
        }

    # Gründe wie sie der TransitionRouter setzt (siehe plan_between).
    TRANSITION_REJECTION_REASONS = {
        "outside_mow_area": "der Weg verlässt die Mähfläche",
        "sub_zone": "der Weg führt durch eine Sperrzone",
        "vehicle_footprint": "die Fahrzeugkontur passt nicht durch",
    }

    @classmethod
    def _transition_rejection_message(cls, transition: Dict[str, Any]) -> str:
        reason = transition.get("reason")
        if reason is None:
            return "Unsafe transitions blockieren die Ausführung"
        from_index = transition.get("from_segment_index")
        to_index = transition.get("to_segment_index")
        explained = cls.TRANSITION_REJECTION_REASONS.get(str(reason), str(reason))
        where = (
            f" (Segment {from_index} → {to_index})"
            if from_index is not None and to_index is not None
            else ""
        )
        return f"Übergang{where} nicht fahrbar: {explained}"

    def _oriented_track_coords(
        self,
        segment: Dict[str, Any],
        target: Optional[List[float]],
        heading_deg: Optional[float] = None,
        vehicle: Optional[List[float]] = None,
    ) -> List[List[float]]:
        """Traverse a lane from whichever end the vehicle is closest to.

        This only decides the order the points are driven in. Whether the
        vehicle drives that order nose-first or backwards is decided
        separately in _track_segment, from the live heading.
        """
        coords = self._coords(segment)
        if not coords or target is None:
            return coords
        if self._is_closed(coords):
            return self._rotate_closed_ring_near(
                coords, target, heading_deg, vehicle=vehicle
            )
        if segment.get("type") != "rest_lane" or len(coords) < 2:
            return coords
        forward = self._coord_distance_m(coords[0], target)
        reverse = self._coord_distance_m(coords[-1], target)
        return list(reversed(coords)) if reverse < forward else coords

    def _coords_from_selected_start(
        self,
        segment: Dict[str, Any],
        point: List[float],
    ) -> List[List[float]]:
        """Start the first route segment at the UI-selected path point."""
        coords = self._coords(segment)
        if len(coords) < 2:
            raise ValueError("Gewählte Abfahrposition hat keinen fahrbaren Pfad")


        best_index = min(
            range(len(coords) - 1),
            key=lambda index: self._point_to_line_distance_m(point, coords[index], coords[index + 1]),
        )
        distance = self._point_to_line_distance_m(point, coords[best_index], coords[best_index + 1])
        if distance > 1.0:
            raise ValueError("Gewählte Abfahrposition liegt nicht auf dem gewählten Pfad")

        # Auf die Bahn projizieren statt den Klickpunkt zu übernehmen. Bis zu
        # 1 m Abweichung wird oben bewusst toleriert, weil der Punkt aus einem
        # UI-Slider kommt - als Bahnstützpunkt eingesetzt liegt er dann aber
        # neben der Bahn und kann ausserhalb der Mähfläche landen. Der
        # Übergang zum nächsten Ring wurde dadurch als outside_mow_area
        # verworfen und der ganze Plan abgelehnt (real, 02.08.: 0,49 m
        # ausserhalb, Ring 0 -> Ring 1). Gefahren wird die geplante Bahn.
        point = self._project_on_segment(point, coords[best_index], coords[best_index + 1])

        # Der gewählte Punkt ist der Startpunkt - immer, auch wenn der Ring
        # dort quer zur Anflugrichtung liegt. Bis zum 08.08. rutschte der
        # Start in genau dem Fall einige Meter am Ring entlang (real: 12,45 m
        # beim Brunnen), damit die Anfahrt ihn geradeaus erreichen konnte. Der
        # Marker in der Karte blieb dabei stehen, und das Fahrzeug fuhr
        # sichtbar woandershin. Nötig ist das nicht mehr: die Anfahrt schwenkt
        # jetzt selbst ein und kommt in Bahnrichtung an, egal wie das Fahrzeug
        # steht (_tangential_approach_coords).
        if self._is_closed(coords):
            open_ring = coords[:-1]
            next_index = (best_index + 1) % len(open_ring)
            rotated = open_ring[next_index:] + open_ring[:next_index]
            return [point] + rotated + [point]

        suffix = [point] + coords[best_index + 1:]
        if segment.get("type") == "rest_lane":
            # An arbitrary start on a boustrophedon lane must continue toward
            # the farther endpoint.  Always following the stored coordinate
            # order can leave only a few centimetres, skip the first lane and
            # then force an immediate 180-degree direction change at the next
            # lane.  Choosing the longer half preserves useful mowing and lets
            # the following alternating forward/reverse lane start at the
            # adjacent endpoint without a U-turn.
            prefix = [point] + list(reversed(coords[:best_index + 1]))
            trimmed = (
                prefix
                if self._polyline_length_m(prefix) > self._polyline_length_m(suffix)
                else suffix
            )
        else:
            trimmed = suffix
        deduplicated = [trimmed[0]]
        for coord in trimmed[1:]:
            if self._coord_distance_m(deduplicated[-1], coord) > 0.02:
                deduplicated.append(coord)
        trimmed = deduplicated
        if len(trimmed) < 2 or self._coord_distance_m(trimmed[0], trimmed[-1]) < 0.02:
            raise ValueError("Gewählte Abfahrposition liegt am Ende des Plans")
        return trimmed

    @staticmethod
    def _project_on_segment(point: List[float], start: List[float], end: List[float]) -> List[float]:
        """Foot of the perpendicular from ``point`` onto the segment."""
        import math

        latitude = math.radians(float(point[1]))
        lon_scale = 111320.0 * max(0.01, math.cos(latitude))
        lat_scale = 110540.0
        ax = (float(start[0]) - float(point[0])) * lon_scale
        ay = (float(start[1]) - float(point[1])) * lat_scale
        bx = (float(end[0]) - float(point[0])) * lon_scale
        by = (float(end[1]) - float(point[1])) * lat_scale
        dx = bx - ax
        dy = by - ay
        denominator = dx * dx + dy * dy
        if denominator <= 1e-12:
            return [float(start[0]), float(start[1])]
        t = max(0.0, min(1.0, -(ax * dx + ay * dy) / denominator))
        return [
            float(start[0]) + (float(end[0]) - float(start[0])) * t,
            float(start[1]) + (float(end[1]) - float(start[1])) * t,
        ]

    @classmethod
    def _distance_to_polyline_m(
        cls,
        point: List[float],
        coords: List[List[float]],
    ) -> float:
        """Kuerzester Abstand zur Bahn selbst, nicht zu ihren Stuetzpunkten."""
        if len(coords) < 2:
            return cls._coord_distance_m(point, coords[0]) if coords else 0.0
        return min(
            cls._point_to_line_distance_m(point, start, end)
            for start, end in zip(coords, coords[1:])
        )

    @staticmethod
    def _point_to_line_distance_m(point: List[float], start: List[float], end: List[float]) -> float:
        """Approximate point-to-segment distance in a local metric projection."""
        import math

        latitude = math.radians(float(point[1]))
        lon_scale = 111320.0 * max(0.01, math.cos(latitude))
        lat_scale = 110540.0
        ax = (float(start[0]) - float(point[0])) * lon_scale
        ay = (float(start[1]) - float(point[1])) * lat_scale
        bx = (float(end[0]) - float(point[0])) * lon_scale
        by = (float(end[1]) - float(point[1])) * lat_scale
        dx = bx - ax
        dy = by - ay
        denominator = dx * dx + dy * dy
        if denominator <= 1e-12:
            return math.hypot(ax, ay)
        t = max(0.0, min(1.0, -(ax * dx + ay * dy) / denominator))
        return math.hypot(ax + t * dx, ay + t * dy)

    @staticmethod
    def _validated_coord(coord: Optional[List[float]]) -> Optional[List[float]]:
        if coord is None:
            return None
        if not isinstance(coord, (list, tuple)) or len(coord) < 2:
            raise ValueError("start_coordinate muss [Längengrad, Breitengrad] sein")
        try:
            lon = float(coord[0])
            lat = float(coord[1])
        except (TypeError, ValueError):
            raise ValueError("start_coordinate enthält ungültige Werte")
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError("start_coordinate liegt außerhalb gültiger Grenzen")
        return [lon, lat]

    def _trim_coords_from_point(
        self,
        coords: List[List[float]],
        point: List[float],
        max_distance_m: float,
    ) -> Optional[List[List[float]]]:
        if len(coords) < 2:
            return None
        best: Optional[Tuple[float, int]] = None
        for index, coord in enumerate(coords):
            candidate = (self._coord_distance_m(coord, point), index)
            if best is None or candidate < best:
                best = candidate
        if best is None or best[0] > max_distance_m:
            return None
        index = best[1]
        trimmed = [point] + coords[index + 1:]
        return trimmed if len(trimmed) >= 2 else None

    @classmethod
    def _runtime_transition_router(cls, plan: Dict[str, Any]):
        """Rebuild routing geometry from a persisted plan.

        Persisted transition endpoints describe planning-time ring vertices.
        The executor may rotate those rings, so safe execution needs the map
        geometry itself to route between the final endpoints.
        """
        try:
            from shapely.geometry import LineString, Polygon
            from shapely.ops import unary_union
        except ImportError:
            return None

        boundary_ring = cls._boundary_ring(plan.get("map") or {})
        if len(boundary_ring) < 4:
            return None
        zone_rings = [
            item.get("coordinates") or []
            for item in plan.get("exclusion_contours") or []
            if item.get("type") == "sub_buffer_boundary"
            and len(item.get("coordinates") or []) >= 4
        ]
        if not zone_rings:
            for item in plan.get("subs") or []:
                payload = item.get("map") if isinstance(item, dict) else None
                ring = cls._boundary_ring(payload or {})
                if len(ring) >= 4:
                    zone_rings.append(ring)

        origin_coords = list(boundary_ring)
        for ring in zone_rings:
            origin_coords.extend(ring)
        origin_lat = sum(float(coord[1]) for coord in origin_coords) / len(origin_coords)
        origin_lon = sum(float(coord[0]) for coord in origin_coords) / len(origin_coords)

        main_poly = Polygon([
            lonlat_to_xy(coord, origin_lat, origin_lon)
            for coord in boundary_ring
        ])
        if not main_poly.is_valid:
            main_poly = main_poly.buffer(0)
        outer_margin = max(
            0.0,
            float((plan.get("parameters") or {}).get("outer_margin_m", 0.0) or 0.0),
        )
        if outer_margin > 0.0 and not main_poly.is_empty:
            main_poly = main_poly.buffer(-outer_margin)
        if main_poly.is_empty:
            return None

        zone_polys = []
        for ring in zone_rings:
            poly = Polygon([
                lonlat_to_xy(coord, origin_lat, origin_lon)
                for coord in ring
            ])
            if not poly.is_valid:
                poly = poly.buffer(0)
            if not poly.is_empty:
                zone_polys.append(poly)
        sub_union = unary_union(zone_polys) if zone_polys else None
        mow_area = main_poly.difference(sub_union) if sub_union is not None else main_poly
        if mow_area.is_empty:
            return None
        return TransitionRouter(
            mow_area,
            sub_union,
            LineString,
            origin_lat,
            origin_lon,
        )

    @staticmethod
    def _boundary_ring(payload: Dict[str, Any]) -> List[List[float]]:
        for feature in payload.get("features", []):
            if feature.get("properties", {}).get("type") != "boundary":
                continue
            geometry = feature.get("geometry") or {}
            if geometry.get("type") != "Polygon":
                continue
            return geometry.get("coordinates", [[]])[0] or []
        return []

    @classmethod
    def _approach_bearing(
        cls,
        vehicle: Optional[List[float]],
        reference: Optional[List[float]],
        heading_deg: Optional[float],
    ) -> Optional[float]:
        """Richtung, aus der das Fahrzeug die erste Bahn erreicht.

        Steht es praktisch schon dort - nach einem Abbruch der übliche Fall -,
        ist die Peilung dorthin nur noch Rauschen. Dann zählt die
        Fahrzeugausrichtung selbst: sonst wurde ein Startpunkt gewählt, für
        den das Fahrzeug 54 m im Kreis fahren musste, um 0,1 m entfernt
        wieder anzukommen (real, 02.08.).
        """
        if vehicle is None or reference is None:
            return heading_deg
        if cls._coord_distance_m(vehicle, reference) < cls.ON_TRACK_DISTANCE_M:
            return heading_deg
        return cls._edge_bearing_deg(vehicle, reference) or heading_deg

    @classmethod
    def _prefers_reversed_rings(
        cls,
        segment: Optional[Dict[str, Any]],
        target: Optional[List[float]],
        approach_bearing_deg: Optional[float],
        vehicle: Optional[List[float]] = None,
    ) -> bool:
        """Wählt den Drehsinn, in dem die erste Bahn erreichbar ist.

        Ein geschlossener Ring wird in beide Richtungen vollständig gemäht.
        Verglichen wird, wie weit das Fahrzeug in der jeweiligen Richtung bis
        zu einer *fahrbaren* Anfangsstelle fahren muss - dieselbe Bewertung
        wie bei der Startpunktwahl. Fest im Planer verdrahtet zwang der
        Drehsinn das Fahrzeug in eine Schleife, nur um von der falschen Seite
        auf den Ring zu kommen (real, 02.08.).
        """
        if segment is None or target is None or approach_bearing_deg is None:
            return False
        vehicle = vehicle if vehicle is not None else target
        coords = cls._coords(segment)
        if not cls._is_closed(coords) or len(coords) < 4:
            return False
        costs = {}
        for reverse in (False, True):
            ring = list(reversed(coords)) if reverse else list(coords)
            open_ring = ring[:-1]
            nearest = min(cls._coord_distance_m(point, target) for point in open_ring)
            point, _ = cls._ring_start_point(
                open_ring, nearest, approach_bearing_deg, target, vehicle=vehicle
            )
            costs[reverse] = cls._coord_distance_m(vehicle, point)
        return costs[True] < costs[False]

    @classmethod
    def _rotate_closed_ring_near(
        cls,
        ring: List[List[float]],
        target: List[float],
        heading_deg: Optional[float] = None,
        vehicle: Optional[List[float]] = None,
    ) -> List[List[float]]:
        open_ring = ring[:-1] if cls._is_closed(ring) else ring[:]
        if len(open_ring) < 2:
            return ring
        distances = [cls._coord_distance_m(point, target) for point in open_ring]
        best_index = min(range(len(open_ring)), key=lambda index: distances[index])
        if heading_deg is None:
            rotated = open_ring[best_index:] + open_ring[:best_index]
            rotated.append(rotated[0])
            return rotated

        point, edge_index = cls._ring_start_point(
            open_ring, distances[best_index], heading_deg, target, vehicle
        )
        following = (edge_index + 1) % len(open_ring)
        rotated = [list(point)] + open_ring[following:] + open_ring[:following]
        deduplicated = [rotated[0]]
        for coord in rotated[1:]:
            if cls._coord_distance_m(deduplicated[-1], coord) > 0.02:
                deduplicated.append(coord)
        deduplicated.append(list(point))
        return deduplicated

    @classmethod
    def _ring_start_point(
        cls,
        open_ring: List[List[float]],
        nearest_distance_m: float,
        heading_deg: float,
        target: List[float],
        vehicle: Optional[List[float]] = None,
    ) -> Tuple[List[float], int]:
        """Nächstgelegene Ringstelle, die auch anfahrbar ausgerichtet ist.

        Bewertet wird die ganze Kette, die das Fahrzeug tatsächlich fährt:
        erst der Übergang zur Stelle, dann der Ring ab dort. Nur die Tangente
        zu prüfen wählt eine Stelle, auf der der Ring zwar passend weiterläuft,
        die aber quer neben dem Fahrzeug liegt und einen 95° Übergang auf
        0,35 m verlangt (real, 02.08., vierter Ring). Die Anfahrt darf dabei
        rückwärts gefahren werden - sie vorwärts zu bewerten verwarf genau die
        Stellen, die _select_transfer_direction sauber rückwärts angefahren
        hätte.

        Gesucht wird entlang der Kanten, nicht nur auf den Stützpunkten: im
        6-m-Fenster um den gewählten Startpunkt lag auf der Wiese genau ein
        einziger Stützpunkt, es gab also gar keine Alternative zu bewerten
        (real, 02.08.).
        """
        # Das Suchfenster muss so groß sein, dass eine Drehung überhaupt
        # hineinpasst: gedreht wird rollend, eine halbe Umdrehung braucht
        # rund 13 m Strecke. Mit einem starren 6-m-Fenster gab es für ein
        # Fahrzeug, das 1 m neben der Bahn und quer dazu stand, gar keinen
        # fahrbaren Anfang - es blieb bei 0,0 m stehen (real, 02.08.).
        # Zusätzlich darf höchstens noch einmal die Strecke dazukommen, die
        # ohnehin zu fahren ist; bei Übergängen von Ring zu Ring bleibt die
        # Wahl dadurch trotzdem beim nächstgelegenen fahrbaren Punkt.
        turn_room = 180.0 / (cls.MAX_TURN_STEP_DEG / cls.TURN_STEP_M)
        limit = nearest_distance_m + max(
            cls.RING_START_MAX_DETOUR_M, nearest_distance_m, turn_room
        )
        vehicle = vehicle if vehicle is not None else target
        candidates = []
        for edge_index, start in enumerate(open_ring):
            end = open_ring[(edge_index + 1) % len(open_ring)]
            edge_length = cls._coord_distance_m(start, end)
            if edge_length <= 1e-6:
                continue
            steps = max(1, int(edge_length / cls.RING_START_SAMPLE_M))
            for step in range(steps):
                fraction = step / steps
                point = [
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                ]
                distance = cls._coord_distance_m(point, target)
                if distance > limit:
                    continue
                tangent = cls._edge_bearing_deg(point, end) or cls._edge_bearing_deg(start, end)
                # Ob der Ring an dieser Stelle knickt, spielt bewusst keine
                # Rolle: bei einem geschlossenen Ring ist eine Ecke sogar der
                # beste Anfang, weil sie dann auf der Naht zwischen Anfang und
                # Ende liegt und nie durchfahren wird. Ein Knick-Kriterium
                # schob den Start von der Feldecke weg mitten in die Bahn -
                # das Fahrzeug wäre 3,2 m gefahren und dann in dieselben 67°
                # gelaufen, wo der Regler sperrt (real, 02.08.).
                if distance <= 0.05:
                    # Kein eigener Übergang: das Fahrzeug steht schon dort.
                    cost = cls._angle_error_deg(tangent, heading_deg)
                else:
                    approach = cls._edge_bearing_deg(target, point)
                    if approach is None:
                        continue
                    forward_error = cls._angle_error_deg(approach, heading_deg)
                    # Dieselbe Regel wie _select_transfer_direction.
                    if forward_error > cls.TRANSFER_REVERSE_THRESHOLD_DEG:
                        nose_after = (approach + 180.0) % 360.0
                        transfer_error = 180.0 - forward_error
                    else:
                        nose_after = approach
                        transfer_error = forward_error
                    cost = max(transfer_error, cls._angle_error_deg(tangent, nose_after))
                # Gedreht wird rollend, also braucht jeder Winkel Strecke.
                # Ohne diese Bedingung gewinnt der nächstgelegene Punkt: ein
                # 0,86-m-Übergang, auf dem das Fahrzeug die verlangten 24°
                # nicht schafft und die folgende Bahn mit 48° blockiert
                # (real, 02.08.).
                required = cost / (cls.MAX_TURN_STEP_DEG / cls.TURN_STEP_M)
                candidates.append((cost, distance, point, edge_index, required))
        if not candidates:
            return list(open_ring[0]), 0
        drivable = [
            item for item in candidates
            if item[0] <= cls.RING_START_HEADING_LIMIT_DEG and item[1] >= item[4]
        ]
        if drivable:
            chosen = min(drivable, key=lambda item: item[1])
        else:
            # Keine erreichbare Stelle passt zur Ankunftsrichtung. Dann
            # wenigstens die mit dem kleinsten Winkel nehmen - der Regler
            # lehnt das gegebenenfalls immer noch ab, aber sichtbar knapper
            # als die blind nächstgelegene Stelle.
            chosen = min(candidates, key=lambda item: item[0])
        return chosen[2], chosen[3]

    @staticmethod
    def _is_closed(coords: List[List[float]]) -> bool:
        return len(coords) > 2 and coords[0][0] == coords[-1][0] and coords[0][1] == coords[-1][1]

    @staticmethod
    def _coord_distance_m(a: List[float], b: List[float]) -> float:
        return distance_m(MowingPlanManager._point(a), MowingPlanManager._point(b))

    @staticmethod
    def _pose_coord(pose: Optional[Dict[str, Any]]) -> Optional[List[float]]:
        if not isinstance(pose, dict):
            return None
        gps = pose.get("gps") if isinstance(pose.get("gps"), dict) else {}
        lat = pose.get("latitude", pose.get("lat", gps.get("lat", gps.get("latitude"))))
        lon = pose.get("longitude", pose.get("lon", pose.get("lng", gps.get("lon", gps.get("lng", gps.get("longitude"))))))
        try:
            return [float(lon), float(lat)]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _pose_heading(pose: Optional[Dict[str, Any]]) -> Optional[float]:
        if not isinstance(pose, dict):
            return None
        gps = pose.get("gps") if isinstance(pose.get("gps"), dict) else {}
        value = pose.get("heading_deg", pose.get("heading", gps.get("heading")))
        try:
            heading = float(value)
        except (TypeError, ValueError):
            return None
        return heading % 360.0

    def _persisted_payload(self, map_name: str, plan: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        keys = [
            "strategy", "parameters", "lane_count", "rest_lane_count", "connector_count",
            "transition_count", "unsafe_transition_count", "skipped_sharp_lanes",
            "mow_length_m", "rest_length_m", "connector_length_m",
            "unsafe_transition_length_m", "total_drive_length_m", "total_length_m",
            "lanes", "rest_lanes", "sequence", "transitions",
            "exclusion_contours", "map", "subs",
        ]
        payload = {key: plan.get(key) for key in keys if key in plan}
        payload.update({
            "schema": self.SCHEMA,
            "map_name": map_name,
            "name": map_name,
            "created_at": now,
        })
        return payload

    def _current_pose(self) -> Optional[Dict[str, Any]]:
        if self.pose_provider is None:
            return None
        try:
            pose = self.pose_provider()
        except Exception:
            return None
        if not isinstance(pose, dict):
            return None
        lat = pose.get("latitude", pose.get("lat"))
        lon = pose.get("longitude", pose.get("lon", pose.get("lng")))
        if lat is None and isinstance(pose.get("gps"), dict):
            lat = pose["gps"].get("lat", pose["gps"].get("latitude"))
            lon = pose["gps"].get("lon", pose["gps"].get("lng", pose["gps"].get("longitude")))
        if lat is None or lon is None:
            return None
        normalized = dict(pose)
        normalized["latitude"] = lat
        normalized["longitude"] = lon
        return normalized

    @classmethod
    def pose_rtk_ok(cls, pose: Optional[Dict[str, Any]]) -> bool:
        return cls.is_rtk_fixed(cls.rtk_status_from_pose(pose))

    @staticmethod
    def rtk_status_from_pose(pose: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(pose, dict):
            return None
        status = pose.get("rtk_status")
        if status is None and isinstance(pose.get("gps"), dict):
            status = pose["gps"].get("rtk_status")
        return None if status is None else str(status)

    @staticmethod
    def is_rtk_fixed(status: Optional[str]) -> bool:
        return str(status or "").strip().upper() in ("RTK FIXED", "FIXED")

    def _plan_path(self, name: str) -> Path:
        clean_name = self._sanitize_name(name)
        if not clean_name:
            raise ValueError("Kartenname erforderlich")
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        return self.plans_dir / f"{clean_name}.plan.json"

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _coords(segment: Dict[str, Any]) -> List[List[float]]:
        return [coord for coord in (segment.get("coordinates") or []) if isinstance(coord, list) and len(coord) >= 2]

    @staticmethod
    def _point(coord: List[float]) -> Dict[str, float]:
        return {"longitude": float(coord[0]), "latitude": float(coord[1])}

    @staticmethod
    def _sanitize_name(name: str) -> str:
        import re
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name).strip())
        return cleaned.strip("._")

    @staticmethod
    def _unsafe_transition_count(plan: Dict[str, Any]) -> int:
        return len([item for item in plan.get("transitions") or [] if item.get("safe") is not True])

    @staticmethod
    def _reverse_segment_count(plan: Dict[str, Any]) -> int:
        return len([
            item for item in plan.get("sequence") or []
            if item.get("type") == "rest_lane" and item.get("direction") == "reverse"
        ])

    @classmethod
    def _short_rest_lane_count(cls, plan: Dict[str, Any]) -> int:
        """Rest lanes too short to be worth driving as their own leg.

        A serpentine pass is not its own leg: it is one link of a run whose
        passes meet end to end, and near a sub-zone the links get short by
        design. Judging those individually would reject a perfectly
        driveable plan, so there the whole run is measured instead.
        """
        lanes = [
            item for item in plan.get("sequence") or []
            if item.get("type") == "rest_lane"
        ]
        if (plan.get("parameters") or {}).get("rest_pattern") != "serpentine":
            return len([
                item for item in lanes
                if cls._segment_length_m(item) < cls.MIN_PLANNED_REST_LANE_M
            ])
        run_length: Dict[Any, float] = {}
        for item in lanes:
            key = item.get("rest_group")
            run_length[key] = run_length.get(key, 0.0) + cls._segment_length_m(item)
        return len([
            item for item in lanes
            if run_length.get(item.get("rest_group"), 0.0) < cls.MIN_PLANNED_REST_LANE_M
        ])

    @staticmethod
    def _segment_length_m(segment: Dict[str, Any]) -> float:
        try:
            return float(segment.get("length_m", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
