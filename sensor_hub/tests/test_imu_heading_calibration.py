import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from imu_heading_calibration import ImuHeadingOffsetEstimator


class ImuHeadingOffsetEstimatorTests(unittest.TestCase):
    def test_initial_state_is_not_ready(self):
        est = ImuHeadingOffsetEstimator(window_size=10, min_samples=3)
        self.assertFalse(est.is_ready())
        self.assertIsNone(est.current_offset_deg())
        self.assertEqual(est.sample_count(), 0)

    def test_rejects_when_rtk_status_below_threshold(self):
        est = ImuHeadingOffsetEstimator(min_samples=1)
        accepted = est.update(
            corrected_gps_heading_deg=100.0,
            imu_heading_deg=10.0,
            rtk_status='GPS FIX',
            timestamp=1.0,
        )
        self.assertFalse(accepted)
        self.assertEqual(est.sample_count(), 0)
        self.assertIn('rtk_status', est.status()['last_reject_reason'] or '')

    def test_rejects_when_inputs_missing(self):
        est = ImuHeadingOffsetEstimator(min_samples=1)
        self.assertFalse(est.update(None, 10.0, 'RTK FIXED', 1.0))
        self.assertFalse(est.update(100.0, None, 'RTK FIXED', 1.0))
        self.assertEqual(est.sample_count(), 0)

    def test_accepts_when_rtk_fixed_and_inputs_valid(self):
        est = ImuHeadingOffsetEstimator(min_samples=1)
        accepted = est.update(
            corrected_gps_heading_deg=100.0,
            imu_heading_deg=10.0,
            rtk_status='RTK FIXED',
            timestamp=1.0,
        )
        self.assertTrue(accepted)
        self.assertEqual(est.sample_count(), 1)
        self.assertAlmostEqual(est.current_offset_deg(), 90.0, places=4)

    def test_circular_mean_handles_wrap_around(self):
        est = ImuHeadingOffsetEstimator(min_samples=2, max_heading_rate_dps=20.0)
        # Beide Samples ergeben offset = 355°; ein naiver linearer Mittelwert
        # zwischen 350° und 0° käme bei ~175° heraus, der zirkuläre Mittelwert
        # muss aber wieder bei ~355° landen.
        est.update(350.0, 355.0, 'RTK FIXED', 1.0)
        est.update(0.0, 5.0, 'RTK FIXED', 2.0)
        offset = est.current_offset_deg()
        self.assertIsNotNone(offset)
        self.assertTrue(offset < 10.0 or offset > 350.0,
                        f'circular mean should be near 355°, got {offset}')

    def test_offset_is_normalized_to_0_360(self):
        est = ImuHeadingOffsetEstimator(min_samples=1)
        est.update(10.0, 100.0, 'RTK FIXED', 1.0)
        offset = est.current_offset_deg()
        self.assertIsNotNone(offset)
        self.assertGreaterEqual(offset, 0.0)
        self.assertLess(offset, 360.0)
        self.assertAlmostEqual(offset, 270.0, places=4)

    def test_rejects_high_heading_rate(self):
        est = ImuHeadingOffsetEstimator(min_samples=1, max_heading_rate_dps=5.0)
        est.update(100.0, 10.0, 'RTK FIXED', 1.0)
        accepted = est.update(120.0, 10.0, 'RTK FIXED', 2.0)
        self.assertFalse(accepted)
        self.assertEqual(est.sample_count(), 1)
        self.assertIn('heading_rate', est.status()['last_reject_reason'] or '')

    def test_window_size_caps_samples(self):
        est = ImuHeadingOffsetEstimator(window_size=3, min_samples=1)
        for i in range(10):
            est.update(100.0 + 0.1 * i, 10.0, 'RTK FIXED', 1.0 + i * 10.0)
        self.assertEqual(est.sample_count(), 3)

    def test_not_ready_until_min_samples(self):
        est = ImuHeadingOffsetEstimator(window_size=10, min_samples=3)
        est.update(100.0, 10.0, 'RTK FIXED', 1.0)
        self.assertFalse(est.is_ready())
        self.assertIsNone(est.current_offset_deg())
        est.update(100.5, 10.5, 'RTK FIXED', 11.0)
        est.update(101.0, 11.0, 'RTK FIXED', 21.0)
        self.assertTrue(est.is_ready())
        self.assertIsNotNone(est.current_offset_deg())

    def test_reset_clears_state(self):
        est = ImuHeadingOffsetEstimator(min_samples=1)
        est.update(100.0, 10.0, 'RTK FIXED', 1.0)
        self.assertTrue(est.is_ready())
        est.reset()
        self.assertEqual(est.sample_count(), 0)
        self.assertFalse(est.is_ready())
        self.assertIsNone(est.current_offset_deg())

    def test_status_reports_window_and_min_samples(self):
        est = ImuHeadingOffsetEstimator(window_size=42, min_samples=5)
        status = est.status()
        self.assertEqual(status['window_size'], 42)
        self.assertEqual(status['min_samples'], 5)
        self.assertFalse(status['ready'])


if __name__ == '__main__':
    unittest.main()
