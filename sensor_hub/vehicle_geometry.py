"""Lädt und verarbeitet statische Fahrzeuggeometrie für UI/Diagnose."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


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