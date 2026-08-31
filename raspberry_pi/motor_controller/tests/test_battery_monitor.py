"""Tests for the Junctek KG110F battery monitor.

The frames below are real captures from the vehicle's meter, taken over its
CH9141 BLE bridge on 2026-07-29 while the vehicle sat idle. Decoding them is
pure logic, so the whole wire format is covered without any hardware.
"""

import asyncio
import logging
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.config import BatteryConfig
from motor_controller.hardware.battery_monitor import (
    BatteryMonitor,
    bcd_to_int,
    decode_frame,
    is_bcd,
    iter_frames,
)

# Captured frames, including the leading 0xbb and trailing 0xee.
VOLTAGE_FRAME = b"\xbb\x26\x59\xc0\x06\xee"
CURRENT_POWER_FRAME = b"\xbb\x39\xc1\x10\x36\xd8\x23\xee"
CAPACITY_FRAME = b"\xbb\x35\x99\xd5\x04\x99\x46\xd2\x03\x31\xd3\x06\xee"
RUNTIME_FRAME = b"\xbb\x74\x92\xd6\x75\x00\xd7\x95\xee"


def body_of(frame: bytes) -> bytes:
    return frame[1:-1]


def make_config(**overrides) -> BatteryConfig:
    values = {
        'enabled': True,
        'address': 'E4:66:E5:60:FB:1C',
        'capacity_ah': 50.0,
        'warn_percent': 30.0,
        'mow_stop_percent': 25.0,
        'drive_stop_percent': 20.0,
        'stale_timeout_s': 120.0,
    }
    values.update(overrides)
    return BatteryConfig(**values)


class BcdTest(unittest.TestCase):
    def test_valid_and_invalid_bytes(self):
        self.assertTrue(is_bcd(0x00))
        self.assertTrue(is_bcd(0x99))
        self.assertFalse(is_bcd(0x9A))
        self.assertFalse(is_bcd(0xC0))
        self.assertFalse(is_bcd(0xD5))

    def test_multi_byte_values(self):
        self.assertEqual(bcd_to_int(b"\x26\x59"), 2659)
        self.assertEqual(bcd_to_int(b"\x04\x99\x46"), 49946)
        self.assertIsNone(bcd_to_int(b"\x26\xc0"))


class DecodeFrameTest(unittest.TestCase):
    def test_voltage_only(self):
        self.assertEqual(decode_frame(body_of(VOLTAGE_FRAME)), {'voltage_v': 26.59})

    def test_current_and_power(self):
        decoded = decode_frame(body_of(CURRENT_POWER_FRAME))
        self.assertEqual(decoded['current_a'], 0.39)
        self.assertEqual(decoded['power_w'], 10.36)

    def test_capacity_frame_carries_three_fields(self):
        decoded = decode_frame(body_of(CAPACITY_FRAME))
        self.assertEqual(decoded['runtime_s'], 3599)
        self.assertEqual(decoded['remaining_ah'], 49.946)
        self.assertEqual(decoded['discharged_ah'], 0.331)

    def test_runtime_and_resistance(self):
        decoded = decode_frame(body_of(RUNTIME_FRAME))
        self.assertEqual(decoded['time_left_min'], 7492)
        self.assertEqual(decoded['internal_resistance_mohm'], 75.0)

    def test_power_matches_voltage_times_current(self):
        volts = decode_frame(body_of(VOLTAGE_FRAME))['voltage_v']
        decoded = decode_frame(body_of(CURRENT_POWER_FRAME))
        self.assertAlmostEqual(
            volts * decoded['current_a'], decoded['power_w'], delta=0.05
        )

    def test_unknown_tags_are_surfaced_not_dropped(self):
        # 0xd9 has never been observed; it must not vanish silently, otherwise
        # a charging direction flag could go unnoticed.
        decoded = decode_frame(b"\x12\x34\xd9\x00")
        self.assertEqual(decoded['unknown_tags'], {'0xd9': 1234})

    def test_implausible_values_are_rejected(self):
        # 99.99 V cannot occur on a 24 V pack and indicates a mis-framed read.
        self.assertEqual(decode_frame(b"\x99\x99\xc0\x00"), {})

    def test_short_frame_is_ignored(self):
        self.assertEqual(decode_frame(b"\x26"), {})


