"""Der Statusstrom zur Oberflaeche muss sparsam sein.

Das Fahrzeug haengt an einer SIM-Karte. Frueher ging zehnmal je Sekunde der
vollstaendige Status ueber die Leitung - gut 5,5 kB je Sendung, rund 200 MB in
der Stunde, obwohl sich zwischen zwei Sendungen fast nichts aenderte. Diese
Tests halten fest, dass nur noch Aenderungen uebertragen werden, dass sich der
volle Stand daraus wieder zusammensetzen laesst und dass ohne Aenderung gar
nichts gesendet wird.
"""

import gzip
import json
import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.web import status_delta
from motor_controller.web.web_server import WebServer
from motor_controller.tests.web_test_support import authenticated_client, web_config


class RecordingSocketIO:
    def __init__(self):
        self.emitted = []

    def emit(self, event, payload=None, **kwargs):
        self.emitted.append((event, payload, kwargs.get('to')))


class FakeBattery:
    def __init__(self, status):
        self.status = status

    def get_status(self):
        return dict(self.status)


def build_server(battery=None, joystick_enabled=False, **config_overrides):
    dummy = SimpleNamespace()
    can = SimpleNamespace(
        get_sensor_data=lambda: {'gps': {'lat': 53.3323205, 'lon': 11.0787511}},
        get_status=lambda **_kwargs: {'odrives': {}, 'sensor_hub': {}},
    )
    motor = SimpleNamespace(
        get_status=lambda: {'current_pwm': {'left': 1500, 'right': 1500}}
    )
    joystick = SimpleNamespace(
        get_status=lambda: {'enabled': joystick_enabled, 'max_speed': 100}
    )
    return WebServer(
        web_config(**config_overrides), motor, joystick, can, dummy, battery=battery
    )


class QuantisierungTests(unittest.TestCase):
    def test_zahlen_werden_auf_das_angezeigte_mass_gerundet(self):
        raw = {
            'battery_status': {'voltage_v': 26.5412345, 'soc_percent': 97.71234},
            'sensor_data': {'gps': {'lat': 53.33232051234, 'heading': 209.6712}},
        }

        quantized = status_delta.quantize(raw)

        self.assertEqual(quantized['battery_status']['voltage_v'], 26.54)
        self.assertEqual(quantized['battery_status']['soc_percent'], 97.7)
        self.assertEqual(quantized['sensor_data']['gps']['lat'], 53.3323205)
        self.assertEqual(quantized['sensor_data']['gps']['heading'], 209.7)

    def test_alterswerte_werden_auf_ganze_sekunden_gerundet(self):
        """Alter steht nur in Sprechblasen; entschieden wird ueber ``fresh``.

        Auf Zehntel gerundet wanderte es in jeder Sendung weiter und war
        allein ein Viertel des uebrigen Datenstroms.
        """
        quantized = status_delta.quantize({
            'battery_status': {'age_s': 0.62},
            'odrive_heartbeat_ages': {'0': 1.17, '1': 0.14},
        })

        self.assertEqual(quantized['battery_status']['age_s'], 1)
        # Der Schluessel ist hier eine Knotennummer - die Bedeutung steht im
        # Namen des Elternteils und muss durchgereicht werden.
        self.assertEqual(quantized['odrive_heartbeat_ages'], {'0': 1, '1': 0})

    def test_rauschen_erzeugt_keine_aenderung(self):
        """Eine Spannung, die in der vierten Stelle zappelt, ist keine Aenderung.

        Ohne diesen Schritt waere jede Differenz so gross wie der volle Status,
        und die ganze Ersparnis waere dahin.
        """
        first = status_delta.quantize({'battery_status': {'voltage_v': 26.5412}})
        second = status_delta.quantize({'battery_status': {'voltage_v': 26.5389}})

        self.assertEqual(status_delta.diff(first, second), {})


class DifferenzTests(unittest.TestCase):
    def test_nur_geaenderte_felder_stehen_in_der_differenz(self):
        old = {'a': {'x': 1, 'y': 2}, 'b': 'gleich'}
        new = {'a': {'x': 1, 'y': 3}, 'b': 'gleich'}

        self.assertEqual(status_delta.diff(old, new), {'a': {'y': 3}})

    def test_listen_werden_als_ganzes_ersetzt(self):
        old = {'waypoints': [{'lat': 1.0}]}
        new = {'waypoints': [{'lat': 1.0}, {'lat': 2.0}]}

        self.assertEqual(status_delta.diff(old, new), {'waypoints': new['waypoints']})

    def test_entfallene_schluessel_werden_gemeldet(self):
        patch = status_delta.diff({'a': 1, 'weg': 2}, {'a': 1})

        self.assertEqual(patch, {status_delta.DELETED_KEY: ['weg']})
        self.assertEqual(status_delta.apply_patch({'a': 1, 'weg': 2}, patch), {'a': 1})

    def test_voller_stand_laesst_sich_wieder_zusammensetzen(self):
        old = {'a': {'x': 1, 'y': 2}, 'weg': True, 'liste': [1]}
        new = {'a': {'x': 5, 'y': 2}, 'liste': [1, 2], 'neu': 'da'}

        rebuilt = status_delta.apply_patch(old, status_delta.diff(old, new))

        self.assertEqual(rebuilt, new)


