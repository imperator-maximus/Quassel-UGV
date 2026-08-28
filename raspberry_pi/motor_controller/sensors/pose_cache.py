#!/usr/bin/env python3
"""Zwischenspeicher fuer die zuletzt gemeldete Fahrzeugpose.

Diesen Zwischenspeicher hielt frueher der CAN-Handler nebenbei: die Pose kam
vom SensorHub ueber den Bus, und wer sie brauchte - Navigation, Kartierung,
Safety, Weboberflaeche - fragte dort nach. Seit der GNSS-Empfaenger direkt am
Raspberry haengt, gibt es weder Bus noch SensorHub mehr, wohl aber dieselben
Leser. Sie fragen jetzt hier.

Der Speicher kennt die Quelle nicht, die ihn fuellt. Er haelt nur den letzten
Datensatz und den Zeitpunkt, zu dem er eintraf. Genau daraus entsteht das
Alter, an dem die Fahrpause haengt: Bleibt die Quelle stumm, altert die Pose
von selbst, und der Watchdog greift - ohne dass die Quelle ihren Ausfall
selbst melden muesste.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional


class PoseCache:
    """Thread-sicherer Halter der letzten Pose samt Altersauskunft."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {}
        self._last_seen_monotonic = 0.0

        self.pose_callback: Optional[Callable] = None
        self.source_status_callback: Optional[Callable] = None

    def set_pose_callback(self, callback: Callable) -> None:
        """Setzt den Listener, der jede frische Pose bekommt."""
        self.pose_callback = callback

    def set_source_status_callback(self, callback: Callable) -> None:
        """Registriert den Detailstatus der speisenden Quelle."""
        self.source_status_callback = callback

    def inject_sensor_data(self, data: Dict[str, Any]) -> None:
        """Nimmt eine frische Pose auf und weckt den Listener."""
        if not isinstance(data, dict):
            raise TypeError("Pose muss ein Dictionary sein")

        now = time.monotonic()
        with self._lock:
            self._data = dict(data)
            self._last_seen_monotonic = now

        if self.pose_callback:
            try:
                self.pose_callback(data)
            except Exception as e:
                self.logger.error(f"❌ Pose-Callback Fehler: {e}")

    def get_sensor_data(self) -> Dict[str, Any]:
        """Gibt die zuletzt gemeldete Pose zurueck (Kopie)."""
        with self._lock:
            return self._data.copy()

    def get_status(self, pose_timeout_s: float = 2.0) -> Dict[str, Any]:
        """Meldet Alter und Erreichbarkeit der Pose.

        Args:
            pose_timeout_s: Ab diesem Alter gilt die Pose als weg. Die
                Aufrufer setzen hier bewusst verschiedene Werte ein: die
                Fahrpause eine knappe, der Sicherheitsstopp eine lange.
        """
        now = time.monotonic()
        with self._lock:
            last_seen = self._last_seen_monotonic

        age = None if last_seen <= 0.0 else max(0.0, now - last_seen)
        source_status = None
        if self.source_status_callback:
            try:
                source_status = self.source_status_callback()
            except Exception as exc:
                source_status = {'online': False, 'last_error': str(exc)}

        return {
            'online': age is not None and age <= float(pose_timeout_s),
            'age_s': None if age is None else round(age, 2),
            'source': source_status,
        }
