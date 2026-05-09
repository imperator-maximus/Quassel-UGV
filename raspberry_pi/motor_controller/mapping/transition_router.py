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
    def __init__(self, mow_area, sub_union, line_string_cls, origin_lat: float, origin_lon: float):
        self.mow_area = mow_area
        self.sub_union = sub_union
        self.line_string_cls = line_string_cls
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon

    def plan_transitions(self, sequence: List[PlanSegment]) -> List[TransitionSegment]:
        transitions: List[TransitionSegment] = []
        if len(sequence) < 2:
            return transitions
        allowed_area = self.mow_area.buffer(0.02)
        for index in range(len(sequence) - 1):
            current = sequence[index]
            nxt = sequence[index + 1]
            current_coords = current.coordinates or []
            next_coords = nxt.coordinates or []
            if not current_coords or not next_coords:
                continue
            start = current_coords[-1]
            end = next_coords[0]
            start_xy = lonlat_to_xy(start, self.origin_lat, self.origin_lon)
            end_xy = lonlat_to_xy(end, self.origin_lat, self.origin_lon)
            line = self.line_string_cls([start_xy, end_xy])
            line_length = polyline_length_lonlat([start, end])
            crosses_sub = bool(self.sub_union and line.intersects(self.sub_union))
            within_mow_area = allowed_area.covers(line)
            safe = within_mow_area and not crosses_sub
            route_coords_xy = [start_xy, end_xy]
            route_kind = "direct"
            if not safe and self.sub_union is not None:
                routed = self.route_around_sub(start_xy, end_xy)
                if routed:
                    route_coords_xy = routed
                    routed_line = self.line_string_cls(route_coords_xy)
                    safe = allowed_area.covers(routed_line) and not routed_line.intersects(self.sub_union)
                    route_kind = "around_sub" if safe else "failed"
                    line_length = polyline_length_xy(route_coords_xy)
            transitions.append(TransitionSegment(
                type="transition",
                transition_index=len(transitions),
                from_segment_index=current.segment_index if current.segment_index is not None else index,
                to_segment_index=nxt.segment_index if nxt.segment_index is not None else index + 1,
                from_type=current.type,
                to_type=nxt.type,
                safe=safe,
                reason="ok" if safe else ("sub_zone" if crosses_sub else "outside_mow_area"),
                route_kind=route_kind,
                coordinates=xy_ring_to_latlon(route_coords_xy, self.origin_lat, self.origin_lon),
                length_m=round(line_length, 2),
            ))
        return transitions

    def route_around_sub(self, start_xy, end_xy):
        best_route = None
        best_length = float("inf")
        allowed = self.mow_area.buffer(0.05)
        for sub_poly in iter_polygons(self.sub_union):
            route_poly = sub_poly.buffer(0.15)
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
        for i, j in edge_pairs:
            edge = self.line_string_cls([nodes[i], nodes[j]])
            if edge.intersects(self.sub_union) or not allowed_area.covers(edge):
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