class StatusstromTests(unittest.TestCase):
    def test_neuer_client_bekommt_den_vollen_stand_allein(self):
        server = build_server(FakeBattery({'enabled': True, 'soc_percent': 97.7}))
        server.socketio = RecordingSocketIO()

        server._emit_full_status(to='sid-1')

        event, message, target = server.socketio.emitted[-1]
        self.assertEqual(event, 'status_update')
        self.assertEqual(target, 'sid-1')
        self.assertEqual(message['status']['battery_status']['soc_percent'], 97.7)
        self.assertGreater(message['seq'], 0)

    def test_danach_geht_nur_noch_die_aenderung_raus(self):
        battery = FakeBattery({'enabled': True, 'soc_percent': 97.7})
        server = build_server(battery)
        server.socketio = RecordingSocketIO()
        server._emit_full_status(to='sid-1')
        _event, first, _to = server.socketio.emitted[-1]

        battery.status['soc_percent'] = 97.6
        server._emit_status_update()

        event, message, _to = server.socketio.emitted[-1]
        self.assertEqual(event, 'status_delta')
        self.assertEqual(message['seq'], first['seq'] + 1)
        self.assertEqual(message['patch'], {'battery_status': {'soc_percent': 97.6}})

    def test_die_differenz_ergibt_wieder_den_vollen_status(self):
        battery = FakeBattery({'enabled': True, 'soc_percent': 97.7})
        server = build_server(battery)
        server.socketio = RecordingSocketIO()
        server._emit_full_status(to='sid-1')
        _event, first, _to = server.socketio.emitted[-1]

        battery.status['soc_percent'] = 90.0
        server._emit_status_update()
        _event, delta, _to = server.socketio.emitted[-1]

        rebuilt = status_delta.apply_patch(first['status'], delta['patch'])
        self.assertEqual(rebuilt, server._status_baseline)

    def test_ohne_aenderung_wird_nichts_gesendet(self):
        server = build_server(FakeBattery({'enabled': True, 'soc_percent': 97.7}))
        server.socketio = RecordingSocketIO()
        server._emit_full_status(to='sid-1')
        vorher = len(server.socketio.emitted)

        server._emit_status_update()

        self.assertEqual(len(server.socketio.emitted), vorher)

    def test_ein_zweiter_client_setzt_auf_derselben_nummer_auf(self):
        """Beide Clients muessen dieselbe Nummer sehen.

        Bekaeme der zweite einen Stand, den der erste nie gesehen hat, wuerde
        die naechste Differenz bei einem von beiden nicht passen - und der
        volle Status ginge wieder ueber die Leitung.
        """
        battery = FakeBattery({'enabled': True, 'soc_percent': 97.7})
        server = build_server(battery)
        server.socketio = RecordingSocketIO()
        server._emit_full_status(to='sid-1')

        battery.status['soc_percent'] = 95.0
        server._emit_full_status(to='sid-2')

        events = [e for e, _p, _t in server.socketio.emitted]
        self.assertEqual(events[-2:], ['status_delta', 'status_update'])
        _e, delta, _t = server.socketio.emitted[-2]
        _e, full, target = server.socketio.emitted[-1]
        self.assertEqual(target, 'sid-2')
        self.assertEqual(delta['seq'], full['seq'])


class SendetaktTests(unittest.TestCase):
    def test_im_stillstand_wird_langsam_gesendet(self):
        server = build_server()

        self.assertEqual(server._status_interval(), 1.0)

    def test_bei_aktivem_joystick_wird_schnell_gesendet(self):
        server = build_server(joystick_enabled=True)

        self.assertEqual(server._status_interval(), 0.25)


class KomprimierungTests(unittest.TestCase):
    def test_statusantwort_geht_gepackt_raus(self):
        server = build_server(
            FakeBattery({'enabled': True, 'soc_percent': 97.7}),
            compress_min_bytes=10,
        )
        client = authenticated_client(server)

        response = client.get('/api/status', headers={'Accept-Encoding': 'gzip'})

        self.assertEqual(response.headers.get('Content-Encoding'), 'gzip')
        self.assertIn('Accept-Encoding', response.headers.get('Vary', ''))
        payload = json.loads(gzip.decompress(response.get_data()))
        self.assertEqual(payload['battery_status']['soc_percent'], 97.7)

    def test_ohne_gzip_im_browser_bleibt_die_antwort_lesbar(self):
        server = build_server(
            FakeBattery({'enabled': True, 'soc_percent': 97.7}),
            compress_min_bytes=10,
        )
        client = authenticated_client(server)

        response = client.get('/api/status', headers={'Accept-Encoding': 'identity'})

        self.assertIsNone(response.headers.get('Content-Encoding'))
        self.assertEqual(
            response.get_json()['battery_status']['soc_percent'], 97.7
        )

    def test_kurze_antworten_bleiben_ungepackt(self):
        server = build_server(compress_min_bytes=100000)
        client = authenticated_client(server)

        response = client.get('/api/status', headers={'Accept-Encoding': 'gzip'})

        self.assertIsNone(response.headers.get('Content-Encoding'))


if __name__ == '__main__':
    unittest.main()
