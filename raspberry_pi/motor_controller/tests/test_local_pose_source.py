"""Tests fuer die lokale GNSS-Pose am Raspberry.

Der Schwerpunkt liegt auf dem Verhalten im Fehlerfall. Solange der Empfaenger
liefert, ist wenig zu beweisen; gefaehrlich wird es, wenn er stehenbleibt oder
den Kurs verliert, und die Quelle trotzdem munter weiter einspeist.
"""

import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# pyserial gibt es nur auf dem Fahrzeug. Der Ersatz reicht fuer den Import;
# angefasst wird er in diesen Tests nicht, weil der GPS-Handler ausgetauscht
# wird.
if 'serial' not in sys.modules:
    serial_stub = types.ModuleType('serial')
    serial_stub.Serial = object
    sys.modules['serial'] = serial_stub

from navigation.navigation_controller import NavigationController
from sensors.local_pose_source import LocalPoseSource
from sensors.nmea import parse_gga, parse_heading, split_sentence
from sensors.vehicle_geometry import (
    correct_to_vehicle_center,
    gps_primary_offset_m,
    load_vehicle_geometry,
    resolve_heading,
)

GEOMETRY_PATH = Path(__file__).resolve().parents[1] / 'sensors' / 'vehicle_geometry.json'


@dataclass
class FakePoseConfig:
    """Nur die Felder, die LocalPoseSource liest."""
    poll_interval_s: float = 0.2
    telemetry_timeout_s: float = 30.0
    gps_port: str = '/dev/null'
    gps_baudrate: int = 230400
    gps_read_timeout_s: float = 1.0
    gps_max_fix_age_s: float = 2.0
    gps_max_heading_age_s: float = 2.0
    vehicle_geometry_path: str = str(GEOMETRY_PATH)
    ntrip_enabled: bool = False
    ntrip_host: str = 'openrtk-mv.de'
    ntrip_port: int = 2101
    ntrip_mountpoint: str = 'openrtk_mv'
    ntrip_username: str = ''
    ntrip_password: str = ''


class FakeGPS:
    """GPS-Handler-Ersatz, dessen Status der Test frei setzt."""

    def __init__(self, status: Dict[str, Any]):
        self.status = status
        self.port = '/dev/null'
        self.baudrate = 230400

    def get_status(self) -> Dict[str, Any]:
        return dict(self.status)

    def start(self):
        return True

    def stop(self):
        pass


def build_source(**status_overrides) -> tuple:
    """Baut eine Quelle mit ausgetauschtem GPS-Handler."""
    published: List[Dict[str, Any]] = []
    source = LocalPoseSource(FakePoseConfig(), published.append)
    status = {
        'latitude': 53.3324561,
        'longitude': 11.0786915,
        'altitude': 14.57,
        'heading': 268.47,
        'rtk_status': 'RTK FIXED',
        'satellites': 28,
        'is_connected': True,
        'fix_age_s': 0.1,
        'heading_age_s': 0.1,
        'sentence_age_s': 0.1,
        'sentences_ok': 100,
        'sentences_bad': 0,
        'reconnects': 1,
        'last_error': None,
        'port': '/dev/null',
    }
    status.update(status_overrides)
    source.gps = FakeGPS(status)
    return source, published


