#!/usr/bin/env python3
"""
CAN Protocol - Multi-Frame JSON-Kommunikation
Thread-Safe Buffer-Verwaltung für Multi-Frame-Nachrichten
"""

import json
import logging
import threading
import time
from typing import Optional, Dict, Any


class CANProtocol:
    """
    CAN-Protokoll für Multi-Frame JSON-Nachrichten
    Thread-Safe Buffer-Verwaltung
    """
    
    def __init__(self, max_frame_size: int = 6, frame_timeout: float = 1.0):
        """
        Initialisiert CAN-Protokoll
        
        Args:
            max_frame_size: Maximale Nutzdaten pro Frame (Bytes)
            frame_timeout: Timeout für unvollständige Frames (Sekunden)
        """
        self.logger = logging.getLogger(__name__)
        self.max_frame_size = max_frame_size
        self.frame_timeout = frame_timeout
        
        # Thread-Safe Frame-Buffer
        self._frame_buffer: Dict[int, Dict[str, Any]] = {}
        self._buffer_lock = threading.Lock()
    
    def encode_message(self, data: Dict[str, Any]) -> list:
        """
        Kodiert JSON-Nachricht in CAN-Frames
        
        Args:
            data: Dictionary mit Nachrichtendaten
            
        Returns:
            Liste von CAN-Frame-Daten (bytes)
        """
        try:
            # JSON serialisieren
            json_str = json.dumps(data)
            json_bytes = json_str.encode('utf-8')
            
            # In Chunks aufteilen
            chunks = []
            for i in range(0, len(json_bytes), self.max_frame_size):
                chunk = json_bytes[i:i + self.max_frame_size]
                chunks.append(chunk)
            
            # Frames erstellen
            total_frames = len(chunks)
            frames = []
            
            for frame_idx, chunk in enumerate(chunks):
                # Frame-Format: [frame_idx, total_frames, ...data (max 6 bytes)]
                frame_data = bytearray([frame_idx, total_frames])
                frame_data.extend(chunk)
                
                # Auf 8 Bytes auffüllen (CAN-Standard)
                while len(frame_data) < 8:
                    frame_data.append(0x00)
                
                frames.append(bytes(frame_data))
            
            return frames
        
        except Exception as e:
            self.logger.error(f"❌ Message-Encoding Fehler: {e}")
            return []
    
    def decode_frame(self, arbitration_id: int, frame_data: bytes) -> Optional[str]:
        """
        Dekodiert CAN-Frame und gibt vollständige JSON-Nachricht zurück (Thread-Safe)
        
        Args:
            arbitration_id: CAN-Arbitration-ID (zur Buffer-Identifikation)
            frame_data: CAN-Frame-Daten
            
        Returns:
            JSON-String wenn vollständig, None sonst
        """
        if len(frame_data) < 2:
            return None
        
        frame_idx = frame_data[0]
        total_frames = frame_data[1]
        chunk = frame_data[2:8]  # Max 6 Bytes Nutzdaten
        
        with self._buffer_lock:
            # Ersten Frame: Buffer initialisieren
            if frame_idx == 0:
                self._frame_buffer[arbitration_id] = {
                    'total': total_frames,
                    'frames': [None] * total_frames,
                    'timestamp': time.time()
                }
            
            # Frame im Buffer speichern
            if arbitration_id in self._frame_buffer:
                buffer = self._frame_buffer[arbitration_id]
                
                if frame_idx < len(buffer['frames']):
                    buffer['frames'][frame_idx] = chunk
                
                # Prüfen ob alle Frames empfangen
                if all(f is not None for f in buffer['frames']):
                    # Alle Frames zusammensetzen
                    full_data = b''.join(buffer['frames'])
                    # Null-Bytes entfernen
                    full_data = full_data.rstrip(b'\x00')
                    # Buffer leeren
                    del self._frame_buffer[arbitration_id]
                    
                    try:
                        return full_data.decode('utf-8')
                    except UnicodeDecodeError as e:
                        self.logger.error(f"❌ UTF-8 Decode Fehler: {e}")
                        return None
        
        return None
    
    def cleanup_old_buffers(self):
        """Entfernt alte unvollständige Buffers (Thread-Safe)"""
        current_time = time.time()
        
        with self._buffer_lock:
            expired_ids = [
                arb_id for arb_id, buffer in self._frame_buffer.items()
                if current_time - buffer['timestamp'] > self.frame_timeout
            ]
            
            for arb_id in expired_ids:
                del self._frame_buffer[arb_id]
                self.logger.warning(f"⚠️ Frame-Buffer Timeout für ID 0x{arb_id:X}")
    
    def get_buffer_status(self) -> Dict[str, Any]:
        """
        Gibt Buffer-Status zurück (Thread-Safe)
        
        Returns:
            Dictionary mit Buffer-Informationen
        """
        with self._buffer_lock:
            return {
                'active_buffers': len(self._frame_buffer),
                'buffer_ids': [f"0x{arb_id:X}" for arb_id in self._frame_buffer.keys()]
            }

