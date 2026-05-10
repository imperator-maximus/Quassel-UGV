"""Persistence and execution preparation for mowing plans."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .geometry import distance_m


class MowingPlanManager:
    """Stores generated mowing plans and converts them into executable steps."""

    SCHEMA = "raspberrycan.mowing_plan.v1"

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

    def check_plan(self, map_name: str, plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
                executable = self.executable_segments(payload)
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

    def executable_segments(self, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self._unsafe_transition_count(plan) > 0:
            raise ValueError("Unsafe transitions blockieren die Ausführung")

        sequence = [item for item in plan.get("sequence") or [] if self._coords(item)]
        transitions_by_from = {
            item.get("from_segment_index"): item
            for item in plan.get("transitions") or []
        }
        executable: List[Dict[str, Any]] = []
        current_end = None

        for segment in sequence:
            coords = self._coords(segment)
            start = coords[0]
            if current_end is None or distance_m(self._point(current_end), self._point(start)) > 0.05:
                executable.append({
                    "type": "positioning",
                    "source_type": segment.get("type"),
                    "mode": "goto",
                    "direction": "forward",
                    "coordinates": [start],
                    "length_m": 0.0,
                })

            executable.append(self._track_segment(segment))
            current_end = coords[-1]

            transition = transitions_by_from.get(segment.get("segment_index"))
            if transition is not None:
                executable.append(self._transition_segment(transition))
                transition_coords = self._coords(transition)
                if transition_coords:
                    current_end = transition_coords[-1]

        return executable

    def summarize_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "map_name": plan.get("map_name", plan.get("name")),
            "segment_count": len(plan.get("sequence") or []),
            "transition_count": len(plan.get("transitions") or []),
            "unsafe_transition_count": self._unsafe_transition_count(plan),
            "reverse_segment_count": self._reverse_segment_count(plan),
            "total_drive_length_m": round(float(plan.get("total_drive_length_m", plan.get("total_length_m", 0.0)) or 0.0), 2),
        }

    def _track_segment(self, segment: Dict[str, Any]) -> Dict[str, Any]:
        direction = "forward"
        if segment.get("type") == "rest_lane":
            direction = segment.get("direction", "forward")
        if direction == "reverse" and not self.reverse_track_supported:
            raise ValueError("Plan enthält Rückwärtssegmente, Ausführung noch nicht unterstützt")
        return {
            "type": "mow",
            "source_type": segment.get("type"),
            "source_index": segment.get("segment_index"),
            "mode": "track",
            "direction": direction,
            "coordinates": self._coords(segment),
            "length_m": float(segment.get("length_m", 0.0) or 0.0),
        }

    def _transition_segment(self, transition: Dict[str, Any]) -> Dict[str, Any]:
        if transition.get("safe") is not True:
            raise ValueError("Unsafe transitions blockieren die Ausführung")
        route_kind = transition.get("route_kind", "direct")
        if route_kind not in ("direct", "around_sub"):
            raise ValueError(f"Unbekannte Transition-Route: {route_kind}")
        coords = self._coords(transition)
        return {
            "type": "transition",
            "source_index": transition.get("transition_index"),
            "mode": "track" if len(coords) >= 2 else "goto",
            "direction": "forward",
            "route_kind": route_kind,
            "coordinates": coords,
            "length_m": float(transition.get("length_m", 0.0) or 0.0),
        }

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
