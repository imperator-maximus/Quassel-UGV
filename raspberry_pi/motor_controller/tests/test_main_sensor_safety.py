import logging
import threading
import unittest
from dataclasses import dataclass, field
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# pyserial gibt es nur auf dem Fahrzeug, main.py zieht es ueber die GNSS-Kette
# beim Import mit. Ohne diesen Ersatz laeuft diese Datei nur dann, wenn zufaellig
# vorher ein anderer Test denselben Ersatz gesetzt hat - die Suite haenge damit
# an der alphabetischen Reihenfolge ihrer Dateien.
if 'serial' not in sys.modules:
    import types as _types
    _serial = _types.ModuleType('serial')
    _serial.Serial = object
    sys.modules['serial'] = _serial

from motor_controller.hardware.odrive_mower import ODriveMowerController
from motor_controller.hardware.safety_monitor import SafetyMonitor
from motor_controller.main import MotorControllerApp


class FakePoseCache:
    def __init__(self, pose_online=False):
        self.pose_online = pose_online

    def get_status(self, **_kwargs):
        return {'online': self.pose_online, 'age_s': 0.1, 'source': {}}


@dataclass
class FakeUSBConfig:
    enabled: bool = True
    node_id: int = 0
    node_ids: list[int] = field(default_factory=lambda: [0, 1, 2])
    axis_state: int = 5
    min_rpm: int = 500
    max_rpm: int = 5000
    default_rpm: int = 500
    ramp_rate_rpm_s: int = 300
    command_interval_s: float = 0.1
    heartbeat_timeout_s: float = 1.0
    usb_status_timeout_s: float = 3.0
    usb_startup_hang_timeout_s: float = 8.0
    current_startup_grace_s: float = 2.0
    command_loop_timeout_s: float = 2.0
    runtime_rpm_monitor_enabled: bool = False


class FakeUSBMower(ODriveMowerController):
    """Echter Controller mit USB-Transportkennung.

    Bewusst kein handgeschriebenes Status-Dictionary: genau eine solche
    Attrappe hat die falsch benannten Schluessel im USB-Zweig des zentralen
    Watchdogs gruen aussehen lassen, waehrend der Watchdog produktiv blind war.
    """

    transport = 'usb'

    def __init__(self, *, running=False, missing=None, errors=None, startup=False):
        super().__init__(FakeUSBConfig())
        now = time.monotonic()
        self.running = running
        self._run_started_monotonic = now - 10.0
        self._loop_alive_monotonic = now
        self._command_loop_expected = running
        self.startup_status['active'] = startup
        stale = now - 60.0
        missing_nodes = set(missing or [])
        for node_id in self.node_ids:
            self.odrive_last_seen[node_id] = stale if node_id in missing_nodes else now
            self.odrive_states[node_id] = 5 if running else 1
            self.odrive_errors[node_id] = int((errors or {}).get(node_id, 0))


