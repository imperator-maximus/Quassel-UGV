#!/usr/bin/env python3
"""ODrive/ODESC mower deck control over SimpleCAN."""

import logging
import math
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
CMD_GET_IQ = 0x014
CMD_CLEAR_ERRORS = 0x018

AXIS_STATE_IDLE = 1
AXIS_ERROR_WATCHDOG_TIMER_EXPIRED = 0x00000800


class ODriveMowerController:
    """Keeps an ODrive axis running at a requested RPM until stopped."""

    def __init__(self, config, can_handler, safety_monitor=None):
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.can_handler = can_handler
        self.safety_monitor = safety_monitor
        self.enabled = bool(config.enabled)
        self.running = False
        self.target_rpm = int(config.default_rpm)
        self.commanded_rpm = 0
        self.last_error = None
        self.node_ids = self._configured_node_ids()
        self.odrive_errors = {node_id: 0 for node_id in self.node_ids}
        self.odrive_states = {node_id: 1 for node_id in self.node_ids}
        self.odrive_last_seen = {node_id: 0.0 for node_id in self.node_ids}
        self.odrive_iq = {
            node_id: {'setpoint_a': None, 'measured_a': None, 'last_seen': 0.0}
            for node_id in self.node_ids
        }
        self._overcurrent_since = {node_id: None for node_id in self.node_ids}
        self._critical_current_since = {node_id: None for node_id in self.node_ids}
        self._run_started_monotonic = 0.0
        self._system_stop_callback = None
        self._system_stop_pending = False
        self.odrive_error = 0
        self.odrive_state = 1
        self._lock = threading.Lock()
        self._op_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker = None
        self._monitor_stop_event = threading.Event()
        self._monitor_worker = None
        self._startup_watchdog_clear_pending = False
        self._startup_watchdog_clear_done = False
        self._last_poll_error_log = 0.0

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

    def _send_rtr(self, node_id: int, command_id: int, dlc: int = 8) -> None:
        """Sendet einen Classical-CAN RTR-Request ohne Nutzdaten."""
        if not CAN_AVAILABLE:
            raise RuntimeError("python-can nicht verfuegbar")
        if not self.can_handler or not self.can_handler.can_bus:
            raise RuntimeError("CAN-Bus nicht verfuegbar")
        message = can.Message(
            arbitration_id=self._arbitration_id(node_id, command_id),
            is_extended_id=False,
            is_remote_frame=True,
            dlc=int(dlc),
        )
        self.can_handler.can_bus.send(message, timeout=1.0)

    def set_system_stop_callback(self, callback) -> None:
        """Registriert den zentralen Stopp fuer Fahrantrieb und Maehdeck."""
        self._system_stop_callback = callback

    def _motion_allowed(self) -> bool:
        if self.safety_monitor and hasattr(self.safety_monitor, 'is_motion_allowed'):
            return bool(self.safety_monitor.is_motion_allowed())
        return True

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
            if not self._motion_allowed():
                return self.get_status(
                    success=False,
                    error="Sicherheitsstopp ist verriegelt; zuerst Safety-Reset ausfuehren",
                )

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
                self._run_started_monotonic = time.monotonic()
                self._system_stop_pending = False
                for node_id in self.node_ids:
                    self.odrive_iq[node_id] = {
                        'setpoint_a': None,
                        'measured_a': None,
                        'last_seen': 0.0,
                    }
                    self._overcurrent_since[node_id] = None
                    self._critical_current_since[node_id] = None

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
                self._request_system_stop(f"ODrive Start fehlgeschlagen: {exc}")
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

    def emergency_stop(self, reason: str) -> Dict[str, Any]:
        """Stoppt das Deck sofort und best-effort, auch bei defektem CAN."""
        self._stop_event.set()
        with self._lock:
            self.running = False
            self.commanded_rpm = 0
            self.last_error = str(reason)
            self._system_stop_pending = True

        errors = []
        data = struct.pack("<I", AXIS_STATE_IDLE)
        for node_id in self.node_ids:
            try:
                self._send(node_id, CMD_SET_AXIS_STATE, data)
            except Exception as exc:
                errors.append(f"node {node_id}: {exc}")
        if errors:
            self.logger.error("ODrive Notstopp nur teilweise gesendet: %s", "; ".join(errors))
        self.logger.critical("ODrive-Maehdeck Sicherheitsstopp: %s", reason)
        return self.get_status(success=not errors)

    def _request_system_stop(self, reason: str) -> None:
        """Verriegelt den lokalen Fehler und fordert asynchron Gesamtstopp an."""
        with self._lock:
            if self._system_stop_pending:
                return
            self._system_stop_pending = True
            self.running = False
            self.commanded_rpm = 0
            self.last_error = str(reason)
            self._stop_event.set()

        self.logger.critical("Maehdeck-Sicherheitsfehler: %s", reason)
        callback = self._system_stop_callback
        if callback:
            threading.Thread(
                target=self._invoke_system_stop,
                args=(callback, str(reason)),
                daemon=True,
            ).start()
        else:
            self.emergency_stop(str(reason))

    def _invoke_system_stop(self, callback, reason: str) -> None:
        try:
            callback(reason)
        except Exception as exc:
            self.logger.exception("Zentraler Sicherheitsstopp fehlgeschlagen: %s", exc)
            self.emergency_stop(reason)

    def _poll_currents(self) -> None:
        for node_id in self.node_ids:
            self._send_rtr(node_id, CMD_GET_IQ, dlc=8)

    def start_monitor(self) -> None:
        """Startet die Stromueberwachung; IDLE-Polling ist optional."""
        if self._monitor_worker and self._monitor_worker.is_alive():
            return
        self._monitor_stop_event.clear()
        self._startup_watchdog_clear_pending = False
        self._startup_watchdog_clear_done = False
        self._monitor_worker = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_worker.start()
        self.logger.info("ODrive CAN-Strommonitor gestartet: nodes=%s", self.node_ids)

    def stop_monitor(self) -> None:
        self._monitor_stop_event.set()
        worker = self._monitor_worker
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=1.0)

    def _monitor_loop(self) -> None:
        interval_s = float(getattr(self.config, 'current_poll_interval_s', 0.1))
        while not self._monitor_stop_event.wait(max(0.02, interval_s)):
            try:
                with self._lock:
                    running = self.running
                    safety_stopped = self._system_stop_pending
                poll_while_idle = bool(
                    getattr(self.config, 'current_poll_while_idle', False)
                )
                # Im Betrieb fragt ausschliesslich der Kommando-Thread GET_IQ
                # ab. Stirbt er, darf dieser Monitor den Hardware-Watchdog
                # nicht weiterfuettern. Nach einem Safety-Stopp gilt dasselbe.
                # Ohne aktivierten ODrive-Hardware-Watchdog erzeugen Abfragen
                # im IDLE nur unnoetigen RTR-Verkehr auf dem gemeinsamen Bus.
                if not running and not safety_stopped and poll_while_idle:
                    self._poll_currents()
            except Exception as exc:
                # Der zentrale CAN-Watchdog entscheidet anhand der empfangenen
                # Heartbeats. Hier nicht blockieren oder bei Systemstart latched
                # stoppen, waehrend SocketCAN noch hochkommt.
                now = time.monotonic()
                if now - self._last_poll_error_log >= 5.0:
                    self._last_poll_error_log = now
                    self.logger.warning("ODrive GET_IQ Poll fehlgeschlagen: %s", exc)

    def clear_watchdog_errors(self) -> tuple[bool, str | None]:
        """Loescht ausschliesslich reine Watchdog-Fehler nach CAN-Wiederkehr."""
        with self._lock:
            errors = dict(self.odrive_errors)
        nonzero = {node_id: error for node_id, error in errors.items() if error != 0}
        if not nonzero:
            return True, None
        unsafe = {
            node_id: error
            for node_id, error in nonzero.items()
            if error != AXIS_ERROR_WATCHDOG_TIMER_EXPIRED
        }
        if unsafe:
            details = ", ".join(
                f"node {node_id}=0x{error:08X}" for node_id, error in sorted(unsafe.items())
            )
            return False, f"Nicht-Watchdog-ODrive-Fehler aktiv: {details}"
        try:
            self._send_all(CMD_CLEAR_ERRORS)
        except Exception as exc:
            return False, f"Watchdog-Fehler konnten nicht geloescht werden: {exc}"
        return True, None

    def prepare_safety_reset(self) -> tuple[bool, str | None]:
        """Bereitet den expliziten Reset vor und startet IDLE-Polling erneut."""
        success, error = self.clear_watchdog_errors()
        if not success:
            return success, error
        with self._lock:
            self._system_stop_pending = False
        try:
            self._poll_currents()
        except Exception as exc:
            with self._lock:
                self._system_stop_pending = True
            return False, f"ODrive CAN-Poll nach Safety-Reset fehlgeschlagen: {exc}"
        return True, None

    def _maybe_clear_startup_watchdog_errors(self) -> None:
        """Bereinigt nur den erwartbaren Watchdog-Fehler vor Host-Start."""
        with self._lock:
            if self._startup_watchdog_clear_done or self._startup_watchdog_clear_pending:
                return
            if any(self.odrive_last_seen[node_id] <= 0.0 for node_id in self.node_ids):
                return
            if any(self.odrive_iq[node_id]['last_seen'] <= 0.0 for node_id in self.node_ids):
                return
            errors = list(self.odrive_errors.values())
            if not any(error == AXIS_ERROR_WATCHDOG_TIMER_EXPIRED for error in errors):
                if all(error == 0 for error in errors):
                    self._startup_watchdog_clear_done = True
                return
            if any(error not in (0, AXIS_ERROR_WATCHDOG_TIMER_EXPIRED) for error in errors):
                self._startup_watchdog_clear_done = True
                return
            self._startup_watchdog_clear_pending = True

        threading.Thread(target=self._clear_startup_watchdog_errors, daemon=True).start()

    def _clear_startup_watchdog_errors(self) -> None:
        success, error = self.clear_watchdog_errors()
        with self._lock:
            self._startup_watchdog_clear_pending = False
            self._startup_watchdog_clear_done = True
        if success:
            self.logger.info("ODrive Start-Watchdogfehler nach aktivem GET_IQ-Poll geloescht")
        else:
            self.logger.error("ODrive Start-Watchdogfehler blieb aktiv: %s", error)

    def _check_current_response_timeout(self, now: float) -> str | None:
        if not bool(getattr(self.config, 'current_monitor_enabled', True)):
            return None
        grace_s = float(getattr(self.config, 'current_startup_grace_s', 2.0))
        if now - self._run_started_monotonic <= grace_s:
            return None
        timeout_s = float(getattr(self.config, 'current_response_timeout_s', 0.75))
        with self._lock:
            missing = [
                node_id
                for node_id in self.node_ids
                if self.odrive_iq[node_id]['last_seen'] <= self._run_started_monotonic
                or now - self.odrive_iq[node_id]['last_seen'] > timeout_s
            ]
        if missing:
            return f"ODrive GET_IQ timeout: nodes {missing}"
        return None

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
                self._require_live_nodes()
                self._set_input_rpm(rpm)
                if bool(getattr(self.config, 'current_monitor_enabled', True)):
                    self._poll_currents()
                    timeout_error = self._check_current_response_timeout(time.monotonic())
                    if timeout_error:
                        self._request_system_stop(timeout_error)
                        return
            except Exception as exc:
                self._request_system_stop(f"ODrive-Maehdeck CAN-Fehler: {exc}")
                return

    def on_iq(self, node_id: int, iq_setpoint: float, iq_measured: float) -> None:
        """Verarbeitet GET_IQ und erkennt mechanische Ueberlastung."""
        node_id = int(node_id)
        if node_id not in self.node_ids:
            return

        now = time.monotonic()
        should_trip = False
        trip_current = 0.0
        invalid_sample = not (
            math.isfinite(float(iq_setpoint)) and math.isfinite(float(iq_measured))
        )
        with self._lock:
            self.odrive_iq[node_id] = {
                'setpoint_a': float(iq_setpoint),
                'measured_a': float(iq_measured),
                'last_seen': now,
            }
            monitoring_active = (
                self.running
                and bool(getattr(self.config, 'current_monitor_enabled', True))
                and now - self._run_started_monotonic > float(
                    getattr(self.config, 'current_startup_grace_s', 2.0)
                )
            )
            if not monitoring_active:
                self._overcurrent_since[node_id] = None
                self._critical_current_since[node_id] = None
            else:
                measured_abs = abs(float(iq_measured))
                threshold_a = float(getattr(self.config, 'current_trip_a', 25.0))
                critical_threshold_a = float(
                    getattr(self.config, 'current_critical_trip_a', 29.0)
                )
                if measured_abs >= threshold_a:
                    if self._overcurrent_since[node_id] is None:
                        self._overcurrent_since[node_id] = now
                    duration_s = now - self._overcurrent_since[node_id]
                    if duration_s >= float(
                        getattr(self.config, 'current_trip_duration_s', 0.5)
                    ):
                        should_trip = True
                        trip_current = measured_abs
                else:
                    self._overcurrent_since[node_id] = None

                if measured_abs >= critical_threshold_a:
                    if self._critical_current_since[node_id] is None:
                        self._critical_current_since[node_id] = now
                    critical_duration_s = now - self._critical_current_since[node_id]
                    if critical_duration_s >= float(
                        getattr(self.config, 'current_critical_trip_duration_s', 0.1)
                    ):
                        should_trip = True
                        trip_current = measured_abs
                else:
                    self._critical_current_since[node_id] = None

        if invalid_sample and monitoring_active:
            self._request_system_stop(f"ODrive ungueltige GET_IQ-Antwort: node={node_id}")
        elif should_trip:
            self._request_system_stop(
                f"ODrive Ueberstrom node={node_id}: {trip_current:.1f} A"
            )
        self._maybe_clear_startup_watchdog_errors()

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
        should_trip = False
        trip_reason = None
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
                    should_trip = True
                    trip_reason = f"ODrive node={node_id} error=0x{error:08X} state={state}"
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
        if should_trip:
            self._request_system_stop(trip_reason)
        self._maybe_clear_startup_watchdog_errors()

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
            currents = {
                node_id: {
                    'setpoint_a': self.odrive_iq[node_id]['setpoint_a'],
                    'measured_a': self.odrive_iq[node_id]['measured_a'],
                    'age_s': (
                        None
                        if self.odrive_iq[node_id]['last_seen'] <= 0.0
                        else round(time.monotonic() - self.odrive_iq[node_id]['last_seen'], 2)
                    ),
                }
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
            "odrive_currents": currents,
            "current_monitor_enabled": bool(getattr(self.config, 'current_monitor_enabled', True)),
            "current_trip_a": float(getattr(self.config, 'current_trip_a', 25.0)),
            "current_trip_duration_s": float(getattr(self.config, 'current_trip_duration_s', 0.5)),
            "current_critical_trip_a": float(getattr(self.config, 'current_critical_trip_a', 29.0)),
            "current_critical_trip_duration_s": float(
                getattr(self.config, 'current_critical_trip_duration_s', 0.1)
            ),
        }

    def cleanup(self) -> None:
        self.stop_monitor()
        if self.running:
            self.stop()
