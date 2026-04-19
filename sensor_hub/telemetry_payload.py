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
) -> Dict[str, Any]:
    """Erstellt eine kompakte CAN-Telemetrie-Payload."""
    payload: Dict[str, Any] = {
        'timestamp': round_if_number(time.time() if timestamp is None else timestamp, 3)
    }

    if gps_status:
        payload['gps'] = {
            'lat': round_if_number(gps_status.get('latitude', 0.0), 7),
            'lon': round_if_number(gps_status.get('longitude', 0.0), 7),
            'altitude': round_if_number(gps_status.get('altitude', 0.0), 2),
        }
        payload['rtk_status'] = gps_status.get('rtk_status', 'NO GPS')
        payload['heading'] = round_if_number(gps_status.get('heading', 0.0), 2)

    if imu_data and orientation:
        payload['imu'] = {
            'roll': round_if_number(orientation.get('roll', 0.0), 2),
            'pitch': round_if_number(orientation.get('pitch', 0.0), 2),
            'yaw': round_if_number(orientation.get('yaw', 0.0), 2),
            'heading': round_if_number(orientation.get('heading', 0.0), 2),
            'is_calibrated': imu_data.get('is_calibrated', False),
        }
        payload['heading'] = round_if_number(orientation.get('heading', payload.get('heading', 0.0)), 2)

    return payload


def build_status_payload(telemetry: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    """Erweitert Telemetrie um Status-Metadaten für On-Demand-Abfragen."""
    payload = dict(telemetry)
    payload['meta'] = meta
    return payload


def serialize_can_payload(payload: Dict[str, Any]) -> str:
    """Serialisiert eine Payload kompakt für den CAN-Transport."""
    return json.dumps(payload, separators=(',', ':'))