class SensorSafetyScopeTests(unittest.TestCase):
    def _app(self, *, sensor_online=False, joystick_active=False, navigation_running=False):
        app = MotorControllerApp.__new__(MotorControllerApp)
        app.config = SimpleNamespace(
            pose=SimpleNamespace(
                telemetry_timeout_s=10.0,
                pause_timeout_s=1.0,
                resume_stable_s=2.0,
            )
        )
        app.odrive_mower = FakeUSBMower()
        app.pose_cache = FakePoseCache(pose_online=sensor_online)
        app.web = None
        app.navigation = SimpleNamespace(
            get_status=lambda: {'running': navigation_running}
        )
        app.safety = SimpleNamespace(
            get_status=lambda: {'joystick_active': joystick_active}
        )
        app._sensor_pause_resume_mode = None
        app._sensor_recovery_started_monotonic = None
        return app

    def test_offline_sensor_does_not_latch_idle_system_at_boot(self):
        app = self._app(sensor_online=False)

        self.assertEqual(app._sensor_motion_health_check(), (True, None))
        self.assertEqual(app._link_health_check(), (True, None))

    def test_offline_sensor_does_not_stop_manual_motion(self):
        app = self._app(sensor_online=False, joystick_active=True)

        self.assertEqual(app._sensor_motion_health_check(), (True, None))
        self.assertEqual(app._link_health_check(), (True, None))

    def test_offline_sensor_stops_autonomous_motion(self):
        app = self._app(sensor_online=False, navigation_running=True)

        self.assertFalse(app._sensor_motion_health_check()[0])
        self.assertFalse(app._link_health_check()[0])

    def test_sensor_pause_remains_monitored_until_resume(self):
        app = self._app(sensor_online=False)
        app._sensor_pause_resume_mode = 'plan'

        self.assertFalse(app._sensor_motion_health_check()[0])
        self.assertFalse(app._link_health_check()[0])

    def test_sensor_must_be_stable_before_paused_plan_resumes(self):
        app = self._app(sensor_online=True)
        app._sensor_pause_resume_mode = 'plan'

        healthy, reason = app._sensor_motion_health_check()
        self.assertFalse(healthy)
        self.assertIn('stabilisiert', reason)

        app._sensor_recovery_started_monotonic -= 2.1
        self.assertEqual(app._sensor_motion_health_check(), (True, None))

    def test_idle_usb_poll_gap_does_not_latch_vehicle(self):
        app = self._app(sensor_online=True)
        app.odrive_mower = FakeUSBMower(missing=[1, 2])

        self.assertEqual(app._link_health_check(), (True, None))

    def test_running_usb_poll_gap_stops_vehicle(self):
        app = self._app(sensor_online=True)
        app.odrive_mower = FakeUSBMower(running=True, missing=[1, 2])

        healthy, reason = app._link_health_check()

        self.assertFalse(healthy)
        self.assertEqual(reason, "ODrive-Status veraltet: nodes [1, 2]")

    def test_running_usb_odrive_error_stops_vehicle(self):
        app = self._app(sensor_online=True)
        app.odrive_mower = FakeUSBMower(running=True, errors={2: 0x800})

        healthy, reason = app._link_health_check()

        self.assertFalse(healthy)
        self.assertIn('node 2=0x00000800', reason)

    def test_frozen_mower_command_thread_stops_vehicle(self):
        """Der reale Ausfall: Fibre haengt, der Kommando-Thread steht still."""
        app = self._app(sensor_online=True)
        mower = FakeUSBMower(running=True)
        mower._loop_alive_monotonic = time.monotonic() - 30.0
        app.odrive_mower = mower

        healthy, reason = app._link_health_check()

        self.assertFalse(healthy)
        self.assertIn('Kommandoschleife', reason)

    def test_hanging_usb_call_stops_vehicle_and_ends_process(self):
        app = self._app(sensor_online=True)
        mower = FakeUSBMower(running=True)
        mower.transport_stall_reason = lambda: 'USB-Aufruf ohne Antwort seit 4.0s'
        app.odrive_mower = mower

        healthy, reason = app._link_health_check()

        self.assertFalse(healthy)
        self.assertIn('USB-Aufruf ohne Antwort', reason)
        # Ein haengender Fibre-Aufruf ist prozessintern nicht abbrechbar; der
        # Hauptloop muss ihn deshalb zusaetzlich als Neustartgrund erkennen.
        self.assertIn('USB-Aufruf ohne Antwort', app._odrive_usb_hang_reason())

    def test_usb_startup_owns_its_axis_validation(self):
        app = self._app(sensor_online=True)
        app.odrive_mower = FakeUSBMower(
            running=True,
            missing=[2],
            startup=True,
        )

        self.assertEqual(app._link_health_check(), (True, None))

    def test_stuck_usb_start_is_detected_independently_of_fibre_thread(self):
        app = self._app(sensor_online=True)
        mower = FakeUSBMower(running=True, startup=True)
        mower.startup_status.update({
            'active': True,
            'phase': 'node',
            'node_id': 1,
            'node_started_monotonic': time.monotonic() - 9.0,
        })
        app.odrive_mower = mower

        reason = app._odrive_usb_startup_hang_reason()

        self.assertIn('node=1', reason)
        self.assertIn('Limit 8.0s', reason)


