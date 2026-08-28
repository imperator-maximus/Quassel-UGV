"""NTRIP-Client fuer RTK-Korrekturdaten.

Uebernommen vom SensorHub (``sensor_hub/ntrip_client.py``). Der Daten-Wachhund
stammt aus dem Vorfall, bei dem der Caster sieben Minuten lang keine Daten mehr
schickte, die TCP-Verbindung aber offen liess: ``connected`` blieb wahr, der
Empfaenger fiel still auf GPS FIX zurueck, und niemand bemerkte es waehrend der
Fahrt. Ein offener Socket ist deshalb kein Beweis fuer einen laufenden Strom -
nur der Zeitpunkt des letzten empfangenen Bytes zaehlt.

Alle Alter laufen ueber ``time.monotonic()``, damit ein NTP-Sprung den
Wachhund nicht aushebelt.
"""

import base64
import logging
import socket
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class NTRIPClient:
    """Holt RTCM-Korrekturen von einem NTRIP-Caster."""

    def __init__(self, host: str, port: int, mountpoint: str,
                 username: str, password: str, timeout: float = 10.0,
                 reconnect_interval: float = 30.0,
                 stale_timeout: float = 10.0,
                 user_agent: str = 'NTRIP Quassel-UGV/1.0'):
        """
        Args:
            host: Adresse des Casters
            port: Port des Casters, ueblicherweise 2101
            mountpoint: Mountpoint, beim Open-RTK-Dienst M-V ``openrtk_mv``
            username: Zugangskennung
            password: Passwort
            timeout: Zeitlimit fuer Verbindungsaufbau und Lesen
            reconnect_interval: Wartezeit zwischen zwei Verbindungsversuchen
            stale_timeout: Fliessen so lange keine Bytes, obwohl der Socket
                noch als verbunden gilt, wird die Verbindung als tot behandelt
                und neu aufgebaut.
            user_agent: Kennung fuer den Caster
        """
        self.host = host
        self.port = int(port)
        self.mountpoint = mountpoint
        self.username = username
        self.password = password
        self.timeout = float(timeout)
        self.reconnect_interval = float(reconnect_interval)
        self.stale_timeout = max(0.0, float(stale_timeout))
        self.user_agent = user_agent

        self.socket: Optional[socket.socket] = None
        self.running = False
        self.connected = False
        self.reader_thread: Optional[threading.Thread] = None

        self._last_connection_attempt = 0.0
        self.connection_attempts = 0
        self.bytes_received = 0
        self._last_data_monotonic = 0.0
        self._connected_since = 0.0
        self._last_error: Optional[str] = None
        self._forced_reconnects = 0

        # Wird bei jedem erfolgreichen Verbindungsaufbau ausgeloest. Die Bruecke
        # haengt sich hier ein, um die GGA sofort nachzuschicken: eine VRS
        # liefert erst RTCM, wenn sie die Roverposition kennt.
        self.on_connected: Optional[Callable[[], None]] = None
        self.on_data_received: Optional[Callable[[bytes], None]] = None

        self._lock = threading.Lock()
        self._send_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Verbindung
    # ------------------------------------------------------------------
    def enable(self):
        """Gibt Verbindungsversuche frei."""
        self.running = True

    def connect(self) -> bool:
        """Baut die Verbindung auf und startet den Lesethread."""
        try:
            logger.info("Verbinde mit NTRIP-Caster %s:%d/%s",
                        self.host, self.port, self.mountpoint)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            self._enable_keepalive(sock)
            sock.connect((self.host, self.port))
            self.socket = sock

            auth = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            request = (
                f"GET /{self.mountpoint} HTTP/1.0\r\n"
                f"User-Agent: {self.user_agent}\r\n"
                f"Authorization: Basic {auth}\r\n"
                f"Accept: */*\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            )
            sock.sendall(request.encode())

            response = b""
            while b"\r\n\r\n" not in response:
                chunk = sock.recv(1024)
                if not chunk:
                    raise ConnectionError("Caster hat die Verbindung geschlossen")
                response += chunk
                if len(response) > 8192:
                    raise ConnectionError("Antwort des Casters ohne Kopfende")

            text = response.decode('utf-8', errors='ignore')
            status_line = text.split('\r\n', 1)[0]
            # Der Open-RTK-Dienst antwortet mit "ICY 200 OK", andere Caster mit
            # "HTTP/1.1 200 OK". Beide tragen die 200 in der Statuszeile.
            if '200' not in status_line:
                if '401' in status_line:
                    logger.error("NTRIP-Anmeldung abgelehnt (401) - Zugangsdaten pruefen")
                elif '404' in status_line:
                    logger.error("NTRIP-Mountpoint %s nicht gefunden (404)", self.mountpoint)
                else:
                    logger.error("NTRIP-Fehler: %s", status_line)
                with self._lock:
                    self._last_error = status_line
                self._close_socket()
                return False

            now = time.monotonic()
            with self._lock:
                self.connected = True
                self.connection_attempts = 0
                self._last_error = None
                # Frisch setzen, damit der Wachhund auch eine Verbindung
                # erkennt, die nie Daten liefert.
                self._last_data_monotonic = now
                self._connected_since = now
            self.running = True

            logger.info("NTRIP verbunden - RTK-Korrekturen laufen")
            self.reader_thread = threading.Thread(
                target=self._read_loop, name='ntrip-reader', daemon=True
            )
            self.reader_thread.start()

            if self.on_connected:
                try:
                    self.on_connected()
                except Exception as exc:
                    logger.debug("on_connected-Callback fehlgeschlagen: %s", exc)
            return True

        except socket.timeout:
            with self._lock:
                self._last_error = f"Zeitlimit nach {self.timeout}s"
            logger.error("NTRIP-Zeitlimit nach %.0fs", self.timeout)
            self._close_socket()
            return False
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            logger.error("NTRIP-Verbindungsfehler: %s", exc)
            self._close_socket()
            return False

    def disconnect(self):
        """Beendet den Client."""
        self.running = False
        with self._lock:
            self.connected = False
        thread = self.reader_thread
        self._close_socket()
        if thread is not None:
            thread.join(timeout=2.0)
        logger.info("NTRIP getrennt")

    def _close_socket(self):
        sock = self.socket
        self.socket = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------
    def _read_loop(self):
        """Nimmt RTCM entgegen und reicht es an den Callback weiter."""
        while self.running and self.connected:
            sock = self.socket
            if sock is None:
                break
            try:
                data = sock.recv(4096)
            except socket.timeout:
                # Kein Fehler. Ob der Strom wirklich steht, entscheidet der
                # Wachhund ueber das Alter des letzten Bytes.
                continue
            except Exception as exc:
                logger.warning("NTRIP-Lesefehler: %s", exc)
                with self._lock:
                    self.connected = False
                    self._last_error = str(exc)
                break

            if not data:
                logger.warning("NTRIP-Caster hat die Verbindung geschlossen")
                with self._lock:
                    self.connected = False
                break

            with self._lock:
                self.bytes_received += len(data)
                self._last_data_monotonic = time.monotonic()

            if self.on_data_received:
                try:
                    self.on_data_received(data)
                except Exception as exc:
                    logger.warning("Weiterreichen der RTCM-Daten fehlgeschlagen: %s", exc)

    # ------------------------------------------------------------------
    # Wachhund
    # ------------------------------------------------------------------
    @staticmethod
    def _enable_keepalive(sock: socket.socket) -> None:
        """Aktiviert TCP-Keepalive so aggressiv wie die Plattform es erlaubt.

        Zweiter Riegel hinter dem Daten-Wachhund, nicht dessen Ersatz.
        """
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            return
        for name, value in (('TCP_KEEPIDLE', 15),
                            ('TCP_KEEPINTVL', 5),
                            ('TCP_KEEPCNT', 3)):
            option = getattr(socket, name, None)
            if option is None:
                continue
            try:
                sock.setsockopt(socket.IPPROTO_TCP, option, value)
            except OSError:
                pass

    def seconds_since_data(self) -> Optional[float]:
        """Sekunden seit dem letzten empfangenen Byte, ``None`` wenn getrennt."""
        with self._lock:
            if not self.connected or self._last_data_monotonic <= 0.0:
                return None
            return max(0.0, time.monotonic() - self._last_data_monotonic)

    def data_is_stale(self) -> bool:
        """Wahr, wenn der Socket offen ist, aber zu lange nichts kam."""
        if self.stale_timeout <= 0:
            return False
        gap = self.seconds_since_data()
        return gap is not None and gap > self.stale_timeout

    def check_stalled_stream(self) -> bool:
        """Erkennt einen stehenden Strom und erzwingt den Neuaufbau.

        Der Caster hoert bei einem Ausfall auf zu senden, haelt die
        TCP-Verbindung aber offen. ``recv()`` laeuft dann in sein Zeitlimit,
        ``connected`` bliebe wahr, und der Empfaenger fiele bis zum
        serverseitigen Zeitlimit auf GPS FIX zurueck. Genau das hat einmal
        sieben Minuten Fahrt gekostet.
        """
        if not self.data_is_stale():
            return False
        gap = self.seconds_since_data() or 0.0
        with self._lock:
            self.connected = False
            self._forced_reconnects += 1
            self._last_error = f"{gap:.0f}s ohne Daten"
        self._close_socket()
        logger.warning("NTRIP-Datenstrom steht still (%.0fs ohne Daten) - erzwinge Neuaufbau", gap)
        return True

    def is_connected(self) -> bool:
        with self._lock:
            return self.connected and self.running

    def reconnect_if_needed(self) -> bool:
        """Baut die Verbindung neu auf, sobald das Intervall abgelaufen ist."""
        if self.is_connected() or not self.running:
            return False
        now = time.monotonic()
        with self._lock:
            attempts = self.connection_attempts
            last_attempt = self._last_connection_attempt
        if attempts > 0 and (now - last_attempt) <= self.reconnect_interval:
            return False
        with self._lock:
            self.connection_attempts += 1
            self._last_connection_attempt = now
            attempt_no = self.connection_attempts
        logger.info("NTRIP-Verbindungsversuch #%d", attempt_no)
        return self.connect()

    # ------------------------------------------------------------------
    # Senden
    # ------------------------------------------------------------------
    def send_gga(self, gga_sentence: str) -> bool:
        """Schickt einen GGA-Satz an den Caster.

        Die VRS braucht die Roverposition, sonst liefert sie keine
        Korrekturen fuer die richtige Gegend.
        """
        if not self.is_connected():
            return False
        sock = self.socket
        if sock is None:
            return False
        try:
            with self._send_lock:
                sock.sendall(gga_sentence.encode('ascii') + b'\r\n')
            return True
        except Exception as exc:
            logger.warning("Senden der GGA an den Caster fehlgeschlagen: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        gap = self.seconds_since_data()
        with self._lock:
            uptime = (
                None if self._connected_since <= 0.0 or not self.connected
                else round(time.monotonic() - self._connected_since, 1)
            )
            return {
                'connected': self.connected,
                'host': self.host,
                'port': self.port,
                'mountpoint': self.mountpoint,
                'bytes_received': self.bytes_received,
                'seconds_since_data': None if gap is None else round(gap, 1),
                'stale': gap is not None and self.stale_timeout > 0 and gap > self.stale_timeout,
                'connection_attempts': self.connection_attempts,
                'forced_reconnects': self._forced_reconnects,
                'uptime_s': uptime,
                'last_error': self._last_error,
            }
