"""Pose aus dem direkt angeschlossenen GNSS-Empfaenger.

Tritt an die Stelle des ausgebauten SensorHubs. Bis zum 28.08.2026 kam
die Pose per HTTP von dort; seit dessen Ausfall haengt der UM982 per USB
am Raspberry. Nach aussen aendert sich nichts: dieselbe Struktur landet ueber
denselben Rueckruf im selben Zwischenspeicher, damit Navigation, Regler und
Planlogik unveraendert bleiben.

Der Unterschied liegt darin, was beim Ausfall passiert. Eine HTTP-Quelle
verstummt, wenn die Gegenstelle weg ist - das Altern der Pose ergab sich von
selbst. Eine lokale Schleife laeuft weiter, auch wenn der Empfaenger schweigt.
Wuerde sie stur alle 200 ms einspeisen, waere die Pose immer frisch und das
Fahrzeug fuehre auf einer eingefrorenen Position weiter. Deshalb gilt hier:

* Eingespeist wird nur, wenn der letzte Positionsfix juenger als
  ``max_fix_age_s`` ist. Sonst schweigt diese Quelle, die Pose altert, und die
  bestehende Kette aus Fahrpause und Watchdog greift wie bei einem
  SensorHub-Ausfall.
* ``timestamp`` im Nutzdatensatz ist der Zeitpunkt der Messung, nicht der des
  Verpackens.
* Das Heading wandert nur mit, wenn es ebenfalls frisch ist. Fehlt es, bleibt
  das Feld leer: die Navigation verwirft die Pose dann still, waehrend
  Handbetrieb und Oberflaeche weiterlaufen. Ein erfundener Kurs waere
  gefaehrlicher als gar keiner.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .gps_handler import GPSHandler
from .gps_ntrip_bridge import GPSNTRIPBridge
from .ntrip_client import NTRIPClient
from .vehicle_geometry import (
    correct_to_vehicle_center,
    gnss_heading_offset_deg,
    load_vehicle_geometry,
    resolve_heading,
)


class LocalPoseSource:
    """Baut die Fahrzeugpose aus dem lokalen GNSS-Empfaenger."""

    def __init__(self, config, telemetry_callback: Callable[[Dict[str, Any]], None]):
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.telemetry_callback = telemetry_callback

        self.running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._poll_interval_s = max(0.05, float(getattr(config, 'poll_interval_s', 0.2)))
        self._max_fix_age_s = float(getattr(config, 'gps_max_fix_age_s', 2.0))
        self._max_heading_age_s = float(getattr(config, 'gps_max_heading_age_s', 2.0))

        self._geometry: Optional[Dict[str, Any]] = None
        self._heading_offset_deg = 0.0
        self._load_geometry()

        self.gps = GPSHandler(
            port=str(getattr(config, 'gps_port', '')),
            baudrate=int(getattr(config, 'gps_baudrate', 230400)),
            timeout=float(getattr(config, 'gps_read_timeout_s', 1.0)),
        )

        self.ntrip: Optional[NTRIPClient] = None
        self.bridge: Optional[GPSNTRIPBridge] = None
        if bool(getattr(config, 'ntrip_enabled', True)):
            self.ntrip = NTRIPClient(
                host=str(getattr(config, 'ntrip_host', '')),
                port=int(getattr(config, 'ntrip_port', 2101)),
                mountpoint=str(getattr(config, 'ntrip_mountpoint', '')),
                username=str(getattr(config, 'ntrip_username', '')),
                password=str(getattr(config, 'ntrip_password', '')),
                timeout=float(getattr(config, 'ntrip_timeout_s', 10.0)),
                reconnect_interval=float(getattr(config, 'ntrip_reconnect_interval_s', 15.0)),
                stale_timeout=float(getattr(config, 'ntrip_stale_timeout_s', 10.0)),
            )
            self.bridge = GPSNTRIPBridge(self.gps, self.ntrip)

        # Plausibilitaetsschranke fuer den Kurs: wie schnell er sich pro
        # Sekunde hoechstens aendern darf, plus ein Sockel fuer Messrauschen.
        # Das Fahrzeug dreht gemessen mit 2,9 Grad/s bei vollem Lenkbefehl
        # (02.08.) und im Ausrichtbogen mit 2,6 Grad/s (29,7 auf 1,3 Grad in
        # 11 s, 25.07.) - 20 Grad/s sind das Siebenfache. Alles darueber hat
        # das Fahrzeug nicht gefahren, das hat der Empfaenger erfunden.
        self._heading_jump_base_deg = max(
            5.0, float(getattr(config, 'gps_heading_jump_base_deg', 10.0))
        )
        self._heading_jump_rate_dps = max(
            5.0, float(getattr(config, 'gps_heading_jump_rate_dps', 20.0))
        )
        self._accepted_heading_deg: Optional[float] = None
        self._accepted_heading_monotonic = 0.0
        self._heading_jump_started_monotonic: Optional[float] = None

        # Zaehler fuer Oberflaeche und Fehlersuche
        self._packets_published = 0
        self._suppressed_stale_fix = 0
        self._suppressed_no_heading = 0
        self._suppressed_heading_jump = 0
        self._last_published_monotonic = 0.0
        self._last_error: Optional[str] = None
        self._last_heading_source = 'unknown'

    # ------------------------------------------------------------------
    # Geometrie
    # ------------------------------------------------------------------
    def _load_geometry(self):
        """Laedt die Fahrzeuggeometrie; ohne sie gibt es keinen Kurs."""
        configured = getattr(self.config, 'vehicle_geometry_path', '') or ''
        path = Path(configured) if configured else Path(__file__).with_name('vehicle_geometry.json')
        try:
            self._geometry = load_vehicle_geometry(path)
            self._heading_offset_deg = gnss_heading_offset_deg(self._geometry)
            self.logger.info(
                "Fahrzeuggeometrie geladen: %s (Heading-Offset %.1f Grad)",
                path, self._heading_offset_deg,
            )
        except Exception as exc:
            # Ohne Geometrie fehlen Baseline-Offset und Hebelarm. Ein
            # stillschweigender Offset von 0 waere ein um 90 Grad verdrehter
            # Kurs - das muss laut auffallen.
            self._geometry = None
            self._heading_offset_deg = 0.0
            self._last_error = f"Fahrzeuggeometrie nicht ladbar: {exc}"
            self.logger.error(
                "Fahrzeuggeometrie %s nicht ladbar: %s - ohne sie bleibt der "
                "Baseline-Offset unberuecksichtigt und der gemeldete Kurs ist falsch.",
                path, exc,
            )

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------
    def start(self):
        if self.running:
            return
        self.running = True
        self._stop_event.clear()

        self.gps.start()
        if self.bridge is not None:
            self.bridge.start()
        else:
            self.logger.warning(
                "NTRIP ist abgeschaltet - der Empfaenger bleibt ohne Korrekturen "
                "auf GPS FIX und erreicht die Genauigkeit fuer autonome Fahrt nicht."
            )

        self._thread = threading.Thread(
            target=self._publish_loop, name='local-pose', daemon=True
        )
        self._thread.start()
        self.logger.info(
            "Lokale GNSS-Pose gestartet: %s @ %d baud, Einspeisung alle %.0f ms",
            self.gps.port, self.gps.baudrate, self._poll_interval_s * 1000.0,
        )

    def stop(self):
        self.running = False
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        if self.bridge is not None:
            self.bridge.stop()
        self.gps.stop()
        self.logger.info("Lokale GNSS-Pose gestoppt")

    # ------------------------------------------------------------------
    # Einspeisung
    # ------------------------------------------------------------------
    def _publish_loop(self):
        while self.running and not self._stop_event.is_set():
            try:
                payload = self._build_payload()
                if payload is not None:
                    with self._lock:
                        self._packets_published += 1
                        self._last_published_monotonic = time.monotonic()
                    self.telemetry_callback(payload)
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                self.logger.warning("Aufbau der lokalen Pose fehlgeschlagen: %s", exc)
            self._stop_event.wait(self._poll_interval_s)

    def _build_payload(self) -> Optional[Dict[str, Any]]:
        """Baut den Nutzdatensatz - oder nichts, wenn die Position veraltet ist.

        Nichts zurueckzugeben ist hier die sichere Antwort: es laesst die Pose
        im Zwischenspeicher altern, genau wie ein ausbleibender HTTP-Abruf.
        """
        status = self.gps.get_status()

        fix_age = status.get('fix_age_s')
        if fix_age is None or fix_age > self._max_fix_age_s:
            with self._lock:
                self._suppressed_stale_fix += 1
            return None

        latitude = status.get('latitude')
        longitude = status.get('longitude')
        if latitude is None or longitude is None:
            with self._lock:
                self._suppressed_stale_fix += 1
            return None

        heading_age = status.get('heading_age_s')
        raw_heading = status.get('heading')
        heading_fresh = (
            raw_heading is not None
            and heading_age is not None
            and heading_age <= self._max_heading_age_s
        )
        heading_info = resolve_heading(
            raw_heading if heading_fresh else None,
            self._heading_offset_deg,
        )
        heading_deg = heading_info.get('heading_deg')

        if heading_deg is not None and not self._heading_plausible(heading_deg):
            # Die ganze Pose zurueckhalten, nicht nur den Kurs. Eine Pose
            # ohne Kurs gilt dem PoseCache weiter als "online" - dann laeuft
            # der Plan gegen den Navigations-Watchdog statt in die Fahrpause.
            # Bleibt die Pose ganz aus, pausiert die zentrale Safety-Logik
            # nach pose.pause_timeout_s (1 s) und setzt von selbst fort.
            # Ausserdem steckt der Kurs in der Hebelarm-Korrektur: mit einem
            # um 67 Grad falschen Kurs stuende auch die Position gut einen
            # halben Meter daneben.
            return None

        if heading_deg is None:
            with self._lock:
                self._suppressed_no_heading += 1
        else:
            # Der Hebelarm laesst sich nur mit bekanntem Kurs drehen. Ohne ihn
            # bleibt die Antennenposition stehen - rund einen halben Meter
            # hinter dem Fahrzeugmittelpunkt, aber ehrlich statt geraten.
            latitude, longitude = correct_to_vehicle_center(
                antenna_latitude=latitude,
                antenna_longitude=longitude,
                heading_deg=heading_deg,
                geometry=self._geometry,
            )

        # Zeitpunkt der Messung, nicht des Verpackens. Verbraucher, die das
        # Alter aus diesem Feld ableiten, duerfen nicht den Augenblick sehen,
        # in dem die Schleife zufaellig vorbeikam.
        measured_at = time.time() - float(fix_age)

        payload: Dict[str, Any] = {
            'timestamp': round(measured_at, 3),
            'rtk_status': status.get('rtk_status', 'NO GPS'),
            'gps': {
                'lat': round(float(latitude), 7),
                'lon': round(float(longitude), 7),
                'altitude': round(float(status.get('altitude') or 0.0), 2),
                'satellites': int(status.get('satellites') or 0),
                'heading': round(float(raw_heading), 2) if raw_heading is not None else None,
                'fix_age_s': round(float(fix_age), 3),
                'heading_age_s': None if heading_age is None else round(float(heading_age), 3),
            },
        }

        if heading_deg is not None:
            payload['heading'] = round(float(heading_deg), 2)
            payload['heading_source'] = heading_info.get('heading_source', 'dual_gnss')
            payload['heading_offset_deg'] = self._heading_offset_deg
        else:
            # Feld bewusst weglassen statt auf 0 zu setzen: die Navigation
            # verwirft eine Pose ohne Kurs, ein Nullwert waere ein Kurs.
            payload['heading_source'] = 'unknown'

        with self._lock:
            self._last_heading_source = payload['heading_source']

        return payload

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def set_voice(self, voice):
        """Reicht den Ansager an die NTRIP-Bruecke durch.

        Die Bruecke sieht den RTK-Statuswechsel als Erste; sie steckt aber
        zwei Ebenen tief und wird nicht von aussen gebaut.
        """
        bridge = getattr(self, 'bridge', None)
        if bridge is not None:
            bridge.set_voice(voice)

    def _heading_plausible(self, heading_deg: float) -> bool:
        """Verwirft Kursspruenge, die das Fahrzeug nicht gefahren haben kann.

        Der UM982 liefert beim Neuaufbau seiner Heading-Loesung kurzzeitig
        0,0 mit gueltiger Kennung; der Baseline-Offset von 90 Grad macht
        daraus einen Kurs von exakt 90,0. Real am 31.08. um 15:03: das
        Fahrzeug fuhr seine Bahn mit 0,3 Grad Fehler und 1 cm Querabstand,
        dann stand der Kurs drei Posen lang auf 90,0 - der Regler stoppte mit
        heading_block (+67,2 Grad), die Planausfuehrung baute aus dem
        erfundenen Kurs ein Rangiermanoever, und als der echte Kurs eine
        Sekunde spaeter zurueck war, stand das Manoever 80,5 Grad quer und
        der Plan war tot. parse_heading kann das nicht abfangen: der Satz
        selbst ist formal gueltig.

        Massstab ist deshalb die Physik. Erlaubt ist Sockel plus Rate mal
        Zeit seit dem letzten angenommenen Kurs. Dreht sich das Fahrzeug
        wirklich (umgesetzt, getragen), waechst die Schranke von selbst, bis
        der neue Kurs angenommen wird - bei 180 Grad nach gut 8 s. Solange
        die Pose fehlt, haelt die zentrale Safety-Logik den Plan an und setzt
        automatisch fort; ein Empfaenger-Aussetzer von 1-2 s wird damit zur
        kurzen Fahrpause statt zum Planabbruch.
        """
        now = time.monotonic()
        with self._lock:
            reference = self._accepted_heading_deg
            reference_time = self._accepted_heading_monotonic
        if reference is not None:
            dt = max(0.0, now - reference_time)
            allowed = self._heading_jump_base_deg + self._heading_jump_rate_dps * dt
            difference = abs(
                (float(heading_deg) - reference + 180.0) % 360.0 - 180.0
            )
            if difference > allowed:
                with self._lock:
                    self._suppressed_heading_jump += 1
                    episode_start = self._heading_jump_started_monotonic
                    if episode_start is None:
                        self._heading_jump_started_monotonic = now
                if episode_start is None:
                    self.logger.warning(
                        "GNSS-Kurs springt von %.1f auf %.1f Grad "
                        "(%.1f Grad in %.2f s, erlaubt %.1f) - "
                        "Pose wird zurueckgehalten",
                        reference, float(heading_deg), difference, dt, allowed,
                    )
                return False
        with self._lock:
            episode_start = self._heading_jump_started_monotonic
            self._heading_jump_started_monotonic = None
            self._accepted_heading_deg = float(heading_deg)
            self._accepted_heading_monotonic = now
        if episode_start is not None:
            self.logger.info(
                "GNSS-Kurs wieder plausibel bei %.1f Grad "
                "(%.2f s zurueckgehalten)",
                float(heading_deg), now - episode_start,
            )
        return True

    def get_status(self) -> Dict[str, Any]:
        """Detailstatus fuer Oberflaeche und Diagnose.

        Die Feldnamen ``online``, ``age_s`` und ``last_error`` entsprechen dem
        HTTP-Client, damit die Statusleiste ohne Sonderfall auskommt.
        """
        now = time.monotonic()
        gps_status = self.gps.get_status()
        with self._lock:
            last_published = self._last_published_monotonic
            packets = self._packets_published
            suppressed_fix = self._suppressed_stale_fix
            suppressed_heading = self._suppressed_no_heading
            suppressed_jump = self._suppressed_heading_jump
            last_error = self._last_error
            heading_source = self._last_heading_source

        age = None if last_published <= 0.0 else max(0.0, now - last_published)
        timeout_s = float(getattr(self.config, 'telemetry_timeout_s', 30.0))

        status: Dict[str, Any] = {
            'running': self.running,
            'online': age is not None and age <= timeout_s,
            'age_s': None if age is None else round(age, 3),
            'transport': 'local',
            'source': 'gnss-usb',
            'url': gps_status.get('port'),
            'packets_received': packets,
            'suppressed_stale_fix': suppressed_fix,
            'suppressed_no_heading': suppressed_heading,
            'suppressed_heading_jump': suppressed_jump,
            'heading_source': heading_source,
            'heading_offset_deg': self._heading_offset_deg,
            'geometry_loaded': self._geometry is not None,
            'last_error': last_error,
            'gnss': gps_status,
        }
        if self.bridge is not None:
            bridge_status = self.bridge.get_status()
            status['ntrip'] = bridge_status['ntrip']
            status['rtk'] = {
                'current': bridge_status['current_rtk_status'],
                'uptime_s': bridge_status['rtk_uptime_s'],
                'fix_count': bridge_status['rtk_fix_count'],
                'float_count': bridge_status['rtk_float_count'],
                'gga_sent': bridge_status['gga_sent'],
                'rtcm_bytes_to_receiver': bridge_status['rtcm_bytes_to_receiver'],
            }
        else:
            status['ntrip'] = {'connected': False, 'last_error': 'NTRIP abgeschaltet'}
        return status
