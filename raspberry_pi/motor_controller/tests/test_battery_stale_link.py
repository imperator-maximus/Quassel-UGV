"""Tests fuer die Erholung aus einer haengengebliebenen BLE-Verbindung.

Der Fall, den diese Tests festhalten, ist am 28.08.2026 aufgetreten. Nach
vielen Dienst-Neustarts hielt das Betriebssystem eine Verbindung zum
Junctek-Zaehler, aus der kein Prozess mehr las (``Connected: yes``,
``ServicesResolved: no``). Weil der Zaehler nur eine Verbindung zulaesst und
bei bestehender Verbindung das Advertising einstellt, fand ihn kein Scan mehr.
Der Monitor drehte sich acht Minuten im Kreis - und solange gab es keine
Ladezustandsueberwachung, also auch keine Abschaltung von Maehdeck und Fahrt
bei leerer Batterie.
"""

import logging
import sys
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.hardware.battery_monitor import BatteryMonitor


@dataclass
class FakeBatteryConfig:
    enabled: bool = True
    address: str = 'E4:66:E5:60:FB:1C'
    notify_uuid: str = '0000ffe1-0000-1000-8000-00805f9b34fb'
    capacity_ah: float = 50.0
    warn_percent: float = 30.0
    mow_stop_percent: float = 25.0
    drive_stop_percent: float = 20.0
    rearm_hysteresis_percent: float = 3.0
    stale_timeout_s: float = 120.0
    scan_timeout_s: float = 1.0
    connect_timeout_s: float = 1.0
    reconnect_delay_s: float = 0.01
    reconnect_max_delay_s: float = 0.05
    stale_link_recovery_enabled: bool = True
    stale_link_min_interval_s: float = 60.0


def build_monitor(**overrides):
    getrennt: List[str] = []
    config = FakeBatteryConfig(**overrides)
    monitor = BatteryMonitor(
        config,
        logger=logging.getLogger('test-battery'),
        link_dropper=lambda addr: (getrennt.append(addr), True)[1],
    )
    return monitor, getrennt


class StaleLinkRecoveryTests(unittest.TestCase):
    def test_trennt_nach_gescheiterter_uebernahme(self):
        monitor, getrennt = build_monitor()

        self.assertTrue(monitor._recover_stale_link(monitor.config.address))
        self.assertEqual(getrennt, [monitor.config.address])

    def test_trennt_nicht_oefter_als_der_mindestabstand(self):
        """Ein wirklich abgeschalteter Zaehler darf nicht dauernd bluetoothctl rufen."""
        monitor, getrennt = build_monitor()

        self.assertTrue(monitor._recover_stale_link(monitor.config.address))
        self.assertFalse(monitor._recover_stale_link(monitor.config.address))
        self.assertFalse(monitor._recover_stale_link(monitor.config.address))
        self.assertEqual(len(getrennt), 1)

    def test_trennt_nach_ablauf_des_mindestabstands_erneut(self):
        monitor, getrennt = build_monitor(stale_link_min_interval_s=0.05)

        self.assertTrue(monitor._recover_stale_link(monitor.config.address))
        time.sleep(0.08)
        self.assertTrue(monitor._recover_stale_link(monitor.config.address))
        self.assertEqual(len(getrennt), 2)

    def test_abschaltbar(self):
        monitor, getrennt = build_monitor(stale_link_recovery_enabled=False)

        self.assertFalse(monitor._recover_stale_link(monitor.config.address))
        self.assertEqual(getrennt, [])

    def test_gescheiterter_trennversuch_wird_gemeldet(self):
        config = FakeBatteryConfig()
        monitor = BatteryMonitor(
            config,
            logger=logging.getLogger('test-battery'),
            link_dropper=lambda addr: False,
        )
        self.assertFalse(monitor._recover_stale_link(config.address))


