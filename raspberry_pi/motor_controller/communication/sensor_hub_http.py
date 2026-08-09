#!/usr/bin/env python3
"""Fail-safe HTTP telemetry client for the Orange Pi SensorHub."""

import base64
import json
import logging
import math
import ipaddress
import socket
import threading
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class SensorHubHttpClient:
    """Polls compact SensorHub telemetry without blocking control threads."""

    def __init__(self, config, telemetry_callback: Callable[[Dict[str, Any]], None]):
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.telemetry_callback = telemetry_callback
        self.running = False
        self._threads = []
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_received_monotonic = 0.0
        self._last_source_timestamp: Optional[float] = None
        self._last_error: Optional[str] = None
        self._last_http_status: Optional[int] = None
        self._last_latency_ms: Optional[float] = None
        self._packets_received = 0
        self._stale_packets = 0
        self._error_count = 0
        self._consecutive_errors = 0
        self._last_error_log_monotonic = 0.0
        # Rate-Limit fuer Fehler-Logs: max. eine Meldung alle 5 s
        self._error_log_interval_s = 5.0
        self._configured_url = str(self.config.wifi_url)
        self._request_url = self._configured_url
        self._host_header: Optional[str] = None
        self._stream_connections = 0
        self._auth_header = self._build_auth_header()

    def _build_auth_header(self) -> Dict[str, str]:
        """Erzeugt den Basic-Auth-Header fuer den geschuetzten SensorHub.

        Ohne konfigurierte Zugangsdaten bleibt der Header leer. Der SensorHub
        antwortet dann mit 401, die Pose bleibt aus und der Watchdog pausiert
        nach etwa einer Sekunde den Fahrantrieb - sichtbar, aber nicht
        gefaehrlich.
        """
        username = str(getattr(self.config, 'auth_username', '') or '')
        password = str(getattr(self.config, 'auth_password', '') or '')
        if not username or not password:
            return {}
        token = base64.b64encode(
            f"{username}:{password}".encode('utf-8')
        ).decode('ascii')
        return {'Authorization': f'Basic {token}'}

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._threads = [
            threading.Thread(target=self._run, args=(0.0,), daemon=True),
            threading.Thread(target=self._run, args=(0.1,), daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        self.logger.info("SensorHub WiFi-Empfang gestartet: %s", self.config.wifi_url)

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=max(1.0, float(self.config.request_timeout_s) + 0.5))
        self.logger.info("SensorHub WiFi-Empfang gestoppt")

    def _run(self, startup_delay_s: float = 0.0) -> None:
        # Die produktive Verbindung laeuft ueber einen NAT-Hairpin. Der lokale
        # DNS-Resolver zeigte dabei mehrsekündige Blockaden, die nicht vom
        # HTTP-Timeout erfasst werden. Einmal aufloesen und danach die IP
        # verwenden; der originale Host-Header bleibt erhalten.
        if self._stop_event.wait(max(0.0, startup_delay_s)):
            return
        self._refresh_resolved_url()
        reconnect_delay_s = max(0.05, float(self.config.poll_interval_s))
        while not self._stop_event.is_set():
            self._stream_once()
            if not self._stop_event.is_set():
                self._stop_event.wait(reconnect_delay_s)

    def _stream_once(self) -> bool:
        """Empfaengt NDJSON-Telemetrie ueber eine dauerhafte HTTP-Verbindung."""
        started = time.monotonic()
        connected = False
        try:
            request = Request(
                self._get_stream_url(),
                headers={
                    'Accept': 'application/x-ndjson',
                    'Connection': 'keep-alive',
                    **self._auth_header,
                    **({'Host': self._host_header} if self._host_header else {}),
                },
            )
            with urlopen(request, timeout=float(self.config.request_timeout_s)) as response:
                status = getattr(response, 'status', None)
                if status is None:
                    status = response.getcode()
                status = int(status)
                if status != 200:
                    raise RuntimeError(f"HTTP {status}")

                with self._lock:
                    self._stream_connections += 1
                connected = True
                while not self._stop_event.is_set():
                    raw = response.readline(65537)
                    if not raw:
                        raise ConnectionError("SensorHub-Telemetriestrom beendet")
                    if len(raw) > 65536:
                        raise ValueError("Telemetrie-Antwort ist zu gross")
                    payload = json.loads(raw.decode('utf-8'))
                    self._accept_payload(payload, status, started)
                    started = time.monotonic()
            return True
        except Exception as exc:
            if not self._stop_event.is_set():
                self._record_error(exc, started)
            return False
        finally:
            if connected:
                with self._lock:
                    self._stream_connections = max(0, self._stream_connections - 1)

    def _poll_once(self, timeout_s: Optional[float] = None) -> bool:
        started = time.monotonic()
        try:
            request = Request(
                self._request_url,
                headers={
                    'Accept': 'application/json',
                    'Connection': 'close',
                    **self._auth_header,
                    **({'Host': self._host_header} if self._host_header else {}),
                },
            )
            request_timeout_s = (
                float(self.config.request_timeout_s)
                if timeout_s is None
                else float(timeout_s)
            )
            with urlopen(request, timeout=request_timeout_s) as response:
                status = getattr(response, 'status', None)
                if status is None:
                    status = response.getcode()
                status = int(status)
                if status != 200:
                    raise RuntimeError(f"HTTP {status}")
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Telemetrie-Antwort ist zu gross")
                payload = json.loads(raw.decode('utf-8'))

            return self._accept_payload(payload, status, started)
        except Exception as exc:
            self._record_error(exc, started)
            return False

    def _accept_payload(self, payload: Any, status: int, started: float) -> bool:
        source_timestamp = self._validate_payload(payload)
        with self._lock:
            if (
                self._last_source_timestamp is not None
                and source_timestamp <= self._last_source_timestamp
            ):
                self._stale_packets += 1
                self._last_error = "Veraltete oder doppelte Telemetrie"
                return False
            self._last_source_timestamp = source_timestamp
            self._last_received_monotonic = time.monotonic()
            self._last_error = None
            self._last_http_status = status
            self._last_latency_ms = (time.monotonic() - started) * 1000.0
            self._packets_received += 1
            recovered_errors = self._consecutive_errors
            self._consecutive_errors = 0

        if recovered_errors > 0:
            self.logger.info(
                "SensorHub WiFi-Empfang wiederhergestellt nach %d Fehlern",
                recovered_errors,
            )
        self.telemetry_callback(payload)
        return True

    def _record_error(self, exc: Exception, started: float) -> None:
        with self._lock:
            self._last_error = str(exc)
            self._last_latency_ms = (time.monotonic() - started) * 1000.0
            self._error_count += 1
            self._consecutive_errors += 1
            now = time.monotonic()
            should_log = (
                self._consecutive_errors == 1
                or (now - self._last_error_log_monotonic) >= self._error_log_interval_s
            )
            if should_log:
                self._last_error_log_monotonic = now
            error_count = self._error_count
            consecutive_errors = self._consecutive_errors
        if should_log:
            if self._is_auth_error(exc):
                # Diese Ursache ist von aussen nicht von einem Netzausfall zu
                # unterscheiden, die Behebung aber voellig anders. Sie gehoert
                # deshalb als eigene Meldung ins Log.
                self.logger.error(
                    "SensorHub weist die Anmeldung ab (%s). "
                    "sensor_hub.auth_username und SENSOR_HUB_TELEMETRY_PASSWORD "
                    "muessen zu WEB_AUTH_USERNAME/WEB_AUTH_PASSWORD des "
                    "SensorHub passen. Ohne Pose bleibt der Fahrantrieb pausiert.",
                    exc,
                )
            else:
                self.logger.warning(
                    "SensorHub WiFi-Abruf fehlgeschlagen (%d Fehler gesamt): %s",
                    error_count,
                    exc,
                )
        # Nicht bei einem kurzen Netzruckler sofort wieder den langsamen
        # lokalen DNS-Resolver betreten. Erst zehn aufeinanderfolgende
        # HTTP-Fehler deuten auf eine geaenderte Zieladresse hin.
        if consecutive_errors >= 10 and consecutive_errors % 10 == 0:
            self._refresh_resolved_url()

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        """Erkennt eine abgewiesene Anmeldung am HTTP-Status.

        Der Stream prueft den Status selbst und wirft RuntimeError('HTTP 401'),
        urlopen wirft bei 401/403 eine HTTPError mit .code.
        """
        code = getattr(exc, 'code', None)
        if code in (401, 403, 429):
            return True
        text = str(exc)
        return any(marker in text for marker in ('HTTP 401', 'HTTP 403', 'HTTP 429'))

    def _get_stream_url(self) -> str:
        parts = urlsplit(self._request_url)
        path = parts.path.rstrip('/')
        if path.endswith('/telemetry'):
            path += '/stream'
        elif not path.endswith('/telemetry/stream'):
            path += '/stream'
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))

    def _refresh_resolved_url(self) -> bool:
        """Loest den HTTP-Host einmalig auf und cached die numerische Ziel-IP."""
        try:
            parts = urlsplit(self._configured_url)
            hostname = parts.hostname
            if parts.scheme.lower() != 'http' or not hostname:
                return False
            try:
                ipaddress.ip_address(hostname)
                self._request_url = self._configured_url
                self._host_header = None
                return True
            except ValueError:
                pass

            port = parts.port or 80
            addresses = socket.getaddrinfo(
                hostname,
                port,
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
            )
            address = addresses[0][4][0]
            netloc = f'{address}:{port}'
            request_url = urlunsplit((
                parts.scheme,
                netloc,
                parts.path,
                parts.query,
                parts.fragment,
            ))
            host_header = hostname if port == 80 else f'{hostname}:{port}'
            changed = request_url != self._request_url
            self._request_url = request_url
            self._host_header = host_header
            if changed:
                self.logger.info(
                    "SensorHub DNS-Ziel gecached: %s -> %s",
                    hostname,
                    address,
                )
            return True
        except Exception as exc:
            self.logger.warning("SensorHub DNS-Aufloesung fehlgeschlagen: %s", exc)
            return False

    @staticmethod
    def _validate_payload(payload: Any) -> float:
        if not isinstance(payload, dict):
            raise ValueError("Telemetrie ist kein JSON-Objekt")
        timestamp = payload.get('timestamp')
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise ValueError("Telemetrie-Zeitstempel fehlt")
        timestamp = float(timestamp)
        if not math.isfinite(timestamp):
            raise ValueError("Telemetrie-Zeitstempel ist ungueltig")
        gps = payload.get('gps')
        if not isinstance(gps, dict) or not {'lat', 'lon'} <= set(gps):
            raise ValueError("GPS-Pose fehlt in der Telemetrie")
        return timestamp

    def get_status(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            last_received = self._last_received_monotonic
            age = None if last_received <= 0.0 else max(0.0, now - last_received)
            timeout_s = float(self.config.telemetry_timeout_s)
            return {
                'running': self.running,
                'stream_active': self._stream_connections > 0,
                'stream_connections': self._stream_connections,
                'online': age is not None and age <= timeout_s,
                'age_s': None if age is None else round(age, 3),
                'url': self._configured_url,
                'resolved_url': self._request_url,
                'last_error': self._last_error,
                'last_http_status': self._last_http_status,
                'latency_ms': (
                    None if self._last_latency_ms is None
                    else round(self._last_latency_ms, 1)
                ),
                'packets_received': self._packets_received,
                'stale_packets': self._stale_packets,
                'error_count': self._error_count,
                'consecutive_errors': self._consecutive_errors,
            }
