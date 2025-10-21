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
                 reconnect_interval: float = 30.0):
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
        """
        self.host = host
        self.port = port
        self.mountpoint = mountpoint
        self.username = username
        self.password = password
        self.timeout = timeout
        self.reconnect_interval = reconnect_interval
        
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
    
    def connect(self) -> bool:
        """Verbindet mit NTRIP-Server"""
        try:
            logger.info(f"🔗 Verbinde mit NTRIP-Server: {self.host}:{self.port}/{self.mountpoint}")
            
            # Socket erstellen
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            
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
    
    def get_status(self) -> dict:
        """Gibt NTRIP-Status zurück"""
        return {
            'connected': self.connected,
            'host': self.host,
            'port': self.port,
            'mountpoint': self.mountpoint,
            'bytes_received': self.bytes_received,
            'last_data_time': self.last_data_time,
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
            if now - self.last_connection_attempt > self.reconnect_interval:
                self.connection_attempts += 1
                self.last_connection_attempt = now
                logger.info(f"🔄 NTRIP Reconnect-Versuch #{self.connection_attempts}")
                self.connect()

