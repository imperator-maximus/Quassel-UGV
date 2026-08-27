import time
import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.hardware.odrive_usb_mower import ODriveUSBMowerController


class FakeAxis:
    def __init__(self):
        self.error = 0
        self.current_state = 1
        self.feed_count = 0
        self.config = SimpleNamespace(enable_watchdog=True, watchdog_timeout=1.0)
        self.controller = SimpleNamespace(
            error=0,
            input_vel=0.0,
            config=SimpleNamespace(vel_limit=100.0),
        )
        self.motor = SimpleNamespace(
            error=0,
            config=SimpleNamespace(current_lim=30.0),
            current_control=SimpleNamespace(Iq_setpoint=2.0, Iq_measured=1.5),
        )
        self.encoder = SimpleNamespace(error=0)
        self.sensorless_estimator = SimpleNamespace(
            error=0, pll_pos=1.25, vel_estimate=10.0
        )

    def watchdog_feed(self):
        self.feed_count += 1

    @property
    def requested_state(self):
        return self.current_state

    @requested_state.setter
    def requested_state(self, value):
        self.current_state = int(value)


class FakeBoard:
    def __init__(self, serial):
        self.serial_number = int(serial, 16)
        self.fw_version_major = 0
        self.fw_version_minor = 5
        self.fw_version_revision = 6
        self.hw_version_major = 3
        self.hw_version_minor = 6
        self.hw_version_variant = 56
        self.vbus_voltage = 26.5
        self.axis0 = FakeAxis()
        self.axis1 = FakeAxis()
        self.clear_count = 0

    def clear_errors(self):
        self.clear_count += 1
        self.axis0.error = 0
        self.axis1.error = 0


class FakeODriveModule:
    def __init__(self, boards):
        self.boards = boards

    def find_any(self, serial_number, timeout):
        del timeout
        return self.boards[serial_number]


def config_for(serial="386132523135"):
    return SimpleNamespace(
        enabled=True,
        node_id=0,
        node_ids=[0],
        usb_axes=[{"node_id": 0, "serial_number": serial, "axis": 0}],
        usb_connect_timeout_s=0.1,
        usb_reconnect_interval_s=0.1,
        usb_watchdog_timeout_s=3.0,
        axis_state=5,
        min_rpm=500,
        max_rpm=5000,
        default_rpm=500,
        ramp_rate_rpm_s=300,
        command_interval_s=0.1,
        heartbeat_timeout_s=1.0,
        usb_status_timeout_s=3.0,
        current_monitor_enabled=True,
        current_poll_interval_s=0.1,
        current_poll_while_idle=False,
        current_response_timeout_s=2.0,
        current_startup_grace_s=2.0,
        current_trip_a=25.0,
        current_trip_duration_s=0.5,
        current_critical_trip_a=29.0,
        current_critical_trip_duration_s=0.1,
        sequential_start_enabled=True,
        usb_call_stall_timeout_s=2.0,
        command_loop_timeout_s=2.0,
    )


