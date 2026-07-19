import time
import unittest
from dataclasses import dataclass
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from communication.can_handler import CANHandler


@dataclass
class FakeCANConfig:
    interface: str = "can0"
    bitrate: int = 250000
    motor_controller_id: int = 0x200
    sensor_hub_id: int = 0x100
    max_frame_size: int = 6
    frame_timeout: float = 1.0


class CANStatusTests(unittest.TestCase):
    def setUp(self):
        with patch("communication.can_handler.CAN_AVAILABLE", False):
            self.handler = CANHandler(FakeCANConfig())
        self.handler.can_available = True
        self.handler.reader_running = True

    def tearDown(self):
        self.handler.cleanup()

    def test_reports_sensor_hub_and_all_expected_odrives_online(self):
        self.handler._process_sensor_data({"gps": {"rtk_status": "FIXED"}})
        for node_id in range(4):
            self.handler._record_odrive_heartbeat(node_id, 0, 1)

        status = self.handler.get_status(expected_odrive_node_ids=[0, 1, 2, 3])

        self.assertTrue(status["interface_online"])
        self.assertTrue(status["sensor_hub"]["online"])
        self.assertEqual(status["odrives"]["online_count"], 4)
        self.assertTrue(status["odrives"]["all_online"])
        self.assertTrue(status["odrives"]["all_healthy"])
        self.assertTrue(status["network_healthy"])
        self.assertEqual(status["odrives"]["nodes"]["3"]["state"], 1)

    def test_reports_missing_and_stale_odrive_nodes(self):
        self.handler._process_sensor_data({"imu": {"heading": 90.0}})
        self.handler._record_odrive_heartbeat(0, 0, 1)
        self.handler._record_odrive_heartbeat(1, 0x20, 1)
        with self.handler._odrive_heartbeats_lock:
            self.handler._odrive_heartbeats[1]["last_seen_monotonic"] = time.monotonic() - 5.0

        status = self.handler.get_status(
            expected_odrive_node_ids=[0, 1, 2, 3],
            odrive_timeout_s=1.0,
        )

        self.assertEqual(status["odrives"]["online_count"], 1)
        self.assertFalse(status["odrives"]["all_online"])
        self.assertFalse(status["odrives"]["nodes"]["1"]["online"])
        self.assertEqual(status["odrives"]["nodes"]["1"]["error"], 0x20)
        self.assertEqual(status["odrives"]["error_node_ids"], [1])
        self.assertFalse(status["odrives"]["all_healthy"])
        self.assertIsNone(status["odrives"]["nodes"]["2"]["age_s"])
        self.assertFalse(status["network_healthy"])

    def test_navigation_command_does_not_fake_sensor_telemetry_status(self):
        self.handler._process_sensor_data({"cmd": "nav_start"})

        status = self.handler.get_status(expected_odrive_node_ids=[0])

        self.assertFalse(status["sensor_hub"]["online"])
        self.assertIsNone(status["sensor_hub"]["age_s"])


if __name__ == "__main__":
    unittest.main()
