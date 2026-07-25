#!/usr/bin/env python3
"""ODrive mower-deck transport over native ODrive USB/Fibre."""

import logging
import struct
import threading
import time
from typing import Any

from .odrive_mower import (
    AXIS_STATE_IDLE,
    AXIS_ERROR_WATCHDOG_TIMER_EXPIRED,
    CMD_CLEAR_ERRORS,
    CMD_GET_IQ,
    CMD_GET_SENSORLESS_ESTIMATES,
    CMD_SET_AXIS_STATE,
    CMD_SET_INPUT_VEL,
    CMD_SET_LIMITS,
    ODriveMowerController,
)

try:
    import odrive

    ODRIVE_USB_AVAILABLE = True
except ImportError:
    odrive = None
    ODRIVE_USB_AVAILABLE = False


class ODriveUSBMowerController(ODriveMowerController):
    """Runs the existing mower safety logic through two direct USB links.

    Logical ``node_id`` values remain part of the public status API, but they
    only identify an entry in ``usb_axes``. No CAN traffic is generated.
    """

    transport = "usb"

    def __init__(self, config, safety_monitor=None, odrive_module=None):
        super().__init__(config, can_handler=None, safety_monitor=safety_monitor)
        self.logger = logging.getLogger(__name__)
        self._odrive = odrive_module if odrive_module is not None else odrive
        self._usb_specs = self._parse_usb_specs(getattr(config, "usb_axes", []))
        self._boards: dict[str, Any] = {}
        self._axes: dict[int, Any] = {}
        self._board_locks: dict[str, threading.RLock] = {}
        self._axis_serials = {
            node_id: spec["serial_number"] for node_id, spec in self._usb_specs.items()
        }
        self._connection_lock = threading.RLock()
        self._usb_metadata: dict[str, dict[str, Any]] = {}
        self._last_connect_attempt = {serial: 0.0 for serial in set(self._axis_serials.values())}
        self._idle_poll_index = 0
        self._watchdog_cleanup_pending = False

    def _parse_usb_specs(self, specs) -> dict[int, dict[str, Any]]:
        parsed = {}
        for raw in specs or []:
            node_id = int(raw["node_id"])
            serial = str(raw["serial_number"]).strip().upper().removeprefix("0X")
            axis_index = int(raw["axis"])
            if not serial or axis_index not in (0, 1):
                raise ValueError(f"Ungueltige ODrive-USB-Zuordnung: {raw}")
            if node_id in parsed:
                raise ValueError(f"Doppelte ODrive-USB-Node-ID: {node_id}")
            parsed[node_id] = {
                "node_id": node_id,
                "serial_number": serial,
                "axis": axis_index,
            }
        missing = sorted(set(self.node_ids) - set(parsed))
        extra = sorted(set(parsed) - set(self.node_ids))
        if missing or extra:
            raise ValueError(
                f"ODrive-USB-Zuordnung passt nicht zu node_ids; missing={missing}, extra={extra}"
            )
        return parsed

    @staticmethod
    def _serial_text(board) -> str:
        return f"{int(board.serial_number):012X}"

    def _connect_serial(self, serial: str) -> None:
        if self._odrive is None:
            raise RuntimeError("ODrive-Pythonpaket nicht verfuegbar")
        timeout_s = float(getattr(self.config, "usb_connect_timeout_s", 5.0))
        board = self._odrive.find_any(serial_number=serial, timeout=timeout_s)
        actual = self._serial_text(board)
        if actual != serial:
            raise RuntimeError(f"Falsches ODrive: erwartet {serial}, gefunden {actual}")

        firmware = (
            int(board.fw_version_major),
            int(board.fw_version_minor),
            int(board.fw_version_revision),
        )
        hardware = (
            int(board.hw_version_major),
            int(board.hw_version_minor),
            int(board.hw_version_variant),
        )
        board_lock = self._board_locks.setdefault(serial, threading.RLock())
        with self._connection_lock:
            self._boards[serial] = board
            for node_id, spec in self._usb_specs.items():
                if spec["serial_number"] == serial:
                    self._axes[node_id] = getattr(board, f"axis{spec['axis']}")
            self._usb_metadata[serial] = {
                "online": True,
                "firmware": ".".join(str(value) for value in firmware),
                "hardware": ".".join(str(value) for value in hardware),
                "vbus_voltage": None,
                "last_error": None,
            }
        with board_lock:
            vbus = float(board.vbus_voltage)
        self._usb_metadata[serial]["vbus_voltage"] = round(vbus, 3)
        self.logger.info(
            "ODrive USB verbunden: serial=%s fw=%s hw=%s vbus=%.3fV",
            serial,
            firmware,
            hardware,
            vbus,
        )

    def _mark_disconnected(self, serial: str, exc: Exception) -> None:
        with self._connection_lock:
            self._boards.pop(serial, None)
            for node_id, axis_serial in self._axis_serials.items():
                if axis_serial == serial:
                    self._axes.pop(node_id, None)
            metadata = self._usb_metadata.setdefault(serial, {})
            metadata.update({"online": False, "last_error": str(exc)})

    def _connect_missing(self) -> None:
        reconnect_s = max(0.2, float(getattr(self.config, "usb_reconnect_interval_s", 1.0)))
        now = time.monotonic()
        for serial in sorted(set(self._axis_serials.values())):
            with self._connection_lock:
                connected = serial in self._boards
            if connected or now - self._last_connect_attempt.get(serial, 0.0) < reconnect_s:
                continue
            self._last_connect_attempt[serial] = now
            try:
                self._connect_serial(serial)
            except Exception as exc:
                self._mark_disconnected(serial, exc)
                self.logger.warning("ODrive USB %s nicht erreichbar: %s", serial, exc)

    def _axis_and_lock(self, node_id: int):
        node_id = int(node_id)
        serial = self._axis_serials.get(node_id)
        with self._connection_lock:
            axis = self._axes.get(node_id)
        if serial is None or axis is None:
            raise RuntimeError(f"ODrive USB node {node_id} nicht verbunden")
        return serial, axis, self._board_locks[serial]

    def _run_axis_operation(self, node_id: int, operation) -> Any:
        serial, axis, board_lock = self._axis_and_lock(node_id)
        try:
            with board_lock:
                return operation(axis, self._boards[serial])
        except Exception as exc:
            self._mark_disconnected(serial, exc)
            raise RuntimeError(f"ODrive USB {serial}/node {node_id}: {exc}") from exc

    @staticmethod
    def _clear_axis_errors(axis, board) -> None:
        if hasattr(board, "clear_errors"):
            board.clear_errors()
            return
        # Old unreleased firmware has no board-level clear_errors function.
        for obj in (
            axis,
            axis.motor,
            axis.encoder,
            axis.controller,
            axis.sensorless_estimator,
        ):
            try:
                obj.error = 0
            except (AttributeError, TypeError):
                pass

    def _send(self, node_id: int, command_id: int, data: bytes = b"") -> None:
        def operation(axis, board):
            if command_id == CMD_SET_INPUT_VEL:
                turns_per_second = struct.unpack("<fhh", bytes(data))[0]
                axis.controller.input_vel = float(turns_per_second)
                # Fibre property writes do not implicitly guarantee a watchdog
                # feed on all old firmware variants, so feed it explicitly.
                axis.watchdog_feed()
            elif command_id == CMD_SET_AXIS_STATE:
                axis.requested_state = struct.unpack("<I", bytes(data))[0]
            elif command_id == CMD_SET_LIMITS:
                velocity_limit, current_limit = struct.unpack("<ff", bytes(data))
                axis.controller.config.vel_limit = float(velocity_limit)
                axis.motor.config.current_lim = float(current_limit)
            elif command_id == CMD_CLEAR_ERRORS:
                self._clear_axis_errors(axis, board)
            else:
                raise ValueError(f"Nicht unterstuetztes USB-Kommando 0x{command_id:03X}")

        self._run_axis_operation(node_id, operation)

    def _send_rtr(self, node_id: int, command_id: int, dlc: int = 8) -> None:
        del dlc
        if command_id == CMD_GET_IQ:
            self._refresh_node(node_id, include_sensorless=False)
        elif command_id == CMD_GET_SENSORLESS_ESTIMATES:
            self._refresh_node(node_id, include_current=False)
        else:
            raise ValueError(f"Nicht unterstuetzte USB-Abfrage 0x{command_id:03X}")

    def clear_watchdog_errors(self) -> tuple[bool, str | None]:
        """Clear and verify only the expected USB watchdog startup error."""
        with self._lock:
            errors = dict(self.odrive_errors)
        nonzero = {node_id: value for node_id, value in errors.items() if value}
        unsafe = {
            node_id: value
            for node_id, value in nonzero.items()
            if value != AXIS_ERROR_WATCHDOG_TIMER_EXPIRED
        }
        if unsafe:
            details = ", ".join(
                f"node {node_id}=0x{value:08X}"
                for node_id, value in sorted(unsafe.items())
            )
            return False, f"Nicht-Watchdog-ODrive-Fehler aktiv: {details}"
        if not nonzero:
            return True, None

        for attempt in range(1, 4):
            try:
                # On both installed firmware generations the watchdog must be
                # fed around clear_errors; otherwise 0x800 can be re-latched
                # before the next status sample and a false Safety stop follows.
                for node_id in self.node_ids:
                    self._run_axis_operation(
                        node_id, lambda axis, _board: axis.watchdog_feed()
                    )
                self._send_all(CMD_CLEAR_ERRORS)
                for node_id in self.node_ids:
                    self._run_axis_operation(
                        node_id, lambda axis, _board: axis.watchdog_feed()
                    )
                time.sleep(0.05)
                for node_id in self.node_ids:
                    self._refresh_node(node_id)
                with self._lock:
                    remaining = {
                        node_id: value
                        for node_id, value in self.odrive_errors.items()
                        if value
                    }
                if not remaining:
                    return True, None
            except Exception as exc:
                remaining = {"transport": str(exc)}
            self.logger.warning(
                "ODrive USB-Watchdog-Clear noch nicht bestaetigt: attempt=%d remaining=%s",
                attempt,
                remaining,
            )
        return False, f"ODrive USB-Watchdogfehler blieb aktiv: {remaining}"

    def _set_watchdog_enabled(self, node_id: int, enabled: bool) -> None:
        """Keep the hardware watchdog armed only while blades may run."""
        def operation(axis, _board):
            axis.config.watchdog_timeout = max(
                1.0,
                float(getattr(self.config, "usb_watchdog_timeout_s", 3.0)),
            )
            axis.config.enable_watchdog = bool(enabled)
            if enabled:
                axis.watchdog_feed()

        self._run_axis_operation(node_id, operation)

    def _set_all_watchdogs(self, enabled: bool) -> None:
        errors = []
        for node_id in self.node_ids:
            try:
                self._set_watchdog_enabled(node_id, enabled)
            except Exception as exc:
                errors.append(f"node {node_id}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))

    def _prepare_start_transport(self) -> None:
        # Waiting axes must remain disarmed. Node 0 takes around two seconds
        # to validate, so later axes are armed only when their own sequential
        # start begins.
        self._set_all_watchdogs(False)
        cleared, error = self.clear_watchdog_errors()
        if not cleared:
            raise RuntimeError(error or "ODrive-Watchdogfehler nicht loeschbar")

    def _prepare_node_start_transport(self, node_id: int) -> None:
        # Runtime-only: a validated/running axis remains armed, while later
        # axes are enabled only immediately before their own first command.
        self._set_watchdog_enabled(node_id, True)

    def _prepare_parallel_start_transport(self) -> None:
        self._set_all_watchdogs(True)

    def _finalize_start_transport(self) -> None:
        # Feed all watchdogs first, then refresh every node. During a
        # sequential start node 0's last status sample can otherwise be older
        # than usb_status_timeout_s by the time node 2 has validated.
        for node_id in self.node_ids:
            self._set_node_input_rpm(node_id, self.commanded_rpm)
        for node_id in self.node_ids:
            self._refresh_node(node_id, include_sensorless=False)

    def _cleanup_failed_start_transport(self) -> None:
        try:
            self._set_all_watchdogs(False)
        except Exception as exc:
            self.logger.warning("ODrive USB-Watchdogs nach Startfehler nicht deaktiviert: %s", exc)

    def _refresh_node(
        self,
        node_id: int,
        *,
        include_current: bool = True,
        include_sensorless: bool = True,
    ) -> None:
        def operation(axis, board):
            sample = {
                "error": int(axis.error),
                "state": int(axis.current_state),
                "vbus": float(board.vbus_voltage),
            }
            if include_current:
                sample["iq_setpoint"] = float(axis.motor.current_control.Iq_setpoint)
                sample["iq_measured"] = float(axis.motor.current_control.Iq_measured)
            if include_sensorless:
                try:
                    sample["position"] = float(axis.sensorless_estimator.pos_estimate)
                except AttributeError:
                    # v3.x firmware 0.5.x and the old unreleased Board-B build
                    # expose the same estimate as ``pll_pos``.
                    sample["position"] = float(axis.sensorless_estimator.pll_pos)
                sample["velocity"] = float(axis.sensorless_estimator.vel_estimate)
            return sample

        sample = self._run_axis_operation(node_id, operation)
        serial = self._axis_serials[int(node_id)]
        self._usb_metadata[serial]["online"] = True
        self._usb_metadata[serial]["last_error"] = None
        self._usb_metadata[serial]["vbus_voltage"] = round(sample["vbus"], 3)
        self.on_heartbeat(int(node_id), sample["error"], sample["state"])
        if include_current:
            self.on_iq(int(node_id), sample["iq_setpoint"], sample["iq_measured"])
        if include_sensorless:
            self.on_sensorless_estimates(
                int(node_id), sample["position"], sample["velocity"]
            )

    def start_monitor(self) -> None:
        if self._monitor_worker and self._monitor_worker.is_alive():
            return
        self._monitor_stop_event.clear()
        # Native Fibre discovery takes several seconds per board. Complete the
        # first discovery and status sample before the central safety watchdog
        # starts, otherwise its old 5 s CAN startup grace produces a false
        # system stop while two healthy USB boards are still being opened.
        self._connect_missing()
        for node_id in self.node_ids:
            try:
                self._refresh_node(node_id)
            except Exception as exc:
                self.logger.warning("ODrive USB initialer Poll fehlgeschlagen: %s", exc)
        # IDLE axes need no watchdog. Disabling it removes the continuous feed
        # traffic that previously produced 0x800 errors between mower runs.
        self._set_all_watchdogs(False)
        cleared, clear_error = self.clear_watchdog_errors()
        if not cleared:
            self.logger.warning("ODrive USB Startbereinigung fehlgeschlagen: %s", clear_error)
        self._monitor_worker = threading.Thread(
            target=self._usb_monitor_loop,
            name="odrive-usb-monitor",
            daemon=True,
        )
        self._monitor_worker.start()
        self.logger.info("ODrive USB-Monitor gestartet: nodes=%s", self.node_ids)

    def _should_feed_idle_watchdog(self, node_id: int) -> bool:
        with self._lock:
            return bool(
                not self._system_stop_pending
                and self.odrive_states.get(int(node_id)) == AXIS_STATE_IDLE
            )

    def _usb_monitor_loop(self) -> None:
        interval_s = max(
            0.2,
            float(getattr(self.config, "usb_idle_poll_interval_s", 0.5)),
        )
        while not self._monitor_stop_event.is_set():
            self._connect_missing()
            with self._lock:
                busy = bool(self.running or self.startup_status.get('active'))
            # During start the validation loop owns Fibre; while running the
            # command loop writes and polls round-robin. A second high-rate
            # telemetry loop overloaded the old native Fibre transport.
            if not busy and self.node_ids:
                node_id = self.node_ids[self._idle_poll_index % len(self.node_ids)]
                self._idle_poll_index += 1
                try:
                    self._refresh_node(node_id)
                    self._cleanup_idle_watchdogs_if_ready()
                except Exception as exc:
                    now = time.monotonic()
                    if now - self._last_poll_error_log >= 5.0:
                        self._last_poll_error_log = now
                        self.logger.warning("ODrive USB-Poll fehlgeschlagen: %s", exc)
            self._monitor_stop_event.wait(interval_s)

    def _cleanup_idle_watchdogs_if_ready(self) -> None:
        with self._lock:
            pending = self._watchdog_cleanup_pending
            all_idle = not self._active_axis_nodes_locked()
        if not pending or not all_idle:
            return
        try:
            self._set_all_watchdogs(False)
            cleared, error = self.clear_watchdog_errors()
            if not cleared:
                self.logger.warning(
                    "ODrive USB-Watchdog-Nachbereitung fehlgeschlagen: %s",
                    error,
                )
                return
            with self._lock:
                self._watchdog_cleanup_pending = False
        except Exception as exc:
            self.logger.warning(
                "ODrive USB-Watchdogs nach verzoegertem IDLE nicht bereinigt: %s",
                exc,
            )

    def _schedule_or_run_watchdog_cleanup(self, status) -> None:
        active_nodes = list(status.get('active_axis_nodes') or [])
        with self._lock:
            self._watchdog_cleanup_pending = True
        if not active_nodes:
            self._cleanup_idle_watchdogs_if_ready()

    def stop(self):
        status = super().stop()
        self._schedule_or_run_watchdog_cleanup(status)
        return status

    def emergency_stop(self, reason: str):
        status = super().emergency_stop(reason)
        self._schedule_or_run_watchdog_cleanup(status)
        return status

    def get_status(self, success: bool = True, error: str | None = None):
        status = super().get_status(success=success, error=error)
        with self._connection_lock:
            usb_boards = {
                serial: dict(metadata) for serial, metadata in self._usb_metadata.items()
            }
        status.update({"transport": self.transport, "usb_boards": usb_boards})
        return status

    def cleanup(self) -> None:
        if self.running:
            self.stop()
        self.stop_monitor()