class ODriveUSBTests(unittest.TestCase):
    def setUp(self):
        self.serial = "386132523135"
        self.board = FakeBoard(self.serial)
        self.controller = ODriveUSBMowerController(
            config_for(self.serial),
            odrive_module=FakeODriveModule({self.serial: self.board}),
        )
        self.controller._connect_serial(self.serial)

    def test_refresh_exposes_usb_health_current_and_sensorless_speed(self):
        self.controller._refresh_node(0)

        status = self.controller.get_status()
        self.assertEqual(status["transport"], "usb")
        self.assertEqual(status["odrive_missing_heartbeats"], [])
        self.assertEqual(status["odrive_currents"][0]["measured_a"], 1.5)
        self.assertEqual(status["odrive_sensorless"][0]["rpm"], 600.0)
        self.assertTrue(status["usb_boards"][self.serial]["online"])

    def test_completed_calls_leave_no_stall_marker(self):
        self.controller._refresh_node(0)

        self.assertIsNone(self.controller.transport_stall_reason())
        self.assertEqual(self.controller._inflight, {})

    def test_hanging_fibre_call_is_reported_with_board_and_node(self):
        """libfibre blockiert ohne Timeout; das muss von aussen sichtbar sein."""
        started = time.monotonic()
        call_id = self.controller._begin_call(self.serial, 0)
        self.controller._inflight[call_id] = (started - 5.0, self.serial, 0)

        reason = self.controller.transport_stall_reason()

        self.assertIsNotNone(reason)
        self.assertIn(self.serial, reason)
        self.assertIn('node 0', reason)
        self.assertIn('Limit 2.0s', reason)

        self.controller._end_call(call_id)
        self.assertIsNone(self.controller.transport_stall_reason())

    def test_short_call_is_not_reported_as_stall(self):
        call_id = self.controller._begin_call(self.serial, 0)
        try:
            self.assertIsNone(self.controller.transport_stall_reason())
        finally:
            self.controller._end_call(call_id)

    def test_failed_call_clears_its_stall_marker(self):
        def explode(_axis, _board):
            raise RuntimeError('USB weg')

        with self.assertRaises(RuntimeError):
            self.controller._run_axis_operation(0, explode)

        self.assertEqual(self.controller._inflight, {})

    def test_velocity_write_explicitly_feeds_axis_watchdog(self):
        self.controller._set_node_input_rpm(0, 600)

        self.assertAlmostEqual(self.board.axis0.controller.input_vel, 10.0)
        self.assertEqual(self.board.axis0.feed_count, 1)

    def test_axis_state_and_limits_use_native_usb_properties(self):
        self.controller._set_node_limits(0, 12.0)
        self.controller._set_node_axis_state(0, 5)

        self.assertAlmostEqual(
            self.board.axis0.controller.config.vel_limit, 5000 / 60, places=5
        )
        self.assertEqual(self.board.axis0.motor.config.current_lim, 12.0)
        self.assertEqual(self.board.axis0.current_state, 5)

    def test_duplicate_or_missing_usb_mapping_is_rejected(self):
        cfg = config_for(self.serial)
        cfg.node_ids = [0, 1]
        with self.assertRaisesRegex(ValueError, "missing=\\[1\\]"):
            ODriveUSBMowerController(cfg, odrive_module=FakeODriveModule({}))

    def test_watchdog_error_clear_is_fed_and_verified(self):
        self.board.axis0.error = 0x800
        self.controller.on_heartbeat(0, 0x800, 1)

        success, error = self.controller.clear_watchdog_errors()

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(self.controller.odrive_errors[0], 0)
        self.assertGreaterEqual(self.board.axis0.feed_count, 2)

    def test_waiting_idle_axis_is_eligible_for_feed_during_sequential_start(self):
        self.controller.running = True
        self.controller.odrive_states[0] = 1

        self.assertTrue(self.controller._should_feed_idle_watchdog(0))

        self.controller.odrive_states[0] = 5
        self.assertFalse(self.controller._should_feed_idle_watchdog(0))

    def test_usb_status_timeout_is_independent_from_hardware_watchdog_timeout(self):
        self.controller.on_heartbeat(0, 0, 1)
        self.controller.odrive_last_seen[0] -= 1.5

        status = self.controller.get_status()

        self.assertEqual(status["odrive_missing_heartbeats"], [])

    def test_sequential_start_arms_only_the_axis_about_to_start(self):
        self.board.axis0.config.enable_watchdog = True

        self.controller._prepare_start_transport()
        self.assertFalse(self.board.axis0.config.enable_watchdog)

        self.controller._prepare_node_start_transport(0)
        self.assertTrue(self.board.axis0.config.enable_watchdog)
        self.assertEqual(self.board.axis0.config.watchdog_timeout, 3.0)

    def test_start_finalization_refreshes_stale_usb_status(self):
        self.controller.running = True
        self.controller.commanded_rpm = 500
        self.controller.on_heartbeat(0, 0, 5)
        self.controller.odrive_last_seen[0] -= 10.0

        self.controller._finalize_start_transport()

        status = self.controller.get_status()
        self.assertEqual(status["odrive_missing_heartbeats"], [])
        self.assertAlmostEqual(
            self.board.axis0.controller.input_vel, 500 / 60, places=5
        )
        self.assertGreaterEqual(self.board.axis0.feed_count, 1)

    def test_startup_validation_owns_transient_axis_errors(self):
        reasons = []
        self.controller.running = True
        self.controller.startup_status['active'] = True
        self.controller.set_system_stop_callback(reasons.append)

        self.controller.on_heartbeat(0, 0x800, 1)

        self.assertEqual(reasons, [])
        self.assertFalse(self.controller._system_stop_pending)

    def test_delayed_idle_disarms_and_clears_watchdog_after_stop(self):
        self.board.axis0.current_state = 5
        self.board.axis0.config.enable_watchdog = True
        self.controller.on_heartbeat(0, 0, 5)

        self.controller._schedule_or_run_watchdog_cleanup({"active_axis_nodes": [0]})

        self.assertTrue(self.controller._watchdog_cleanup_pending)
        self.assertTrue(self.board.axis0.config.enable_watchdog)

        self.board.axis0.current_state = 1
        self.board.axis0.error = 0x800
        self.controller.on_heartbeat(0, 0x800, 1)
        self.controller._cleanup_idle_watchdogs_if_ready()

        self.assertFalse(self.controller._watchdog_cleanup_pending)
        self.assertFalse(self.board.axis0.config.enable_watchdog)
        self.assertEqual(self.controller.odrive_errors[0], 0)