class BluetoothctlTests(unittest.TestCase):
    """Der Vorgabeweg ruft bluetoothctl auf - er darf nie durchschlagen."""

    def test_fehlendes_bluetoothctl_wirft_nicht(self):
        monitor, _ = build_monitor()
        import motor_controller.hardware.battery_monitor as modul

        original = modul.subprocess.run

        def platzt(*_a, **_k):
            raise FileNotFoundError('bluetoothctl')

        modul.subprocess.run = platzt
        try:
            self.assertFalse(monitor._bluetoothctl_disconnect('AA:BB:CC:DD:EE:FF'))
        finally:
            modul.subprocess.run = original

    def test_zeitlimit_wirft_nicht(self):
        monitor, _ = build_monitor()
        import motor_controller.hardware.battery_monitor as modul

        original = modul.subprocess.run

        def haengt(*_a, **_k):
            raise modul.subprocess.TimeoutExpired(cmd='bluetoothctl', timeout=10.0)

        modul.subprocess.run = haengt
        try:
            self.assertFalse(monitor._bluetoothctl_disconnect('AA:BB:CC:DD:EE:FF'))
        finally:
            modul.subprocess.run = original

    def test_erfolgsmeldung_wird_erkannt(self):
        monitor, _ = build_monitor()
        import motor_controller.hardware.battery_monitor as modul

        original = modul.subprocess.run

        class Ergebnis:
            stdout = 'Successful disconnected'
            stderr = ''
            returncode = 0

        modul.subprocess.run = lambda *_a, **_k: Ergebnis()
        try:
            self.assertTrue(monitor._bluetoothctl_disconnect('AA:BB:CC:DD:EE:FF'))
        finally:
            modul.subprocess.run = original


class ReaderLoopTests(unittest.TestCase):
    """Das Zusammenspiel in der Leseschleife, mit einem gefaelschten bleak."""

    def _mit_fake_bleak(self, scan_ergebnis, connect_fehler_bis):
        """Baut ein bleak-Modul, das erst scheitert und dann verbindet."""
        import types

        zustand = {'connects': 0, 'scans': 0}

        class FakeScanner:
            @staticmethod
            async def find_device_by_address(address, timeout=None):
                zustand['scans'] += 1
                return scan_ergebnis

        class FakeClient:
            def __init__(self, ziel, timeout=None):
                self.ziel = ziel
                self.is_connected = True

            async def __aenter__(self):
                zustand['connects'] += 1
                if zustand['connects'] <= connect_fehler_bis:
                    raise RuntimeError(
                        f"Device with address {FakeBatteryConfig.address} was not found."
                    )
                return self

            async def __aexit__(self, *_exc):
                return False

            async def start_notify(self, _uuid, _cb):
                # Sobald der Monitor haengt, ist der Test vorbei.
                raise KeyboardInterrupt('verbunden')

            async def stop_notify(self, _uuid):
                return None

        modul = types.ModuleType('bleak')
        modul.BleakScanner = FakeScanner
        modul.BleakClient = FakeClient
        return modul, zustand

    def test_scheiternde_uebernahme_loest_das_trennen_aus(self):
        """Der Ablauf vom 28.08.: kein Scan-Treffer, Uebernahme scheitert."""
        import asyncio

        modul, zustand = self._mit_fake_bleak(scan_ergebnis=None, connect_fehler_bis=1)
        sys.modules['bleak'] = modul
        try:
            monitor, getrennt = build_monitor()
            try:
                asyncio.run(asyncio.wait_for(monitor._reader_loop(), timeout=5.0))
            except (KeyboardInterrupt, asyncio.TimeoutError):
                pass

            self.assertEqual(getrennt, [monitor.config.address],
                             'Die haengende Verbindung muss getrennt werden')
            self.assertGreaterEqual(zustand['connects'], 2,
                                    'Nach dem Trennen muss neu verbunden werden')
        finally:
            sys.modules.pop('bleak', None)

    def test_ohne_uebernahmeversuch_wird_nicht_getrennt(self):
        """Findet der Scan das Geraet, ist ein Fehler ein gewoehnlicher Abriss."""
        import asyncio

        geraet = object()
        modul, _ = self._mit_fake_bleak(scan_ergebnis=geraet, connect_fehler_bis=1)
        sys.modules['bleak'] = modul
        try:
            monitor, getrennt = build_monitor()
            try:
                asyncio.run(asyncio.wait_for(monitor._reader_loop(), timeout=5.0))
            except (KeyboardInterrupt, asyncio.TimeoutError):
                pass

            self.assertEqual(getrennt, [],
                             'Ein normaler Verbindungsabriss darf nichts trennen')
        finally:
            sys.modules.pop('bleak', None)


if __name__ == '__main__':
    unittest.main()