class NmeaParserTests(unittest.TestCase):
    """Der Parser ersetzt pynmea2, das auf dem Pi nicht installierbar ist."""

    GGA = ('$GNGGA,165440.00,5319.94736737,N,01104.72148843,E,4,28,0.5,'
           '14.5653,M,40.5220,M,,*4A')

    def test_gga_wird_in_dezimalgrad_umgerechnet(self):
        fields = split_sentence(self.GGA)
        self.assertIsNotNone(fields, 'Pruefsumme des Beispielsatzes muss stimmen')
        parsed = parse_gga(fields[1:])
        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed['latitude'], 53.33245612, places=7)
        self.assertAlmostEqual(parsed['longitude'], 11.07869147, places=7)
        self.assertEqual(parsed['quality'], 4)
        self.assertEqual(parsed['satellites'], 28)

    def test_verstuemmelter_satz_wird_verworfen(self):
        # Eine einzelne verdrehte Ziffer verschiebt die Position um Meter.
        kaputt = self.GGA.replace('5319.94736737', '5319.94736738')
        self.assertIsNone(split_sentence(kaputt))

    def test_satz_ohne_pruefsumme_wird_verworfen(self):
        self.assertIsNone(split_sentence(self.GGA.split('*')[0]))

    def test_gga_ohne_fix_liefert_nichts(self):
        ohne_fix = '$GNGGA,165440.00,,,,,0,00,99.9,,,,,,*43'
        fields = split_sentence(ohne_fix)
        self.assertIsNotNone(fields)
        self.assertIsNone(parse_gga(fields[1:]))

    def test_heading_aus_hdt_und_ths(self):
        hdt = split_sentence('$GNHDT,268.4651,T*11')
        self.assertEqual(parse_heading(hdt[0], hdt[1:]), 268.4651)
        ths = split_sentence('$GNTHS,268.4651,A*13')
        self.assertEqual(parse_heading(ths[0], ths[1:]), 268.4651)

    def test_ths_mit_ungueltiger_kennung_liefert_nichts(self):
        # 'V' heisst ungueltig. Der Wert im Feld sieht trotzdem plausibel aus.
        ths = split_sentence('$GNTHS,268.4651,V*04')
        self.assertIsNotNone(ths, 'Beispielsatz muss eine gueltige Pruefsumme haben')
        self.assertIsNone(parse_heading(ths[0], ths[1:]))


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.geometry = load_vehicle_geometry(GEOMETRY_PATH)

    def test_mast_und_imu_sind_ausgebaut(self):
        self.assertNotIn('mast', self.geometry)
        self.assertNotIn('imu', self.geometry)
        self.assertNotIn('imu', self.geometry.get('sensors', {}))

    def test_beide_antennen_auf_gleicher_hoehe(self):
        sensors = self.geometry['sensors']
        self.assertEqual(
            sensors['gps_primary']['height_m'],
            sensors['gps_secondary']['height_m'],
            'Nach dem Ausbau des Masts liegen beide Antennen auf Aufbauhoehe',
        )

    def test_baseline_bleibt_quer_zur_fahrtachse(self):
        # Die Antennen sitzen auf gleicher Hoehe und gleicher Laengsposition,
        # nur auf verschiedenen Seiten - die Baseline liegt damit quer, und
        # heading_offset_deg muss 90 sein.
        sensors = self.geometry['sensors']
        self.assertEqual(
            sensors['gps_primary']['rear_inset_m'],
            sensors['gps_secondary']['rear_inset_m'],
        )
        self.assertEqual(self.geometry['gnss']['heading_offset_deg'], 90.0)

    def test_hebelarm_zeigt_nach_hinten_rechts(self):
        offset = gps_primary_offset_m(self.geometry)
        self.assertIsNotNone(offset)
        x, y = offset
        self.assertLess(x, 0.0, 'Primaerantenne sitzt hinter dem Fahrzeugmittelpunkt')
        self.assertGreater(y, 0.0, 'und rechts davon')

    def test_hebelarmkorrektur_verschiebt_die_position(self):
        lat, lon = 53.3324561, 11.0786915
        # Kurs Nord: der Hebelarm zeigt nach hinten, die Mitte liegt also
        # noerdlich der Antenne.
        c_lat, c_lon = correct_to_vehicle_center(lat, lon, 0.0, self.geometry)
        self.assertGreater(c_lat, lat)
        # Ohne Kurs bleibt die Antennenposition stehen, statt geraten zu werden.
        u_lat, u_lon = correct_to_vehicle_center(lat, lon, None, self.geometry)
        self.assertEqual((u_lat, u_lon), (lat, lon))


class ResolveHeadingTests(unittest.TestCase):
    def test_offset_wird_addiert_und_normalisiert(self):
        info = resolve_heading(300.0, 90.0)
        self.assertAlmostEqual(info['heading_deg'], 30.0)
        self.assertEqual(info['heading_source'], 'dual_gnss')

    def test_fehlendes_heading_erzeugt_keinen_kurs(self):
        # Der eigentliche Grund fuer diesen Test: auf dem SensorHub stand hier
        # 0.0 als Ersatzwert, den der Offset in einen Kurs von 90 Grad
        # verwandelt haette. Die IMU fing das auf - die gibt es nicht mehr.
        info = resolve_heading(None, 90.0)
        self.assertIsNone(info['heading_deg'])
        self.assertEqual(info['heading_source'], 'unknown')


