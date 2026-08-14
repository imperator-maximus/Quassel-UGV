"""Tests for the Junctek KG110F battery monitor.

The frames below are real captures from the vehicle's meter, taken over its
CH9141 BLE bridge on 2026-07-29 while the vehicle sat idle. Decoding them is
pure logic, so the whole wire format is covered without any hardware.
"""

import time
import unittest

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


if __name__ == '__main__':
    unittest.main()
