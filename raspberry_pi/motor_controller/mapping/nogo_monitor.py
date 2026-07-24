"""Live vehicle-footprint checks against mowing no-go zones."""

import math
from typing import Any, Dict, List, Optional, Tuple

from .geometry import lonlat_to_xy


class NoGoZoneMonitor:
    """Checks whether the vehicle footprint intrudes into protected zones."""

    def __init__(
        self,
        plan: Dict[str, Any],
        vehicle_length_m: float = 1.15,
        vehicle_width_m: float = 0.79,
        intrusion_tolerance_m: float = 0.35,
        boundary_tolerance_m: float = 0.35,
        enforce_outer_boundary: bool = True,
    ):
        try:
            from shapely.geometry import Point, Polygon
            from shapely.ops import unary_union
        except ImportError as exc:
            raise ValueError("No-Go-Check benötigt Shapely auf raspberrycan") from exc

        self._polygon_cls = Polygon
        self._point_cls = Point
        self.vehicle_length_m = float(vehicle_length_m)
        self.vehicle_width_m = float(vehicle_width_m)
        self.intrusion_tolerance_m = max(0.0, float(intrusion_tolerance_m))
        self.boundary_tolerance_m = max(0.0, float(boundary_tolerance_m))
        self.enforce_outer_boundary = bool(enforce_outer_boundary)
        self.origin_lat, self.origin_lon = self._origin_from_plan(plan)

        self.allowed_area = None
        boundary_ring = (
            self._boundary_ring(plan.get("map") or {})
            if self.enforce_outer_boundary
            else []
        )
        if boundary_ring:
            boundary_xy = [
                lonlat_to_xy(coord, self.origin_lat, self.origin_lon)
                for coord in boundary_ring
            ]
            boundary_poly = Polygon(boundary_xy)
            if not boundary_poly.is_valid:
                boundary_poly = boundary_poly.buffer(0)
            outer_margin_m = max(
                0.0,
                float((plan.get("parameters") or {}).get("outer_margin_m", 0.0)),
            )
            if outer_margin_m > 0.0 and not boundary_poly.is_empty:
                boundary_poly = boundary_poly.buffer(-outer_margin_m)
            if not boundary_poly.is_empty:
                self.allowed_area = boundary_poly

        zone_polygons = []
        for ring in self._zone_rings(plan):
            xy = [lonlat_to_xy(coord, self.origin_lat, self.origin_lon) for coord in ring]
            if len(xy) >= 3:
                poly = Polygon(xy)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if not poly.is_empty:
                    zone_polygons.append(poly)

        self.zone_union = unary_union(zone_polygons) if zone_polygons else None
        self.stop_zone = None
        if self.zone_union is not None and not self.zone_union.is_empty:
            self.stop_zone = self.zone_union.buffer(-self.intrusion_tolerance_m)
            if self.stop_zone.is_empty:
                self.stop_zone = None

    def check_pose(self, pose: Dict[str, Any]) -> Dict[str, Any]:
        if self.zone_union is None and self.allowed_area is None:
            return {"ok": True, "state": "disabled", "reason": "Keine Begrenzungen im Plan"}
        parsed = self._parse_pose(pose)
        if parsed is None:
            return {"ok": False, "state": "stop", "reason": "Keine Pose für Begrenzungs-Check"}
        lat, lon, heading = parsed
        center_x, center_y = lonlat_to_xy([lon, lat], self.origin_lat, self.origin_lon)
        boundary_warning = None
        boundary_distance = None
        if self.allowed_area is not None:
            reference_point = self._point_cls(center_x, center_y)
            boundary_distance = float(reference_point.distance(self.allowed_area))
            if boundary_distance > self.boundary_tolerance_m:
                return {
                    "ok": False,
                    "state": "stop",
                    "reason": (
                        f"RTK-Position {boundary_distance:.2f} m außerhalb der "
                        f"Mähbegrenzung (Toleranz {self.boundary_tolerance_m:.2f} m)"
                    ),
                    "boundary_distance_m": round(boundary_distance, 3),
                }
            if boundary_distance > 0.0:
                boundary_warning = "RTK-Position berührt Toleranzbereich der Mähbegrenzung"

        if self.zone_union is None:
            if boundary_warning:
                return {
                    "ok": True,
                    "state": "warning",
                    "reason": boundary_warning,
                    "boundary_distance_m": round(boundary_distance or 0.0, 3),
                }
            return {
                "ok": True,
                "state": "ok",
                "reason": "Mähbegrenzung eingehalten",
                "boundary_distance_m": 0.0,
            }

        footprint = self._footprint_polygon(lat, lon, heading)
        intersects_zone = footprint.intersects(self.zone_union)
        stop = self.stop_zone is not None and footprint.intersects(self.stop_zone)
        distance = 0.0 if intersects_zone else float(footprint.distance(self.zone_union))
        if stop:
            return {
                "ok": False,
                "state": "stop",
                "reason": f"Fahrzeug-Footprint mehr als {round(self.intrusion_tolerance_m * 100):.0f} cm in No-Go-Zone",
                "distance_m": round(distance, 3),
            }
        if intersects_zone:
            return {
                "ok": True,
                "state": "warning",
                "reason": "Fahrzeug-Footprint berührt No-Go-Zone",
                "distance_m": 0.0,
            }
        if boundary_warning:
            return {
                "ok": True,
                "state": "warning",
                "reason": boundary_warning,
                "distance_m": round(distance, 3),
                "boundary_distance_m": round(boundary_distance or 0.0, 3),
            }
        return {
            "ok": True,
            "state": "ok",
            "reason": "No-Go frei",
            "distance_m": round(distance, 3),
        }

    def _footprint_polygon(self, lat: float, lon: float, heading_deg: float):
        center_x, center_y = lonlat_to_xy([lon, lat], self.origin_lat, self.origin_lon)
        heading = math.radians(heading_deg)
        forward = (math.sin(heading), math.cos(heading))
        right = (math.cos(heading), -math.sin(heading))
        half_length = self.vehicle_length_m / 2.0
        half_width = self.vehicle_width_m / 2.0
        corners = []
        for x_local, y_local in (
            (half_length, -half_width),
            (half_length, half_width),
            (-half_length, half_width),
            (-half_length, -half_width),
        ):
            corners.append((
                center_x + forward[0] * x_local + right[0] * y_local,
                center_y + forward[1] * x_local + right[1] * y_local,
            ))
        return self._polygon_cls(corners)

    @staticmethod
    def _parse_pose(pose: Dict[str, Any]) -> Optional[Tuple[float, float, float]]:
        if not isinstance(pose, dict):
            return None
        gps = pose.get("gps") if isinstance(pose.get("gps"), dict) else {}
        lat = pose.get("latitude", pose.get("lat", gps.get("lat", gps.get("latitude"))))
        lon = pose.get("longitude", pose.get("lon", pose.get("lng", gps.get("lon", gps.get("lng", gps.get("longitude"))))))
        heading = pose.get("heading_deg", pose.get("heading", gps.get("heading", 0.0)))
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            heading_f = float(heading) % 360.0
        except (TypeError, ValueError):
            return None
        return lat_f, lon_f, heading_f

    @classmethod
    def _origin_from_plan(cls, plan: Dict[str, Any]) -> Tuple[float, float]:
        coords = []
        coords.extend(cls._boundary_ring(plan.get("map") or {}))
        for ring in cls._zone_rings(plan):
            coords.extend(ring)
        for segment in plan.get("sequence") or []:
            coords.extend(segment.get("coordinates") or [])
        if not coords:
            return 0.0, 0.0
        return (
            sum(float(coord[1]) for coord in coords) / len(coords),
            sum(float(coord[0]) for coord in coords) / len(coords),
        )

    @classmethod
    def _zone_rings(cls, plan: Dict[str, Any]) -> List[List[List[float]]]:
        contours = [
            item.get("coordinates") or []
            for item in plan.get("exclusion_contours") or []
            if item.get("type") == "sub_buffer_boundary"
        ]
        if contours:
            return contours

        rings = []
        for item in plan.get("subs") or []:
            payload = item.get("map") if isinstance(item, dict) else None
            ring = cls._boundary_ring(payload or {})
            if ring:
                rings.append(ring)
        return rings

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
