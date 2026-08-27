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
CMD_SET_LIMITS = 0x00F
CMD_GET_IQ = 0x014
CMD_GET_SENSORLESS_ESTIMATES = 0x015
CMD_CLEAR_ERRORS = 0x018

AXIS_STATE_IDLE = 1
AXIS_ERROR_WATCHDOG_TIMER_EXPIRED = 0x00000800


# Der Motorfehler, bei dem sich das Nachfragen beim Gate-Treiber lohnt.
MOTOR_ERROR_DRV_FAULT = 0x00000008

# Statusbits des DRV8301, wie ODrive sie in get_drv_fault() zusammenfasst.
# Die Rohzahl steht immer mit in der Meldung: Faellt eine Zuordnung hier
# falsch aus, ist die Angabe des Bausteins trotzdem nicht verloren.
DRV_FAULT_BITS = (
    (0x0001, "FETLC_OC"),
    (0x0002, "FETHC_OC"),
    (0x0004, "FETLB_OC"),
    (0x0008, "FETHB_OC"),
    (0x0010, "FETLA_OC"),
    (0x0020, "FETHA_OC"),
    (0x0040, "Uebertemperatur-Warnung"),
    (0x0080, "Uebertemperatur-Abschaltung"),
    (0x0100, "PVDD_Unterspannung"),
    (0x0200, "Gate-Versorgung_Unterspannung"),
    (0x0400, "FAULT"),
)


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
        # Fehler der Unterobjekte je Knoten, nur solange einer anliegt.
        self.odrive_error_details = {}
        self.last_error = None
        self.node_ids = self._configured_node_ids()
        self.odrive_errors = {node_id: 0 for node_id in self.node_ids}
        self.odrive_states = {node_id: 1 for node_id in self.node_ids}
        self.odrive_last_seen = {node_id: 0.0 for node_id in self.node_ids}
        self.odrive_iq = {
            node_id: {'setpoint_a': None, 'measured_a': None, 'last_seen': 0.0}
            for node_id in self.node_ids
        }
        self.odrive_sensorless = {
            node_id: {'position': None, 'velocity': None, 'rpm': None, 'last_seen': 0.0}
            for node_id in self.node_ids
        }
        self.startup_status = {
            'active': False,
            'phase': None,
            'node_id': None,
            'attempt': 0,
            'validated_nodes': [],
            'last_result': None,
            'started_monotonic': None,
            'node_started_monotonic': None,
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
        self._current_poll_index = 0
        self._sensorless_poll_index = 0
        self._last_sensorless_poll = 0.0
        # Liveness of the command thread itself.  A synchronous transport call
        # can park that thread forever, and then no check that lives inside it
        # can ever fire again.  ``runtime_health`` is evaluated by the central
        # safety watchdog instead and uses this timestamp.  It is only
        # meaningful once the command thread actually owns the blades, which
        # ``_command_loop_expected`` marks.
        self._loop_alive_monotonic = 0.0
        self._command_loop_expected = False
        self._low_rpm_since = {node_id: None for node_id in self.node_ids}

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

    def _set_node_input_rpm(self, node_id: int, rpm: int) -> None:
        turns_per_second = float(rpm) / 60.0
        self._send(
            node_id,
            CMD_SET_INPUT_VEL,
            struct.pack("<fhh", turns_per_second, 0, 0),
        )

    def _set_node_axis_state(self, node_id: int, state: int) -> None:
        self._send(node_id, CMD_SET_AXIS_STATE, struct.pack("<I", int(state)))

    def _set_node_limits(self, node_id: int, current_limit_a: float) -> None:
        velocity_limit_tps = float(self.config.max_rpm) / 60.0
        self._send(
            node_id,
            CMD_SET_LIMITS,
            struct.pack("<ff", velocity_limit_tps, float(current_limit_a)),
        )

    def _poll_node_startup(self, node_id: int) -> None:
        self._send_rtr(node_id, CMD_GET_IQ, dlc=8)
        self._send_rtr(node_id, CMD_GET_SENSORLESS_ESTIMATES, dlc=8)

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

    def _active_axis_nodes_locked(self) -> list[int]:
        """Returns nodes whose latest heartbeat does not report IDLE."""
        return [
            node_id
            for node_id in self.node_ids
            if self.odrive_states.get(node_id, AXIS_STATE_IDLE) != AXIS_STATE_IDLE
        ]

    def _request_idle_verified(
        self,
        attempts: int = 6,
        verify_interval_s: float = 0.15,
    ) -> tuple[list[int], list[str]]:
        """Requests IDLE repeatedly and verifies it through fresh heartbeats.

        SocketCAN accepting a frame only proves that it was queued locally.
        A disturbed CAN receiver may miss one Set_Axis_State frame while its
        transmitted heartbeats remain visible.  A mower stop therefore needs
        retries plus confirmation from every configured axis.
        """
        data = struct.pack("<I", AXIS_STATE_IDLE)
        pending = list(self.node_ids)
        send_errors: list[str] = []
        attempts = max(1, int(attempts))
        verify_interval_s = max(0.02, float(verify_interval_s))

        for attempt in range(1, attempts + 1):
            targets = list(self.node_ids) if attempt == 1 else list(pending)
            for node_id in targets:
                try:
                    self._send(node_id, CMD_SET_AXIS_STATE, data)
                except Exception as exc:
                    send_errors.append(f"node {node_id}: {exc}")

            deadline = time.monotonic() + verify_interval_s
            while time.monotonic() < deadline:
                with self._lock:
                    pending = self._active_axis_nodes_locked()
                if not pending:
                    return [], send_errors
                time.sleep(0.02)

            self.logger.warning(
                "ODrive-IDLE noch nicht bestaetigt: attempt=%d/%d nodes=%s",
                attempt,
                attempts,
                pending,
            )

        with self._lock:
            pending = self._active_axis_nodes_locked()
        return pending, send_errors

    def _clamp_rpm(self, rpm: int) -> int:
        return max(int(self.config.min_rpm), min(int(self.config.max_rpm), int(rpm)))

    def _missing_heartbeats_locked(self) -> list[int]:
        timeout_name = (
            "usb_status_timeout_s"
            if getattr(self, "transport", "can") == "usb"
            else "heartbeat_timeout_s"
        )
        timeout_s = float(
            getattr(
                self.config,
                timeout_name,
                getattr(self.config, "heartbeat_timeout_s", 1.0),
            )
        )
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

    def _reset_startup_measurements(self, node_id: int) -> None:
        with self._lock:
            self.odrive_iq[node_id] = {
                'setpoint_a': None,
                'measured_a': None,
                'last_seen': 0.0,
            }
            self.odrive_sensorless[node_id] = {
                'position': None,
                'velocity': None,
                'rpm': None,
                'last_seen': 0.0,
            }

    def _startup_snapshot(self, node_id: int) -> dict:
        with self._lock:
            return {
                'error': self.odrive_errors.get(node_id, 0),
                'state': self.odrive_states.get(node_id, AXIS_STATE_IDLE),
                'iq': dict(self.odrive_iq[node_id]),
                'sensorless': dict(self.odrive_sensorless[node_id]),
                'system_stop_pending': self._system_stop_pending,
            }

    def _start_node_with_validation(
        self,
        node_id: int,
        already_running: list[int],
        rpm: int,
    ) -> tuple[bool, str | None]:
        timeout_s = float(getattr(self.config, 'startup_timeout_s', 2.5))
        retries = max(0, int(getattr(self.config, 'startup_retries', 1)))
        current_limit_a = float(
            getattr(self.config, 'startup_current_limit_a', 12.0)
        )
        abort_current_a = float(
            getattr(self.config, 'startup_abort_current_a', 12.5)
        )
        min_rpm = float(
            getattr(self.config, 'startup_min_sensorless_rpm', 120.0)
        )
        stable_duration_s = float(
            getattr(self.config, 'startup_stable_duration_s', 0.4)
        )
        operating_limit_a = float(
            getattr(self.config, 'operating_current_limit_a', 30.0)
        )
        interval_s = max(0.05, float(self.config.command_interval_s))
        last_reason = None

        for attempt in range(1, retries + 2):
            self._reset_startup_measurements(node_id)
            with self._lock:
                self.startup_status.update({
                    'active': True,
                    'phase': 'node',
                    'node_id': node_id,
                    'attempt': attempt,
                    'node_started_monotonic': time.monotonic(),
                })

            self._prepare_node_start_transport(node_id)
            self._send(node_id, CMD_CLEAR_ERRORS)
            time.sleep(0.1)
            self._set_node_limits(node_id, current_limit_a)
            self._set_node_input_rpm(node_id, rpm)
            self._set_node_axis_state(node_id, self.config.axis_state)

            started = time.monotonic()
            next_poll = started
            stable_since = None
            last_reason = f"Sensorless-Anlauf Timeout node={node_id}"

            while time.monotonic() - started < timeout_s:
                now = time.monotonic()
                snapshot = self._startup_snapshot(node_id)
                if snapshot['system_stop_pending'] or self._stop_event.is_set():
                    return False, self.last_error or f"Anlauf node={node_id} abgebrochen"

                if snapshot['error']:
                    last_reason = (
                        f"ODrive-Anlauffehler node={node_id}: "
                        f"0x{snapshot['error']:08X}"
                    )
                    break

                measured = snapshot['iq']['measured_a']
                iq_fresh = (
                    snapshot['iq']['last_seen'] > started and measured is not None
                )
                if measured is not None and abs(float(measured)) >= abort_current_a:
                    last_reason = (
                        f"ODrive Anlaufstrom node={node_id}: "
                        f"{abs(float(measured)):.1f} A"
                    )
                    break

                estimated_rpm = snapshot['sensorless']['rpm']
                estimate_fresh = (
                    snapshot['sensorless']['last_seen'] > started
                    and estimated_rpm is not None
                )
                state_ok = snapshot['state'] == int(self.config.axis_state)
                if (
                    iq_fresh
                    and estimate_fresh
                    and state_ok
                    and abs(float(estimated_rpm)) >= min_rpm
                ):
                    if stable_since is None:
                        stable_since = now
                    elif now - stable_since >= stable_duration_s:
                        self._set_node_limits(node_id, operating_limit_a)
                        self.logger.info(
                            "ODrive-Anlauf bestaetigt: node=%d attempt=%d rpm_est=%.1f iq=%.1f A",
                            node_id,
                            attempt,
                            float(estimated_rpm),
                            float(measured or 0.0),
                        )
                        return True, None
                else:
                    stable_since = None

                if now >= next_poll:
                    for active_node in [*already_running, node_id]:
                        self._set_node_input_rpm(active_node, rpm)
                    self._poll_node_startup(node_id)
                    next_poll = now + interval_s
                time.sleep(0.02)

            self._set_node_axis_state(node_id, AXIS_STATE_IDLE)
            self._set_node_limits(node_id, operating_limit_a)
            self.logger.warning(
                "ODrive-Anlauf fehlgeschlagen: node=%d attempt=%d reason=%s",
                node_id,
                attempt,
                last_reason,
            )
            if attempt <= retries and not self._system_stop_pending:
                time.sleep(max(0.2, float(getattr(self.config, 'coast_delay_s', 0.5))))

        return False, last_reason

    def _start_sequentially(self, rpm: int) -> tuple[bool, str | None]:
        validated = []
        operating_limit_a = float(
            getattr(self.config, 'operating_current_limit_a', 30.0)
        )
        with self._lock:
            started_monotonic = self.startup_status.get('started_monotonic')
            self.startup_status = {
                'active': True,
                'phase': 'nodes',
                'node_id': None,
                'attempt': 0,
                'validated_nodes': [],
                'last_result': None,
                'started_monotonic': started_monotonic,
                'node_started_monotonic': time.monotonic(),
            }

        try:
            self._set_axis_state(AXIS_STATE_IDLE)
            self._send_all(CMD_CLEAR_ERRORS)
            time.sleep(0.2)
            for node_id in self.node_ids:
                success, error = self._start_node_with_validation(
                    node_id, validated, rpm
                )
                if not success:
                    return False, error
                validated.append(node_id)
                with self._lock:
                    self.startup_status['validated_nodes'] = list(validated)
            return True, None
        finally:
            with self._lock:
                complete = len(validated) == len(self.node_ids)
                self.startup_status.update({
                    # Der Start ist erst vorbei, wenn der Kommando-Thread laeuft.
                    # Zwischen der letzten Achsvalidierung und dem ersten
                    # Kommandozyklus liegen noch Transportaufrufe. Wird der
                    # Start schon hier als beendet gemeldet, wertet der
                    # Laufzeit-Watchdog die gesamte Anlaufdauer als fehlendes
                    # Lebenszeichen und verriegelt genau in diesem Fenster.
                    'active': complete,
                    'phase': 'finalize' if complete else None,
                    'node_id': None,
                    'last_result': 'ok' if complete else 'failed',
                    # Die Start-Haengererkennung deckt damit die Abschlussphase
                    # ab statt auf die Gesamtstartzeit zurueckzufallen.
                    'node_started_monotonic': time.monotonic() if complete else None,
                })
            if len(validated) != len(self.node_ids):
                for node_id in self.node_ids:
                    try:
                        self._set_node_axis_state(node_id, AXIS_STATE_IDLE)
                        self._set_node_limits(node_id, operating_limit_a)
                    except Exception as exc:
                        self.logger.error(
                            "ODrive-Anlauf-Abbruch node=%d fehlgeschlagen: %s",
                            node_id,
                            exc,
                        )

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
                startup_started = time.monotonic()
                self.startup_status = {
                    'active': True,
                    'phase': 'prepare',
                    'node_id': None,
                    'attempt': 0,
                    'validated_nodes': [],
                    'last_result': None,
                    'started_monotonic': startup_started,
                    'node_started_monotonic': startup_started,
                }
                self._stop_event.clear()
                self._run_started_monotonic = time.monotonic()
                self._loop_alive_monotonic = time.monotonic()
                self._command_loop_expected = False
                self._system_stop_pending = False
                self._low_rpm_since = {node_id: None for node_id in self.node_ids}
                for node_id in self.node_ids:
                    self.odrive_iq[node_id] = {
                        'setpoint_a': None,
                        'measured_a': None,
                        'last_seen': 0.0,
                    }
                    self._overcurrent_since[node_id] = None
                    self._critical_current_since[node_id] = None

            try:
                self._prepare_start_transport()
                self._require_live_nodes()
                if bool(getattr(self.config, 'sequential_start_enabled', True)):
                    success, start_error = self._start_sequentially(self.commanded_rpm)
                    if not success:
                        raise RuntimeError(start_error or "Sequenzieller Anlauf fehlgeschlagen")
                else:
                    self._send_all(CMD_CLEAR_ERRORS)
                    time.sleep(0.2)
                    self._prepare_parallel_start_transport()
                    self._set_input_rpm(self.commanded_rpm)
                    self._set_axis_state(
                        self.config.axis_state,
                        stagger_s=float(getattr(self.config, "start_stagger_s", 0.0)),
                    )
                # A sequential USB start can take several seconds. Refresh
                # every validated axis before the runtime loop performs its
                # first liveness check; otherwise the first axis appears
                # stale merely because the later axes were being validated.
                self._finalize_start_transport()
            except Exception as exc:
                with self._lock:
                    self.startup_status.update({
                        'active': False,
                        'phase': None,
                        'node_id': None,
                        'last_result': 'failed',
                        'node_started_monotonic': None,
                    })
                self._cleanup_failed_start_transport()
                self._request_system_stop(f"ODrive Start fehlgeschlagen: {exc}")
                return self.get_status(success=False)

            with self._lock:
                self._run_started_monotonic = time.monotonic()
                # The runtime health check starts counting from here; the first
                # command cycle is still one interval away.
                self._loop_alive_monotonic = time.monotonic()
                self._command_loop_expected = True
                self.startup_status.update({
                    'active': False,
                    'phase': None,
                    'node_id': None,
                    'last_result': 'ok',
                    'node_started_monotonic': None,
                })
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
                self._command_loop_expected = False

            # Direkt und wiederholt IDLE setzen – freies Auslaufen, kein
            # aktives Bremsen. brake_resistance ist aktuell 0.0; ein aktives
            # Abbremsen per Set_Input_Vel(0) koennte den DC-Bus ueberladen.
            pending, send_errors = self._request_idle_verified()
            if pending:
                details = f"ODrive-IDLE nicht bestaetigt: nodes {pending}"
                if send_errors:
                    details += f"; Sendefehler: {'; '.join(send_errors)}"
                self.last_error = details
                return self.get_status(success=False)

            self.logger.info("ODrive-Maehdeck gestoppt: nodes=%s", self.node_ids)
            return self.get_status()

    def _prepare_start_transport(self) -> None:
        """Transport hook executed after the start is visibly marked pending."""

    def _prepare_node_start_transport(self, node_id: int) -> None:
        """Transport hook immediately before one sequential axis starts."""

    def _prepare_parallel_start_transport(self) -> None:
        """Transport hook immediately before a non-sequential start."""

    def _finalize_start_transport(self) -> None:
        """Transport hook after all axes started, before runtime checks begin."""

    def _cleanup_failed_start_transport(self) -> None:
        """Best-effort transport cleanup after a rejected start."""

    def emergency_stop(self, reason: str) -> Dict[str, Any]:
        """Stoppt das Deck sofort und best-effort, auch bei defektem CAN."""
        self._stop_event.set()
        with self._lock:
            self.running = False
            self.commanded_rpm = 0
            self.last_error = str(reason)
            self._command_loop_expected = False
            self._system_stop_pending = True

        pending, errors = self._request_idle_verified(attempts=8)
        if pending:
            self.logger.critical(
                "ODrive Notstopp nicht bestaetigt: nodes=%s errors=%s",
                pending,
                errors,
            )
        elif errors:
            self.logger.warning(
                "ODrive Notstopp nach Sendefehlern bestaetigt: %s",
                "; ".join(errors),
            )
        self.logger.critical("ODrive-Maehdeck Sicherheitsstopp: %s", reason)
        return self.get_status(success=not pending)

    def _request_system_stop(self, reason: str) -> None:
        """Verriegelt den lokalen Fehler und fordert asynchron Gesamtstopp an."""
        with self._lock:
            if self._system_stop_pending:
                return
            self._system_stop_pending = True
            self.running = False
            self.commanded_rpm = 0
            self.last_error = str(reason)
            self._command_loop_expected = False
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

    def _poll_next_current(self) -> int:
        """Fragt genau einen Node ab, um RTR/Antwort-Bursts zu vermeiden."""
        if not self.node_ids:
            raise RuntimeError("Keine ODrive-Nodes konfiguriert")
        with self._lock:
            index = self._current_poll_index % len(self.node_ids)
            self._current_poll_index = (index + 1) % len(self.node_ids)
            node_id = self.node_ids[index]
        self._send_rtr(node_id, CMD_GET_IQ, dlc=8)
        return node_id

    def _poll_next_sensorless(self) -> int:
        """Holt die Sensorless-Drehzahl eines Nodes waehrend des Betriebs.

        Ohne diese Abfrage bleiben die Drehzahlwerte auf dem Stand der
        Anlaufvalidierung stehen, und ein stehendes Messer faellt nirgends auf.
        """
        if not self.node_ids:
            raise RuntimeError("Keine ODrive-Nodes konfiguriert")
        with self._lock:
            index = self._sensorless_poll_index % len(self.node_ids)
            self._sensorless_poll_index = (index + 1) % len(self.node_ids)
            node_id = self.node_ids[index]
            self._last_sensorless_poll = time.monotonic()
        self._send_rtr(node_id, CMD_GET_SENSORLESS_ESTIMATES, dlc=8)
        return node_id

    def _sensorless_poll_due(self, now: float) -> bool:
        if not bool(getattr(self.config, 'runtime_rpm_monitor_enabled', True)):
            return False
        interval_s = max(
            0.1,
            float(getattr(self.config, 'runtime_sensorless_poll_interval_s', 0.5)),
        )
        with self._lock:
            last = self._last_sensorless_poll
        return now - last >= interval_s

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

    def clear_all_errors(self) -> tuple[bool, str | None, dict]:
        """Loescht jeden ODrive-Fehler - nur auf ausdrueckliche Anweisung.

        ``clear_watchdog_errors`` verweigert alles, was kein Watchdog-Fehler
        ist, und das ist richtig: Eine Maschine mit Messern soll einen echten
        Fehler nicht stillschweigend wegwischen. Es fehlte aber der bewusste
        Gegenweg. Ohne ihn blieb dem Bediener nur, zum Fahrzeug zu gehen und
        die Versorgung zu trennen - die Fehler liegen im Arbeitsspeicher der
        Boards und sind danach weg. Diese Methode tut dasselbe, nur ohne den
        Weg dorthin.

        Zurueck kommen die Fehler, die geloescht wurden, damit im Protokoll
        steht, worueber hinweggegangen wurde.
        """
        with self._lock:
            vorher = {
                node_id: error
                for node_id, error in self.odrive_errors.items()
                if error
            }
        if not vorher:
            return True, None, {}
        try:
            self._send_all(CMD_CLEAR_ERRORS)
        except Exception as exc:
            return (
                False,
                f"ODrive-Fehler konnten nicht geloescht werden: {exc}",
                vorher,
            )
        return True, None, vorher

    def prepare_safety_reset(self) -> tuple[bool, str | None]:
        """Bereitet den expliziten Reset vor und startet IDLE-Polling erneut."""
        success, error = self.clear_watchdog_errors()
        if not success:
            return success, error
        pending, send_errors = self._request_idle_verified()
        if pending:
            details = f"ODrive-Achsen nicht IDLE: nodes {pending}"
            if send_errors:
                details += f"; Sendefehler: {'; '.join(send_errors)}"
            return False, details
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
                if self._sensorless_poll_due(time.monotonic()):
                    self._poll_next_sensorless()
                if bool(getattr(self.config, 'current_monitor_enabled', True)):
                    # Nicht drei RTRs unmittelbar hintereinander senden. Auf
                    # realer Hardware fielen nach rund 20 s alle GET_IQ-
                    # Antworten aus, während Heartbeats weiterliefen. Das
                    # Round-Robin-Polling verteilt Requests und Antworten auf
                    # drei Kommandozyklen und behält den Fail-Safe bei.
                    self._poll_next_current()
                    timeout_error = self._check_current_response_timeout(time.monotonic())
                    if timeout_error:
                        self._request_system_stop(timeout_error)
                        return
            except Exception as exc:
                self._request_system_stop(f"ODrive-Maehdeck CAN-Fehler: {exc}")
                return
            # Only a fully completed cycle counts as a sign of life. A transport
            # call that never returns freezes this timestamp, which is exactly
            # what the external watchdog looks for.
            with self._lock:
                self._loop_alive_monotonic = time.monotonic()

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

    def on_sensorless_estimates(
        self,
        node_id: int,
        position: float,
        velocity: float,
    ) -> None:
        """Speichert Sensorless-Schaetzwerte fuer die Anlaufvalidierung."""
        node_id = int(node_id)
        if node_id not in self.node_ids:
            return
        if not (
            math.isfinite(float(position)) and math.isfinite(float(velocity))
        ):
            return
        with self._lock:
            self.odrive_sensorless[node_id] = {
                'position': float(position),
                'velocity': float(velocity),
                'rpm': float(velocity) * 60.0,
                'last_seen': time.monotonic(),
            }

    @staticmethod
    def _format_error_detail(detail) -> str:
        """Haengt die Fehler der Unterobjekte an, sofern welche vorliegen.

        Ohne sie steht im Log nur der Sammelbegriff. Genau daran ist am
        27.08. die Frage "woher kommt der wiederkehrende 0x40" haengen
        geblieben.
        """
        if not detail:
            return ""
        teile = []
        for name, wert in sorted(detail.items()):
            if not wert:
                continue
            if name == "drv":
                namen = [
                    bezeichnung
                    for bit, bezeichnung in DRV_FAULT_BITS
                    if wert & bit
                ]
                klartext = f" [{', '.join(namen)}]" if namen else ""
                teile.append(f"drv=0x{wert:08X}{klartext}")
            else:
                teile.append(f"{name}=0x{wert:08X}")
        return f" ({', '.join(teile)})" if teile else ""

    def on_heartbeat(
        self, node_id: int, error: int, state: int, detail=None
    ) -> None:
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
            detail: Fehler der darunterliegenden Objekte, sofern der Transport
                sie liefert. Der Achsfehler ist ein Sammelbegriff - 0x40 heisst
                nur "das Motor-Objekt meldet einen Fehler", nicht welchen.
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
            if error:
                self.odrive_error_details[int(node_id)] = dict(detail or {})
            else:
                self.odrive_error_details.pop(int(node_id), None)
            self.odrive_error = max(self.odrive_errors.values(), default=0)
            self.odrive_state = int(state)
            if error != 0:
                klartext = self._format_error_detail(detail)
                self.last_error = (
                    f"ODrive node={node_id} error=0x{error:08X} "
                    f"state={state}{klartext}"
                )
                # Nur bei einem *neuen* Fehler (0 -> !=0) den Lauf abbrechen.
                # Bei stale-Fehlern, die schon vor start() da waren, nicht
                # tearing-down: sonst latched jeder Fehler-Heartbeat running
                # sofort wieder auf False und start() kann den ODrive nie per
                # Clear_Errors (0x018) entstoeren -> "nur einmal startbar".
                if (
                    prev_error == 0
                    and self.running
                    and not self.startup_status.get('active')
                ):
                    should_trip = True
                    trip_reason = f"ODrive node={node_id} error=0x{error:08X} state={state}"
                self.logger.error(
                    "ODrive-Heartbeat Fehler: node=%d error=0x%08X state=%d%s",
                    node_id,
                    error,
                    state,
                    klartext,
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

    def transport_stall_reason(self) -> str | None:
        """Meldet einen haengenden Transportaufruf; CAN kennt keinen solchen."""
        return None

    def runtime_health(self) -> tuple[bool, str | None]:
        """Beurteilt das laufende Maehdeck von ausserhalb des Kommando-Threads.

        Diese Pruefung wird vom zentralen Safety-Watchdog gerufen und darf
        deshalb ausschliesslich auf gespeicherten Werten arbeiten – niemals auf
        einem Transportaufruf, der genauso haengen kann wie der Kommando-Thread.

        Ein ruhendes Deck gilt als gesund: im IDLE werden die ODrives fuer den
        Fahrantrieb nicht gebraucht, und ein Transportproblem im Stillstand
        darf das manuelle Rangieren nicht verriegeln. Sobald das Deck laeuft,
        ist jede dieser Abweichungen ein Grund fuer den Gesamtstopp.
        """
        now = time.monotonic()
        with self._lock:
            running = self.running
            startup_active = bool(self.startup_status.get('active'))
            loop_expected = self._command_loop_expected
            loop_alive = self._loop_alive_monotonic
            run_started = self._run_started_monotonic
            errors = dict(self.odrive_errors)
            states = dict(self.odrive_states)
            missing = self._missing_heartbeats_locked()
            sensorless = {
                node_id: dict(sample)
                for node_id, sample in self.odrive_sensorless.items()
            }
            currents = {
                node_id: dict(sample) for node_id, sample in self.odrive_iq.items()
            }
            if not running:
                self._low_rpm_since = {node_id: None for node_id in self.node_ids}

        # Nur der laufende Kommando-Thread wird hier beurteilt. Vor ihm ist der
        # Startvorgang zustaendig - samt eigener Haengererkennung - und nach
        # einem gescheiterten Start meldet dieser den wahren Grund. Ohne diese
        # Klammer sprang die Pruefung in das Abbruchfenster eines Startfehlers
        # und ueberschrieb "Sensorless-Anlauf Timeout node=0" durch
        # "ODrive-Status veraltet: nodes [1, 2]": waehrend node 0 validiert
        # wird, veralten die beiden anderen Achsen zwangslaeufig, und gemeldet
        # wurden dann ausgerechnet die beiden intakten Motoren (real 07.08.).
        if not running or startup_active or not loop_expected:
            return True, None

        stall = self.transport_stall_reason()
        if stall:
            return False, f"Maehdeck-Transport haengt: {stall}"

        loop_timeout_s = max(
            0.5,
            float(getattr(self.config, 'command_loop_timeout_s', 3.0)),
        )
        loop_age = now - loop_alive if loop_alive > 0.0 else None
        if loop_age is None or loop_age > loop_timeout_s:
            age_text = "nie" if loop_age is None else f"{loop_age:.1f}s"
            return False, f"Maehdeck-Kommandoschleife ohne Lebenszeichen ({age_text})"

        if missing:
            return False, f"ODrive-Status veraltet: nodes {missing}"

        error_nodes = {
            node_id: value for node_id, value in errors.items() if int(value) != 0
        }
        if error_nodes:
            details = ", ".join(
                f"node {node_id}=0x{int(value):08X}"
                for node_id, value in sorted(error_nodes.items())
            )
            return False, f"ODrive-Fehler waehrend des Maehens: {details}"

        expected_state = int(self.config.axis_state)
        dropped = [
            node_id
            for node_id, state in sorted(states.items())
            if int(state) != expected_state
        ]
        if dropped:
            return False, (
                f"ODrive-Achse nicht mehr im Zustand {expected_state}: nodes {dropped}"
            )

        return self._check_blade_rotation(now, run_started, sensorless, currents)

    def _check_blade_rotation(
        self,
        now: float,
        run_started: float,
        sensorless: Dict[int, Dict[str, Any]],
        currents: Dict[int, Dict[str, Any]] | None = None,
    ) -> tuple[bool, str | None]:
        """Erkennt ein stehendes Messer trotz fehlerfreier ODrive-Meldung."""
        if not bool(getattr(self.config, 'runtime_rpm_monitor_enabled', True)):
            return True, None
        grace_s = float(getattr(self.config, 'current_startup_grace_s', 2.0))
        if now - run_started <= grace_s:
            return True, None

        min_rpm = float(getattr(self.config, 'runtime_min_rpm', 150.0))
        sample_timeout_s = max(
            1.0,
            float(getattr(self.config, 'runtime_sensorless_timeout_s', 3.0)),
        )
        fault_duration_s = max(
            0.2,
            float(getattr(self.config, 'runtime_rpm_fault_duration_s', 1.5)),
        )

        stalled_node = None
        stalled_rpm = 0.0
        with self._lock:
            for node_id in self.node_ids:
                sample = sensorless.get(node_id) or {}
                rpm = sample.get('rpm')
                last_seen = float(sample.get('last_seen') or 0.0)
                fresh = last_seen > run_started and now - last_seen <= sample_timeout_s
                # A stale sample says nothing about the blade. Transport
                # liveness is already covered by the checks above, so an
                # unanswered rpm request must not trip a second time here.
                if not fresh or rpm is None or abs(float(rpm)) >= min_rpm:
                    self._low_rpm_since[node_id] = None
                    continue
                if self._low_rpm_since[node_id] is None:
                    self._low_rpm_since[node_id] = now
                elif now - self._low_rpm_since[node_id] >= fault_duration_s:
                    stalled_node = node_id
                    stalled_rpm = abs(float(rpm))
                    break

        if stalled_node is not None:
            # Der Strom trennt die beiden moeglichen Ursachen sofort: ein
            # blockiertes Messer zieht am Limit (real 07.08.: 24.3 A bei
            # Sollstrom 30 A und 31 rpm), ein abgerissener Antrieb oder ein
            # unzuverlaessiger Sensorless-Schaetzwert dagegen fast nichts.
            sample = (currents or {}).get(stalled_node) or {}
            measured = sample.get('measured_a')
            setpoint = sample.get('setpoint_a')
            detail = ''
            if measured is not None:
                detail = f", Strom {abs(float(measured)):.1f} A"
                if setpoint is not None:
                    detail += f" (Soll {abs(float(setpoint)):.1f} A)"
            return False, (
                f"Maehmesser dreht nicht: node={stalled_node} "
                f"{stalled_rpm:.0f} rpm < {min_rpm:.0f} rpm{detail}"
            )
        return True, None

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
            active_axis_nodes = self._active_axis_nodes_locked()
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
            sensorless = {
                node_id: {
                    'rpm': self.odrive_sensorless[node_id]['rpm'],
                    'age_s': (
                        None
                        if self.odrive_sensorless[node_id]['last_seen'] <= 0.0
                        else round(
                            time.monotonic()
                            - self.odrive_sensorless[node_id]['last_seen'],
                            2,
                        )
                    ),
                }
                for node_id in self.node_ids
            }
            startup_status = {
                **self.startup_status,
                'validated_nodes': list(self.startup_status['validated_nodes']),
            }
            status_error = error or self.last_error
            if missing_heartbeats and not status_error:
                status_error = f"ODrive heartbeat timeout: nodes {missing_heartbeats}"
            command_loop_age_s = (
                None
                if not running or self._loop_alive_monotonic <= 0.0
                else round(time.monotonic() - self._loop_alive_monotonic, 2)
            )
        transport_stall = self.transport_stall_reason()
        return {
            "success": success,
            "enabled": self.enabled,
            # Never report the mower as stopped while a live heartbeat still
            # says that an axis is active.  ``command_running`` remains the
            # host-side command-thread state for diagnostics.
            "running": running or bool(active_axis_nodes),
            "command_running": running,
            "active_axis_nodes": active_axis_nodes,
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
            "odrive_sensorless": sensorless,
            "command_loop_age_s": command_loop_age_s,
            "transport_stall": transport_stall,
            "startup_status": startup_status,
            "sequential_start_enabled": bool(
                getattr(self.config, 'sequential_start_enabled', True)
            ),
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
