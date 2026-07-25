"""Persistence and execution preparation for mowing plans."""

import json
import hashlib
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
    ABSORBED_REST_LANE_TRANSFER_M = 0.50
    # Kept as an alias for callers/tests that referred to the first version of
    # this rule when it only covered the initial RTK positioning leg.
    POSITIONING_REVERSE_THRESHOLD_DEG = TRANSFER_REVERSE_THRESHOLD_DEG

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

        for segment in sequence:
            if current_end is None and selected_start is not None:
                coords = self._coords_from_selected_start(segment, selected_start)
            else:
                coords = self._oriented_track_coords(segment, current_end or start_coord)
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
                    executable.append(transfer)
                    current_heading_deg = self._segment_end_heading(
                        transfer,
                        current_heading_deg,
                    )

            track = self._track_segment(segment, coordinates=coords)
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
        return self._select_transfer_direction(segment, start_heading_deg)

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
        ).to_dict()
        segment = self._transition_segment(routed, from_coord=from_coord, to_coord=to_coord)
        if segment is None:
            raise ValueError("Startpositionierung passt nicht zum berechneten sicheren Pfad")
        segment.update({
            "type": "positioning",
            "source_type": source_type,
            "source_index": None,
            "route_kind": f"runtime_{segment['route_kind']}",
        })
        return self._select_transfer_direction(segment, start_heading_deg)

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

    def _track_segment(self, segment: Dict[str, Any], coordinates: Optional[List[List[float]]] = None) -> Dict[str, Any]:
        direction = "forward"
        if segment.get("type") == "rest_lane":
            direction = segment.get("direction", "forward")
        if direction == "reverse" and not self.reverse_track_supported:
            raise ValueError("Plan enthält Rückwärtssegmente, Ausführung noch nicht unterstützt")
        track_coords = coordinates or self._coords(segment)
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
            raise ValueError("Unsafe transitions blockieren die Ausführung")
        route_kind = transition.get("route_kind", "direct")
        if route_kind not in ("direct", "around_sub"):
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

    def _oriented_track_coords(self, segment: Dict[str, Any], target: Optional[List[float]]) -> List[List[float]]:
        coords = self._coords(segment)
        if not coords or target is None:
            return coords
        if self._is_closed(coords):
            return self._rotate_closed_ring_near(coords, target)
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
        """Start the first route segment at the exact UI-selected path point."""
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
    def _rotate_closed_ring_near(cls, ring: List[List[float]], target: List[float]) -> List[List[float]]:
        open_ring = ring[:-1] if cls._is_closed(ring) else ring[:]
        if len(open_ring) < 2:
            return ring
        best_index = min(range(len(open_ring)), key=lambda index: cls._coord_distance_m(open_ring[index], target))
        rotated = open_ring[best_index:] + open_ring[:best_index]
        rotated.append(rotated[0])
        return rotated

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
        return len([
            item for item in plan.get("sequence") or []
            if item.get("type") == "rest_lane"
            and cls._segment_length_m(item) < cls.MIN_PLANNED_REST_LANE_M
        ])

    @staticmethod
    def _segment_length_m(segment: Dict[str, Any]) -> float:
        try:
            return float(segment.get("length_m", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