class SystemStopWiringTests(unittest.TestCase):
    """Ein Maehdeckfehler muss das ganze Fahrzeug stoppen, nicht nur die Messer."""

    def _app(self, mower):
        app = MotorControllerApp.__new__(MotorControllerApp)
        app.logger = logging.getLogger('test-system-stop')
        app.odrive_mower = mower
        app.navigation = None
        app.motor = SimpleNamespace(emergency_stop=lambda: None)
        app.safety = SimpleNamespace(
            set_emergency_stop_callback=lambda cb: None,
            set_system_stop_callback=lambda cb: None,
            set_link_health_check=lambda cb: None,
            set_motion_hold_check=lambda cb: None,
            set_motion_hold_callback=lambda cb: None,
            set_motion_resume_callback=lambda cb: None,
            set_voice=lambda voice: None,
            trigger_system_stop=lambda reason: None,
        )
        app.pose_cache = SimpleNamespace(set_pose_callback=lambda cb: None)
        # Die Verdrahtung reicht den Ansager an alle Quellen durch, die ihre
        # Flanken selbst erkennen. Hier steht keine davon zur Verfuegung.
        app.voice = None
        app.local_pose = None
        app.network = None
        app.battery = None
        return app

    def test_usb_mower_reaches_the_central_system_stop(self):
        mower = FakeUSBMower()
        app = self._app(mower)

        app._setup_callbacks()

        self.assertIs(mower._system_stop_callback, app.safety.trigger_system_stop)

    def test_vehicle_stops_even_when_the_mower_stop_hangs(self):
        calls = []
        blocked = threading.Event()
        self.addCleanup(blocked.set)

        app = self._app(SimpleNamespace(emergency_stop=lambda reason: blocked.wait(30)))
        app.MOWER_STOP_JOIN_TIMEOUT_S = 0.2
        app.web = SimpleNamespace(
            # detail traegt den Klartext des Stopps - daran entscheidet sich
            # spaeter, ob automatisch fortgesetzt werden darf.
            pause_plan_execution=lambda reason, detail=None: calls.append(
                ('plan', reason, detail)
            )
        )
        app.navigation = SimpleNamespace(stop=lambda reason: calls.append(('nav', reason)))
        app.joystick = SimpleNamespace(disable=lambda: calls.append(('joystick',)))

        started = time.monotonic()
        app._system_safety_stop('Maehdeck haengt')
        elapsed = time.monotonic() - started

        self.assertIn(('plan', 'safety_stop', 'Maehdeck haengt'), calls)
        self.assertIn(('nav', 'safety_stop'), calls)
        self.assertIn(('joystick',), calls)
        # Der Safety-Watchdog ruft diesen Pfad; blockiert er hier, ueberwacht
        # danach niemand mehr Joystick- und Kommando-Timeouts.
        self.assertLess(elapsed, 5.0)


@dataclass
class WatchdogSafetyConfig:
    pin: int = 17
    enabled: bool = False
    debounce_time: float = 0.2
    command_timeout: float = 1000.0
    joystick_timeout: float = 1000.0
    link_watchdog_enabled: bool = True
    link_watchdog_startup_grace_s: float = 0.0
    link_watchdog_interval_s: float = 0.02


class DeadMowerStopsVehicleTests(unittest.TestCase):
    """Der Vorfall vom 07.08.2026 als durchgehender Regressionstest.

    Deck laeuft, der Fibre-Aufruf haengt, der Kommando-Thread steht still - und
    das Fahrzeug fuhr trotzdem 20 Minuten weiter, weil der zentrale Watchdog den
    USB-Zweig nie ausgewertet und der Gesamtstopp fuer USB nie gegriffen hat.
    """

    def test_frozen_mower_stops_plan_navigation_and_drive(self):
        stopped = []
        app = MotorControllerApp.__new__(MotorControllerApp)
        app.logger = logging.getLogger('test-dead-mower')
        app.config = SimpleNamespace(
            pose=SimpleNamespace(
                telemetry_timeout_s=10.0,
                pause_timeout_s=1.0,
                resume_stable_s=2.0,
            )
        )
        mower = FakeUSBMower(running=True)
        mower._loop_alive_monotonic = time.monotonic() - 30.0
        app.odrive_mower = mower
        app.pose_cache = FakePoseCache(pose_online=True)
        app.web = SimpleNamespace(
            pause_plan_execution=lambda reason, detail=None: stopped.append(
                ('plan', reason, detail)
            ),
            get_plan_execution_status=lambda: {'running': True},
        )
        app.navigation = SimpleNamespace(
            get_status=lambda: {'running': True},
            stop=lambda reason: stopped.append(('nav', reason)),
        )
        app.joystick = SimpleNamespace(disable=lambda: stopped.append(('joystick',)))
        app.motor = SimpleNamespace(emergency_stop=lambda: stopped.append(('motor',)))
        app._sensor_pause_resume_mode = None
        app._sensor_recovery_started_monotonic = None

        safety = SafetyMonitor(WatchdogSafetyConfig(), gpio_controller=None)
        app.safety = safety
        safety.set_emergency_stop_callback(app.motor.emergency_stop)
        safety.set_system_stop_callback(app._system_safety_stop)
        safety.set_link_health_check(app._link_health_check)
        self.addCleanup(safety.cleanup)

        safety.start_watchdog()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and ('joystick',) not in stopped:
            time.sleep(0.02)

        self.assertFalse(safety.is_motion_allowed(), 'Bewegung blieb freigegeben')
        self.assertIn('Kommandoschleife', safety.get_status()['system_stop_reason'])
        plan_stops = [eintrag for eintrag in stopped if eintrag[0] == 'plan']
        self.assertEqual(len(plan_stops), 1)
        self.assertEqual(plan_stops[0][1], 'safety_stop')
        self.assertTrue(plan_stops[0][2], 'Der Klartext des Stopps fehlt')
        self.assertIn(('nav', 'safety_stop'), stopped)
        self.assertIn(('joystick',), stopped)


if __name__ == '__main__':
    unittest.main()
