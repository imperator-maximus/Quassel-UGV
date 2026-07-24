"""Persistence and execution preparation for mowing plans."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .geometry import distance_m


class MowingPlanManager:
    """Stores generated mowing plans and converts them into executable steps."""

    SCHEMA = "raspberrycan.mowing_plan.v1"
    MIN_PLANNED_REST_LANE_M = 2.0

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
        }

    def executable_segments(
        self,
        plan: Dict[str, Any],
        start_segment_index: Optional[int] = None,
        start_coordinate: Optional[List[float]] = None,
        start_pose: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if self._unsafe_transition_count(plan) > 0:
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
        transitions_by_pair = {
            (item.get("from_segment_index"), item.get("to_segment_index")): item
            for item in plan.get("transitions") or []
        }
        executable: List[Dict[str, Any]] = []
        current_end = None
        previous_index = None
        start_coord = self._pose_coord(start_pose)
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
                    executable.append({
                        "type": "positioning",
                        "source_type": segment.get("type"),
                        "mode": "goto",
                        "direction": "forward",
                        "coordinates": [start],
                        "length_m": 0.0,
                    })
            elif self._coord_distance_m(current_end, start) > 0.05:
                executable.append(self._transfer_segment(
                    transitions_by_pair.get((previous_index, segment.get("segment_index"))),
                    current_end,
                    start,
                ))

            executable.append(self._track_segment(segment, coordinates=coords))
            current_end = coords[-1]
            previous_index = segment.get("segment_index")

        return executable

    def _transfer_segment(
        self,
        transition: Optional[Dict[str, Any]],
        from_coord: List[float],
        to_coord: List[float],
    ) -> Dict[str, Any]:
        if transition is not None:
            segment = self._transition_segment(transition, from_coord=from_coord, to_coord=to_coord)
            if segment is not None:
                return segment
        return {
            "type": "positioning",
            "source_type": "transfer",
            "mode": "goto",
            "direction": "forward",
            "coordinates": [to_coord],
            "length_m": self._coord_distance_m(from_coord, to_coord),
            "route_kind": "direct_reposition",
        }

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

        trimmed = [point] + coords[best_index + 1:]
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