class PayloadTests(unittest.TestCase):
    def test_frische_daten_ergeben_eine_vollstaendige_pose(self):
        source, _ = build_source()
        payload = source._build_payload()
        self.assertIsNotNone(payload)
        self.assertEqual(payload['rtk_status'], 'RTK FIXED')
        self.assertEqual(payload['heading_source'], 'dual_gnss')
        # 268.47 + 90 = 358.47
        self.assertAlmostEqual(payload['heading'], 358.47, places=2)
        self.assertEqual(payload['gps']['satellites'], 28)

    def test_pose_ist_mit_der_navigation_lesbar(self):
        source, _ = build_source()
        payload = source._build_payload()
        lat, lon, heading = NavigationController._parse_pose(payload)
        self.assertAlmostEqual(heading, 358.47, places=2)
        self.assertTrue(53.0 < lat < 54.0)
        self.assertTrue(11.0 < lon < 12.0)

    def test_zeitstempel_ist_der_messzeitpunkt(self):
        """Fallstrick 1: der Zeitstempel darf nicht der des Verpackens sein."""
        import time
        source, _ = build_source(fix_age_s=1.5)
        payload = source._build_payload()
        self.assertIsNotNone(payload)
        alter = time.time() - payload['timestamp']
        self.assertGreater(alter, 1.4)
        self.assertLess(alter, 1.7)

    def test_veralteter_fix_wird_nicht_eingespeist(self):
        """Fallstrick 1: sonst faehrt das Fahrzeug auf eingefrorener Position."""
        source, _ = build_source(fix_age_s=5.0)
        self.assertIsNone(source._build_payload())
        self.assertEqual(source.get_status()['suppressed_stale_fix'], 1)

    def test_ohne_je_empfangenen_fix_wird_nichts_eingespeist(self):
        source, _ = build_source(fix_age_s=None, latitude=None, longitude=None)
        self.assertIsNone(source._build_payload())

    def test_fehlendes_heading_liefert_pose_ohne_kurs(self):
        """Ohne Kurs bleibt die Pose fuer den Handbetrieb, nicht fuer den Plan."""
        source, _ = build_source(heading=None, heading_age_s=None)
        payload = source._build_payload()
        self.assertIsNotNone(payload, 'Handbetrieb und Anzeige brauchen die Position')
        self.assertNotIn('heading', payload,
                         'Ein Kurs, den niemand gemessen hat, darf nicht entstehen')
        self.assertEqual(payload['heading_source'], 'unknown')
        # Die Navigation muss so eine Pose verwerfen statt geradeaus zu fahren.
        with self.assertRaises(ValueError):
            NavigationController._parse_pose(payload)

    def test_veraltetes_heading_zaehlt_als_fehlend(self):
        source, _ = build_source(heading_age_s=9.0)
        payload = source._build_payload()
        self.assertIsNotNone(payload)
        self.assertNotIn('heading', payload)
        self.assertEqual(source.get_status()['suppressed_no_heading'], 1)

    def test_ohne_kurs_bleibt_der_hebelarm_unangewendet(self):
        mit_kurs, _ = build_source()
        ohne_kurs, _ = build_source(heading=None, heading_age_s=None)
        a = mit_kurs._build_payload()
        b = ohne_kurs._build_payload()
        self.assertNotEqual(
            (a['gps']['lat'], a['gps']['lon']),
            (b['gps']['lat'], b['gps']['lon']),
            'Mit Kurs wird auf den Fahrzeugmittelpunkt gerechnet, ohne nicht',
        )


class StatusTests(unittest.TestCase):
    def test_status_meldet_die_lokale_quelle(self):
        source, _ = build_source()
        status = source.get_status()
        self.assertEqual(status['transport'], 'local')
        self.assertTrue(status['geometry_loaded'])
        self.assertEqual(status['heading_offset_deg'], 90.0)

    def test_status_ist_offline_solange_nichts_eingespeist_wurde(self):
        source, _ = build_source()
        status = source.get_status()
        self.assertFalse(status['online'])
        self.assertIsNone(status['age_s'])


if __name__ == '__main__':
    unittest.main()
