#!/usr/bin/env python3
"""Drive-around polygon recorder and GeoJSON persistence."""

import json
import math
import re
import threading
import heapq
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


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
        """Erzeugt eine erste Kontur-/Offset-Bahnenvorschau.

        Diese Methode plant nur Linien für die UI-Vorschau. Sie erzeugt keine
        Fahrbefehle und keine Persistenz.
        """
        try:
            from shapely.geometry import LineString, MultiPolygon, Polygon
            from shapely.ops import unary_union
        except ImportError:
            return {"success": False, "error": "Bahnenplanung benötigt Shapely auf raspberrycan"}

        cut_width = float(cut_width_m)
        overlap = float(overlap_m)
        outer_margin = max(0.0, float(outer_margin_m))
        sub_margin = max(0.0, float(sub_margin_m))
        max_ring_turn = max(45.0, min(179.0, float(max_ring_turn_deg)))
        spacing = cut_width - overlap
        if cut_width <= 0.0:
            return {"success": False, "error": "cut_width_m muss > 0 sein"}
        if spacing <= 0.0:
            return {"success": False, "error": "cut_width_m muss größer als overlap_m sein"}

        main_path = self._map_path(name)
        if not main_path.exists():
            return {"success": False, "error": "Karte nicht gefunden"}

        main_payload = self._read_geojson(main_path)
        main_points = self._boundary_points(main_payload)
        origin_lat = sum(point["latitude"] for point in main_points) / len(main_points)
        origin_lon = sum(point["longitude"] for point in main_points) / len(main_points)
        main_poly = Polygon(self._project_points(main_points, origin_lat, origin_lon))
        if not main_poly.is_valid:
            main_poly = main_poly.buffer(0)

        if outer_margin > 0.0:
            main_poly = main_poly.buffer(-outer_margin)
        if main_poly.is_empty:
            return {"success": False, "error": "Außenfläche ist nach outer_margin leer"}

        sub_payloads = []
        sub_polys = []
        for item in self._matching_sub_maps(main_path.stem):
            payload = self._read_geojson(Path(item["path"]))
            points = self._boundary_points(payload)
            poly = Polygon(self._project_points(points, origin_lat, origin_lon))
            if not poly.is_valid:
                poly = poly.buffer(0)
            if sub_margin > 0.0:
                poly = poly.buffer(sub_margin)
            sub_payloads.append({"name": item["name"], "path": item["path"], "map": payload})
            if not poly.is_empty:
                sub_polys.append(poly)

        sub_union = None
        if sub_polys:
            sub_union = unary_union(sub_polys)
            mow_area = main_poly.difference(sub_union)
        else:
            mow_area = main_poly
        if mow_area.is_empty:
            return {"success": False, "error": "Mähfläche ist nach Sub-Puffer leer"}

        lanes = []
        rest_lanes = []
        sequence = []
        exclusion_contours = []
        if sub_union is not None:
            for sub_poly in self._iter_polygons(sub_union):
                ring = self._xy_ring_to_latlon(sub_poly.exterior.coords, origin_lat, origin_lon)
                if len(ring) >= 4:
                    exclusion_contours.append({
                        "type": "sub_buffer_boundary",
                        "coordinates": ring,
                        "length_m": round(float(sub_poly.exterior.length), 2),
                    })
        covered_geometries = []
        current = main_poly
        lane_index = 0
        skipped_sharp_lanes = 0
        while not current.is_empty and lane_index < 500:
            accepted_in_iteration = 0
            for poly in self._iter_polygons(current):
                exterior_xy = list(poly.exterior.coords)
                lane_line = LineString(exterior_xy)
                lane_coverage = lane_line.buffer(cut_width / 2.0, cap_style=2, join_style=2)
                if sub_union is not None and lane_line.intersects(sub_union.buffer(cut_width / 2.0)):
                    skipped_sharp_lanes += 1
                    continue
                exterior = self._xy_ring_to_latlon(exterior_xy, origin_lat, origin_lon)
                if len(exterior) >= 4:
                    max_turn_angle = self._max_turn_angle_xy(exterior_xy)
                    if max_turn_angle > max_ring_turn:
                        skipped_sharp_lanes += 1
                        continue
                    lane = {
                        "type": "contour",
                        "segment_index": len(sequence),
                        "lane_index": lane_index,
                        "coordinates": exterior,
                        "length_m": round(float(poly.exterior.length), 2),
                        "max_turn_angle_deg": round(max_turn_angle, 1),
                    }
                    lanes.append(lane)
                    sequence.append(lane.copy())
                    covered_geometries.append(lane_coverage.intersection(mow_area))
                    lane_index += 1
                    accepted_in_iteration += 1
            if accepted_in_iteration == 0 and lane_index > 0:
                break
            current = current.buffer(-spacing)

        covered_area = unary_union(covered_geometries) if covered_geometries else None
        rest_area = mow_area.difference(covered_area) if covered_area else mow_area
        if not rest_area.is_empty:
            rest_lanes = self._generate_rest_lanes(
                rest_area,
                spacing,
                LineString,
                origin_lat,
                origin_lon,
            )
            for rest_lane in rest_lanes:
                rest_lane["segment_index"] = len(sequence)
                sequence.append(rest_lane.copy())

        transitions = self._plan_sequence_transitions(
            sequence,
            mow_area,
            sub_union,
            LineString,
            origin_lat,
            origin_lon,
        )
        unsafe_transitions = len([transition for transition in transitions if not transition["safe"]])
        safe_transition_length = sum(transition["length_m"] for transition in transitions if transition["safe"])
        unsafe_transition_length = sum(transition["length_m"] for transition in transitions if not transition["safe"])
        mow_length = sum(item["length_m"] for item in lanes)
        rest_length = sum(item["length_m"] for item in rest_lanes)
        total_drive_length = mow_length + rest_length + safe_transition_length
        return {
            "success": True,
            "name": main_path.stem,
            "strategy": "hybrid_contour_rest_reverse_preview",
            "parameters": {
                "cut_width_m": cut_width,
                "overlap_m": overlap,
                "spacing_m": spacing,
                "outer_margin_m": outer_margin,
                "sub_margin_m": sub_margin,
                "max_ring_turn_deg": max_ring_turn,
            },
            "lane_count": len(lanes),
            "rest_lane_count": len(rest_lanes),
            "connector_count": 0,
            "transition_count": len(transitions),
            "unsafe_transition_count": unsafe_transitions,
            "skipped_sharp_lanes": skipped_sharp_lanes,
            "mow_length_m": round(mow_length, 2),
            "rest_length_m": round(rest_length, 2),
            "connector_length_m": round(safe_transition_length, 2),
            "unsafe_transition_length_m": round(unsafe_transition_length, 2),
            "total_drive_length_m": round(total_drive_length, 2),
            "total_length_m": round(total_drive_length, 2),
            "lanes": lanes,
            "rest_lanes": rest_lanes,
            "sequence": sequence,
            "transitions": transitions,
            "exclusion_contours": exclusion_contours,
            "map": main_payload,
            "subs": sub_payloads,
        }

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
        lat1 = math.radians(a["latitude"])
        lat2 = math.radians(b["latitude"])
        d_lat = lat2 - lat1
        d_lon = math.radians(b["longitude"] - a["longitude"])
        h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
        return 6371000.0 * 2.0 * math.atan2(math.sqrt(h), math.sqrt(1.0 - h))

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
        lat0 = math.radians(origin_lat)
        meters_per_degree_lat = 111320.0
        meters_per_degree_lon = 111320.0 * math.cos(lat0)
        return [
            (
                (point["longitude"] - origin_lon) * meters_per_degree_lon,
                (point["latitude"] - origin_lat) * meters_per_degree_lat,
            )
            for point in points
        ]

    @staticmethod
    def _shoelace_area(points: List[Tuple[float, float]]) -> float:
        if len(points) < 3:
            return 0.0
        total = 0.0
        for index, point in enumerate(points):
            nxt = points[(index + 1) % len(points)]
            total += point[0] * nxt[1] - nxt[0] * point[1]
        return abs(total) / 2.0

    @staticmethod
    def _iter_polygons(geometry):
        if geometry.geom_type == "Polygon":
            return [geometry]
        if geometry.geom_type == "MultiPolygon":
            return list(geometry.geoms)
        return []

    @staticmethod
    def _xy_ring_to_latlon(ring, origin_lat: float, origin_lon: float) -> List[List[float]]:
        lat0 = math.radians(origin_lat)
        meters_per_degree_lat = 111320.0
        meters_per_degree_lon = 111320.0 * math.cos(lat0)
        return [
            [
                origin_lon + x / meters_per_degree_lon,
                origin_lat + y / meters_per_degree_lat,
            ]
            for x, y in ring
        ]

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
        open_ring = list(ring[:-1]) if len(ring) > 1 and ring[0] == ring[-1] else list(ring)
        if len(open_ring) < 3:
            return 0.0
        max_angle = 0.0
        for index, point in enumerate(open_ring):
            prev_point = open_ring[index - 1]
            next_point = open_ring[(index + 1) % len(open_ring)]
            angle = cls._vector_angle_deg(
                (point[0] - prev_point[0], point[1] - prev_point[1]),
                (next_point[0] - point[0], next_point[1] - point[1]),
            )
            max_angle = max(max_angle, angle)
        return max_angle

    @classmethod
    def _generate_rest_lanes(
        cls,
        rest_area,
        spacing: float,
        line_string_cls,
        origin_lat: float,
        origin_lon: float,
    ) -> List[Dict[str, Any]]:
        if rest_area.is_empty or spacing <= 0.0:
            return []
        scan_area = rest_area.buffer(-min(0.08, spacing * 0.25))
        if scan_area.is_empty:
            scan_area = rest_area
        min_x, min_y, max_x, max_y = scan_area.bounds
        candidates = []
        y = min_y + spacing / 2.0
        while y <= max_y and len(candidates) < 500:
            scanline = line_string_cls([(min_x - spacing, y), (max_x + spacing, y)])
            clipped = scan_area.intersection(scanline)
            for line in cls._iter_lines(clipped):
                if line.length < spacing * 0.6:
                    continue
                candidates.append({
                    "coords_xy": list(line.coords),
                    "length_m": float(line.length),
                    "y": y,
                })
            y += spacing

        ordered = cls._order_rest_lane_candidates(candidates, scan_area, line_string_cls, spacing)
        rest_lanes: List[Dict[str, Any]] = []
        for rest_index, item in enumerate(ordered):
            direction = "forward" if rest_index % 2 == 0 else "reverse"
            rest_lanes.append({
                "type": "rest_lane",
                "rest_index": rest_index,
                "rest_group": item["group"],
                "direction": direction,
                "coordinates": cls._xy_ring_to_latlon(item["coords_xy"], origin_lat, origin_lon),
                "length_m": round(item["length_m"], 2),
            })
        return rest_lanes

    @classmethod
    def _order_rest_lane_candidates(cls, candidates, rest_area, line_string_cls, spacing: float):
        remaining = []
        for index, item in enumerate(candidates):
            coords = item["coords_xy"]
            if len(coords) < 2:
                continue
            remaining.append({
                "id": index,
                "coords_xy": coords,
                "length_m": item["length_m"],
                "group": 0,
            })
        if not remaining:
            return []

        allowed = rest_area.buffer(min(0.18, spacing * 0.55))
        ordered = []
        current_end = None
        group = -1
        while remaining and len(ordered) < 500:
            best = None
            best_score = float("inf")
            best_safe = False
            for index, item in enumerate(remaining):
                options = (item["coords_xy"], list(reversed(item["coords_xy"])))
                for coords in options:
                    if current_end is None:
                        score = coords[0][1] * 1000.0 + coords[0][0]
                        safe = True
                    else:
                        distance = math.hypot(coords[0][0] - current_end[0], coords[0][1] - current_end[1])
                        connector = line_string_cls([current_end, coords[0]])
                        safe = distance <= spacing * 5.0 and allowed.covers(connector)
                        score = distance if safe else distance + 10000.0
                    if score < best_score:
                        best_score = score
                        best = (index, item, coords)
                        best_safe = safe
            if best is None:
                break
            index, item, coords = best
            if current_end is None or not best_safe:
                group += 1
            ordered_item = {
                "coords_xy": coords,
                "length_m": item["length_m"],
                "group": group,
            }
            ordered.append(ordered_item)
            current_end = coords[-1]
            remaining.pop(index)
        return ordered

    @classmethod
    def _plan_sequence_transitions(cls, sequence, mow_area, sub_union, line_string_cls, origin_lat: float, origin_lon: float):
        transitions: List[Dict[str, Any]] = []
        if len(sequence) < 2:
            return transitions
        allowed_area = mow_area.buffer(0.02)
        for index in range(len(sequence) - 1):
            current = sequence[index]
            nxt = sequence[index + 1]
            current_coords = current.get("coordinates") or []
            next_coords = nxt.get("coordinates") or []
            if not current_coords or not next_coords:
                continue
            start = current_coords[-1]
            end = next_coords[0]
            start_xy = cls._lonlat_to_xy(start, origin_lat, origin_lon)
            end_xy = cls._lonlat_to_xy(end, origin_lat, origin_lon)
            line = line_string_cls([start_xy, end_xy])
            line_length = cls._polyline_length_lonlat([start, end])
            crosses_sub = bool(sub_union and line.intersects(sub_union))
            within_mow_area = allowed_area.covers(line)
            safe = within_mow_area and not crosses_sub
            route_coords_xy = [start_xy, end_xy]
            route_kind = "direct"
            if not safe and sub_union is not None:
                routed = cls._route_around_sub(start_xy, end_xy, mow_area, sub_union, line_string_cls)
                if routed:
                    route_coords_xy = routed
                    routed_line = line_string_cls(route_coords_xy)
                    safe = allowed_area.covers(routed_line) and not routed_line.intersects(sub_union)
                    route_kind = "around_sub" if safe else "failed"
                    line_length = cls._polyline_length_xy(route_coords_xy)
            transitions.append({
                "type": "transition",
                "transition_index": len(transitions),
                "from_segment_index": current.get("segment_index", index),
                "to_segment_index": nxt.get("segment_index", index + 1),
                "from_type": current.get("type", "unknown"),
                "to_type": nxt.get("type", "unknown"),
                "safe": safe,
                "reason": "ok" if safe else ("sub_zone" if crosses_sub else "outside_mow_area"),
                "route_kind": route_kind,
                "coordinates": cls._xy_ring_to_latlon(route_coords_xy, origin_lat, origin_lon),
                "length_m": round(line_length, 2),
            })
        return transitions

    @classmethod
    def _route_around_sub(cls, start_xy, end_xy, mow_area, sub_union, line_string_cls):
        best_route = None
        best_length = float("inf")
        allowed = mow_area.buffer(0.05)
        for sub_poly in cls._iter_polygons(sub_union):
            route_poly = sub_poly.buffer(0.15)
            if route_poly.is_empty:
                continue
            raw_ring = list(route_poly.exterior.coords)
            open_ring = raw_ring[:-1] if raw_ring and raw_ring[0] == raw_ring[-1] else raw_ring
            if len(open_ring) < 4:
                continue
            step = max(1, len(open_ring) // 40)
            nodes = [start_xy, end_xy] + open_ring[::step]
            route = cls._shortest_ring_route(nodes, allowed, sub_union, line_string_cls)
            if route:
                length = cls._polyline_length_xy(route)
                if length < best_length:
                    best_length = length
                    best_route = route
        return best_route

    @classmethod
    def _shortest_ring_route(cls, nodes, allowed_area, sub_union, line_string_cls):
        graph = [[] for _ in nodes]
        edge_pairs = [(0, 1)]
        ring_indices = list(range(2, len(nodes)))
        for node in ring_indices:
            edge_pairs.append((0, node))
            edge_pairs.append((1, node))
        for offset, node in enumerate(ring_indices):
            nxt = ring_indices[(offset + 1) % len(ring_indices)]
            edge_pairs.append((node, nxt))
        for i, j in edge_pairs:
            edge = line_string_cls([nodes[i], nodes[j]])
            if edge.intersects(sub_union) or not allowed_area.covers(edge):
                continue
            distance = math.hypot(nodes[j][0] - nodes[i][0], nodes[j][1] - nodes[i][1])
            graph[i].append((j, distance))
            graph[j].append((i, distance))
        queue = [(0.0, 0)]
        distances = [float("inf")] * len(nodes)
        previous = [-1] * len(nodes)
        distances[0] = 0.0
        while queue:
            distance, node = heapq.heappop(queue)
            if distance > distances[node]:
                continue
            if node == 1:
                break
            for neighbor, edge_distance in graph[node]:
                new_distance = distance + edge_distance
                if new_distance < distances[neighbor]:
                    distances[neighbor] = new_distance
                    previous[neighbor] = node
                    heapq.heappush(queue, (new_distance, neighbor))
        if not math.isfinite(distances[1]):
            return None
        path = []
        node = 1
        while node != -1:
            path.append(nodes[node])
            node = previous[node]
        path.reverse()
        return path

    @staticmethod
    def _polyline_length_xy(coords) -> float:
        total = 0.0
        for index in range(len(coords) - 1):
            a = coords[index]
            b = coords[index + 1]
            total += math.hypot(b[0] - a[0], b[1] - a[1])
        return total

    @staticmethod
    def _lonlat_to_xy(coord: List[float], origin_lat: float, origin_lon: float) -> Tuple[float, float]:
        lat0 = math.radians(origin_lat)
        meters_per_degree_lat = 111320.0
        meters_per_degree_lon = 111320.0 * math.cos(lat0)
        return (
            (float(coord[0]) - origin_lon) * meters_per_degree_lon,
            (float(coord[1]) - origin_lat) * meters_per_degree_lat,
        )

    @staticmethod
    def _iter_lines(geometry):
        if geometry.is_empty:
            return []
        if geometry.geom_type == "LineString":
            return [geometry]
        if geometry.geom_type == "MultiLineString":
            return list(geometry.geoms)
        if geometry.geom_type == "GeometryCollection":
            lines = []
            for item in geometry.geoms:
                if item.geom_type == "LineString":
                    lines.append(item)
                elif item.geom_type == "MultiLineString":
                    lines.extend(item.geoms)
            return lines
        return []

    @staticmethod
    def _vector_angle_deg(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        a_len = math.hypot(a[0], a[1])
        b_len = math.hypot(b[0], b[1])
        if a_len <= 0.0 or b_len <= 0.0:
            return 180.0
        cos_value = max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / (a_len * b_len)))
        return math.degrees(math.acos(cos_value))

    @staticmethod
    def _lonlat_distance_sq(a: List[float], b: List[float]) -> float:
        return (float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2

    @classmethod
    def _polyline_length_lonlat(cls, coords: List[List[float]]) -> float:
        if len(coords) < 2:
            return 0.0
        total = 0.0
        for index in range(len(coords) - 1):
            a = {"longitude": coords[index][0], "latitude": coords[index][1]}
            b = {"longitude": coords[index + 1][0], "latitude": coords[index + 1][1]}
            total += cls._distance_m(a, b)
        return total

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
