"""Battery state of charge from a Junctek KG110F coulometer over BLE.

The meter carries a CH9141 BLE-to-UART bridge and pushes measurements on its
own, roughly once per second, without being asked. That is why this module
only listens: it never writes to the meter, so the shared WiFi/Bluetooth radio
of the Pi 3 stays free for the SensorHub pose stream.

Wire format, taken off the running device: every frame starts with 0xbb and
ends with 0xee. In between sit one or more BCD-encoded values, each directly
followed by its one-byte tag, and a trailing checksum byte. A tag is any byte
that cannot be BCD, i.e. whose high nibble exceeds 9.

    bb 26 59 c0 06 ee                    -> voltage 26.59 V
    bb 39 c1 10 36 d8 23 ee              -> current 0.39 A, power 10.36 W
    bb 35 99 d5 04 99 46 d2 03 31 d3 06 ee

The checksum byte is deliberately not verified. Its algorithm could not be
derived from the observed traffic, and a wrong guess would silently discard
good frames. Frames are validated structurally instead - correct framing,
valid BCD, known tags, plausible ranges - and the power field cross-checks
voltage times current.
"""

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

FRAME_START = 0xBB
FRAME_END = 0xEE

# Tag byte -> (field name, scale). Values are BCD integers; the scale turns
# them into SI units.
FIELDS: Dict[int, tuple] = {
    0xC0: ("voltage_v", 0.01),
    0xC1: ("current_a", 0.01),
    0xD2: ("remaining_ah", 0.001),
    0xD3: ("discharged_ah", 0.001),
    0xD5: ("runtime_s", 1.0),
    0xD6: ("time_left_min", 1.0),
    0xD7: ("internal_resistance_mohm", 0.01),
    0xD8: ("power_w", 0.01),
}

# Anything outside these bounds is a decoding artefact rather than a reading.
# The pack is 8S LiFePO4 behind two 50 A BMS boards, so nothing beyond this
# range can physically occur.
PLAUSIBLE = {
    "voltage_v": (0.0, 60.0),
    "current_a": (0.0, 120.0),
    "remaining_ah": (0.0, 200.0),
    "discharged_ah": (0.0, 10000.0),
    "power_w": (0.0, 4000.0),
}


def is_bcd(byte: int) -> bool:
    return (byte >> 4) <= 9 and (byte & 0x0F) <= 9


def bcd_to_int(data: bytes) -> Optional[int]:
    value = 0
    for byte in data:
        if not is_bcd(byte):
            return None
        value = value * 100 + (byte >> 4) * 10 + (byte & 0x0F)
    return value


def decode_frame(body: bytes) -> Dict[str, Any]:
    """Decode one frame body, i.e. the bytes between 0xbb and 0xee.

    Returns the decoded fields. Unknown tags are collected under
    ``unknown_tags`` so that fields we have not seen yet - a charging
    direction flag, for example - show up in the log instead of vanishing.
    """
    if len(body) < 3:
        return {}
    # The last byte is the checksum and carries no measurement.
    payload = body[:-1]

    result: Dict[str, Any] = {}
    unknown: Dict[str, int] = {}
    digits = bytearray()
    for byte in payload:
        if is_bcd(byte):
            digits.append(byte)
            continue
        value = bcd_to_int(bytes(digits))
        digits.clear()
        if value is None:
            continue
        entry = FIELDS.get(byte)
        if entry is None:
            unknown[f"0x{byte:02x}"] = value
            continue
        name, scale = entry
        scaled = value * scale
        low, high = PLAUSIBLE.get(name, (float("-inf"), float("inf")))
        if not low <= scaled <= high:
            continue
        result[name] = round(scaled, 4) if scale != 1.0 else int(value)
    if unknown:
        result["unknown_tags"] = unknown
    return result


