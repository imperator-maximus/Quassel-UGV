"""Online-Kalibrierung des IMU-Heading-Offsets gegen Dual-GNSS-Heading.

Der Estimator beobachtet bei gültigem GPS-Heading laufend die Differenz zum
IMU-Yaw und mittelt sie zirkulär. Bei GPS-Ausfall liefert er den gelernten
Offset, sodass das IMU-Heading als sinnvoller Fallback genutzt werden kann.

State lebt ausschließlich im Speicher; keine Persistenz zwischen Reboots.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from typing import Deque, Optional, Tuple

_ALLOWED_RTK_STATUSES_DEFAULT = ('RTK FIXED', 'RTK FLOAT')


def _normalize_deg(value: float) -> float:
    normalized = value % 360.0
    if normalized < 0:
        normalized += 360.0
    return normalized


def _shortest_angular_diff_deg(a: float, b: float) -> float:
    """Liefert die kürzeste signierte Winkeldifferenz a-b in (-180, 180]."""
    diff = (a - b + 540.0) % 360.0 - 180.0
    return diff


class ImuHeadingOffsetEstimator:
    """Schätzt offset = corrected_gps_heading - imu_heading zirkulär."""

    def __init__(
        self,
        window_size: int = 60,
        min_samples: int = 10,
        max_heading_rate_dps: float = 5.0,
        allowed_rtk_statuses: Tuple[str, ...] = _ALLOWED_RTK_STATUSES_DEFAULT,
    ) -> None:
        self._window_size = max(1, int(window_size))
        self._min_samples = max(1, int(min_samples))
        self._max_heading_rate_dps = float(max_heading_rate_dps)
        self._allowed_rtk_statuses = tuple(s.upper() for s in allowed_rtk_statuses)
        self._samples: Deque[Tuple[float, float]] = deque(maxlen=self._window_size)
        self._last_gps_heading: Optional[float] = None
        self._last_timestamp: Optional[float] = None
        self._last_reject_reason: Optional[str] = None
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._last_gps_heading = None
            self._last_timestamp = None
            self._last_reject_reason = None

    def update(
        self,
        corrected_gps_heading_deg: Optional[float],
        imu_heading_deg: Optional[float],
        rtk_status: Optional[str],
        timestamp: float,
    ) -> bool:
        """Versucht ein Sample aufzunehmen. Liefert True bei Annahme."""
        with self._lock:
            if corrected_gps_heading_deg is None or imu_heading_deg is None:
                self._last_reject_reason = 'missing_input'
                return False

            status = (rtk_status or '').upper()
            if self._allowed_rtk_statuses and status not in self._allowed_rtk_statuses:
                self._last_reject_reason = f'rtk_status:{status or "unknown"}'
                return False

            if self._last_gps_heading is not None and self._last_timestamp is not None:
                dt = timestamp - self._last_timestamp
                if dt > 0.0:
                    rate = abs(_shortest_angular_diff_deg(
                        corrected_gps_heading_deg, self._last_gps_heading
                    )) / dt
                    if rate > self._max_heading_rate_dps:
                        self._last_gps_heading = corrected_gps_heading_deg
                        self._last_timestamp = timestamp
                        self._last_reject_reason = f'heading_rate:{rate:.2f}'
                        return False

            offset_deg = _normalize_deg(corrected_gps_heading_deg - imu_heading_deg)
            offset_rad = math.radians(offset_deg)
            self._samples.append((math.cos(offset_rad), math.sin(offset_rad)))
            self._last_gps_heading = corrected_gps_heading_deg
            self._last_timestamp = timestamp
            self._last_reject_reason = None
            return True

    def current_offset_deg(self) -> Optional[float]:
        """Liefert den geglätteten Live-Offset oder None falls unzureichend."""
        with self._lock:
            if len(self._samples) < self._min_samples:
                return None
            cos_mean = sum(c for c, _ in self._samples) / len(self._samples)
            sin_mean = sum(s for _, s in self._samples) / len(self._samples)
            return _normalize_deg(math.degrees(math.atan2(sin_mean, cos_mean)))

    def sample_count(self) -> int:
        with self._lock:
            return len(self._samples)

    def is_ready(self) -> bool:
        with self._lock:
            return len(self._samples) >= self._min_samples

    def status(self) -> dict:
        with self._lock:
            count = len(self._samples)
            ready = count >= self._min_samples
            offset = None
            if ready:
                cos_mean = sum(c for c, _ in self._samples) / count
                sin_mean = sum(s for _, s in self._samples) / count
                offset = _normalize_deg(math.degrees(math.atan2(sin_mean, cos_mean)))
            return {
                'sample_count': count,
                'window_size': self._window_size,
                'min_samples': self._min_samples,
                'ready': ready,
                'live_offset_deg': offset,
                'last_reject_reason': self._last_reject_reason,
                'max_heading_rate_dps': self._max_heading_rate_dps,
                'allowed_rtk_statuses': list(self._allowed_rtk_statuses),
            }
