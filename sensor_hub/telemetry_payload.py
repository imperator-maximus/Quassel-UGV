"""Hilfsfunktionen für kompakte Sensor-Hub Telemetrie- und Status-Payloads."""

import json
import time
from typing import Any, Dict, Optional


def round_if_number(value: Any, digits: int) -> Any:
    """Rundet numerische Werte, lässt andere Typen unverändert."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(value, digits)
    return value


def build_telemetry_payload(
    gps_status: Optional[Dict[str, Any]] = None,
    orientation: Optional[Dict[str, Any]] = None,
    imu_data: Optional[Dict[str, Any]] = None,
    *,
    timestamp: Optional[float] = None,
    heading_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Erstellt eine kompakte CAN-Telemetrie-Payload.

    Das Top-Level-Feld ``heading`` ist die Heading, die der Motor-Controller für
    die Navigation verwendet. Wenn ``heading_info`` (z.B. von
    :func:`vehicle_geometry.select_heading_for_visualization`) übergeben wird,
    übernimmt diese Heading inklusive Offset-Korrektur Vorrang. Andernfalls
    wird die GPS-Dual-Antenna-Heading bevorzugt; nur wenn diese fehlt
    (Heading=0 oder kein GPS), wird auf die IMU-Yaw zurückgegriffen.
    """
    payload: Dict[str, Any] = {
        'timestamp': round_if_number(time.time() if timestamp is None else timestamp, 3)
    }

    gps_heading_raw: Optional[float] = None
    if gps_status:
        payload['gps'] = {
            'lat': round_if_number(gps_status.get('latitude', 0.0), 7),
            'lon': round_if_number(gps_status.get('longitude', 0.0), 7),
            'altitude': round_if_number(gps_status.get('altitude', 0.0), 2),
        }
        payload['rtk_status'] = gps_status.get('rtk_status', 'NO GPS')
        try:
            gps_heading_raw = float(gps_status.get('heading', 0.0))
        except (TypeError, ValueError):
            gps_heading_raw = None
        payload['gps']['heading'] = round_if_number(gps_heading_raw or 0.0, 2)

    imu_heading_raw: Optional[float] = None
    if imu_data and orientation:
        try:
            imu_heading_raw = float(orientation.get('heading', 0.0))
        except (TypeError, ValueError):
            imu_heading_raw = None
        payload['imu'] = {
            'roll': round_if_number(orientation.get('roll', 0.0), 2),
            'pitch': round_if_number(orientation.get('pitch', 0.0), 2),
            'yaw': round_if_number(orientation.get('yaw', 0.0), 2),
            'heading': round_if_number(imu_heading_raw or 0.0, 2),
            'is_calibrated': imu_data.get('is_calibrated', False),
        }

    if heading_info and 'heading_deg' in heading_info:
        payload['heading'] = round_if_number(heading_info.get('heading_deg', 0.0), 2)
        source = heading_info.get('heading_source')
        if source:
            payload['heading_source'] = source
    elif gps_heading_raw is not None and abs(gps_heading_raw) > 0.01:
        payload['heading'] = round_if_number(gps_heading_raw, 2)
        payload['heading_source'] = 'dual_gnss'
    elif imu_heading_raw is not None:
        payload['heading'] = round_if_number(imu_heading_raw, 2)
        payload['heading_source'] = 'imu_fallback'
    elif gps_heading_raw is not None:
        payload['heading'] = round_if_number(gps_heading_raw, 2)
        payload['heading_source'] = 'dual_gnss'

    return payload


def build_status_payload(telemetry: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    """Erweitert Telemetrie um Status-Metadaten für On-Demand-Abfragen."""
    payload = dict(telemetry)
    payload['meta'] = meta
    return payload


def serialize_can_payload(payload: Dict[str, Any]) -> str:
    """Serialisiert eine Payload kompakt für den CAN-Transport."""
    return json.dumps(payload, separators=(',', ':'))