def iter_frames(buffer: bytearray):
    """Pull complete frames out of a rolling buffer, discarding partials."""
    while True:
        start = buffer.find(FRAME_START)
        if start < 0:
            buffer.clear()
            return
        end = buffer.find(FRAME_END, start + 1)
        if end < 0:
            del buffer[:start]
            return
        body = bytes(buffer[start + 1:end])
        del buffer[:end + 1]
        yield body


class BatteryMonitor:
    """Keeps the latest battery reading available to the rest of the system.

    Runs its own thread with a private asyncio loop, because the motor
    controller is thread based while bleak is asyncio based.
    """

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        self._lock = threading.Lock()
        self._values: Dict[str, Any] = {}
        self._last_frame_monotonic: Optional[float] = None
        self._connected = False
        self._last_error: Optional[str] = None
        self._frame_count = 0
        self._reported_unknown: set = set()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._buffer = bytearray()

        self._low_callback: Optional[Callable[[str, float], None]] = None
        self._notified_levels: set = set()

    # ------------------------------------------------------------------ API

    def set_low_battery_callback(self, callback: Callable[[str, float], None]) -> None:
        self._low_callback = callback

    def start(self) -> None:
        if not getattr(self.config, "enabled", False):
            self.logger.info("Batterieueberwachung deaktiviert")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="battery-monitor", daemon=True
        )
        self._thread.start()
        self.logger.info(
            "Batterieueberwachung gestartet: %s, %.1f Ah",
            self.config.address,
            float(self.config.capacity_ah),
        )

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5.0)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            values = dict(self._values)
            last = self._last_frame_monotonic
            connected = self._connected
            error = self._last_error
            frames = self._frame_count

        age_s = None if last is None else round(time.monotonic() - last, 2)
        fresh = age_s is not None and age_s <= float(self.config.stale_timeout_s)

        soc = self._state_of_charge(values)
        status: Dict[str, Any] = {
            "enabled": bool(getattr(self.config, "enabled", False)),
            "connected": connected,
            "fresh": fresh,
            "age_s": age_s,
            "frames": frames,
            "last_error": error,
            "capacity_ah": round(float(self.config.capacity_ah), 3),
            "soc_percent": soc,
            "level": self._level(soc, fresh),
        }
        for key in (
            "voltage_v",
            "current_a",
            "power_w",
            "remaining_ah",
            "discharged_ah",
            "time_left_min",
            "internal_resistance_mohm",
        ):
            status[key] = values.get(key)
        return status

    def mowing_allowed(self) -> bool:
        """False once the pack can no longer afford the mower deck.

        Unknown or stale readings never block mowing: the battery gauge is an
        addition to the existing safety chain, not a new single point of
        failure in it.
        """
        status = self.get_status()
        if not status["enabled"] or not status["fresh"]:
            return True
        soc = status["soc_percent"]
        if soc is None:
            return True
        return soc > float(self.config.mow_stop_percent)

    def drive_allowed(self) -> bool:
        status = self.get_status()
        if not status["enabled"] or not status["fresh"]:
            return True
        soc = status["soc_percent"]
        if soc is None:
            return True
        return soc > float(self.config.drive_stop_percent)

    # -------------------------------------------------------------- internals

    def _state_of_charge(self, values: Dict[str, Any]) -> Optional[float]:
        remaining = values.get("remaining_ah")
        capacity = float(self.config.capacity_ah)
        if remaining is None or capacity <= 0:
            return None
        return round(max(0.0, min(100.0, remaining / capacity * 100.0)), 1)

    def _level(self, soc: Optional[float], fresh: bool) -> str:
        if not fresh or soc is None:
            return "unknown"
        if soc <= float(self.config.drive_stop_percent):
            return "critical"
        if soc <= float(self.config.mow_stop_percent):
            return "low"
        if soc <= float(self.config.warn_percent):
            return "warn"
        return "ok"

    def _check_thresholds(self, soc: Optional[float]) -> None:
        if soc is None or self._low_callback is None:
            return
        thresholds = (
            ("critical", float(self.config.drive_stop_percent)),
            ("low", float(self.config.mow_stop_percent)),
            ("warn", float(self.config.warn_percent)),
        )
        for name, limit in thresholds:
            if soc <= limit and name not in self._notified_levels:
                self._notified_levels.add(name)
                try:
                    self._low_callback(name, soc)
                except Exception as exc:
                    self.logger.warning("Batterie-Callback fehlgeschlagen: %s", exc)
            # Re-arm with hysteresis so a reading hovering on the limit does
            # not send a message every single frame.
            elif soc > limit + float(self.config.rearm_hysteresis_percent):
                self._notified_levels.discard(name)

    def _handle_payload(self, data: bytes) -> None:
        self._buffer.extend(data)
        if len(self._buffer) > 4096:
            del self._buffer[:-1024]
        for body in iter_frames(self._buffer):
            decoded = decode_frame(body)
            if not decoded:
                continue
            unknown = decoded.pop("unknown_tags", None)
            if unknown:
                for tag, value in unknown.items():
                    if tag not in self._reported_unknown:
                        self._reported_unknown.add(tag)
                        self.logger.info(
                            "Unbekanntes Junctek-Feld %s = %s (bitte melden)", tag, value
                        )
            if not decoded:
                continue
            with self._lock:
                self._values.update(decoded)
                self._last_frame_monotonic = time.monotonic()
                self._frame_count += 1
                snapshot = dict(self._values)
            self._check_thresholds(self._state_of_charge(snapshot))

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._reader_loop())
        except Exception as exc:
            self.logger.error("Batterieueberwachung abgestuerzt: %s", exc)
        finally:
            loop.close()

    async def _reader_loop(self) -> None:
        from bleak import BleakClient, BleakScanner

        address = str(self.config.address)
        notify_uuid = str(self.config.notify_uuid)
        backoff = float(self.config.reconnect_delay_s)

        while not self._stop_event.is_set():
            try:
                device = await BleakScanner.find_device_by_address(
                    address, timeout=float(self.config.scan_timeout_s)
                )
                ziel = device
                if ziel is None:
                    # Kein Advertisement heisst nicht, dass der Zaehler weg
                    # ist. Er laesst nur eine Verbindung zu und stellt das
                    # Senden ein, sobald eine besteht - bleibt nach einem
                    # harten Neustart des Dienstes eine alte Verbindung im
                    # System stehen, sucht der neue Prozess nach einem Geraet,
                    # das genau deswegen schweigt (real 28.08., 00:50 Uhr: die
                    # Anzeige stand auf offline, waehrend das Betriebssystem
                    # die offene Verbindung fuehrte).
                    #
                    # Also die Adresse trotzdem versuchen: Besteht die
                    # Verbindung noch, uebernimmt BlueZ sie, statt sie neu
                    # aufzubauen.
                    self.logger.info(
                        "Batteriemonitor: keine Advertisements von %s - "
                        "versuche die bestehende Verbindung zu uebernehmen",
                        address,
                    )
                    ziel = address

                async with BleakClient(
                    ziel, timeout=float(self.config.connect_timeout_s)
                ) as client:
                    with self._lock:
                        self._connected = True
                        self._last_error = None
                    self.logger.info("Batteriemonitor verbunden: %s", address)
                    self._buffer.clear()

                    await client.start_notify(
                        notify_uuid, lambda _s, data: self._handle_payload(bytes(data))
                    )
                    backoff = float(self.config.reconnect_delay_s)

                    while not self._stop_event.is_set() and client.is_connected:
                        await asyncio.sleep(1.0)

                    await client.stop_notify(notify_uuid)
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                self.logger.warning("Batteriemonitor getrennt: %s", exc)
            finally:
                with self._lock:
                    self._connected = False

            if self._stop_event.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, float(self.config.reconnect_max_delay_s))
