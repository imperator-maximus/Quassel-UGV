#!/usr/bin/env python3
"""ODrive/ODESC mower deck control over SimpleCAN."""

import logging
import struct
import threading
import time
from typing import Dict, Any

try:
    import can
    CAN_AVAILABLE = True
except ImportError:
    CAN_AVAILABLE = False


CMD_SET_AXIS_STATE = 0x007
CMD_SET_INPUT_VEL = 0x00D
CMD_CLEAR_ERRORS = 0x018

AXIS_STATE_IDLE = 1


class ODriveMowerController:
    """Keeps an ODrive axis running at a requested RPM until stopped."""

    def __init__(self, config, can_handler):
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.can_handler = can_handler
        self.enabled = bool(config.enabled)
        self.running = False
        self.target_rpm = int(config.default_rpm)
        self.commanded_rpm = 0
        self.last_error = None
        self._lock = threading.Lock()
        self._op_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker = None

    def _arbitration_id(self, command_id: int) -> int:
        return (int(self.config.node_id) << 5) | command_id

    def _send(self, command_id: int, data: bytes = b"") -> None:
        if not CAN_AVAILABLE:
            raise RuntimeError("python-can nicht verfuegbar")
        if not self.can_handler or not self.can_handler.can_bus:
            raise RuntimeError("CAN-Bus nicht verfuegbar")
        message = can.Message(
            arbitration_id=self._arbitration_id(command_id),
            data=data,
            is_extended_id=False,
        )
        self.can_handler.can_bus.send(message, timeout=1.0)

    def _set_input_rpm(self, rpm: int) -> None:
        turns_per_second = float(rpm) / 60.0
        self._send(CMD_SET_INPUT_VEL, struct.pack("<fhh", turns_per_second, 0, 0))

    def _set_axis_state(self, state: int) -> None:
        self._send(CMD_SET_AXIS_STATE, struct.pack("<I", int(state)))

    def _clamp_rpm(self, rpm: int) -> int:
        return max(int(self.config.min_rpm), min(int(self.config.max_rpm), int(rpm)))

    def set_rpm(self, rpm: int) -> Dict[str, Any]:
        with self._lock:
            self.target_rpm = self._clamp_rpm(rpm)
            self.last_error = None
        return self.get_status()

    def start(self, rpm: int | None = None) -> Dict[str, Any]:
        with self._op_lock:
            if not self.enabled:
                return self.get_status(success=False, error="ODrive-Maehdeck ist deaktiviert")

            with self._lock:
                if rpm is not None:
                    self.target_rpm = self._clamp_rpm(rpm)
                elif self.target_rpm <= 0:
                    self.target_rpm = self._clamp_rpm(self.config.default_rpm)
                if self.running:
                    return self.get_status()
                self.running = True
                self.commanded_rpm = min(self.target_rpm, self._clamp_rpm(self.config.default_rpm))
                self.last_error = None
                self._stop_event.clear()

            try:
                self._send(CMD_CLEAR_ERRORS)
                time.sleep(0.2)
                self._set_input_rpm(self.commanded_rpm)
                self._set_axis_state(self.config.axis_state)
            except Exception as exc:
                self.last_error = str(exc)
                with self._lock:
                    self.running = False
                return self.get_status(success=False)

            self._worker = threading.Thread(target=self._command_loop, daemon=True)
            self._worker.start()
            self.logger.info("ODrive-Maehdeck gestartet: %s rpm", self.target_rpm)
            return self.get_status()

    def stop(self) -> Dict[str, Any]:
        with self._op_lock:
            self._stop_event.set()
            worker = self._worker
            if worker and worker.is_alive():
                worker.join(timeout=1.0)

            with self._lock:
                was_running = self.running
                self.running = False
                self.commanded_rpm = 0

            try:
                self._set_input_rpm(0)
                if was_running and self.config.coast_delay_s > 0:
                    time.sleep(float(self.config.coast_delay_s))
                self._set_axis_state(AXIS_STATE_IDLE)
            except Exception as exc:
                self.last_error = str(exc)
                return self.get_status(success=False)

            self.logger.info("ODrive-Maehdeck gestoppt")
            return self.get_status()

    def _command_loop(self) -> None:
        interval_s = float(self.config.command_interval_s)
        while not self._stop_event.wait(interval_s):
            with self._lock:
                if not self.running:
                    return
                max_step = max(1, int(float(self.config.ramp_rate_rpm_s) * interval_s))
                delta = self.target_rpm - self.commanded_rpm
                if abs(delta) <= max_step:
                    self.commanded_rpm = self.target_rpm
                else:
                    self.commanded_rpm += max_step if delta > 0 else -max_step
                rpm = self.commanded_rpm
            try:
                self._set_input_rpm(rpm)
            except Exception as exc:
                self.last_error = str(exc)
                self.logger.error("ODrive-Maehdeck CAN-Fehler: %s", exc)
                with self._lock:
                    self.running = False
                return

    def get_status(self, success: bool = True, error: str | None = None) -> Dict[str, Any]:
        with self._lock:
            running = self.running
            rpm = self.target_rpm
            commanded_rpm = self.commanded_rpm
        return {
            "success": success,
            "enabled": self.enabled,
            "running": running,
            "rpm": rpm,
            "commanded_rpm": commanded_rpm,
            "min_rpm": int(self.config.min_rpm),
            "max_rpm": int(self.config.max_rpm),
            "default_rpm": int(self.config.default_rpm),
            "ramp_rate_rpm_s": int(self.config.ramp_rate_rpm_s),
            "node_id": int(self.config.node_id),
            "axis_state": int(self.config.axis_state),
            "error": error or self.last_error,
        }

    def cleanup(self) -> None:
        if self.running:
            self.stop()