class IterFramesTest(unittest.TestCase):
    def test_extracts_consecutive_frames(self):
        buffer = bytearray(VOLTAGE_FRAME + CURRENT_POWER_FRAME)
        bodies = list(iter_frames(buffer))
        self.assertEqual(bodies, [body_of(VOLTAGE_FRAME), body_of(CURRENT_POWER_FRAME)])
        self.assertEqual(len(buffer), 0)

    def test_keeps_partial_frame_for_next_chunk(self):
        buffer = bytearray(VOLTAGE_FRAME + b"\xbb\x39\xc1")
        bodies = list(iter_frames(buffer))
        self.assertEqual(bodies, [body_of(VOLTAGE_FRAME)])
        # The incomplete tail survives so the split frame still decodes once
        # the rest of the notification arrives.
        buffer.extend(b"\x10\x36\xd8\x23\xee")
        self.assertEqual(list(iter_frames(buffer)), [body_of(CURRENT_POWER_FRAME)])

    def test_leading_garbage_is_discarded(self):
        buffer = bytearray(b"\x00\x01\x02" + VOLTAGE_FRAME)
        self.assertEqual(list(iter_frames(buffer)), [body_of(VOLTAGE_FRAME)])


class StilleAmZaehlerTests(unittest.TestCase):
    """Ein schweigender Zaehler ist nicht unbedingt ein abwesender.

    Der Junctek laesst nur eine BLE-Verbindung zu und stellt das Senden ein,
    solange eine besteht. Am 28.08.2026 um 00:50 Uhr blieb nach mehreren
    Dienstneustarts eine alte Verbindung im Betriebssystem stehen: Das Geraet
    schwieg deshalb, der Suchlauf fand nichts, und die Anzeige stand auf
    offline - waehrend `hcitool con` die offene Verbindung auflistete.
    """

    def setUp(self):
        self.gebaut = []
        # Wird im Test auf das Stopp-Signal des Monitors gesetzt, damit die
        # Schleife nach einer Runde endet.
        self.beenden = lambda: None
        pruefstand = self

        class FakeScanner:
            @staticmethod
            async def find_device_by_address(address, timeout=None):
                del address, timeout
                return None  # sendet nicht, weil verbunden

        class FakeClient:
            def __init__(self, ziel, timeout=None):
                del timeout
                pruefstand.gebaut.append(ziel)
                self.is_connected = True

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def start_notify(self, uuid, handler):
                del uuid, handler
                pruefstand.beenden()
                self.is_connected = False

            async def stop_notify(self, uuid):
                del uuid

        self.bleak = types.ModuleType("bleak")
        self.bleak.BleakScanner = FakeScanner
        self.bleak.BleakClient = FakeClient
        self.vorher = sys.modules.get("bleak")
        sys.modules["bleak"] = self.bleak

    def tearDown(self):
        if self.vorher is None:
            sys.modules.pop("bleak", None)
        else:
            sys.modules["bleak"] = self.vorher

    def test_ohne_advertisement_wird_die_adresse_trotzdem_versucht(self):
        monitor = BatteryMonitor(
            BatteryConfig(
                enabled=True,
                address="E4:66:E5:60:FB:1C",
                scan_timeout_s=0.01,
                connect_timeout_s=0.01,
                reconnect_delay_s=0.01,
                reconnect_max_delay_s=0.01,
            ),
            logging.getLogger("test"),
        )
        self.beenden = monitor._stop_event.set  # eine Runde, dann Schluss

        asyncio.run(monitor._reader_loop())

        self.assertEqual(["E4:66:E5:60:FB:1C"], self.gebaut)


class BatteryMonitorStatusTest(unittest.TestCase):
    def setUp(self):
        self.monitor = BatteryMonitor(make_config())

    def feed(self, *frames: bytes):
        for frame in frames:
            self.monitor._handle_payload(frame)

    def test_status_before_any_frame(self):
        status = self.monitor.get_status()
        self.assertFalse(status['fresh'])
        self.assertIsNone(status['soc_percent'])
        self.assertEqual(status['level'], 'unknown')

    def test_state_of_charge_from_remaining_capacity(self):
        self.feed(CAPACITY_FRAME)
        status = self.monitor.get_status()
        # 49.946 Ah of a 50 Ah pack
        self.assertEqual(status['soc_percent'], 99.9)
        self.assertEqual(status['level'], 'ok')
        self.assertTrue(status['fresh'])

    def test_fields_from_several_frames_are_merged(self):
        self.feed(VOLTAGE_FRAME, CURRENT_POWER_FRAME, CAPACITY_FRAME)
        status = self.monitor.get_status()
        self.assertEqual(status['voltage_v'], 26.59)
        self.assertEqual(status['current_a'], 0.39)
        self.assertEqual(status['remaining_ah'], 49.946)
        self.assertEqual(status['frames'], 3)

    def test_split_notification_still_decodes(self):
        self.feed(CAPACITY_FRAME[:5], CAPACITY_FRAME[5:])
        self.assertEqual(self.monitor.get_status()['remaining_ah'], 49.946)

    def test_levels_follow_thresholds(self):
        # 50 Ah pack: 32 %, 28 %, 22 %, 18 %
        cases = [(16.0, 'ok'), (14.0, 'warn'), (11.0, 'low'), (9.0, 'critical')]
        for remaining_ah, expected in cases:
            with self.subTest(remaining_ah=remaining_ah):
                monitor = BatteryMonitor(make_config())
                monitor._values = {'remaining_ah': remaining_ah}
                monitor._last_frame_monotonic = time.monotonic()
                self.assertEqual(monitor.get_status()['level'], expected)

    def test_stale_reading_is_not_fresh(self):
        self.feed(CAPACITY_FRAME)
        self.monitor._last_frame_monotonic = time.monotonic() - 300.0
        status = self.monitor.get_status()
        self.assertFalse(status['fresh'])
        self.assertEqual(status['level'], 'unknown')


