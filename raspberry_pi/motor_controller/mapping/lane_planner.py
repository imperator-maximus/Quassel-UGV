"""Hybrid contour/rest lane planner for mowing map previews."""

import math
from typing import Any, Dict, List

from .geometry import (
    iter_lines,
    iter_polygons,
    lonlat_to_xy,
    max_curvature_deg_per_m,
    max_turn_angle_xy,
    orient_ring_xy,
    project_points,
    xy_ring_to_latlon,
)
from .plan_types import MowingPlan, PlanParameters, PlanSegment
from .transition_router import TransitionRouter


class LanePlanner:
    # Eine Bahn muss mehr Mähstrecke bringen, als ihre Anfahrt kostet. Ein
    # 3 m langer Stummel am Flächenende zog real einen 33 m langen Wechsel
    # quer über die Wiese nach sich, für den es keine fahrbare Einfahrt gab -
    # der Plan war deswegen an dieser einen Stelle gesperrt (06.08.). Mit 5 m
    # bleiben rund 3 m Gras in einer Ecke stehen und der Plan läuft durch.
    MIN_REST_LANE_LENGTH_M = 5.0

    def __init__(
        self,
        cut_width_m: float = 0.45,
        overlap_m: float = 0.10,
        outer_margin_m: float = 0.0,
        sub_margin_m: float = 0.25,
        max_ring_turn_deg: float = 155.0,
        sub_contour_count: int = 3,
        rest_pattern: str = "parallel",
        max_lane_curvature_deg_per_m: float = 20.0,
    ):
        cut_width = float(cut_width_m)
        overlap = float(overlap_m)
        spacing = cut_width - overlap
        pattern = str(rest_pattern or "parallel").strip().lower()
        if pattern not in ("parallel", "serpentine"):
            raise ValueError("rest_pattern muss parallel oder serpentine sein")
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
            rest_pattern=pattern,
            max_lane_curvature_deg_per_m=max(
                5.0, min(90.0, float(max_lane_curvature_deg_per_m))
            ),
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
        vehicle_blocked = TransitionRouter.blocked_for_vehicle(sub_union)

        plan = MowingPlan(
            name=name,
            parameters=self.parameters,
            map_payload=main_payload,
            subs=sub_payloads,
            exclusion_contours=self._exclusion_contours(sub_union, origin_lat, origin_lon),
        )

        if self.parameters.rest_pattern == "serpentine":
            # Slanted passes converge at the turning end, where the local
            # spacing doubles. Below this the pattern leaves wedge-shaped
            # strips uncut - measured on a real 815 m2 area: 0.7 % uncut at
            # cut 0.85 / spacing 0.35, but 14.4 % at cut 0.45 / spacing 0.35.
            if 2.0 * self.parameters.spacing_m > self.parameters.cut_width_m:
                plan.warnings.append(
                    "Serpentine: Bahnabstand %.2f m ist zu groß für Schnittbreite %.2f m "
                    "(nötig: 2×Abstand ≤ Schnittbreite). An den Wendepunkten bleiben "
                    "Streifen stehen." % (self.parameters.spacing_m, self.parameters.cut_width_m)
                )

        covered_geometries = []
        current = main_poly
        while not current.is_empty and len(plan.lanes) < 500:
            accepted_in_iteration = 0
            for poly in iter_polygons(current):
                exterior_xy = orient_ring_xy(list(poly.exterior.coords), clockwise=True)
                lane_line = LineString(exterior_xy)
                lane_coverage = lane_line.buffer(self.parameters.cut_width_m / 2.0, cap_style=2, join_style=2)
                protected = (
                    vehicle_blocked
                    if vehicle_blocked is not None and not vehicle_blocked.is_empty
                    else (
                        sub_union.buffer(self.parameters.cut_width_m / 2.0)
                        if sub_union is not None else None
                    )
                )
                if protected is not None and lane_line.intersects(protected):
                    plan.skipped_sharp_lanes += 1
                    continue
                exterior = xy_ring_to_latlon(exterior_xy, origin_lat, origin_lon)
                if len(exterior) >= 4:
                    max_turn_angle = max_turn_angle_xy(exterior_xy)
                    if max_turn_angle > self.parameters.max_ring_turn_deg:
                        plan.skipped_sharp_lanes += 1
                        continue
                    # Konturringe werden nach innen zwangsläufig enger. Sobald
                    # einer die Wendefähigkeit des Fahrzeugs übersteigt, wird
                    # er nicht mehr als Ring gefahren - die Fläche fällt dann
                    # an die geraden Bahnen, die diese Krümmung gar nicht erst
                    # haben. Ohne diese Grenze enthielt die Wiese Ringe mit
                    # bis zu 818°/m; das Fahrzeug lief dort aus der Spur
                    # (real, 02.08.).
                    curvature = max_curvature_deg_per_m(exterior_xy)
                    if curvature > self.parameters.max_lane_curvature_deg_per_m:
                        plan.skipped_curved_lanes += 1
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
        if vehicle_blocked is not None and not vehicle_blocked.is_empty:
            rest_area = rest_area.difference(vehicle_blocked)
        if not rest_area.is_empty:
            # Der zuerst aufgezeichnete Randpunkt ist der Startpunkt der
            # Karte - dort soll auch der Plan beginnen.
            anchor_xy = project_points(main_points[:1], origin_lat, origin_lon)[0]
            plan.rest_lanes = self._generate_rest_lanes(
                rest_area, LineString, origin_lat, origin_lon, anchor_xy,
                self._lane_angle_deg(project_points(main_points, origin_lat, origin_lon)),
            )
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
        allowed_area = mow_area.buffer(0.02)
        vehicle_blocked = TransitionRouter.blocked_for_vehicle(sub_union)
        protected = vehicle_blocked if vehicle_blocked is not None else sub_union
        for sub_poly in iter_polygons(protected):
            for offset_index in range(self.parameters.sub_contour_count):
                offset_m = 0.05 + offset_index * spacing
                route_poly = sub_poly.buffer(offset_m)
                if route_poly.is_empty:
                    continue
                ring_xy = orient_ring_xy(list(route_poly.exterior.coords), clockwise=True)
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

    def _scan_rows(self, scan_area, line_string_cls, spacing: float):
        """Clip horizontal scanlines, one row per lane spacing.

        Returns one list of ``(x_start, x_end, y)`` spans per row, in order.
        A row can hold several spans where an exclusion splits the area.
        """
        min_x, min_y, max_x, max_y = scan_area.bounds
        rows = []
        y = min_y + spacing / 2.0
        while y <= max_y and len(rows) < 1000:
            clipped = scan_area.intersection(
                line_string_cls([(min_x - spacing, y), (max_x + spacing, y)])
            )
            spans = []
            for line in iter_lines(clipped):
                xs = [float(coord[0]) for coord in line.coords]
                start, end = min(xs), max(xs)
                if end - start >= spacing * 0.6:
                    spans.append((start, end, y))
            spans.sort()
            rows.append(spans)
            y += spacing
        return rows

    def _chain_rows(self, rows, spacing: float):
        """Group row spans into strips that lie above one another.

        Consecutive rows belong to the same strip only where their spans
        actually overlap in x, so an exclusion that splits the area also
        splits the strip instead of joining across it.
        """
        chains = []
        open_chains = []
        for spans in rows:
            next_open = []
            for span in spans:
                best = None
                best_overlap = spacing * 0.5
                for chain in open_chains:
                    last = chain[-1]
                    overlap = min(last[1], span[1]) - max(last[0], span[0])
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best = chain
                if best is not None and best not in next_open:
                    best.append(span)
                    next_open.append(best)
                else:
                    chain = [span]
                    chains.append(chain)
                    next_open.append(chain)
            open_chains = next_open
        return chains

    def _serpentine_passes(self, chains, allowed, line_string_cls, spacing: float):
        """Turn each strip into slanted passes that meet end to end.

        A skid-steer cannot translate sideways, so the classic pattern of
        parallel lanes plus a short perpendicular connector is unreachable
        for it: the connector demands a 60-90 degree turn for half a metre
        and the same turn straight back (real, 26.07.). Slanting each pass
        so it finishes where the next one starts removes those connectors
        completely - the body only yaws by twice the slant angle, roughly 5
        degrees over an 8 m pass, and simply alternates forward/reverse.

        The price is that two consecutive passes converge at the turning
        end, where the local spacing doubles. Full coverage therefore needs
        ``2 * spacing <= cut_width``; ``plan()`` checks it and warns.
        """
        passes = []
        group = 0
        for chain in chains:
            index = 0
            while index < len(chain):
                use_left_start = True
                emitted = False
                while index + 1 < len(chain):
                    lower, upper = chain[index], chain[index + 1]
                    # Anchor the slant on the x-range both rows share. Using
                    # each row's own outer end instead lets the line poke out
                    # of the area wherever the strip narrows, which used to
                    # abort the run and restart it at the opposite end - one
                    # 16-19 m jump straight across the area per abort, 64 of
                    # them on the real map (26.07.). The cut width covers the
                    # little that is trimmed off the ends.
                    left = max(lower[0], upper[0])
                    right = min(lower[1], upper[1])
                    if right - left < spacing:
                        break
                    if use_left_start:
                        start, end = (left, lower[2]), (right, upper[2])
                    else:
                        start, end = (right, lower[2]), (left, upper[2])
                    if not allowed.covers(line_string_cls([start, end])):
                        # The slant would leave the mowing area. End the run
                        # here and start a fresh one on the next row instead
                        # of carrying on from the wrong end - continuing would
                        # silently break the end-to-end property this whole
                        # pattern exists for, and every later pass in the
                        # chain would then need a large turn.
                        break
                    passes.append({"coords_xy": [start, end], "group": group})
                    use_left_start = not use_left_start
                    emitted = True
                    index += 1
                if not emitted:
                    start, end, y = chain[index]
                    passes.append({"coords_xy": [(start, y), (end, y)], "group": group})
                index += 1
                group += 1
        return passes

    def _generate_rest_lanes(
        self,
        rest_area,
        line_string_cls,
        origin_lat: float,
        origin_lon: float,
        anchor_xy=None,
        lane_angle_deg: float = 0.0,
    ) -> List[PlanSegment]:
        spacing = self.parameters.spacing_m
        if rest_area.is_empty or spacing <= 0.0:
            return []
        scan_area = rest_area.buffer(-min(0.08, spacing * 0.25))
        if scan_area.is_empty:
            scan_area = rest_area
        mirrored = False
        # Die gesamte Abtastung arbeitet mit waagerechten Zeilen. Statt sie
        # umzuschreiben, wird die Fläche in ein Bezugssystem gedreht, in dem
        # die gewünschte Bahnrichtung waagerecht liegt - und die fertigen
        # Bahnen am Ende zurückgedreht.
        if abs(lane_angle_deg) > 1e-9:
            from shapely import affinity

            scan_area = affinity.rotate(scan_area, -lane_angle_deg, origin=(0.0, 0.0))
            if anchor_xy is not None:
                anchor_xy = self._rotate_xy(anchor_xy, -lane_angle_deg)
                # Die Abtastung läuft immer von der unteren Kante des
                # gedrehten Rahmens nach oben - also quer über die Fläche in
                # einer festen Richtung. Liegt der Startpunkt auf der anderen
                # Seite, wird der Rahmen um 180 Grad gedreht: dieselben
                # Bahnen, aber abgearbeitet von dort, wo die Aufzeichnung
                # begonnen hat. Ohne das begann der Plan 13,2 m neben dem
                # Startpunkt auf der Gegenseite (real, 02.08.).
                min_y, max_y = scan_area.bounds[1], scan_area.bounds[3]
                if anchor_xy[1] > (min_y + max_y) / 2.0:
                    lane_angle_deg += 180.0
                    scan_area = affinity.rotate(scan_area, 180.0, origin=(0.0, 0.0))
                    anchor_xy = self._rotate_xy(anchor_xy, 180.0)
                # Und innerhalb der Bahnen beginnt jeder Lauf am linken Ende
                # des Rahmens. Liegt der Startpunkt am rechten, wird die
                # Fläche gespiegelt statt die einzelnen Bahnen umzudrehen -
                # letzteres würde die Kette zerreißen, auf der das
                # Serpentinenmuster beruht.
                min_x, max_x = scan_area.bounds[0], scan_area.bounds[2]
                if anchor_xy[0] > (min_x + max_x) / 2.0:
                    mirrored = True
                    scan_area = affinity.scale(scan_area, xfact=-1.0, yfact=1.0, origin=(0.0, 0.0))
                    anchor_xy = (-anchor_xy[0], anchor_xy[1])

        def to_latlon(coords_xy):
            if mirrored:
                coords_xy = [(-point[0], point[1]) for point in coords_xy]
            if abs(lane_angle_deg) > 1e-9:
                coords_xy = [self._rotate_xy(point, lane_angle_deg) for point in coords_xy]
            return xy_ring_to_latlon(coords_xy, origin_lat, origin_lon)
        if self.parameters.rest_pattern == "serpentine":
            rows = self._scan_rows(scan_area, line_string_cls, spacing)
            chains = self._chain_rows(rows, spacing)
            allowed = scan_area.buffer(min(0.18, spacing * 0.55))
            passes = self._serpentine_passes(chains, allowed, line_string_cls, spacing)
            # MIN_REST_LANE_LENGTH_M rejects pointless stand-alone lanes. A
            # serpentine pass is never stand-alone: it is one link of a run
            # that has to stay unbroken, and near a sub-zone the links get
            # short. Dropping one there removes the very connection the
            # pattern is built on and forces a large turn on both
            # neighbours, so the minimum is applied per run instead.
            run_length = {}
            for item in passes:
                coords_xy = item["coords_xy"]
                item["length_m"] = math.hypot(
                    coords_xy[-1][0] - coords_xy[0][0],
                    coords_xy[-1][1] - coords_xy[0][1],
                )
                run_length[item["group"]] = run_length.get(item["group"], 0.0) + item["length_m"]
            kept = [
                item for item in passes
                if run_length[item["group"]] >= self.MIN_REST_LANE_LENGTH_M
            ]
            kept = self._anchored_order(kept, anchor_xy)
            rest_lanes: List[PlanSegment] = []
            for item in kept:
                rest_lanes.append(PlanSegment(
                    type="rest_lane",
                    rest_index=len(rest_lanes),
                    rest_group=item["group"],
                    direction="forward" if len(rest_lanes) % 2 == 0 else "reverse",
                    coordinates=to_latlon(item["coords_xy"]),
                    length_m=round(item["length_m"], 2),
                ))
            return rest_lanes
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

        ordered = self._order_rest_lane_candidates(
            candidates, scan_area, line_string_cls, anchor_xy
        )
        rest_lanes: List[PlanSegment] = []
        for rest_index, item in enumerate(ordered):
            direction = "forward" if rest_index % 2 == 0 else "reverse"
            rest_lanes.append(PlanSegment(
                type="rest_lane",
                rest_index=rest_index,
                rest_group=item["group"],
                direction=direction,
                coordinates=to_latlon(item["coords_xy"]),
                length_m=round(item["length_m"], 2),
            ))
        return rest_lanes

    @staticmethod
    def _lane_angle_deg(points_xy) -> float:
        """Bahnrichtung aus der längsten Kante des aufgezeichneten Randes.

        Die Abtastung lief bisher fest waagerecht, also Ost-West, unabhängig
        von der Form der Fläche. Auf einer 30 x 49 m langen Wiese standen die
        Bahnen damit quer zur langen Achse - und quer zu der Richtung, aus
        der das Fahrzeug überhaupt hereinfahren kann, weil links und rechts
        Hecken stehen. Entlang der längsten Randkante werden die Bahnen
        länger, es sind weniger, und die Einfahrt liegt in Bahnrichtung.
        """
        best_length = 0.0
        best_angle = 0.0
        for start, end in zip(points_xy, points_xy[1:]):
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = math.hypot(dx, dy)
            if length > best_length:
                best_length = length
                best_angle = math.degrees(math.atan2(dy, dx))
        return best_angle % 180.0

    @staticmethod
    def _rotate_xy(point, angle_deg: float):
        angle = math.radians(angle_deg)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        return (
            point[0] * cos_a - point[1] * sin_a,
            point[0] * sin_a + point[1] * cos_a,
        )

    @staticmethod
    def _anchored_order(passes, anchor_xy):
        """Serpentine am zuerst erfassten Kartenpunkt beginnen lassen.

        Die Abtastung wandert monoton über die Fläche und begänne deshalb an
        deren Rand - auf der Wiese an einer kurzen Eckbahn, während die 50 m
        langen Bahnen genau am Startpunkt enden. Eine Kette lässt sich von
        jeder Stelle aus in beide Richtungen abfahren: erst die eine Hälfte ab
        dem Startpunkt, dann die andere.

        Der Wechsel zwischen den Hälften verlangt einen Spurwechsel, den der
        Regler als Knick ablehnt (real, 06.08.: 72,9° auf 5,92 m, der Mäher
        blieb nach der ersten Hälfte stehen). Den fährt das Eindrehmanöver in
        _turn_in_transfer. Ohne den Schnitt ist die Reihenfolge messbar
        schlechter: 49 statt 1 gesperrtes Segment über den ganzen Plan.
        """
        if anchor_xy is None or len(passes) < 2:
            return passes

        def distance(point):
            return math.hypot(point[0] - anchor_xy[0], point[1] - anchor_xy[1])

        def reversed_pass(item):
            return {**item, "coords_xy": list(reversed(item["coords_xy"]))}

        best_index, at_start, best = 0, True, float("inf")
        for index, item in enumerate(passes):
            for is_start, point in ((True, item["coords_xy"][0]), (False, item["coords_xy"][-1])):
                if distance(point) < best:
                    best = distance(point)
                    best_index, at_start = index, is_start

        if at_start:
            ordered = list(passes[best_index:])
            ordered += [reversed_pass(item) for item in reversed(passes[:best_index])]
        else:
            ordered = [reversed_pass(item) for item in reversed(passes[:best_index + 1])]
            ordered += list(passes[best_index + 1:])

        # Gruppennummern bleiben aufsteigend, damit nachgelagerte Schritte die
        # zusammenhängenden Läufe weiter erkennen.
        renumber = {}
        for item in ordered:
            renumber.setdefault(item["group"], len(renumber))
            item["group"] = renumber[item["group"]]
        return ordered

    @staticmethod
    def _latlon_ring_to_xy(ring: List[List[float]], origin_lat: float, origin_lon: float):
        return [lonlat_to_xy(coord, origin_lat, origin_lon) for coord in ring]

    def _order_rest_lane_candidates(self, candidates, rest_area, line_string_cls, anchor_xy=None):
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
                        # Die erste Bahn beginnt am zuerst erfassten
                        # Kartenpunkt. Vorher gewann hart das kleinste y,
                        # also der Südrand - unabhängig davon, wo die
                        # Aufzeichnung begonnen hatte.
                        score = (
                            math.hypot(coords[0][0] - anchor_xy[0], coords[0][1] - anchor_xy[1])
                            if anchor_xy is not None
                            else coords[0][1] * 1000.0 + coords[0][0]
                        )
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
