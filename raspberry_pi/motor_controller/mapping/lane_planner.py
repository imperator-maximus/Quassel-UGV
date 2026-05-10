"""Hybrid contour/rest lane planner for mowing map previews."""

import math
from typing import Any, Dict, List

from .geometry import iter_lines, iter_polygons, lonlat_to_xy, max_turn_angle_xy, project_points, xy_ring_to_latlon
from .plan_types import MowingPlan, PlanParameters, PlanSegment
from .transition_router import TransitionRouter


class LanePlanner:
    MIN_REST_LANE_LENGTH_M = 2.0

    def __init__(
        self,
        cut_width_m: float = 0.45,
        overlap_m: float = 0.10,
        outer_margin_m: float = 0.0,
        sub_margin_m: float = 0.25,
        max_ring_turn_deg: float = 155.0,
        sub_contour_count: int = 3,
    ):
        cut_width = float(cut_width_m)
        overlap = float(overlap_m)
        spacing = cut_width - overlap
        if cut_width <= 0.0:
            raise ValueError("cut_width_m muss > 0 sein")
        if spacing <= 0.0:
            raise ValueError("cut_width_m muss größer als overlap_m sein")
        try:
            sub_contours = int(float(sub_contour_count))
        except (TypeError, ValueError):
            raise ValueError("sub_contour_count muss eine Zahl sein")
        self.parameters = PlanParameters(
            cut_width_m=cut_width,
            overlap_m=overlap,
            spacing_m=spacing,
            outer_margin_m=max(0.0, float(outer_margin_m)),
            sub_margin_m=max(0.0, float(sub_margin_m)),
            max_ring_turn_deg=max(45.0, min(179.0, float(max_ring_turn_deg))),
            sub_contour_count=max(0, min(8, sub_contours)),
        )

    def plan(
        self,
        name: str,
        main_payload: Dict[str, Any],
        main_points: List[Dict[str, float]],
        sub_payloads: List[Dict[str, Any]],
        boundary_points_reader,
    ) -> Dict[str, Any]:
        try:
            from shapely.geometry import LineString, Polygon
            from shapely.ops import unary_union
        except ImportError:
            return {"success": False, "error": "Bahnenplanung benötigt Shapely auf raspberrycan"}

        origin_lat = sum(point["latitude"] for point in main_points) / len(main_points)
        origin_lon = sum(point["longitude"] for point in main_points) / len(main_points)
        main_poly = Polygon(project_points(main_points, origin_lat, origin_lon))
        if not main_poly.is_valid:
            main_poly = main_poly.buffer(0)

        if self.parameters.outer_margin_m > 0.0:
            main_poly = main_poly.buffer(-self.parameters.outer_margin_m)
        if main_poly.is_empty:
            return {"success": False, "error": "Außenfläche ist nach outer_margin leer"}

        sub_polys = []
        for item in sub_payloads:
            points = boundary_points_reader(item["map"])
            poly = Polygon(project_points(points, origin_lat, origin_lon))
            if not poly.is_valid:
                poly = poly.buffer(0)
            if self.parameters.sub_margin_m > 0.0:
                poly = poly.buffer(self.parameters.sub_margin_m)
            if not poly.is_empty:
                sub_polys.append(poly)

        sub_union = unary_union(sub_polys) if sub_polys else None
        mow_area = main_poly.difference(sub_union) if sub_union is not None else main_poly
        if mow_area.is_empty:
            return {"success": False, "error": "Mähfläche ist nach Sub-Puffer leer"}

        plan = MowingPlan(
            name=name,
            parameters=self.parameters,
            map_payload=main_payload,
            subs=sub_payloads,
            exclusion_contours=self._exclusion_contours(sub_union, origin_lat, origin_lon),
        )

        covered_geometries = []
        current = main_poly
        while not current.is_empty and len(plan.lanes) < 500:
            accepted_in_iteration = 0
            for poly in iter_polygons(current):
                exterior_xy = list(poly.exterior.coords)
                lane_line = LineString(exterior_xy)
                lane_coverage = lane_line.buffer(self.parameters.cut_width_m / 2.0, cap_style=2, join_style=2)
                if sub_union is not None and lane_line.intersects(sub_union.buffer(self.parameters.cut_width_m / 2.0)):
                    plan.skipped_sharp_lanes += 1
                    continue
                exterior = xy_ring_to_latlon(exterior_xy, origin_lat, origin_lon)
                if len(exterior) >= 4:
                    max_turn_angle = max_turn_angle_xy(exterior_xy)
                    if max_turn_angle > self.parameters.max_ring_turn_deg:
                        plan.skipped_sharp_lanes += 1
                        continue
                    lane = PlanSegment(
                        type="contour",
                        segment_index=len(plan.sequence),
                        lane_index=len(plan.lanes),
                        coordinates=exterior,
                        length_m=round(float(poly.exterior.length), 2),
                        max_turn_angle_deg=round(max_turn_angle, 1),
                    )
                    plan.lanes.append(lane)
                    plan.sequence.append(lane)
                    covered_geometries.append(lane_coverage.intersection(mow_area))
                    accepted_in_iteration += 1
            if accepted_in_iteration == 0 and plan.lanes:
                break
            current = current.buffer(-self.parameters.spacing_m)

        covered_area = unary_union(covered_geometries) if covered_geometries else None
        rest_area = mow_area.difference(covered_area) if covered_area else mow_area
        if sub_union is not None and self.parameters.sub_contour_count > 0:
            sub_contours = self._generate_sub_contours(
                sub_union,
                mow_area,
                LineString,
                origin_lat,
                origin_lon,
            )
            for sub_contour in sub_contours:
                sub_contour.segment_index = len(plan.sequence)
                sub_contour.lane_index = len(plan.lanes)
                plan.lanes.append(sub_contour)
                plan.sequence.append(sub_contour)
                contour_xy = self._latlon_ring_to_xy(
                    sub_contour.coordinates,
                    origin_lat,
                    origin_lon,
                )
                if len(contour_xy) >= 2:
                    covered_geometries.append(
                        LineString(contour_xy)
                        .buffer(self.parameters.cut_width_m / 2.0, cap_style=2, join_style=2)
                        .intersection(mow_area)
                    )
            if sub_contours:
                covered_area = unary_union(covered_geometries) if covered_geometries else None
                rest_area = mow_area.difference(covered_area) if covered_area else mow_area
        if not rest_area.is_empty:
            plan.rest_lanes = self._generate_rest_lanes(rest_area, LineString, origin_lat, origin_lon)
            for rest_lane in plan.rest_lanes:
                rest_lane.segment_index = len(plan.sequence)
                plan.sequence.append(rest_lane)

        router = TransitionRouter(mow_area, sub_union, LineString, origin_lat, origin_lon)
        plan.transitions = router.plan_transitions(plan.sequence)
        return plan.to_dict()

    def _exclusion_contours(self, sub_union, origin_lat: float, origin_lon: float) -> List[Dict[str, Any]]:
        exclusion_contours = []
        if sub_union is None:
            return exclusion_contours
        for sub_poly in iter_polygons(sub_union):
            ring = xy_ring_to_latlon(sub_poly.exterior.coords, origin_lat, origin_lon)
            if len(ring) >= 4:
                exclusion_contours.append({
                    "type": "sub_buffer_boundary",
                    "coordinates": ring,
                    "length_m": round(float(sub_poly.exterior.length), 2),
                })
        return exclusion_contours

    def _generate_sub_contours(self, sub_union, mow_area, line_string_cls, origin_lat: float, origin_lon: float) -> List[PlanSegment]:
        sub_contours: List[PlanSegment] = []
        if sub_union is None or sub_union.is_empty:
            return sub_contours

        spacing = self.parameters.spacing_m
        cut_half = self.parameters.cut_width_m / 2.0
        allowed_area = mow_area.buffer(0.02)
        protected = sub_union.buffer(cut_half)
        for sub_poly in iter_polygons(sub_union):
            for offset_index in range(self.parameters.sub_contour_count):
                offset_m = cut_half + 0.03 + offset_index * spacing
                route_poly = sub_poly.buffer(offset_m)
                if route_poly.is_empty:
                    continue
                ring_xy = list(route_poly.exterior.coords)
                if len(ring_xy) < 4:
                    continue
                line = line_string_cls(ring_xy)
                if line.length < self.MIN_REST_LANE_LENGTH_M:
                    continue
                if line.intersects(protected) or not allowed_area.covers(line):
                    continue
                max_turn_angle = max_turn_angle_xy(ring_xy)
                if max_turn_angle > self.parameters.max_ring_turn_deg:
                    continue
                sub_contours.append(PlanSegment(
                    type="sub_contour",
                    coordinates=xy_ring_to_latlon(ring_xy, origin_lat, origin_lon),
                    length_m=round(float(line.length), 2),
                    max_turn_angle_deg=round(max_turn_angle, 1),
                ))
        return sub_contours

    def _generate_rest_lanes(self, rest_area, line_string_cls, origin_lat: float, origin_lon: float) -> List[PlanSegment]:
        spacing = self.parameters.spacing_m
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
            for line in iter_lines(clipped):
                if line.length < spacing * 0.6:
                    continue
                if line.length < self.MIN_REST_LANE_LENGTH_M:
                    continue
                candidates.append({
                    "coords_xy": list(line.coords),
                    "length_m": float(line.length),
                    "y": y,
                })
            y += spacing

        ordered = self._order_rest_lane_candidates(candidates, scan_area, line_string_cls)
        rest_lanes: List[PlanSegment] = []
        for rest_index, item in enumerate(ordered):
            direction = "forward" if rest_index % 2 == 0 else "reverse"
            rest_lanes.append(PlanSegment(
                type="rest_lane",
                rest_index=rest_index,
                rest_group=item["group"],
                direction=direction,
                coordinates=xy_ring_to_latlon(item["coords_xy"], origin_lat, origin_lon),
                length_m=round(item["length_m"], 2),
            ))
        return rest_lanes

    @staticmethod
    def _latlon_ring_to_xy(ring: List[List[float]], origin_lat: float, origin_lon: float):
        return [lonlat_to_xy(coord, origin_lat, origin_lon) for coord in ring]

    def _order_rest_lane_candidates(self, candidates, rest_area, line_string_cls):
        spacing = self.parameters.spacing_m
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
