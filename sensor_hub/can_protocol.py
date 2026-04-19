"""
CAN Protocol - Multi-Frame JSON-Kommunikation für den Sensor Hub.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional


class CANProtocol:
    """Thread-sichere Buffer-Verwaltung für Multi-Frame JSON-Nachrichten."""

    def __init__(self, max_frame_size: int = 6, frame_timeout: float = 1.0):
        self.logger = logging.getLogger(__name__)
        self.max_frame_size = max_frame_size
        self.frame_timeout = frame_timeout
        self._frame_buffer: Dict[int, Dict[str, Any]] = {}
        self._buffer_lock = threading.Lock()

    def decode_frame(self, arbitration_id: int, frame_data: bytes) -> Optional[str]:
        """Dekodiert einen Frame und liefert vollständiges JSON zurück, sobald komplett."""
        if len(frame_data) < 2:
            return None

        frame_idx = frame_data[0]
        total_frames = frame_data[1]
        chunk = frame_data[2:2 + self.max_frame_size]

        with self._buffer_lock:
            if frame_idx == 0:
                self._frame_buffer[arbitration_id] = {
                    'total': total_frames,
                    'frames': [None] * total_frames,
                    'timestamp': time.time()
                }

            if arbitration_id not in self._frame_buffer:
                return None

            buffer = self._frame_buffer[arbitration_id]
            if frame_idx < len(buffer['frames']):
                buffer['frames'][frame_idx] = chunk

            if all(frame is not None for frame in buffer['frames']):
                full_data = b''.join(buffer['frames']).rstrip(b'\x00')
                del self._frame_buffer[arbitration_id]
                try:
                    return full_data.decode('utf-8')
                except UnicodeDecodeError as exc:
                    self.logger.error(f"❌ UTF-8 Decode Fehler: {exc}")
                    return None

        return None

    def cleanup_old_buffers(self):
        """Entfernt alte unvollständige Buffer."""
        current_time = time.time()
        with self._buffer_lock:
            expired_ids = [
                arb_id for arb_id, buffer in self._frame_buffer.items()
                if current_time - buffer['timestamp'] > self.frame_timeout
            ]
            for arb_id in expired_ids:
                del self._frame_buffer[arb_id]
                self.logger.warning(f"⚠️ Frame-Buffer Timeout für ID 0x{arb_id:X}")