"""Tests fuer die Push-Meldungen bei Stoerungen.

Der Meldeweg haengt an der Sicherheitslogik. Er muss deshalb zwei Dinge
beweisen: dass eine Stoerung tatsaechlich ankommt, und dass er unter keinen
Umstaenden den aufrufenden Thread aufhaelt oder eine Ausnahme durchreicht.
"""

import json
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.communication.push_notifier import PushNotifier


def notify_config(**overrides):
    config = dict(
        enabled=True,
        server='https://ntfy.example',
        topic='geheimes-topic',
        token='',
        click_url='',
        request_timeout_s=1.0,
        min_interval_s=120.0,
        retry_max_age_s=60.0,
        queue_size=8,
        fault_priority=5,
        recovery_priority=3,
        notify_recovery=True,
        motion_hold_after_s=20.0,
    )
    config.update(overrides)
    return SimpleNamespace(**config)


class RecordingSender:
    """Sammelt gesendete Nachrichten und kann Fehlschlaege simulieren."""

    def __init__(self, fail_times=0):
        self.calls = []
        self.fail_times = fail_times
        self.received = threading.Event()

    def __call__(self, url, body, headers, timeout_s):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError('kein Netz')
        self.calls.append({
            'url': url,
            'payload': json.loads(body.decode('utf-8')),
            'headers': headers,
            'timeout_s': timeout_s,
        })
        self.received.set()

    def wait(self, timeout=2.0):
        return self.received.wait(timeout)


def run_notifier(notifier, expected=1, timeout=2.0):
    """Startet den Notifier und wartet, bis die Warteschlange leer ist."""
    notifier.start()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(notifier._sender.calls) >= expected:
                break
            time.sleep(0.01)
        notifier.flush(timeout_s=0.5)
    finally:
        notifier.stop()


class DeliveryTest(unittest.TestCase):
    def test_fault_reaches_the_topic_as_json(self):
        sender = RecordingSender()
        notifier = PushNotifier(notify_config(), sender=sender)
        notifier.fault('plan', 'UGV: Mähdeck-Störung', 'Messer stehen still')
        run_notifier(notifier)

        self.assertEqual(len(sender.calls), 1)
        call = sender.calls[0]
        self.assertEqual(call['url'], 'https://ntfy.example')
        self.assertEqual(call['payload']['topic'], 'geheimes-topic')
        self.assertEqual(call['payload']['title'], 'UGV: Mähdeck-Störung')
        self.assertIn('Messer stehen still', call['payload']['message'])
        self.assertEqual(call['payload']['priority'], 5)

    def test_message_carries_the_time_of_the_fault(self):
        """Nach einem Netzausfall kommt die Meldung spaeter an als der Fehler."""
        sender = RecordingSender()
        notifier = PushNotifier(notify_config(), sender=sender)
        notifier.fault('plan', 'Titel', 'Grund')
        run_notifier(notifier)
        message = sender.calls[0]['payload']['message']
        self.assertRegex(message, r'^\d{2}:\d{2}:\d{2} · Grund$')

    def test_token_becomes_a_bearer_header(self):
        sender = RecordingSender()
        notifier = PushNotifier(notify_config(token='tk_geheim'), sender=sender)
        notifier.fault('plan', 'Titel', 'Grund')
        run_notifier(notifier)
        self.assertEqual(
            sender.calls[0]['headers']['Authorization'], 'Bearer tk_geheim'
        )

    def test_click_url_is_attached_when_configured(self):
        sender = RecordingSender()
        notifier = PushNotifier(
            notify_config(click_url='https://ugv.example/'), sender=sender
        )
        notifier.fault('plan', 'Titel', 'Grund')
        run_notifier(notifier)
        self.assertEqual(sender.calls[0]['payload']['click'], 'https://ugv.example/')

    def test_retries_until_the_network_is_back(self):
        sender = RecordingSender(fail_times=2)
        notifier = PushNotifier(notify_config(), sender=sender)
        # Kurze Wartezeiten, sonst dauert der Test Minuten.
        notifier._RETRY_DELAYS_S = (0.01,)
        notifier.fault('plan', 'Titel', 'Grund')
        run_notifier(notifier, timeout=3.0)
        self.assertEqual(len(sender.calls), 1)

    def test_gives_up_on_a_message_that_is_too_old(self):
        sender = RecordingSender(fail_times=99)
        notifier = PushNotifier(notify_config(retry_max_age_s=0.0), sender=sender)
        notifier.fault('plan', 'Titel', 'Grund')
        notifier.start()
        time.sleep(0.3)
        notifier.stop()
        self.assertEqual(sender.calls, [])
        self.assertEqual(notifier.get_status()['dropped'], 1)