class BatteryMonitorGatingTest(unittest.TestCase):
    def build(self, remaining_ah, age_s=0.0, enabled=True):
        monitor = BatteryMonitor(make_config(enabled=enabled))
        monitor._values = {'remaining_ah': remaining_ah}
        monitor._last_frame_monotonic = time.monotonic() - age_s
        return monitor

    def test_full_pack_allows_everything(self):
        monitor = self.build(45.0)
        self.assertTrue(monitor.mowing_allowed())
        self.assertTrue(monitor.drive_allowed())

    def test_mowing_stops_before_driving(self):
        monitor = self.build(11.0)  # 22 %
        self.assertFalse(monitor.mowing_allowed())
        self.assertTrue(monitor.drive_allowed())

    def test_driving_stops_at_critical(self):
        monitor = self.build(9.0)  # 18 %
        self.assertFalse(monitor.mowing_allowed())
        self.assertFalse(monitor.drive_allowed())

    def test_stale_reading_never_blocks(self):
        # A dropped BLE link must not immobilise the vehicle; the gauge is an
        # addition to the safety chain, not a new single point of failure.
        monitor = self.build(9.0, age_s=600.0)
        self.assertTrue(monitor.mowing_allowed())
        self.assertTrue(monitor.drive_allowed())

    def test_disabled_monitor_never_blocks(self):
        monitor = self.build(1.0, enabled=False)
        self.assertTrue(monitor.mowing_allowed())
        self.assertTrue(monitor.drive_allowed())


class BatteryMonitorCallbackTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.monitor = BatteryMonitor(make_config())
        self.monitor.set_low_battery_callback(
            lambda level, soc: self.events.append((level, soc))
        )

    def drive_soc(self, percent):
        remaining = percent / 100.0 * 50.0
        self.monitor._check_thresholds(
            self.monitor._state_of_charge({'remaining_ah': remaining})
        )

    def test_each_threshold_reports_once(self):
        self.drive_soc(28.0)
        self.drive_soc(27.0)
        self.assertEqual([event[0] for event in self.events], ['warn'])

    def test_falling_through_levels_reports_each(self):
        self.drive_soc(28.0)
        self.drive_soc(24.0)
        self.drive_soc(19.0)
        self.assertEqual(
            [event[0] for event in self.events], ['warn', 'low', 'critical']
        )

    def test_recovery_rearms_after_hysteresis(self):
        self.drive_soc(28.0)
        self.drive_soc(50.0)
        self.drive_soc(28.0)
        self.assertEqual([event[0] for event in self.events], ['warn', 'warn'])


