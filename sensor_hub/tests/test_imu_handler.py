import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from imu_handler import WitMotionUSBIMU, create_imu_handler


def build_frame(frame_type: int, values):
    payload = bytearray([0x55, frame_type])
    for value in values:
        payload.extend(int(value).to_bytes(2, byteorder='little', signed=True))
    checksum = sum(payload) & 0xFF
    payload.append(checksum)
    return bytes(payload)


class WitMotionHandlerTests(unittest.TestCase):
    def test_parser_updates_accel_gyro_orientation_and_mag(self):
        imu = WitMotionUSBIMU(port='COM_TEST', baudrate=9600)

        imu._process_bytes(build_frame(0x51, [2048, -1024, 16384, 2500]))
        imu._process_bytes(build_frame(0x52, [1638, -819, 327, 2500]))
        imu._process_bytes(build_frame(0x53, [8192, -4096, -2048, 0]))
        imu._process_bytes(build_frame(0x54, [120, -240, 360, 0]))

        data = imu.get_data()
        orientation = imu.get_orientation()
        motion = imu.get_motion_status()

        self.assertAlmostEqual(data['accel']['x'], 9.81, places=2)
        self.assertAlmostEqual(data['gyro']['x'], 99.98, places=1)
        self.assertAlmostEqual(data['temperature'], 25.0, places=2)
        self.assertAlmostEqual(orientation['roll'], 45.0, places=2)
        self.assertAlmostEqual(orientation['pitch'], -22.5, places=2)
        self.assertAlmostEqual(orientation['yaw'], 348.75, places=2)
        self.assertEqual(data['mag']['z'], 360.0)
        self.assertTrue(data['is_calibrated'])
        self.assertFalse(motion['zupt_enabled'])

    def test_stationary_detection_accepts_tilted_rest_pose(self):
        imu = WitMotionUSBIMU(port='COM_TEST', baudrate=9600)

        imu._process_bytes(build_frame(0x51, [300, -200, 2015, 2500]))
        imu._process_bytes(build_frame(0x52, [3, -4, 2, 2500]))
        imu._process_bytes(build_frame(0x53, [255, -692, 4024, 0]))

        motion = imu.get_motion_status()
        orientation = imu.get_orientation()

        self.assertTrue(imu.get_data()['is_calibrated'])
        self.assertTrue(motion['is_stationary'])
        self.assertTrue(orientation['is_stationary'])

    def test_stationary_detection_marks_rotation_as_moving(self):
        imu = WitMotionUSBIMU(port='COM_TEST', baudrate=9600)

        imu._process_bytes(build_frame(0x51, [0, 0, 16384, 2500]))
        imu._process_bytes(build_frame(0x52, [0, 0, 82, 2500]))
        imu._process_bytes(build_frame(0x53, [0, 0, 4096, 0]))

        motion = imu.get_motion_status()

        self.assertFalse(motion['is_stationary'])

    def test_invalid_checksum_is_ignored(self):
        imu = WitMotionUSBIMU(port='COM_TEST', baudrate=9600)
        frame = bytearray(build_frame(0x53, [0, 0, 0, 0]))
        frame[-1] = (frame[-1] + 1) & 0xFF

        imu._process_bytes(bytes(frame))

        self.assertFalse(imu.get_data()['is_calibrated'])
        self.assertEqual(imu.get_orientation()['yaw'], 0.0)

    def test_create_imu_handler_returns_witmotion_handler(self):
        imu = create_imu_handler('witmotion', port='COM_TEST', baudrate=9600)
        self.assertIsInstance(imu, WitMotionUSBIMU)

    def test_create_imu_handler_rejects_legacy_types(self):
        with self.assertRaises(ValueError):
            create_imu_handler('icm42688p', port='COM_TEST', baudrate=9600)


if __name__ == '__main__':
    unittest.main()