class GateTreiberMeldungTests(unittest.TestCase):
    """Was der Gate-Treiber gesehen hat - und was die Klemme dabei fuehrte.

    Am 27.08.2026 um 23:52 Uhr fielen beide Achsen eines Boards gleichzeitig
    mit DRV_FAULT aus. Im Log stand nur der Sammelbegriff: kein Register, keine
    Spannung. Unterspannung und Ueberstrom sahen damit gleich aus.
    """

    def setUp(self):
        self.serial = "386132523135"
        self.board = FakeBoard(self.serial)
        self.controller = ODriveUSBMowerController(
            config_for(self.serial),
            odrive_module=FakeODriveModule({self.serial: self.board}),
        )
        self.controller._connect_serial(self.serial)
        self.board.axis0.error = 0x40
        self.board.axis0.motor.error = 0x08

    def test_bei_treiberfehler_kommen_register_und_spannung_mit(self):
        self.board.vbus_voltage = 21.4
        self.board.axis0.motor.get_drv_fault = lambda: 0x0100

        self.controller._refresh_node(0)

        self.assertIn("drv=0x00000100", self.controller.last_error)
        self.assertIn("PVDD_Unterspannung", self.controller.last_error)
        self.assertIn("vbus=21.40V", self.controller.last_error)

    def test_ein_leeres_register_wird_als_leer_gemeldet(self):
        self.board.axis0.motor.get_drv_fault = lambda: 0

        self.controller._refresh_node(0)

        self.assertIn("drv=0x00000000", self.controller.last_error)
        self.assertIn("kein Bit gesetzt", self.controller.last_error)

    def test_eine_gescheiterte_abfrage_wird_nicht_verschluckt(self):
        def kaputt():
            raise RuntimeError("Fibre-Aufruf abgebrochen")

        self.board.axis0.motor.get_drv_fault = kaputt

        self.controller._refresh_node(0)

        self.assertIn("drv nicht lesbar: Fibre-Aufruf abgebrochen",
                      self.controller.last_error)

    def test_ohne_treiberfehler_wird_der_treiber_nicht_gefragt(self):
        """Jede Abfrage ist ein USB-Umlauf - und haengende Aufrufe sind hier
        das bekannte Problem."""
        gefragt = []
        self.board.axis0.motor.error = 0x1000
        self.board.axis0.motor.get_drv_fault = lambda: gefragt.append(1) or 0

        self.controller._refresh_node(0)

        self.assertEqual([], gefragt)

    def test_die_spannung_steht_bei_jedem_achsfehler(self):
        """Sie liegt in derselben Abfrage schon vor und kostet nichts extra."""
        self.board.vbus_voltage = 22.9
        self.board.axis0.motor.error = 0x1000

        self.controller._refresh_node(0)

        self.assertIn("vbus=22.90V", self.controller.last_error)


class NachbereitungsmeldungTests(unittest.TestCase):
    """Dieselbe Zeile zweimal pro Sekunde begraebt das naechste Ereignis.

    Nach dem Ausfall vom 27.08. lief das Protokoll ueber eine Stunde mit
    ``Watchdog-Nachbereitung fehlgeschlagen`` voll, weil der anstehende Fehler
    sich nicht aendert.
    """

    def setUp(self):
        self.serial = "386132523135"
        self.board = FakeBoard(self.serial)
        self.controller = ODriveUSBMowerController(
            config_for(self.serial),
            odrive_module=FakeODriveModule({self.serial: self.board}),
        )
        self.meldungen = []
        self.controller.logger = SimpleNamespace(
            warning=lambda text, *args: self.meldungen.append(text % args),
            info=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        )

    def test_derselbe_grund_wird_einmal_gemeldet(self):
        for _ in range(20):
            self.controller._melde_nachbereitung("Nicht-Watchdog-Fehler aktiv")

        self.assertEqual(1, len(self.meldungen))

    def test_ein_neuer_grund_wird_sofort_gemeldet(self):
        self.controller._melde_nachbereitung("Nicht-Watchdog-Fehler aktiv")
        self.controller._melde_nachbereitung("Achse antwortet nicht")

        self.assertEqual(2, len(self.meldungen))

    def test_nach_der_sprechpause_wird_erinnert(self):
        """Ganz verstummen darf sie nicht - der Zustand haelt ja an."""
        self.controller._melde_nachbereitung("Nicht-Watchdog-Fehler aktiv")
        self.controller._letzte_nachbereitungszeit -= (
            self.controller._NACHBEREITUNG_WIEDERHOLUNG_S + 1.0
        )
        self.controller._melde_nachbereitung("Nicht-Watchdog-Fehler aktiv")

        self.assertEqual(2, len(self.meldungen))


if __name__ == "__main__":
    unittest.main()
