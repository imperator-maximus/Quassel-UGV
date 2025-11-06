"""
GPS-NTRIP Bridge
Verbindet GPS-Gerät mit NTRIP-Server für RTK-Korrekturdaten
"""

import threading
import time
import logging
from typing import Optional
from gps_handler import GPSHandler
from ntrip_client import NTRIPClient

logger = logging.getLogger(__name__)


class GPSNTRIPBridge:
    """Verbindet GPS mit NTRIP für RTK-Korrekturdaten"""
    
    def __init__(self, gps: GPSHandler, ntrip: NTRIPClient):
        """
        Initialisiert GPS-NTRIP Bridge

        Args:
            gps: GPSHandler Instanz
            ntrip: NTRIPClient Instanz
        """
        self.gps = gps
        self.ntrip = ntrip
        self.running = False
        self.monitor_thread = None

        # Statistiken
        self.rtk_fix_count = 0
        self.rtk_float_count = 0
        self.gps_fix_count = 0
        self.last_rtk_status = "NO GPS"
        self.rtk_fix_time = None
        self.rtk_uptime = 0

        # GPGGA Versand (für NTRIP VRS)
        self.last_gga_send_time = 0
        self.gga_send_interval = 10.0  # Alle 10 Sekunden
    
    def start(self) -> bool:
        """Startet die Bridge"""
        try:
            logger.info("🌉 Starte GPS-NTRIP Bridge")

            # NTRIP Client aktivieren (für Reconnect-Versuche)
            self.ntrip.enable()

            # NTRIP Callback registrieren
            self.ntrip.on_data_received = self._on_ntrip_data

            # Monitor-Thread starten (auch wenn initiale Verbindung fehlschlägt)
            self.running = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()

            # NTRIP verbinden (erster Versuch)
            if self.ntrip.connect():
                logger.info("✅ GPS-NTRIP Bridge gestartet - NTRIP verbunden")
                return True
            else:
                logger.warning("⚠️  NTRIP initiale Verbindung fehlgeschlagen - Reconnect-Versuche laufen im Hintergrund")
                return True  # Trotzdem True zurückgeben, da Monitor-Thread läuft

        except Exception as e:
            logger.error(f"❌ Bridge Start-Fehler: {e}")
            return False
    
    def stop(self):
        """Stoppt die Bridge"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
        if self.ntrip:
            self.ntrip.disconnect()
        logger.info("GPS-NTRIP Bridge gestoppt")
    
    def _on_ntrip_data(self, data: bytes):
        """Callback wenn NTRIP-Daten empfangen werden"""
        try:
            # NTRIP-Daten an GPS-Gerät senden (über öffentliche Methode für Kapselung)
            self.gps.write_data(data)
            logger.debug(f"📤 {len(data)} Bytes NTRIP-Daten an GPS gesendet")
        except Exception as e:
            logger.warning(f"⚠️  Fehler beim Senden von NTRIP-Daten: {e}")
    
    def _monitor_loop(self):
        """Überwacht RTK-Status und Verbindungen"""
        while self.running:
            try:
                # NTRIP Reconnect wenn nötig
                self.ntrip.reconnect_if_needed()

                # RTK-Status überwachen
                gps_status = self.gps.get_status()
                current_rtk_status = gps_status['rtk_status']

                # Status-Änderungen tracken
                if current_rtk_status != self.last_rtk_status:
                    self._on_rtk_status_changed(self.last_rtk_status, current_rtk_status)
                    self.last_rtk_status = current_rtk_status

                # RTK-Uptime berechnen
                if current_rtk_status == "RTK FIXED":
                    if self.rtk_fix_time is None:
                        self.rtk_fix_time = time.time()
                    self.rtk_uptime = time.time() - self.rtk_fix_time
                else:
                    self.rtk_fix_time = None
                    self.rtk_uptime = 0

                # GPGGA periodisch an NTRIP senden (für VRS - Virtuelle Referenzstation)
                now = time.time()
                if self.ntrip.is_connected() and now - self.last_gga_send_time > self.gga_send_interval:
                    raw_gga = self.gps.get_last_raw_gga()
                    if raw_gga:
                        self.ntrip.send_gga_data(raw_gga)
                        self.last_gga_send_time = now
                    else:
                        # Warnung: Kein gültiger GGA-Satz verfügbar
                        # Dies deutet auf schlechten GPS-Empfang hin
                        logger.warning("⚠️  Wollte GPGGA an NTRIP senden, aber kein gültiger Satz vom GPS verfügbar. Prüfe GPS-Antenne und Himmelssicht!")

                time.sleep(1.0)

            except Exception as e:
                logger.warning(f"⚠️  Monitor-Fehler: {e}")
                time.sleep(1.0)
    
    def _on_rtk_status_changed(self, old_status: str, new_status: str):
        """Wird aufgerufen wenn sich RTK-Status ändert"""
        logger.info(f"🔄 RTK-Status: {old_status} → {new_status}")
        
        if new_status == "RTK FIXED":
            self.rtk_fix_count += 1
            logger.info(f"✅ RTK FIXED erreicht! (#{self.rtk_fix_count})")
        elif new_status == "RTK FLOAT":
            self.rtk_float_count += 1
            logger.info(f"⚠️  RTK FLOAT (#{self.rtk_float_count})")
        elif new_status == "GPS FIX":
            self.gps_fix_count += 1
            logger.info(f"📍 GPS FIX (#{self.gps_fix_count})")
    
    def get_status(self) -> dict:
        """Gibt Bridge-Status zurück"""
        gps_status = self.gps.get_status()
        ntrip_status = self.ntrip.get_status()
        
        return {
            'gps': gps_status,
            'ntrip': ntrip_status,
            'rtk_fix_count': self.rtk_fix_count,
            'rtk_float_count': self.rtk_float_count,
            'gps_fix_count': self.gps_fix_count,
            'rtk_uptime': self.rtk_uptime,
            'current_rtk_status': self.last_rtk_status
        }

