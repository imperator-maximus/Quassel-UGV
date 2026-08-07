"""Geometry and projection helpers for map analysis and lane planning."""

import math
from typing import Dict, List, Tuple


Point = Dict[str, float]
XY = Tuple[float, float]


def distance_m(a: Point, b: Point) -> float:
    lat1 = math.radians(a["latitude"])
    lat2 = math.radians(b["latitude"])
    d_lat = lat2 - lat1
    d_lon = math.radians(b["longitude"] - a["longitude"])
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 6371000.0 * 2.0 * math.atan2(math.sqrt(h), math.sqrt(1.0 - h))


def project_points(points: List[Point], origin_lat: float, origin_lon: float) -> List[XY]:
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


def lonlat_to_xy(coord: List[float], origin_lat: float, origin_lon: float) -> XY:
    lat0 = math.radians(origin_lat)
    meters_per_degree_lat = 111320.0
    meters_per_degree_lon = 111320.0 * math.cos(lat0)
    return (
        (float(coord[0]) - origin_lon) * meters_per_degree_lon,
        (float(coord[1]) - origin_lat) * meters_per_degree_lat,
    )


def xy_ring_to_latlon(ring, origin_lat: float, origin_lon: float) -> List[List[float]]:
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


def shoelace_area(points: List[XY]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        total += point[0] * nxt[1] - nxt[0] * point[1]
    return abs(total) / 2.0


def signed_area_xy(ring) -> float:
    """Shoelace area with sign: positive counter-clockwise, negative clockwise."""
    points = list(ring[:-1]) if len(ring) > 1 and tuple(ring[0]) == tuple(ring[-1]) else list(ring)
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        total += point[0] * nxt[1] - nxt[0] * point[1]
    return total / 2.0


def orient_ring_xy(ring, clockwise: bool = True):
    """Force a consistent traversal sense on a closed ring.

    Contour rings come from two sources: the recorded outer boundary keeps
    whatever order it was walked in, while the inner rings come out of
    successive buffer operations. Both senses therefore occur in one plan,
    and the vehicle then arrives at the end of one ring facing away from the
    start of the next - real, 02.08.: -156° demanded on a 0.39 m transfer,
    which no skid-steer turns on the spot. The traversal sense itself is
    irrelevant for mowing, only its consistency matters.
    """
    coords = list(ring)
    if len(coords) < 4:
        return coords
    area = signed_area_xy(coords)
    if area == 0.0:
        return coords
    is_clockwise = area < 0.0
    if is_clockwise == clockwise:
        return coords
    closed = tuple(coords[0]) == tuple(coords[-1])
    flipped = list(reversed(coords[:-1] if closed else coords))
    if closed:
        flipped.append(flipped[0])
    return flipped


def iter_polygons(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    return []


def iter_lines(geometry):
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


def vector_angle_deg(a: XY, b: XY) -> float:
    a_len = math.hypot(a[0], a[1])
    b_len = math.hypot(b[0], b[1])
    if a_len <= 0.0 or b_len <= 0.0:
        return 180.0
    cos_value = max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / (a_len * b_len)))
    return math.degrees(math.acos(cos_value))


def max_turn_angle_xy(ring) -> float:
    open_ring = list(ring[:-1]) if len(ring) > 1 and ring[0] == ring[-1] else list(ring)
    if len(open_ring) < 3:
        return 0.0
    max_angle = 0.0
    for index, point in enumerate(open_ring):
        prev_point = open_ring[index - 1]
        next_point = open_ring[(index + 1) % len(open_ring)]
        angle = vector_angle_deg(
            (point[0] - prev_point[0], point[1] - prev_point[1]),
            (next_point[0] - point[0], next_point[1] - point[1]),
        )
        max_angle = max(max_angle, angle)
    return max_angle


def max_curvature_deg_per_m(ring) -> float:
    """Schärfste Richtungsänderung je Meter entlang eines Streckenzugs.

    Das ist das Maß, an dem ein Skid-Steer scheitert - nicht der Knickwinkel
    allein. Real gemessen am 02.08.: das Fahrzeug schafft rollend rund
    10-15°/m; die Bahn verlangte an der Stelle, an der es aus der Spur lief,
    17,6°/m (26,7° auf 1,51 m). Ein ebenso großer Knick auf 5 m wäre
    problemlos gewesen.
    """
    points = list(ring[:-1]) if len(ring) > 1 and tuple(ring[0]) == tuple(ring[-1]) else list(ring)
    if len(points) < 3:
        return 0.0
    worst = 0.0
    for index in range(len(points)):
        previous = points[index - 1]
        point = points[index]
        following = points[(index + 1) % len(points)]
        edge = math.hypot(following[0] - point[0], following[1] - point[1])
        if edge < 0.05:
            continue
        turn = vector_angle_deg(
            (point[0] - previous[0], point[1] - previous[1]),
            (following[0] - point[0], following[1] - point[1]),
        )
        worst = max(worst, turn / edge)
    return worst


def polyline_length_xy(coords) -> float:
    total = 0.0
    for index in range(len(coords) - 1):
        a = coords[index]
        b = coords[index + 1]
        total += math.hypot(b[0] - a[0], b[1] - a[1])
    return total


def polyline_length_lonlat(coords: List[List[float]]) -> float:
    if len(coords) < 2:
        return 0.0
    total = 0.0
    for index in range(len(coords) - 1):
        a = {"longitude": coords[index][0], "latitude": coords[index][1]}
        b = {"longitude": coords[index + 1][0], "latitude": coords[index + 1][1]}
        total += distance_m(a, b)
    return total


def lonlat_distance_sq(a: List[float], b: List[float]) -> float:
    return (float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2