class DebounceTest(unittest.TestCase):
    def test_same_fault_is_not_repeated_within_the_interval(self):
        sender = RecordingSender()
        notifier = PushNotifier(notify_config(), sender=sender)
        self.assertTrue(notifier.fault('plan', 'Titel', 'Grund'))
        self.assertFalse(notifier.fault('plan', 'Titel', 'Grund erneut'))
        run_notifier(notifier)
        self.assertEqual(len(sender.calls), 1)

    def test_different_faults_are_reported_independently(self):
        sender = RecordingSender()
        notifier = PushNotifier(notify_config(), sender=sender)
        self.assertTrue(notifier.fault('plan', 'A', 'Grund'))
        self.assertTrue(notifier.fault('system_stop', 'B', 'Grund'))
        run_notifier(notifier, expected=2)
        self.assertEqual(len(sender.calls), 2)

    def test_recovery_only_follows_a_reported_fault(self):
        sender = RecordingSender()
        notifier = PushNotifier(notify_config(), sender=sender)
        self.assertFalse(notifier.recovery('plan', 'Entwarnung', 'laeuft'))
        notifier.fault('plan', 'Stoerung', 'Grund')
        self.assertTrue(notifier.recovery('plan', 'Entwarnung', 'laeuft'))
        run_notifier(notifier, expected=2)
        self.assertEqual(
            [call['payload']['title'] for call in sender.calls],
            ['Stoerung', 'Entwarnung'],
        )

    def test_recovery_clears_the_debounce_for_the_next_fault(self):
        """Sonst bliebe die zweite Stoerung nach kurzer Erholung stumm."""
        sender = RecordingSender()
        notifier = PushNotifier(notify_config(), sender=sender)
        notifier.fault('plan', 'Stoerung 1', 'Grund')
        notifier.recovery('plan', 'Entwarnung', 'laeuft')
        self.assertTrue(notifier.fault('plan', 'Stoerung 2', 'Grund'))
        run_notifier(notifier, expected=3)
        self.assertEqual(len(sender.calls), 3)

    def test_recovery_can_be_switched_off(self):
        sender = RecordingSender()
        notifier = PushNotifier(notify_config(notify_recovery=False), sender=sender)
        notifier.fault('plan', 'Stoerung', 'Grund')
        self.assertFalse(notifier.recovery('plan', 'Entwarnung', 'laeuft'))
        run_notifier(notifier)
        self.assertEqual(len(sender.calls), 1)


class RobustnessTest(unittest.TestCase):
    def test_disabled_without_a_topic(self):
        notifier = PushNotifier(notify_config(topic=''))
        self.assertFalse(notifier.enabled)
        self.assertFalse(notifier.fault('plan', 'Titel', 'Grund'))

    def test_disabled_on_an_unusable_server(self):
        for server in ('', 'ftp://ntfy.example', 'kein-url'):
            with self.subTest(server=server):
                notifier = PushNotifier(notify_config(server=server))
                self.assertFalse(notifier.enabled)

    def test_notify_never_blocks_the_caller(self):
        """Der Aufrufer ist ein Sicherheitsthread - er darf nicht warten."""
        def slow_sender(url, body, headers, timeout_s):
            time.sleep(5.0)

        notifier = PushNotifier(notify_config(), sender=slow_sender)
        notifier.start()
        try:
            started = time.monotonic()
            for index in range(20):
                notifier.fault(f'event{index}', 'Titel', 'Grund')
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            notifier.stop()

    def test_full_queue_drops_instead_of_blocking(self):
        def slow_sender(url, body, headers, timeout_s):
            time.sleep(5.0)

        notifier = PushNotifier(notify_config(queue_size=2), sender=slow_sender)
        for index in range(10):
            notifier.fault(f'event{index}', 'Titel', 'Grund')
        self.assertLessEqual(notifier.get_status()['queued'], 2)
        self.assertGreater(notifier.get_status()['dropped'], 0)

    def test_a_broken_sender_does_not_escape(self):
        def exploding_sender(url, body, headers, timeout_s):
            raise RuntimeError('kaputt')

        notifier = PushNotifier(notify_config(retry_max_age_s=5.0), sender=exploding_sender)
        notifier.fault('plan', 'Titel', 'Grund')
        notifier.start()
        time.sleep(0.2)
        notifier.stop()
        self.assertIsNotNone(notifier.get_status()['last_error'])


if __name__ == '__main__':
    unittest.main()