class BatteryZeroPointTest(unittest.TestCase):
    """Der Nullpunkt, mit dem ein Batteriewechsel in der Anzeige ankommt."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'zero.json'

    def build(self, discharged_ah=None, remaining_ah=None, age_s=0.0, **overrides):
        monitor = BatteryMonitor(
            make_config(zero_point_path=str(self.path), **overrides)
        )
        werte = {}
        if discharged_ah is not None:
            werte['discharged_ah'] = discharged_ah
        if remaining_ah is not None:
            werte['remaining_ah'] = remaining_ah
        monitor._values = werte
        if werte:
            monitor._last_frame_monotonic = time.monotonic() - age_s
        return monitor

    def test_without_zero_point_the_meter_value_stands(self):
        monitor = self.build(discharged_ah=30.0, remaining_ah=20.0)
        status = monitor.get_status()
        self.assertEqual(status['soc_percent'], 40.0)
        self.assertEqual(status['soc_source'], 'meter')
        self.assertIsNone(status['zero_point'])

    def test_reset_declares_the_current_reading_full(self):
        monitor = self.build(discharged_ah=30.0, remaining_ah=20.0)
        result = monitor.reset_charge_level()
        self.assertTrue(result['success'], result.get('error'))
        status = monitor.get_status()
        self.assertEqual(status['soc_percent'], 100.0)
        self.assertEqual(status['soc_source'], 'zero_point')

    def test_charge_falls_with_consumption_after_the_reset(self):
        monitor = self.build(discharged_ah=30.0, remaining_ah=20.0)
        monitor.reset_charge_level()
        # 5 Ah aus 50 Ah verbraucht.
        monitor._values['discharged_ah'] = 35.0
        self.assertEqual(monitor.get_status()['soc_percent'], 90.0)

    def test_charge_keeps_falling_past_the_meter_floor(self):
        """Der eigentliche Grund fuer den Verbrauchszaehler als Grundlage.

        Der Zaehler klemmt seine Restkapazitaet bei null fest. Haenge man den
        Nullpunkt daran, bliebe die Anzeige genau dann stehen, wenn die
        Batterie leer wird - und die Abschaltungen kaemen nie.
        """
        monitor = self.build(discharged_ah=40.0, remaining_ah=10.0)
        monitor.reset_charge_level()
        monitor._values['discharged_ah'] = 85.0   # 45 Ah verbraucht
        monitor._values['remaining_ah'] = 0.0     # Zaehler steht am Anschlag
        status = monitor.get_status()
        self.assertEqual(status['soc_percent'], 10.0)
        self.assertEqual(status['level'], 'critical')
        self.assertFalse(monitor.drive_allowed())

    def test_charging_beyond_the_zero_point_stays_at_full(self):
        monitor = self.build(discharged_ah=30.0, remaining_ah=20.0)
        monitor.reset_charge_level()
        monitor._values['discharged_ah'] = 28.0
        self.assertEqual(monitor.get_status()['soc_percent'], 100.0)

    def test_zero_point_survives_a_restart(self):
        monitor = self.build(discharged_ah=30.0, remaining_ah=20.0)
        monitor.reset_charge_level()
        # Der Batteriewechsel nimmt dem Fahrzeug die Versorgung; danach laeuft
        # ein neuer Prozess gegen denselben weiterzaehlenden Zaehler.
        neu = self.build(discharged_ah=32.0, remaining_ah=18.0)
        status = neu.get_status()
        self.assertEqual(status['soc_source'], 'zero_point')
        self.assertEqual(status['soc_percent'], 96.0)

    def test_reset_refuses_on_a_stale_reading(self):
        monitor = self.build(discharged_ah=30.0, remaining_ah=20.0, age_s=600.0)
        result = monitor.reset_charge_level()
        self.assertFalse(result['success'])
        self.assertIn('aktuelle', result['error'].lower())
        self.assertFalse(self.path.exists())

    def test_reset_refuses_without_a_consumption_value(self):
        monitor = self.build(remaining_ah=20.0)
        result = monitor.reset_charge_level()
        self.assertFalse(result['success'])
        self.assertFalse(self.path.exists())

    def test_reset_needs_a_configured_path(self):
        monitor = BatteryMonitor(make_config())
        monitor._values = {'discharged_ah': 30.0, 'remaining_ah': 20.0}
        monitor._last_frame_monotonic = time.monotonic()
        result = monitor.reset_charge_level()
        self.assertFalse(result['success'])
        self.assertFalse(monitor.get_status()['can_reset'])

    def test_reset_rearms_the_warnings(self):
        monitor = self.build(discharged_ah=45.0, remaining_ah=5.0)
        events = []
        monitor.set_low_battery_callback(lambda level, soc: events.append(level))
        monitor._check_thresholds(monitor._state_of_charge(monitor._values))
        self.assertIn('critical', events)
        monitor.reset_charge_level()
        events.clear()
        monitor._values['discharged_ah'] = 90.0  # wieder 45 Ah verbraucht
        monitor._check_thresholds(monitor._state_of_charge(monitor._values))
        self.assertIn('critical', events)

    def test_replaced_meter_falls_back_instead_of_lying(self):
        monitor = self.build(discharged_ah=80.0, remaining_ah=20.0)
        monitor.reset_charge_level()
        # Ein zurueckgesetzter oder getauschter Zaehler faengt von vorn an.
        # Sein Stand und der Nullpunkt haben nichts mehr miteinander zu tun.
        monitor._values['discharged_ah'] = 1.0
        monitor._values['remaining_ah'] = 49.0
        status = monitor.get_status()
        self.assertEqual(status['soc_source'], 'meter')
        self.assertEqual(status['soc_percent'], 98.0)

    def test_broken_file_does_not_kill_the_monitor(self):
        self.path.write_text('{kaputt', encoding='utf-8')
        monitor = self.build(discharged_ah=30.0, remaining_ah=20.0)
        status = monitor.get_status()
        self.assertEqual(status['soc_source'], 'meter')
        self.assertEqual(status['soc_percent'], 40.0)


if __name__ == '__main__':
    unittest.main()
