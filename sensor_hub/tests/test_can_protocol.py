import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from can_protocol import CANProtocol


class CANProtocolTests(unittest.TestCase):
    def test_decode_frame_reassembles_complete_json(self):
        protocol = CANProtocol()
        payload = b'{"cmd":"restart"}'
        chunks = [payload[i:i + 6] for i in range(0, len(payload), 6)]

        result = None
        for idx, chunk in enumerate(chunks):
            frame = bytes([idx, len(chunks)]) + chunk
            frame += b'\x00' * (8 - len(frame))
            result = protocol.decode_frame(0x200, frame)

        self.assertEqual(result, '{"cmd":"restart"}')


if __name__ == '__main__':
    unittest.main()