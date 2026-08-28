"""Statische Fahrzeuggeometrie: Heading-Offset und Hebelarm der Antenne.

Uebernommen vom SensorHub (``sensor_hub/vehicle_geometry.py``). Die
IMU-Zweige sind entfallen - mit dem Mast ist auch die IMU ausgebaut, und ein
Rueckfall auf einen nicht vorhandenen Sensor waere toter Code an genau der
Stelle, an der man ihn spaeter faelschlich fuer eine Absicherung haelt.

Zwei Groessen entscheiden hier ueber die Fahrspur:

``heading_offset_deg``
    Der Winkel zwischen der Antennen-Baseline und der Fahrzeug-Vorwaertsachse.
    Die Baseline liegt quer, deshalb 90 Grad. Ein falscher Wert meldet sich
    nicht als Fehler, sondern als gleichbleibender Zug zur Seite.

Hebelarm der Primaerantenne
    Die Antenne sitzt nicht in der Fahrzeugmitte, sondern rund einen halben
    Meter dahinter und ein Stueck rechts davon. Ohne die Umrechnung faehrt die
    Navigation die Antenne auf die Bahn statt das Fahrzeug.
"""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

METERS_PER_DEG_LAT = 111320.0


def normalize_heading_deg(value: float) -> float:
    """Normalisiert einen Heading-Wert auf [0, 360)."""
    normalized = value % 360.0
    if normalized < 0:
        normalized += 360.0
    return normalized


