"""Persistence and execution preparation for mowing plans."""

import json
import hashlib
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
    # Kept as an alias for callers/tests that referred to the first version of
    # this rule when it only covered the initial RTK positioning leg.
    POSITIONING_REVERSE_THRESHOLD_DEG = TRANSFER_REVERSE_THRESHOLD_DEG
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
    # Eindrehmanöver: wie weit in die Zielbahn hineingefahren wird, bevor das
    # Fahrzeug an deren Anfang zurückstößt. Aus dem Drehwinkel gerechnet
    # (~13°/m gemessen) plus Reserve; genau diese Strecke wird doppelt
    # befahren.
    TURN_IN_RESERVE_M = 2.0
    MIN_TURN_IN_M = 4.0
    MAX_TURN_IN_M = 20.0

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
        if max_source_segments is not None:
            try:
                source_limit = int(max_source_segments)
            except (TypeError, ValueError):
                raise ValueError("max_source_segments muss eine Zahl sein")
            if source_limit < 1:
                raise ValueError("max_source_segments muss mindestens 1 sein")
            sequence = sequence[:source_limit]
        transitions_by_pair = {
            (item.get("from_segment_index"), item.get("to_segment_index")): item
            for item in plan.get("transitions") or []
        }
        executable: List[Dict[str, Any]] = []
        runtime_router = self._runtime_transition_router(plan)
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

        for segment in sequence:
            if reverse_rings:
                segment = dict(segment, coordinates=list(reversed(self._coords(segment))))
            if current_end is None and selected_start is not None:
                coords = self._coords_from_selected_start(
                    segment,
                    selected_start,
                    # Anflugrichtung auf die gewählte Abfahrposition. Ein
                    # geschlossener Ring wird an jeder Stelle vollständig
                    # gemäht, also darf der Startpunkt ein Stück wandern,
                    # wenn er sonst auf einer Spitze läge: die Wiese hat an
                    # der gewählten Stelle eine 155°-Haarnadel, die kein
                    # Skid-Steer am Bahnanfang fahren kann (real, 02.08.).
                    approach_heading_deg=approach_bearing,
                    vehicle=start_coord,
                )
            else:
                coords = self._oriented_track_coords(
                    segment,
                    current_end or start_coord,
                    # Vor der ersten Bahn steht die Anfahrt, die auf die Bahn
                    # einschwenkt - dort zählt die Anflugrichtung, nicht der
                    # Kurs am Stellplatz.
                    approach_bearing if current_end is None else current_heading_deg,
                    vehicle=start_coord if current_end is None else None,
                )
            if current_end is None and selected_start is None and start_coord is not None:
                trimmed = self._trim_coords_from_point(coords, start_coord, max_distance_m=1.5)
                if trimmed is not None:
                    coords = trimmed
            start = coords[0]
            if current_end is None:
                if start_coord is None or self._coord_distance_m(start_coord, start) > 0.05:
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
                        )
                        executable.append(positioning)
                        current_heading_deg = self._segment_end_heading(
                            positioning,
                            current_heading_deg,
                        )
            elif self._coord_distance_m(current_end, start) > 0.05:
                transfer = self._transfer_segment(
                    transitions_by_pair.get((previous_index, segment.get("segment_index"))),
                    current_end,
                    start,
                    runtime_router=runtime_router,
                    previous_segment=previous_segment,
                    next_segment=segment,
                    start_heading_deg=current_heading_deg,
                )
                if not self._absorbs_short_rest_lane_transfer(
                    transfer,
                    previous_segment,
                    segment,
                    current_end,
                    start,
                ):
                    # Sperrt der Regler diesen Übergang am Winkel, wird
                    # stattdessen in die Fläche hinein eingedreht und an den
                    # Bahnanfang zurückgestoßen.
                    manoeuvre = None
                    if self._blocks_on_heading(transfer, current_heading_deg):
                        manoeuvre = self._turn_in_transfer(
                            current_end, current_heading_deg, coords, runtime_router
                        )
                    for item in manoeuvre or [transfer]:
                        executable.append(item)
                        current_heading_deg = self._segment_end_heading(
                            item,
                            current_heading_deg,
                        )

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
        return self._coord_distance_m(from_coord, to_coord) <= self.ABSORBED_REST_LANE_TRANSFER_M

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
            # Zeigt das Fahrzeug annähernd von der Bahn weg, ist Rückwärts-
            # fahren der kürzeste Weg: geradeaus zurückstoßen statt einen
            # Wendebogen über die Wiese zu fahren.
            return segment
        if start_heading_deg is not None and len(coordinates) >= 2:
            # Das Fahrzeug dreht nicht auf der Stelle, also muss die Kurve in
            # den Weg. Mehr Anspruch als das erhebt die Anfahrt nicht: sie
            # fährt die Gerade zum Bahnanfang, und dass der Ring dort in
            # Fahrtrichtung weiterläuft, hat die Startpunktwahl schon
            # sichergestellt.
            turned = self._rolling_turn_coords(
                coordinates[0], start_heading_deg, coordinates[1:]
            )
            # Der Bogen stammt nicht vom Router und darf deshalb nur gefahren
            # werden, wenn er dieselbe Prüfung besteht wie die gerade
            # Verbindung. Sonst bleibt es beim geraden Weg - lieber eine
            # Anfahrt, die der Regler ablehnt, als eine durch eine Sperrzone.
            if len(turned) > len(coordinates) and runtime_router.is_polyline_safe(
                turned, confine_to_mow_area=False
            ):
                segment["coordinates"] = turned
                segment["length_m"] = round(self._polyline_length_m(turned), 2)
        return segment

    @classmethod
    def _rolling_turn_coords(
        cls,
        start: List[float],
        heading_deg: float,
        waypoints: List[List[float]],
        clockwise: Optional[bool] = None,
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
        for waypoint in waypoints:
            for _ in range(cls.MAX_TURN_STEPS):
                bearing = cls._edge_bearing_deg(position, waypoint)
                if bearing is None:
                    break
                error = (bearing - heading + 540.0) % 360.0 - 180.0
                if abs(error) <= cls.MAX_TURN_STEP_DEG:
                    break
                remaining = cls._coord_distance_m(position, waypoint)
                if remaining <= cls.TURN_STEP_M:
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
                position = cls._offset_coord(position, heading, cls.TURN_STEP_M)
                path.append(list(position))
            heading = cls._edge_bearing_deg(position, waypoint) or heading
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
        approach_heading_deg: Optional[float] = None,
        vehicle: Optional[List[float]] = None,
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

        if approach_heading_deg is not None and self._is_closed(coords):
            # Der gewählte Punkt bleibt der Startpunkt, solange die Bahn dort
            # ungefähr in die Richtung läuft, aus der das Fahrzeug ankommt.
            # Nur wenn sie quer dazu liegt, beginnt der Ring wenige Meter
            # daneben - gemäht wird derselbe geschlossene Ring, nur fahrbar
            # begonnen. Ob der Ring hier knickt, ist dafür ohne Belang: eine
            # Ecke am Anfang liegt auf der Naht und wird nie durchfahren.
            tangent = self._edge_bearing_deg(point, coords[best_index + 1])
            if self._angle_error_deg(tangent, approach_heading_deg) > self.RING_START_HEADING_LIMIT_DEG:
                return self._rotate_closed_ring_near(
                    coords, point, approach_heading_deg, vehicle=vehicle
                )

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
