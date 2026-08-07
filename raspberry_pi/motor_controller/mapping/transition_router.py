"""Transition safety checks and routing between mowing plan segments."""

import heapq
import math
from typing import List

from .geometry import (
    iter_polygons,
    lonlat_to_xy,
    polyline_length_lonlat,
    polyline_length_xy,
    xy_ring_to_latlon,
)
from .plan_types import PlanSegment, TransitionSegment


class TransitionRouter:
    VEHICLE_LENGTH_M = 1.15
    VEHICLE_WIDTH_M = 0.79
    NOGO_INTRUSION_TOLERANCE_M = 0.35
    ROUTE_CLEARANCE_M = 0.05

    def __init__(self, mow_area, sub_union, line_string_cls, origin_lat: float, origin_lon: float):
        self.mow_area = mow_area
        self.sub_union = sub_union
        self.line_string_cls = line_string_cls
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.blocked_union = self.blocked_for_vehicle(sub_union)

    @classmethod
    def blocked_for_vehicle(cls, sub_union):
        """Conservative center-path obstacle matching the runtime footprint stop.

        The live monitor stops when any corner of the 1.15 x 0.79 m vehicle
        reaches the exclusion polygon reduced by the 35 cm intrusion tolerance.
        Buffering that stop polygon by the vehicle half diagonal makes transition
        checks heading-independent and prevents a centerline-only false positive.
        """
        if sub_union is None or sub_union.is_empty:
            return None
        stop_zone = sub_union.buffer(-cls.NOGO_INTRUSION_TOLERANCE_M)
        if stop_zone.is_empty:
            return None
        half_diagonal = math.hypot(
            cls.VEHICLE_LENGTH_M / 2.0,
            cls.VEHICLE_WIDTH_M / 2.0,
        )
        return stop_zone.buffer(half_diagonal)

    def _intersects_blocked(self, geometry) -> bool:
        return bool(
            self.blocked_union is not None
            and not self.blocked_union.is_empty
            and geometry.intersects(self.blocked_union)
        )

    def plan_transitions(self, sequence: List[PlanSegment]) -> List[TransitionSegment]:
        transitions: List[TransitionSegment] = []
        if len(sequence) < 2:
            return transitions
        for index in range(len(sequence) - 1):
            current = sequence[index]
            nxt = sequence[index + 1]
            current_coords = current.coordinates or []
            next_coords = nxt.coordinates or []
            if not current_coords or not next_coords:
                continue
            transitions.append(self.plan_between(
                current_coords[-1],
                next_coords[0],
                transition_index=len(transitions),
                from_segment_index=current.segment_index if current.segment_index is not None else index,
                to_segment_index=nxt.segment_index if nxt.segment_index is not None else index + 1,
                from_type=current.type,
                to_type=nxt.type,
            ))
        return transitions

    def plan_between(
        self,
        start: List[float],
        end: List[float],
        *,
        transition_index: int = 0,
        from_segment_index: int = -1,
        to_segment_index: int = -1,
        from_type: str = "unknown",
        to_type: str = "unknown",
        confine_to_mow_area: bool = True,
    ) -> TransitionSegment:
        """Route one transition between the final, execution-time endpoints.

        Planning-time ring start vertices are not stable: the executor rotates
        closed contours to the nearest reachable point.  This method is shared
        by the planner and executor so a transition is always checked against
        the endpoints that will actually be driven.

        ``confine_to_mow_area`` may be switched off for the approach from the
        parking spot to the first lane, which legitimately starts outside the
        mapped area. Obstacle checks against the sub zones and the vehicle
        clearance still apply; only the outer boundary is not enforced,
        because nothing is mapped out there to check against.
        """
        allowed_area = self.mow_area.buffer(0.02)
        start_xy = lonlat_to_xy(start, self.origin_lat, self.origin_lon)
        end_xy = lonlat_to_xy(end, self.origin_lat, self.origin_lon)
        line = self.line_string_cls([start_xy, end_xy])
        line_length = polyline_length_lonlat([start, end])
        crosses_sub = bool(
            self.sub_union is not None
            and not self.sub_union.is_empty
            and line.intersects(self.sub_union)
        )
        crosses_vehicle_block = self._intersects_blocked(line)
        within_mow_area = allowed_area.covers(line) if confine_to_mow_area else True
        safe = within_mow_area and not crosses_sub and not crosses_vehicle_block
        route_coords_xy = [start_xy, end_xy]
        route_kind = "direct"
        if not safe and self.sub_union is not None and not self.sub_union.is_empty:
            routed = self.route_around_sub(start_xy, end_xy, confine=confine_to_mow_area)
            if routed:
                route_coords_xy = routed
                routed_line = self.line_string_cls(route_coords_xy)
                safe = (
                    (allowed_area.covers(routed_line) if confine_to_mow_area else True)
                    and not routed_line.intersects(self.sub_union)
                    and not self._intersects_blocked(routed_line)
                )
                route_kind = "around_sub" if safe else "failed"
                line_length = polyline_length_xy(route_coords_xy)
        if not safe and confine_to_mow_area and not within_mow_area:
            # Die gerade Verbindung schneidet über den Rand. Auf einer nicht
            # konvexen Fläche ist das für jeden längeren Wechsel der Normalfall
            # - zwei Bahnenden auf gegenüberliegenden Seiten einer sechseckigen
            # Wiese liegen 33 m auseinander, und die Sehne dazwischen läuft
            # außen herum. Innen am Rand entlang ist derselbe Wechsel fahrbar;
            # dieselbe Wegsuche wie um eine Sperrzone, nur mit dem Rand als
            # Stützpunktring (real, 02.08.).
            routed = self.route_inside_boundary(start_xy, end_xy)
            if routed:
                routed_line = self.line_string_cls(routed)
                inside_safe = (
                    allowed_area.covers(routed_line)
                    and not (
                        self.sub_union is not None
                        and not self.sub_union.is_empty
                        and routed_line.intersects(self.sub_union)
                    )
                    and not self._intersects_blocked(routed_line)
                )
                if inside_safe:
                    route_coords_xy = routed
                    route_kind = "inside_boundary"
                    line_length = polyline_length_xy(route_coords_xy)
                    safe = True
        return TransitionSegment(
            type="transition",
            transition_index=transition_index,
            from_segment_index=from_segment_index,
            to_segment_index=to_segment_index,
            from_type=from_type,
            to_type=to_type,
            safe=safe,
            reason=(
                "ok" if safe
                else "vehicle_footprint" if crosses_vehicle_block
                else "sub_zone" if crosses_sub
                else "outside_mow_area"
            ),
            route_kind=route_kind,
            coordinates=xy_ring_to_latlon(route_coords_xy, self.origin_lat, self.origin_lon),
            length_m=round(line_length, 2),
        )

    def is_polyline_safe(self, coords, confine_to_mow_area: bool = True) -> bool:
        """Prüft einen fertigen Streckenzug mit denselben Kriterien wie plan_between.

        Wird für Pfade gebraucht, die nicht der Router selbst erzeugt hat -
        etwa den eingelenkten Anfahrbogen. Ein solcher Pfad darf nie ohne
        dieselbe Prüfung gefahren werden wie eine gerade Verbindung.
        """
        if len(coords) < 2:
            return True
        xy = [lonlat_to_xy(coord, self.origin_lat, self.origin_lon) for coord in coords]
        line = self.line_string_cls(xy)
        if self.sub_union is not None and not self.sub_union.is_empty and line.intersects(self.sub_union):
            return False
        if self._intersects_blocked(line):
            return False
        if confine_to_mow_area and not self.mow_area.buffer(0.02).covers(line):
            return False
        return True

    def route_inside_boundary(self, start_xy, end_xy):
        """Weg von A nach B, der die Mähfläche nicht verlässt.

        Stützpunkte sind der um die Fahrzeugfreiheit eingezogene Rand; die
        Wegsuche selbst ist dieselbe wie beim Umfahren einer Sperrzone.
        """
        allowed = self.mow_area.buffer(0.02)
        inner = self.mow_area.buffer(-self.ROUTE_CLEARANCE_M)
        nodes = [start_xy, end_xy]
        ring_nodes = []
        for poly in iter_polygons(inner):
            raw_ring = list(poly.exterior.coords)
            open_ring = raw_ring[:-1] if raw_ring and raw_ring[0] == raw_ring[-1] else raw_ring
            if len(open_ring) < 4:
                continue
            step = max(1, len(open_ring) // 60)
            ring_nodes.extend(open_ring[::step])
        if not ring_nodes:
            return None
        return self.shortest_ring_route(nodes + ring_nodes, allowed)

    def route_around_sub(self, start_xy, end_xy, confine: bool = True):
        best_route = None
        best_length = float("inf")
        allowed = self.mow_area.buffer(0.05) if confine else None
        route_obstacles = (
            self.blocked_union
            if self.blocked_union is not None and not self.blocked_union.is_empty
            else self.sub_union
        )
        for sub_poly in iter_polygons(route_obstacles):
            route_poly = sub_poly.buffer(self.ROUTE_CLEARANCE_M)
            if route_poly.is_empty:
                continue
            raw_ring = list(route_poly.exterior.coords)
            open_ring = raw_ring[:-1] if raw_ring and raw_ring[0] == raw_ring[-1] else raw_ring
            if len(open_ring) < 4:
                continue
            step = max(1, len(open_ring) // 40)
            nodes = [start_xy, end_xy] + open_ring[::step]
            route = self.shortest_ring_route(nodes, allowed)
            if route:
                length = polyline_length_xy(route)
                if length < best_length:
                    best_length = length
                    best_route = route
        return best_route

    def shortest_ring_route(self, nodes, allowed_area):
        graph = [[] for _ in nodes]
        edge_pairs = [(0, 1)]
        ring_indices = list(range(2, len(nodes)))
        for node in ring_indices:
            edge_pairs.append((0, node))
            edge_pairs.append((1, node))
        for offset, node in enumerate(ring_indices):
            nxt = ring_indices[(offset + 1) % len(ring_indices)]
            edge_pairs.append((node, nxt))
        # Ohne Sperrzonen ist sub_union None. Der Aufruf kam bisher nur aus
        # route_around_sub und damit nie ohne, seit dem Randrouting schon.
        has_subs = self.sub_union is not None and not self.sub_union.is_empty
        for i, j in edge_pairs:
            edge = self.line_string_cls([nodes[i], nodes[j]])
            if (
                (has_subs and edge.intersects(self.sub_union))
                or self._intersects_blocked(edge)
                or (allowed_area is not None and not allowed_area.covers(edge))
            ):
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