def load_vehicle_geometry(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Laedt die Fahrzeuggeometrie aus einer JSON-Datei."""
    geometry_path = (
        Path(path) if path is not None
        else Path(__file__).with_name('vehicle_geometry.json')
    )
    return json.loads(geometry_path.read_text(encoding='utf-8'))


def gnss_heading_offset_deg(geometry: Optional[Dict[str, Any]]) -> float:
    """Liest den Baseline-Offset aus der Geometrie."""
    gnss_cfg = (geometry or {}).get('gnss', {}) or {}
    try:
        return float(gnss_cfg.get('heading_offset_deg', 0.0))
    except (TypeError, ValueError):
        return 0.0


def resolve_heading(
    raw_heading_deg: Optional[float],
    heading_offset_deg: float = 0.0,
) -> Dict[str, Any]:
    """Rechnet das rohe Dual-GNSS-Heading in den Fahrzeugkurs um.

    ``raw_heading_deg`` ist ``None``, wenn der Empfaenger keine
    Heading-Loesung geliefert hat. Dann gibt es keinen Kurs - und ausdruecklich
    keinen Vorgabewert. Auf dem SensorHub stand an dieser Stelle 0.0 als
    Ersatzwert, den der Baseline-Offset in einen Kurs von 90 Grad verwandelt
    haette; aufgefangen wurde das nur durch die IMU, die es nicht mehr gibt.
    Die Navigation uebernimmt jeden Heading-Wert ungeprueft, deshalb darf hier
    nichts entstehen, was nicht gemessen wurde.
    """
    if raw_heading_deg is None:
        return {'heading_deg': None, 'heading_source': 'unknown'}
    try:
        raw = float(raw_heading_deg)
    except (TypeError, ValueError):
        return {'heading_deg': None, 'heading_source': 'unknown'}
    return {
        'heading_deg': normalize_heading_deg(raw + heading_offset_deg),
        'heading_source': 'dual_gnss',
        'heading_raw_deg': raw,
        'heading_offset_deg': heading_offset_deg,
    }


def build_local_footprint(geometry: Dict[str, Any]) -> List[Dict[str, float]]:
    """Rechteckiger Fahrzeug-Footprint relativ zum Fahrzeugzentrum."""
    dimensions = geometry.get('dimensions_m', {})
    half_length = float(dimensions.get('length', 0.0)) / 2.0
    half_width = float(dimensions.get('width', 0.0)) / 2.0
    return [
        {'x': half_length, 'y': -half_width},
        {'x': half_length, 'y': half_width},
        {'x': -half_length, 'y': half_width},
        {'x': -half_length, 'y': -half_width},
    ]


def _anchor_point(anchor: str, half_length: float, half_width: float) -> Dict[str, float]:
    anchors = {
        'rear_left': {'x': -half_length + 0.08, 'y': -half_width + 0.08},
        'rear_right': {'x': -half_length + 0.08, 'y': half_width - 0.08},
        'front_left': {'x': half_length - 0.08, 'y': -half_width + 0.08},
        'front_right': {'x': half_length - 0.08, 'y': half_width - 0.08},
        'center': {'x': 0.0, 'y': 0.0},
    }
    return anchors.get(anchor, anchors['center'])


def resolve_visual_marker_local(geometry: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, float]:
    """Leitet eine lokale Markerposition in Metern ab (x vorwaerts, y rechts)."""
    dimensions = geometry.get('dimensions_m', {})
    half_length = float(dimensions.get('length', 0.0)) / 2.0
    half_width = float(dimensions.get('width', 0.0)) / 2.0
    anchor = _anchor_point(item.get('visual_anchor', 'center'), half_length, half_width)
    mount_position = str(item.get('mount_position', ''))

    x = anchor['x']
    y = anchor['y']

    rear_inset = item.get('rear_inset_m')
    if rear_inset is not None:
        x = -half_length + float(rear_inset)
    elif 'rear' in mount_position:
        x = -half_length + 0.08
    elif 'front' in mount_position:
        x = half_length - 0.08

    side_inset = item.get('side_inset_m')
    if side_inset is not None:
        inset = float(side_inset)
        if 'left' in mount_position or item.get('visual_anchor') == 'rear_left':
            y = -(half_width - inset)
        elif 'right' in mount_position or item.get('visual_anchor') == 'rear_right':
            y = half_width - inset

    return {
        'x': round(x, 3),
        'y': round(y, 3),
        'z': round(float(item.get('height_m', 0.0)), 3),
    }


def build_visual_markers_local(geometry: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Markerpositionen fuer die schematische Fahrzeugdarstellung."""
    markers: Dict[str, Dict[str, Any]] = {}
    sensors = geometry.get('sensors') or {}
    for key in ('gps_primary', 'gps_secondary'):
        item = sensors.get(key)
        if not item:
            continue
        markers[key] = {
            'label': item.get('label', key),
            'point_local_m': resolve_visual_marker_local(geometry, item),
        }
    return markers


def gps_primary_offset_m(geometry: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Hebelarm der Primaerantenne im Fahrzeug-Frame in Metern.

    Rueckgabe ``(x_vorwaerts, y_rechts)`` relativ zum Fahrzeugzentrum,
    ``None`` bei unvollstaendiger Geometrie.
    """
    if not geometry:
        return None
    primary = (geometry.get('sensors') or {}).get('gps_primary')
    if not primary:
        return None
    try:
        local = resolve_visual_marker_local(geometry, primary)
    except (TypeError, ValueError):
        return None
    x = local.get('x')
    y = local.get('y')
    if x is None or y is None:
        return None
    return float(x), float(y)


def correct_to_vehicle_center(
    antenna_latitude: float,
    antenna_longitude: float,
    heading_deg: Optional[float],
    geometry: Optional[Dict[str, Any]],
) -> Tuple[float, float]:
    """Rechnet die Antennenposition auf den Fahrzeugmittelpunkt um.

    Ohne gueltiges Heading oder vollstaendige Geometrie bleibt die Eingabe
    unveraendert - eine Drehung des Hebelarms braucht den Kurs.

    Konvention (``reference_frame`` in vehicle_geometry.json):
        Fahrzeug-x = vorwaerts, Fahrzeug-y = rechts,
        Heading in Kompassgrad (0 = Nord, im Uhrzeigersinn).
    """
    if heading_deg is None or geometry is None:
        return antenna_latitude, antenna_longitude

    offset = gps_primary_offset_m(geometry)
    if offset is None:
        return antenna_latitude, antenna_longitude

    ant_x_v, ant_y_v = offset
    if abs(ant_x_v) < 1e-9 and abs(ant_y_v) < 1e-9:
        return antenna_latitude, antenna_longitude

    try:
        heading_rad = math.radians(float(heading_deg))
        lat_f = float(antenna_latitude)
        lon_f = float(antenna_longitude)
    except (TypeError, ValueError):
        return antenna_latitude, antenna_longitude

    cos_h = math.cos(heading_rad)
    sin_h = math.sin(heading_rad)
    delta_north_m = ant_x_v * cos_h - ant_y_v * sin_h
    delta_east_m = ant_x_v * sin_h + ant_y_v * cos_h

    meters_per_deg_lon = METERS_PER_DEG_LAT * math.cos(math.radians(lat_f))
    if meters_per_deg_lon < 1.0:
        return antenna_latitude, antenna_longitude

    center_lat = lat_f - delta_north_m / METERS_PER_DEG_LAT
    center_lon = lon_f - delta_east_m / meters_per_deg_lon
    return center_lat, center_lon
