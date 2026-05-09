"""Lädt und verarbeitet statische Fahrzeuggeometrie für UI/Diagnose."""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


METERS_PER_DEG_LAT = 111320.0


def _normalize_heading_deg(value: float) -> float:
    """Normalisiert einen Heading-Wert auf das Intervall [0, 360)."""
    normalized = value % 360.0
    if normalized < 0:
        normalized += 360.0
    return normalized


def select_heading_for_visualization(
    gps_status: Optional[Dict[str, Any]] = None,
    orientation: Optional[Dict[str, Any]] = None,
    gps_heading_offset_deg: float = 0.0,
    imu_heading_offset_deg: float = 0.0,
    imu_offset_source: str = 'none',
) -> Dict[str, Any]:
    """Wählt eine sinnvolle Heading-Quelle für UI/Visualisierung.

    Aktuell gilt:
    - GPS/Dual-GNSS nur verwenden, wenn ein nicht-triviales Heading vorliegt.
    - Sonst auf IMU-Heading zurückfallen, optional mit gelerntem oder statischem
      Offset, der den IMU-Yaw an die GPS-Referenz angleicht.
    - Falls beides nicht brauchbar ist, 0.0 zurückgeben.

    ``gps_heading_offset_deg`` kompensiert den Winkel zwischen Antennen-Baseline
    und Fahrzeug-Vorwärtsachse. ``imu_heading_offset_deg`` kompensiert den Yaw
    zwischen IMU-Mount/Magnetometer und der Fahrzeug-Vorwärtsachse. Beide
    Ergebnisse werden auf [0, 360) normalisiert. ``imu_offset_source`` gibt an,
    woher der IMU-Offset stammt: 'live' (online kalibriert), 'static'
    (vehicle_geometry.json) oder 'none' (kein Offset bekannt).
    """
    gps_heading = None
    if gps_status is not None:
        try:
            gps_heading = float(gps_status.get('heading', 0.0))
        except (TypeError, ValueError):
            gps_heading = None

    imu_heading = None
    imu_source = 'imu'
    if orientation is not None:
        try:
            imu_heading = float(orientation.get('heading', 0.0))
            imu_source = orientation.get('source', 'imu')
        except (TypeError, ValueError):
            imu_heading = None

    if gps_heading is not None and abs(gps_heading) > 0.01:
        corrected = _normalize_heading_deg(gps_heading + gps_heading_offset_deg)
        return {
            'heading_deg': corrected,
            'heading_source': 'dual_gnss',
            'heading_raw_deg': gps_heading,
            'heading_offset_deg': gps_heading_offset_deg,
        }

    if imu_heading is not None:
        return _build_imu_fallback(
            imu_heading=imu_heading,
            imu_source=imu_source,
            gps_status=gps_status,
            imu_heading_offset_deg=imu_heading_offset_deg,
            imu_offset_source=imu_offset_source,
        )

    if gps_heading is not None:
        corrected = _normalize_heading_deg(gps_heading + gps_heading_offset_deg)
        return {
            'heading_deg': corrected,
            'heading_source': 'dual_gnss',
            'heading_raw_deg': gps_heading,
            'heading_offset_deg': gps_heading_offset_deg,
        }

    return {'heading_deg': 0.0, 'heading_source': 'unknown'}


def _build_imu_fallback(
    imu_heading: float,
    imu_source: str,
    gps_status: Optional[Dict[str, Any]],
    imu_heading_offset_deg: float,
    imu_offset_source: str,
) -> Dict[str, Any]:
    """Erstellt das Fallback-Ergebnis basierend auf IMU + Offset."""
    offset_source = (imu_offset_source or 'none').lower()
    has_offset = offset_source in ('live', 'static') and abs(imu_heading_offset_deg) > 1e-6

    if has_offset:
        corrected = _normalize_heading_deg(imu_heading + imu_heading_offset_deg)
        if offset_source == 'live':
            label = 'imu_calibrated_fallback'
        else:
            label = 'imu_static_fallback'
        return {
            'heading_deg': corrected,
            'heading_source': label,
            'heading_raw_deg': imu_heading,
            'imu_heading_offset_deg': imu_heading_offset_deg,
            'imu_offset_source': offset_source,
        }

    base_source = imu_source if gps_status is None else f'{imu_source}_fallback'
    return {
        'heading_deg': _normalize_heading_deg(imu_heading),
        'heading_source': base_source,
        'imu_offset_source': 'none',
    }


def load_vehicle_geometry(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Lädt die Fahrzeuggeometrie aus einer JSON-Datei."""
    geometry_path = Path(path) if path is not None else Path(__file__).with_name('vehicle_geometry.json')
    return json.loads(geometry_path.read_text(encoding='utf-8'))


def build_local_footprint(geometry: Dict[str, Any]) -> List[Dict[str, float]]:
    """Erstellt den rechteckigen Fahrzeug-Footprint relativ zum Fahrzeugzentrum."""
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
    """Leitet eine schematische lokale Markerposition in Meter ab."""
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
        'z': round(float(item.get('height_m', item.get('top_height_m', 0.0))), 3),
    }


def build_visual_markers_local(geometry: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Erstellt Markerpositionen für schematische Fahrzeugdarstellung."""
    markers: Dict[str, Dict[str, Any]] = {}
    entries = {
        'mast': geometry.get('mast'),
        'gps_primary': (geometry.get('sensors') or {}).get('gps_primary'),
        'gps_secondary': (geometry.get('sensors') or {}).get('gps_secondary'),
        'imu': (geometry.get('sensors') or {}).get('imu'),
    }
    for key, item in entries.items():
        if not item:
            continue
        markers[key] = {
            'label': item.get('label', key),
            'point_local_m': resolve_visual_marker_local(geometry, item),
        }
    return markers


def gps_primary_offset_m(geometry: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Liefert den Hebelarm der GPS-Primärantenne im Fahrzeug-Frame in Metern.

    Rückgabe ``(x_forward, y_right)`` relativ zum Fahrzeugzentrum. ``None``
    wenn die Geometrie unvollständig ist.
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
    """Wandelt die Position der GPS-Primärantenne in den Fahrzeugmittelpunkt um.

    Wendet den dokumentierten Hebelarm der Primärantenne auf die gemeldete
    GPS-Position an und gibt die korrigierte Lat/Lon zurück. Ohne gültiges
    Heading oder vollständige Geometrie wird die Eingabe unverändert
    zurückgegeben.

    Konvention (vehicle_geometry.json reference_frame):
        - Fahrzeug-x = vorwärts, Fahrzeug-y = rechts
        - Heading in Kompassgrad (0° = Nord, im Uhrzeigersinn).
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
