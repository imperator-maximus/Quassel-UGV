import sys
import types
import unittest
from pathlib import Path


class _FakeParseError(Exception):
    pass


class _FakeGGA:
    pass


class _FakeHDT:
    pass


def _fake_parse(sentence: str):
    if sentence.startswith('$GNGGA'):
        msg = _FakeGGA()
        msg.gps_qual = 4
        msg.latitude = 53.1234
        msg.longitude = 11.5678
        msg.altitude = 12.3
        msg.num_sats = 21
        return msg

    if sentence.startswith('$GNHDT'):
        msg = _FakeHDT()
        msg.heading = 123.4
        return msg

    raise _FakeParseError(sentence)


fake_serial = types.ModuleType('serial')
fake_serial.Serial = object
fake_pynmea2 = types.ModuleType('pynmea2')
fake_pynmea2.ParseError = _FakeParseError
fake_pynmea2.GGA = _FakeGGA
fake_pynmea2.HDT = _FakeHDT
fake_pynmea2.parse = _fake_parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_orig_serial = sys.modules.get('serial')
_orig_pynmea2 = sys.modules.get('pynmea2')
sys.modules['serial'] = fake_serial
sys.modules['pynmea2'] = fake_pynmea2

from gps_handler import GPSHandler

if _orig_serial is not None:
    sys.modules['serial'] = _orig_serial
else:
    del sys.modules['serial']

if _orig_pynmea2 is not None:
    sys.modules['pynmea2'] = _orig_pynmea2
else:
    del sys.modules['pynmea2']


class GPSHandlerTests(unittest.TestCase):
    def test_parses_hdt_heading(self):
        gps = GPSHandler('/dev/null', 230400)

        gps._parse_nmea('$GNHDT,123.4,T*00')

        self.assertAlmostEqual(gps.get_status()['heading'], 123.4)

    def test_parses_ths_heading_with_valid_mode(self):
        gps = GPSHandler('/dev/null', 230400)

        gps._parse_nmea('$GNTHS,91.5,A*00')

        self.assertAlmostEqual(gps.get_status()['heading'], 91.5)

    def test_ignores_ths_heading_with_invalid_mode(self):
        gps = GPSHandler('/dev/null', 230400)

        gps._parse_nmea('$GNTHS,91.5,V*00')

        self.assertAlmostEqual(gps.get_status()['heading'], 0.0)

    def test_gga_updates_rtk_status_and_position(self):
        gps = GPSHandler('/dev/null', 230400)

        gps._parse_nmea('$GNGGA,205742.00,5319.9380,N,01104.7240,E,4,21,0.5,12.3,M,0.0,M,,*00')

        status = gps.get_status()
        self.assertEqual(status['rtk_status'], 'RTK FIXED')
        self.assertAlmostEqual(status['latitude'], 53.1234)
        self.assertAlmostEqual(status['longitude'], 11.5678)
        self.assertEqual(status['satellites'], 21)


if __name__ == '__main__':
    unittest.main()