"""
NTRIP Client für RTK-Korrekturdaten
Verbindet mit NTRIP-Server und sendet Korrekturdaten an GPS-Gerät
"""

import socket
import threading
import time
import logging
import base64
from typing import Optional

logger = logging.getLogger(__name__)


class NTRIPClient:
    """NTRIP Client für RTK-Korrekturdaten"""
    
    def __init__(self, host: str, port: int, mountpoint: str,
                 username: str, password: str, timeout: float = 10.0,
                 reconnect_interval: float = 30.0,
                 stale_timeout: float = 10.0):
        """
        Initialisiert NTRIP Client

        Args:
            host: NTRIP Server Host
            port: NTRIP Server Port
            mountpoint: NTRIP Mountpoint
            username: Benutzername
            password: Passwort
            timeout: Verbindungs-Timeout
            reconnect_interval: Reconnect-Versuch nach X Sekunden
            stale_timeout: Fliessen so lange keine Bytes, obwohl der Socket noch
                als verbunden gilt, wird die Verbindung als tot behandelt und
                neu aufgebaut. Der Caster laesst den Socket bei einem Ausfall
                minutenlang offen, ohne Daten zu senden - ohne diese Schwelle
                haengt RTK bis zum serverseitigen Timeout auf GPS FIX.
        """
        self.host = host
        self.port = port
        self.mountpoint = mountpoint
        self.username = username
        self.password = password
        self.timeout = timeout
        self.reconnect_interval = reconnect_interval
        self.stale_timeout = max(0.0, float(stale_timeout))
        
        self.socket = None
        self.running = False
        self.connected = False
        self.reader_thread = None
        self.last_connection_attempt = 0
        self.connection_attempts = 0
        self.bytes_received = 0
        self.last_data_time = 0
        
        # Callback für empfangene Daten
        self.on_data_received = None

    def enable(self):
        """Aktiviert den Client für Verbindungsversuche"""
        self.running = True
        logger.debug("NTRIP Client aktiviert - Reconnect-Versuche möglich")

    def connect(self) -> bool:
        """Verbindet mit NTRIP-Server"""
        try:
            logger.info(f"🔗 Verbinde mit NTRIP-Server: {self.host}:{self.port}/{self.mountpoint}")
            
            # Socket erstellen
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)

            # TCP-Keepalive aktivieren, damit ein halboffener Socket auf
            # Betriebssystemebene erkannt wird. Der eigentliche Schutz gegen
            # einen still stehenden Caster ist der Daten-Wachhund
            # (check_stalled_stream); Keepalive ist der zweite Riegel.
            self._enable_keepalive(self.socket)

            # Mit Server verbinden
            self.socket.connect((self.host, self.port))
            
            # NTRIP Request senden
            auth_string = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            request = (
                f"GET /{self.mountpoint} HTTP/1.0\r\n"
                f"User-Agent: NTRIP Quassel-UGV/1.0\r\n"
                f"Authorization: Basic {auth_string}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            )
            
            self.socket.sendall(request.encode())
            logger.debug(f"📤 NTRIP Request gesendet")
            
            # Response lesen (HTTP Header)
            response = b""
            while b"\r\n\r\n" not in response:
                chunk = self.socket.recv(1024)
                if not chunk:
                    raise Exception("Server hat Verbindung geschlossen")
                response += chunk
            
            response_str = response.decode('utf-8', errors='ignore')
            
            # HTTP Status überprüfen
            if "200" in response_str:
                logger.info("✅ NTRIP verbunden - RTK-Daten werden empfangen")
                self.connected = True
                self.connection_attempts = 0
                self.running = True
                # Frisch setzen, damit der Daten-Wachhund auch eine Verbindung
                # erkennt, die nie Daten liefert (last_data_time bliebe sonst 0).
                self.last_data_time = time.time()
                
                # Reader-Thread starten
                self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
                self.reader_thread.start()
                
                return True
            else:
                # Fehler extrahieren
                status_line = response_str.split('\r\n')[0]
                logger.error(f"❌ NTRIP Fehler: {status_line}")
                
                if "401" in response_str:
                    logger.error("❌ Authentifizierung fehlgeschlagen (401)")
                elif "404" in response_str:
                    logger.error("❌ Mountpoint nicht gefunden (404)")
                
                self.socket.close()
                return False
        
        except socket.timeout:
            logger.error(f"❌ NTRIP Timeout nach {self.timeout}s")
            return False
        except ConnectionRefusedError:
            logger.error(f"❌ NTRIP Verbindung abgelehnt")
            return False
        except Exception as e:
            logger.error(f"❌ NTRIP Verbindungsfehler: {e}")
            return False
    
    def disconnect(self):
        """Trennt NTRIP-Verbindung"""
        self.running = False
        if self.reader_thread:
            self.reader_thread.join(timeout=2.0)
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        self.connected = False
        logger.info("NTRIP getrennt")
    
    def _read_loop(self):
        """Liest kontinuierlich NTRIP-Daten"""
        while self.running and self.connected:
            try:
                data = self.socket.recv(4096)
                
                if not data:
                    logger.warning("⚠️  NTRIP Server hat Verbindung geschlossen")
                    self.connected = False
                    break
                
                self.bytes_received += len(data)
                self.last_data_time = time.time()
                
                # Callback aufrufen wenn registriert
                if self.on_data_received:
                    self.on_data_received(data)
            
            except socket.timeout:
                # Timeout ist ok, einfach weitermachen
                pass
            except Exception as e:
                logger.warning(f"⚠️  NTRIP Read-Fehler: {e}")
                self.connected = False
                break
    
    def is_connected(self) -> bool:
        """Gibt Verbindungsstatus zurück"""
        return self.connected and self.running

    @staticmethod
    def _enable_keepalive(sock: socket.socket) -> None:
        """Aktiviert TCP-Keepalive so aggressiv wie die Plattform es erlaubt."""
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
        """Sekunden seit dem letzten empfangenen Byte, None wenn getrennt."""
        if not self.connected or self.last_data_time <= 0:
            return None
        return max(0.0, time.time() - self.last_data_time)

    def data_is_stale(self) -> bool:
        """True, wenn der Socket verbunden ist, aber zu lange keine Daten kamen."""
        if self.stale_timeout <= 0:
            return False
        gap = self.seconds_since_data()
        return gap is not None and gap > self.stale_timeout

    def _force_disconnect(self, reason: str) -> None:
        """Behandelt einen offenen, aber toten Socket wie eine Trennung."""
        self.connected = False
        sock = self.socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        logger.warning(
            f"⚠️  NTRIP-Datenstrom steht still ({reason}) - erzwinge Reconnect"
        )

    def check_stalled_stream(self) -> bool:
        """Erkennt einen stehenden NTRIP-Strom und stößt den Reconnect an.

        Der Caster hört bei einem Ausfall auf, RTCM zu senden, hält die
        TCP-Verbindung aber offen. ``recv()`` läuft dann in seinen Timeout und
        wird verschluckt, ``connected`` bliebe True, und der Empfänger fiele
        bis zum serverseitigen Timeout (~7 min) auf GPS FIX zurück. Diese
        Prüfung verkürzt das auf wenige Sekunden.

        Returns:
            True, wenn ein Stillstand erkannt und die Verbindung getrennt wurde.
        """
        if self.data_is_stale():
            gap = self.seconds_since_data() or 0.0
            self._force_disconnect(f"{gap:.0f}s ohne Daten")
            return True
        return False

    def get_status(self) -> dict:
        """Gibt NTRIP-Status zurück"""
        return {
            'connected': self.connected,
            'host': self.host,
            'port': self.port,
            'mountpoint': self.mountpoint,
            'bytes_received': self.bytes_received,
            'last_data_time': self.last_data_time,
            'seconds_since_data': self.seconds_since_data(),
            'stale': self.data_is_stale(),
            'connection_attempts': self.connection_attempts
        }
    
    def send_gga_data(self, gga_sentence: str):
        """
        Sendet einen GPGGA-Satz an den NTRIP-Server
        Wichtig: Der Server braucht die Position für VRS (Virtuelle Referenzstation)

        Args:
            gga_sentence: Roher GGA-Satz (z.B. "$GNGGA,...")
        """
        if self.is_connected():
            try:
                # GGA-Satz mit CRLF senden
                self.socket.sendall(gga_sentence.encode('ascii') + b'\r\n')
                logger.debug(f"📤 GPGGA an NTRIP gesendet: {gga_sentence[:50]}...")
            except Exception as e:
                logger.warning(f"⚠️ Fehler beim Senden von GPGGA: {e}")

    def reconnect_if_needed(self):
        """Versucht zu reconnecten wenn nötig"""
        if not self.connected and self.running:
            now = time.time()
            # Beim ersten Versuch (connection_attempts == 0) sofort verbinden
            if self.connection_attempts == 0 or (now - self.last_connection_attempt > self.reconnect_interval):
                self.connection_attempts += 1
                self.last_connection_attempt = now
                logger.info(f"🔄 NTRIP Reconnect-Versuch #{self.connection_attempts}")
                self.connect()

