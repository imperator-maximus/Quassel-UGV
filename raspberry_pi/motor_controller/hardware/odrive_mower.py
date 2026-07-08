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
        self.node_ids = self._configured_node_ids()
        self.odrive_errors = {node_id: 0 for node_id in self.node_ids}
        self.odrive_states = {node_id: 1 for node_id in self.node_ids}
        self.odrive_last_seen = {node_id: 0.0 for node_id in self.node_ids}
        self.odrive_error = 0
        self.odrive_state = 1
        self._lock = threading.Lock()
        self._op_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker = None

    def _configured_node_ids(self) -> list[int]:
        node_ids = getattr(self.config, "node_ids", None) or []
        if not node_ids:
            node_ids = [getattr(self.config, "node_id", 0)]
        return [int(node_id) for node_id in node_ids]

    def _arbitration_id(self, node_id: int, command_id: int) -> int:
        return (int(node_id) << 5) | command_id

    def _send(self, node_id: int, command_id: int, data: bytes = b"") -> None:
        if not CAN_AVAILABLE:
            raise RuntimeError("python-can nicht verfuegbar")
        if not self.can_handler or not self.can_handler.can_bus:
            raise RuntimeError("CAN-Bus nicht verfuegbar")
        message = can.Message(
            arbitration_id=self._arbitration_id(node_id, command_id),
            data=data,
            is_extended_id=False,
        )
        self.can_handler.can_bus.send(message, timeout=1.0)

    def _send_all(self, command_id: int, data: bytes = b"") -> None:
        errors = []
        for node_id in self.node_ids:
            try:
                self._send(node_id, command_id, data)
            except Exception as exc:
                errors.append(f"node {node_id}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))

    def _set_input_rpm(self, rpm: int) -> None:
        turns_per_second = float(rpm) / 60.0
        self._send_all(CMD_SET_INPUT_VEL, struct.pack("<fhh", turns_per_second, 0, 0))

    def _set_axis_state(self, state: int, stagger_s: float = 0.0) -> None:
        data = struct.pack("<I", int(state))
        errors = []
        for index, node_id in enumerate(self.node_ids):
            if index > 0 and stagger_s > 0:
                time.sleep(stagger_s)
            try:
                self._send(node_id, CMD_SET_AXIS_STATE, data)
            except Exception as exc:
                errors.append(f"node {node_id}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))

    def _clamp_rpm(self, rpm: int) -> int:
        return max(int(self.config.min_rpm), min(int(self.config.max_rpm), int(rpm)))

    def _missing_heartbeats_locked(self) -> list[int]:
        timeout_s = float(getattr(self.config, "heartbeat_timeout_s", 1.0))
        now = time.monotonic()
        return [
            node_id
            for node_id in self.node_ids
            if self.odrive_last_seen.get(node_id, 0.0) <= 0.0
            or now - self.odrive_last_seen[node_id] > timeout_s
        ]

    def _require_live_nodes(self) -> None:
        with self._lock:
            missing = self._missing_heartbeats_locked()
        if missing:
            raise RuntimeError(f"ODrive heartbeat timeout: nodes {missing}")

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
                self._require_live_nodes()
                self._send_all(CMD_CLEAR_ERRORS)
                time.sleep(0.2)
                self._set_input_rpm(self.commanded_rpm)
                self._set_axis_state(
                    self.config.axis_state,
                    stagger_s=float(getattr(self.config, "start_stagger_s", 0.0)),
                )
            except Exception as exc:
                self.last_error = str(exc)
                with self._lock:
                    self.running = False
                return self.get_status(success=False)

            self._worker = threading.Thread(target=self._command_loop, daemon=True)
            self._worker.start()
            self.logger.info(
                "ODrive-Maehdeck gestartet: nodes=%s rpm=%s",
                self.node_ids,
                self.target_rpm,
            )
            return self.get_status()

    def stop(self) -> Dict[str, Any]:
        with self._op_lock:
            self._stop_event.set()
            worker = self._worker
            if worker and worker.is_alive():
                worker.join(timeout=1.0)

            with self._lock:
                self.running = False
                self.commanded_rpm = 0

            try:
                self._require_live_nodes()
                # Direkt IDLE setzen – freies Auslaufen, kein aktives Bremsen.
                #
                # WICHTIG: brake_resistance ist aktuell 0.0 (kein Bremswider-
                # stand). Aktives Bremsen per Set_Input_Vel(0) wuerde Rueck-
                # energie in den DC-Bus treiben -> Ueberspannung -> ODrive-Crash.
                # IDLE entkoppelt den Regler sofort, der Motor laeuft frei aus.
                self._set_axis_state(AXIS_STATE_IDLE)
            except Exception as exc:
                self.last_error = str(exc)
                return self.get_status(success=False)

            self.logger.info("ODrive-Maehdeck gestoppt: nodes=%s", self.node_ids)
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

    def on_heartbeat(self, node_id: int, error: int, state: int) -> None:
        """Verarbeitet ODrive-Heartbeat-Nachrichten vom CAN-Reader.

        Wird vom CANHandler bei jedem empfangenen Heartbeat (cmd 0x01) gerufen.
        Speichert error/state fuer konfigurierte Achsen (config.node_ids)
        und aktualisiert ``last_error``, damit Web-App/UI ODrive-Fehler sehen.

        Bei error!=0 wird der ODrive-internen Fehlercode als Hex-String in
        ``last_error`` geschrieben, damit /api/status ihn als ``mower_error``
        meldet. Bei error=0 wird ein vorheriger ODrive-Fehler geloescht – aber
        nur wenn er von ODrive kam (nicht wenn er ein Python-CAN-Send-Fehler war).

        Args:
            node_id: ODrive-Knoten-ID aus der Arbitration-ID.
            error: ODrive-Fehlercode (0 = kein Fehler).
            state: ODrive-Axis-State (1=IDLE, 5=CLOSED_LOOP_SENSORLESS, ...).
        """
        if node_id not in self.node_ids:
            return
        with self._lock:
            prev_error = self.odrive_errors.get(int(node_id), 0)
            self.odrive_last_seen[int(node_id)] = time.monotonic()
            self.odrive_errors[int(node_id)] = int(error)
            self.odrive_states[int(node_id)] = int(state)
            self.odrive_error = max(self.odrive_errors.values(), default=0)
            self.odrive_state = int(state)
            if error != 0:
                self.last_error = f"ODrive node={node_id} error=0x{error:08X} state={state}"
                # Nur bei einem *neuen* Fehler (0 -> !=0) den Lauf abbrechen.
                # Bei stale-Fehlern, die schon vor start() da waren, nicht
                # tearing-down: sonst latched jeder Fehler-Heartbeat running
                # sofort wieder auf False und start() kann den ODrive nie per
                # Clear_Errors (0x018) entstoeren -> "nur einmal startbar".
                if prev_error == 0 and self.running:
                    self.running = False
                    self.commanded_rpm = 0
                    self._stop_event.set()
                self.logger.error(
                    "ODrive-Heartbeat Fehler: node=%d error=0x%08X state=%d",
                    node_id,
                    error,
                    state,
                )
            else:
                # ODrive-Fehler geloescht – aber Python-CAN-Send-Fehler bleiben
                if (
                    self.last_error
                    and self.last_error.startswith(f"ODrive node={node_id} error=")
                    and all(value == 0 for value in self.odrive_errors.values())
                ):
                    self.last_error = None

    def get_status(self, success: bool = True, error: str | None = None) -> Dict[str, Any]:
        with self._lock:
            running = self.running
            rpm = self.target_rpm
            commanded_rpm = self.commanded_rpm
        with self._lock:
            odrive_error = self.odrive_error
            odrive_state = self.odrive_state
            odrive_errors = dict(self.odrive_errors)
            odrive_states = dict(self.odrive_states)
            missing_heartbeats = self._missing_heartbeats_locked()
            heartbeat_ages = {
                node_id: (
                    None
                    if self.odrive_last_seen.get(node_id, 0.0) <= 0.0
                    else round(time.monotonic() - self.odrive_last_seen[node_id], 2)
                )
                for node_id in self.node_ids
            }
            status_error = error or self.last_error
            if missing_heartbeats and not status_error:
                status_error = f"ODrive heartbeat timeout: nodes {missing_heartbeats}"
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
            "node_id": int(self.node_ids[0]) if self.node_ids else int(self.config.node_id),
            "node_ids": list(self.node_ids),
            "axis_state": int(self.config.axis_state),
            "error": status_error,
            "odrive_error": odrive_error,
            "odrive_state": odrive_state,
            "odrive_errors": odrive_errors,
            "odrive_states": odrive_states,
            "odrive_missing_heartbeats": missing_heartbeats,
            "odrive_heartbeat_ages": heartbeat_ages,
        }

    def cleanup(self) -> None:
        if self.running:
            self.stop()
