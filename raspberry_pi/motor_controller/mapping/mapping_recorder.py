#!/usr/bin/env python3
"""Drive-around polygon recorder and GeoJSON persistence."""

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .geometry import (
    distance_m,
    iter_lines,
    iter_polygons,
    lonlat_distance_sq,
    lonlat_to_xy,
    max_turn_angle_xy,
    polyline_length_lonlat,
    polyline_length_xy,
    project_points,
    shoelace_area,
    vector_angle_deg,
    xy_ring_to_latlon,
)
from .lane_planner import LanePlanner
from .nogo_monitor import NoGoZoneMonitor
from .plan_manager import MowingPlanManager


class MappingRecorder:
    """Records boundary points from the current corrected vehicle pose."""

    def __init__(
        self,
        maps_dir: str,
        pose_provider: Callable[[], Dict[str, Any]],
        min_point_distance_m: float = 0.25,
    ):
        self.maps_dir = Path(maps_dir).expanduser()
        self.pose_provider = pose_provider
        self.min_point_distance_m = float(min_point_distance_m)
        self._lock = threading.Lock()
        self._recording = False
        self._points: List[Dict[str, float]] = []
        self._last_error: Optional[str] = None
        self.plans = MowingPlanManager(self.maps_dir, pose_provider)

    def start(self, clear: bool = True) -> Dict[str, Any]:
        with self._lock:
            if clear:
                self._points = []
            self._recording = True
            self._last_error = None
            return self.get_status()

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            self._recording = False
            return self.get_status()

    def clear(self) -> Dict[str, Any]:
        with self._lock:
            self._points = []
            self._last_error = None
            return self.get_status()

    def add_current_point(self, force: bool = False) -> Dict[str, Any]:
        try:
            point = self._point_from_pose(self.pose_provider())
        except ValueError as exc:
            with self._lock:
                self._last_error = str(exc)
                status = self.get_status()
            return {"success": False, "error": str(exc), **status}

        with self._lock:
            if not self._recording and not force:
                self._last_error = "Mapping-Aufnahme ist nicht aktiv"
                return {"success": False, "error": self._last_error, **self.get_status()}

            if self._points and not force:
                distance = self._distance_m(self._points[-1], point)
                if distance < self.min_point_distance_m:
                    self._last_error = None
                    return {
                        "success": True,
                        "skipped": True,
                        "reason": "min_distance",
                        "distance_m": distance,
                        **self.get_status(),
                    }

            self._points.append(point)
            self._last_error = None
            return {"success": True, "point": point, **self.get_status()}

    def save(self, name: str) -> Dict[str, Any]:
        clean_name = self._sanitize_name(name)
        if not clean_name:
            return {"success": False, "error": "Name erforderlich", **self.get_status()}

        with self._lock:
            if len(self._points) < 3:
                self._last_error = "Mindestens drei Punkte für ein Polygon erforderlich"
                return {"success": False, "error": self._last_error, **self.get_status()}
            points = [p.copy() for p in self._points]

        self.maps_dir.mkdir(parents=True, exist_ok=True)
        path = self.maps_dir / f"{clean_name}.geojson"
        payload = self._to_feature_collection(clean_name, points)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"success": True, "path": str(path), "map": payload, **self.get_status()}

    def list_maps(self) -> List[Dict[str, Any]]:
        self.maps_dir.mkdir(parents=True, exist_ok=True)
        maps = []
        for path in sorted(self.maps_dir.glob("*.geojson")):
            maps.append({"name": path.stem, "path": str(path), "is_sub": self._is_sub_map(path.stem)})
        return maps

    def list_main_maps(self) -> List[Dict[str, Any]]:
        return [item for item in self.list_maps() if not item["is_sub"]]

    def load_map(self, name: str) -> Dict[str, Any]:
        path = self._map_path(name)
        if not path.exists():
            return {"success": False, "error": "Karte nicht gefunden"}
        return {"success": True, "name": path.stem, "path": str(path), "map": self._read_geojson(path)}

    def delete_map(self, name: str) -> Dict[str, Any]:
        path = self._map_path(name)
        if not path.exists():
            return {"success": False, "error": "Karte nicht gefunden"}
        path.unlink()
        return {"success": True, "maps": self.list_maps()}

    def rename_map(self, old_name: str, new_name: str) -> Dict[str, Any]:
        old_path = self._map_path(old_name)
        new_clean = self._sanitize_name(new_name)
        if not new_clean:
            return {"success": False, "error": "Neuer Name erforderlich"}
        new_path = self.maps_dir / f"{new_clean}.geojson"
        if not old_path.exists():
            return {"success": False, "error": "Karte nicht gefunden"}
        if new_path.exists() and new_path != old_path:
            return {"success": False, "error": "Zielname existiert bereits"}

        payload = self._read_geojson(old_path)
        payload.setdefault("properties", {})["name"] = new_clean
        old_path.unlink()
        new_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"success": True, "name": new_clean, "path": str(new_path), "map": payload, "maps": self.list_maps()}

    def update_boundary_points(self, name: str, points: List[Dict[str, float]]) -> Dict[str, Any]:
        if len(points) < 3:
            return {"success": False, "error": "Mindestens drei Punkte für ein Polygon erforderlich"}
        path = self._map_path(name)
        if not path.exists():
            return {"success": False, "error": "Karte nicht gefunden"}

        parsed_points = [self._point_from_pose(point) for point in points]
        payload = self._read_geojson(path)
        boundary = self._find_boundary_feature(payload)
        coordinates = [[p["longitude"], p["latitude"]] for p in parsed_points]
        if coordinates[0] != coordinates[-1]:
            coordinates.append(coordinates[0])
        boundary["geometry"] = {
            "type": "Polygon",
            "coordinates": [coordinates],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"success": True, "name": path.stem, "path": str(path), "map": payload}

    def analyze_map_with_subs(self, name: str) -> Dict[str, Any]:
        main_path = self._map_path(name)
        if not main_path.exists():
            return {"success": False, "error": "Karte nicht gefunden"}

        main_payload = self._read_geojson(main_path)
        main_points = self._boundary_points(main_payload)
        sub_items = self._matching_sub_maps(main_path.stem)
        sub_payloads = []
        for item in sub_items:
            payload = self._read_geojson(Path(item["path"]))
            sub_payloads.append({"name": item["name"], "path": item["path"], "map": payload})

        analysis = self._area_analysis(main_points, sub_payloads)
        return {
            "success": True,
            "name": main_path.stem,
            "map": main_payload,
            "subs": sub_payloads,
            "area": analysis,
        }

    def plan_contour_lanes(
        self,
        name: str,
        cut_width_m: float = 0.45,
        overlap_m: float = 0.10,
        outer_margin_m: float = 0.0,
        sub_margin_m: float = 0.25,
        max_ring_turn_deg: float = 155.0,
    ) -> Dict[str, Any]:
        main_path = self._map_path(name)
        if not main_path.exists():
            return {"success": False, "error": "Karte nicht gefunden"}

        main_payload = self._read_geojson(main_path)
        main_points = self._boundary_points(main_payload)
        sub_payloads = []
        for item in self._matching_sub_maps(main_path.stem):
            payload = self._read_geojson(Path(item["path"]))
            sub_payloads.append({"name": item["name"], "path": item["path"], "map": payload})

        try:
            planner = LanePlanner(
                cut_width_m=cut_width_m,
                overlap_m=overlap_m,
                outer_margin_m=outer_margin_m,
                sub_margin_m=sub_margin_m,
                max_ring_turn_deg=max_ring_turn_deg,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        return planner.plan(
            main_path.stem,
            main_payload,
            main_points,
            sub_payloads,
            self._boundary_points,
        )

    def save_plan(self, name: str, plan: Dict[str, Any]) -> Dict[str, Any]:
        return self.plans.save_plan(name, plan)

    def list_plans(self) -> List[Dict[str, Any]]:
        return self.plans.list_plans()

    def load_plan(self, name: str) -> Dict[str, Any]:
        return self.plans.load_plan(name)

    def check_plan(self, name: str, plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.plans.check_plan(name, plan)

    def check_nogo(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        try:
            monitor = NoGoZoneMonitor(plan)
            return monitor.check_pose(self.pose_provider())
        except ValueError as exc:
            return {"ok": True, "state": "disabled", "reason": str(exc)}

    def get_status(self) -> Dict[str, Any]:
        # Caller may already hold the lock; use only immutable snapshots.
        return {
            "recording": self._recording,
            "point_count": len(self._points),
            "points": [p.copy() for p in self._points],
            "last_error": self._last_error,
            "maps_dir": str(self.maps_dir),
        }

    @staticmethod
    def _point_from_pose(payload: Dict[str, Any]) -> Dict[str, float]:
        if not isinstance(payload, dict):
            raise ValueError("Keine Pose verfügbar")
        gps = payload.get("gps") if isinstance(payload.get("gps"), dict) else None
        lat = payload.get("latitude", payload.get("lat"))
        lon = payload.get("longitude", payload.get("lon", payload.get("lng")))
        if lat is None and gps is not None:
            lat = gps.get("lat", gps.get("latitude"))
        if lon is None and gps is not None:
            lon = gps.get("lon", gps.get("lng", gps.get("longitude")))
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            raise ValueError("Pose benötigt latitude/longitude")
        if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
            raise ValueError("Pose-Koordinaten außerhalb gültiger Grenzen")
        return {"latitude": lat_f, "longitude": lon_f}

    @staticmethod
    def _distance_m(a: Dict[str, float], b: Dict[str, float]) -> float:
        return distance_m(a, b)

    @staticmethod
    def _sanitize_name(name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name).strip())
        return cleaned.strip("._")

    @staticmethod
    def _is_sub_map(name: str) -> bool:
        return str(name).lower().startswith("sub_")

    def _matching_sub_maps(self, main_name: str) -> List[Dict[str, Any]]:
        prefix = f"sub_{main_name}".lower()
        return [
            item for item in self.list_maps()
            if item["name"].lower().startswith(prefix)
        ]

    def _map_path(self, name: str) -> Path:
        clean_name = self._sanitize_name(name)
        if not clean_name:
            raise ValueError("Name erforderlich")
        self.maps_dir.mkdir(parents=True, exist_ok=True)
        return self.maps_dir / f"{clean_name}.geojson"

    @staticmethod
    def _read_geojson(path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("type") != "FeatureCollection":
            raise ValueError("GeoJSON muss eine FeatureCollection sein")
        return payload

    @staticmethod
    def _find_boundary_feature(payload: Dict[str, Any]) -> Dict[str, Any]:
        for feature in payload.get("features", []):
            if feature.get("properties", {}).get("type") == "boundary":
                return feature
        raise ValueError("Boundary-Feature fehlt")

    @classmethod
    def _boundary_points(cls, payload: Dict[str, Any]) -> List[Dict[str, float]]:
        feature = cls._find_boundary_feature(payload)
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Polygon":
            raise ValueError("Boundary muss ein Polygon sein")
        ring = (geometry.get("coordinates") or [[]])[0]
        if len(ring) > 1 and ring[0] == ring[-1]:
            ring = ring[:-1]
        return [{"longitude": float(coord[0]), "latitude": float(coord[1])} for coord in ring]

    @classmethod
    def _area_analysis(cls, main_points: List[Dict[str, float]], sub_payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
        origin_lat = sum(point["latitude"] for point in main_points) / len(main_points)
        origin_lon = sum(point["longitude"] for point in main_points) / len(main_points)
        main_xy = cls._project_points(main_points, origin_lat, origin_lon)
        sub_entries = []
        for item in sub_payloads:
            points = cls._boundary_points(item["map"])
            xy = cls._project_points(points, origin_lat, origin_lon)
            sub_entries.append({"name": item["name"], "points": points, "xy": xy})

        try:
            from shapely.geometry import Polygon
            from shapely.ops import unary_union

            main_poly = Polygon(main_xy)
            sub_polys = [Polygon(entry["xy"]) for entry in sub_entries]
            sub_union = unary_union(sub_polys) if sub_polys else None
            excluded = main_poly.intersection(sub_union).area if sub_union else 0.0
            net = max(0.0, main_poly.area - excluded)
            sub_areas = [
                {
                    "name": entry["name"],
                    "area_m2": main_poly.intersection(Polygon(entry["xy"])).area,
                }
                for entry in sub_entries
            ]
            exact = True
        except Exception:
            gross = cls._shoelace_area(main_xy)
            sub_areas = [{"name": entry["name"], "area_m2": cls._shoelace_area(entry["xy"])} for entry in sub_entries]
            excluded = sum(item["area_m2"] for item in sub_areas)
            net = max(0.0, gross - excluded)
            return {
                "gross_m2": round(gross, 2),
                "excluded_m2": round(excluded, 2),
                "net_m2": round(net, 2),
                "subs": [{"name": item["name"], "area_m2": round(item["area_m2"], 2)} for item in sub_areas],
                "exact": False,
            }

        return {
            "gross_m2": round(main_poly.area, 2),
            "excluded_m2": round(excluded, 2),
            "net_m2": round(net, 2),
            "subs": [{"name": item["name"], "area_m2": round(item["area_m2"], 2)} for item in sub_areas],
            "exact": exact,
        }

    @staticmethod
    def _project_points(points: List[Dict[str, float]], origin_lat: float, origin_lon: float) -> List[Tuple[float, float]]:
        return project_points(points, origin_lat, origin_lon)

    @staticmethod
    def _shoelace_area(points: List[Tuple[float, float]]) -> float:
        return shoelace_area(points)

    @staticmethod
    def _iter_polygons(geometry):
        return iter_polygons(geometry)

    @staticmethod
    def _xy_ring_to_latlon(ring, origin_lat: float, origin_lon: float) -> List[List[float]]:
        return xy_ring_to_latlon(ring, origin_lat, origin_lon)

    @classmethod
    def _rotate_closed_ring_near(cls, ring: List[List[float]], target: Optional[List[float]]) -> List[List[float]]:
        if not target or len(ring) < 4:
            return ring
        open_ring = ring[:-1] if ring[0] == ring[-1] else ring[:]
        if not open_ring:
            return ring
        best_index = min(
            range(len(open_ring)),
            key=lambda index: cls._lonlat_distance_sq(open_ring[index], target),
        )
        rotated = open_ring[best_index:] + open_ring[:best_index]
        rotated.append(rotated[0])
        return rotated

    @classmethod
    def _max_turn_angle_xy(cls, ring) -> float:
        return max_turn_angle_xy(ring)

    @staticmethod
    def _polyline_length_xy(coords) -> float:
        return polyline_length_xy(coords)

    @staticmethod
    def _lonlat_to_xy(coord: List[float], origin_lat: float, origin_lon: float) -> Tuple[float, float]:
        return lonlat_to_xy(coord, origin_lat, origin_lon)

    @staticmethod
    def _iter_lines(geometry):
        return iter_lines(geometry)

    @staticmethod
    def _vector_angle_deg(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        return vector_angle_deg(a, b)

    @staticmethod
    def _lonlat_distance_sq(a: List[float], b: List[float]) -> float:
        return lonlat_distance_sq(a, b)

    @classmethod
    def _polyline_length_lonlat(cls, coords: List[List[float]]) -> float:
        return polyline_length_lonlat(coords)

    @staticmethod
    def _to_feature_collection(name: str, points: List[Dict[str, float]]) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        coordinates: List[Tuple[float, float]] = [(p["longitude"], p["latitude"]) for p in points]
        if coordinates[0] != coordinates[-1]:
            coordinates.append(coordinates[0])
        return {
            "type": "FeatureCollection",
            "properties": {
                "schema": "raspberrycan.mowing_map.v1",
                "name": name,
                "created_at": now,
            },
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [coordinates],
                    },
                    "properties": {
                        "type": "boundary",
                        "name": "Boundary",
                        "created_at": now,
                    },
                }
            ],
        }
