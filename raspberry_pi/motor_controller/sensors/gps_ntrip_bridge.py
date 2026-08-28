"""Verbindet den GNSS-Empfaenger mit dem NTRIP-Caster.

Die Bruecke haelt einen eigenen Ueberwachungsthread. Er tut drei Dinge:
RTCM-Korrekturen in den Empfaenger schieben, die Roverposition als GGA an die
VRS melden, und einen stehenden Datenstrom erkennen, bevor er zur eingefrorenen
Position fuehrt.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional

from .gps_handler import GPSHandler
from .ntrip_client import NTRIPClient

logger = logging.getLogger(__name__)


class GPSNTRIPBridge:
    """Speist RTK-Korrekturen in den Empfaenger und ueberwacht den Strom."""

    def __init__(self, gps: GPSHandler, ntrip: NTRIPClient,
                 gga_interval_s: float = 10.0,
                 monitor_interval_s: float = 1.0):
        self.gps = gps
        self.ntrip = ntrip
        self.gga_interval_s = float(gga_interval_s)
        self.monitor_interval_s = float(monitor_interval_s)

        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None

        self.rtk_fix_count = 0
        self.rtk_float_count = 0
        self.gps_fix_count = 0
        self.last_rtk_status = 'NO GPS'
        self._rtk_fix_since: Optional[float] = None
        self.rtk_uptime_s = 0.0

        self._last_gga_send = 0.0
        # Nach jedem Verbindungsaufbau muss die GGA sofort raus, nicht erst
        # beim naechsten Intervall. Eine VRS ohne Roverposition schickt nichts,
        # der Wachhund traennt nach zehn Sekunden wieder, und der Client haengt
        # in einer Schleife aus Verbinden und Aufgeben.
        self._gga_due = True
        self._gga_sent = 0
        self._rtcm_bytes_to_receiver = 0

        self._lock = threading.Lock()

    def start(self) -> bool:
        """Startet die Bruecke. Ein fehlgeschlagener Erstversuch ist kein Fehler."""
        logger.info("Starte GPS-NTRIP-Bruecke")
        self.ntrip.on_data_received = self._on_ntrip_data
        self.ntrip.on_connected = self._on_ntrip_connected
        self.ntrip.enable()

        connected = self.ntrip.connect()

        # Ueberwachungsthread erst nach dem ersten Versuch starten, damit
        # connect() und reconnect_if_needed() nicht parallel auf denselben
        # Socket losgehen.
        self.running = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop, name='ntrip-monitor', daemon=True
        )
        self.monitor_thread.start()

        if connected:
            logger.info("GPS-NTRIP-Bruecke laeuft - NTRIP verbunden")
        else:
            logger.warning(
                "NTRIP zunaechst nicht erreichbar - die Bruecke versucht es weiter. "
                "Bis dahin bleibt der Empfaenger ohne Korrekturen auf GPS FIX."
            )
        return True

    def stop(self):
        """Beendet Ueberwachung und NTRIP-Verbindung."""
        self.running = False
        thread = self.monitor_thread
        if thread is not None:
            thread.join(timeout=self.monitor_interval_s + 1.0)
        self.ntrip.disconnect()
        logger.info("GPS-NTRIP-Bruecke gestoppt")

    def _on_ntrip_connected(self):
        """Nach dem Verbindungsaufbau die Roverposition sofort nachreichen."""
        with self._lock:
            self._gga_due = True

    def _on_ntrip_data(self, data: bytes):
        """Schiebt empfangenes RTCM in den Empfaenger."""
        if self.gps.write_data(data):
            with self._lock:
                self._rtcm_bytes_to_receiver += len(data)

    def _monitor_loop(self):
        while self.running:
            try:
                # Reihenfolge zaehlt: erst den stehenden Strom erkennen, dann
                # neu verbinden. So erledigt derselbe Durchlauf beides.
                self.ntrip.check_stalled_stream()
                self.ntrip.reconnect_if_needed()

                status = self.gps.get_status()
                current = status['rtk_status']
                if current != self.last_rtk_status:
                    self._on_rtk_status_changed(self.last_rtk_status, current)
                    self.last_rtk_status = current

                if current == 'RTK FIXED':
                    if self._rtk_fix_since is None:
                        self._rtk_fix_since = time.monotonic()
                    self.rtk_uptime_s = time.monotonic() - self._rtk_fix_since
                else:
                    self._rtk_fix_since = None
                    self.rtk_uptime_s = 0.0

                self._send_gga_if_due()

            except Exception as exc:
                logger.warning("Fehler in der NTRIP-Ueberwachung: %s", exc)

            time.sleep(self.monitor_interval_s)

    def _send_gga_if_due(self):
        """Meldet die Roverposition an die VRS, wenn es an der Zeit ist."""
        if not self.ntrip.is_connected():
            return
        now = time.monotonic()
        with self._lock:
            due = self._gga_due or (now - self._last_gga_send) > self.gga_interval_s
        if not due:
            return

        raw_gga = self.gps.get_last_raw_gga()
        if not raw_gga:
            # Kein gueltiger Satz: entweder ist der Empfaenger gerade erst
            # gestartet oder er sieht den Himmel nicht. ``_gga_due`` bleibt
            # stehen, damit der naechste Durchlauf es sofort erneut versucht.
            return

        if self.ntrip.send_gga(raw_gga):
            with self._lock:
                self._last_gga_send = now
                self._gga_due = False
                self._gga_sent += 1

    def _on_rtk_status_changed(self, old_status: str, new_status: str):
        logger.info("RTK-Status: %s -> %s", old_status, new_status)
        if new_status == 'RTK FIXED':
            self.rtk_fix_count += 1
        elif new_status == 'RTK FLOAT':
            self.rtk_float_count += 1
        elif new_status == 'GPS FIX':
            self.gps_fix_count += 1

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            gga_sent = self._gga_sent
            rtcm_bytes = self._rtcm_bytes_to_receiver
        return {
            'gps': self.gps.get_status(),
            'ntrip': self.ntrip.get_status(),
            'rtk_fix_count': self.rtk_fix_count,
            'rtk_float_count': self.rtk_float_count,
            'gps_fix_count': self.gps_fix_count,
            'rtk_uptime_s': round(self.rtk_uptime_s, 1),
            'current_rtk_status': self.last_rtk_status,
            'gga_sent': gga_sent,
            'rtcm_bytes_to_receiver': rtcm_bytes,
        }
