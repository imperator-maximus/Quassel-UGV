import base64
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from motor_controller.web.auth import LoginThrottle, WebAuthGuard


def basic(username, password):
    """Baut einen Authorization-Header wie ihn ein Browser sendet."""
    token = base64.b64encode(f"{username}:{password}".encode('utf-8')).decode('ascii')
    return f'Basic {token}'


def guard(**kwargs):
    defaults = dict(username='ugv', password='geheim')
    defaults.update(kwargs)
    return WebAuthGuard(**defaults)


class BasicAuthParsingTest(unittest.TestCase):
    def test_parses_valid_header(self):
        self.assertEqual(
            WebAuthGuard.parse_basic_auth(basic('ugv', 'geheim')),
            ('ugv', 'geheim'),
        )

    def test_password_may_contain_colon(self):
        self.assertEqual(
            WebAuthGuard.parse_basic_auth(basic('ugv', 'a:b:c')),
            ('ugv', 'a:b:c'),
        )

    def test_rejects_missing_and_malformed_headers(self):
        for header in ('', 'Bearer abc', 'Basic', 'Basic !!!nichtbase64!!!'):
            with self.subTest(header=header):
                self.assertIsNone(WebAuthGuard.parse_basic_auth(header))

    def test_rejects_header_without_colon(self):
        token = base64.b64encode(b'nurbenutzer').decode('ascii')
        self.assertIsNone(WebAuthGuard.parse_basic_auth(f'Basic {token}'))


class CredentialTest(unittest.TestCase):
    def test_accepts_correct_credentials(self):
        self.assertTrue(guard().check_credentials('ugv', 'geheim'))

    def test_rejects_wrong_password_and_user(self):
        self.assertFalse(guard().check_credentials('ugv', 'falsch'))
        self.assertFalse(guard().check_credentials('fremd', 'geheim'))

    def test_rejects_empty_credentials(self):
        self.assertFalse(guard().check_credentials('', ''))

    def test_accepts_werkzeug_hash(self):
        try:
            from werkzeug.security import generate_password_hash
        except ImportError:
            self.skipTest('werkzeug nicht installiert')
        hashed = generate_password_hash('geheim')
        protected = guard(password=hashed)
        self.assertTrue(protected.check_credentials('ugv', 'geheim'))
        self.assertFalse(protected.check_credentials('ugv', 'falsch'))


class AuthorizeTest(unittest.TestCase):
    def test_allows_authenticated_request(self):
        decision = guard().authorize(
            'GET', {'Authorization': basic('ugv', 'geheim')},
            'schloss.fdog.de', '203.0.113.5',
        )
        self.assertTrue(decision.allowed)

    def test_missing_credentials_trigger_challenge(self):
        decision = guard().authorize('GET', {}, 'schloss.fdog.de', '203.0.113.5')
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, 401)
        self.assertTrue(decision.challenge)

    def test_enabled_without_password_fails_closed(self):
        """Eine aktivierte, aber leere Konfiguration darf nicht durchlassen."""
        decision = guard(password='').authorize(
            'GET', {}, 'schloss.fdog.de', '203.0.113.5',
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, 503)

    def test_disabled_guard_allows_everything(self):
        decision = guard(enabled=False).authorize(
            'POST', {}, 'schloss.fdog.de', '203.0.113.5',
        )
        self.assertTrue(decision.allowed)


class OriginTest(unittest.TestCase):
    """Der Browser haengt Basic-Auth auch an Requests fremder Seiten an."""

    def _post(self, headers, guard_obj=None):
        merged = {'Authorization': basic('ugv', 'geheim')}
        merged.update(headers)
        return (guard_obj or guard()).authorize(
            'POST', merged, 'schloss.fdog.de', '203.0.113.5',
        )

    def test_rejects_cross_site_post(self):
        decision = self._post({'Sec-Fetch-Site': 'cross-site'})
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, 403)

    def test_rejects_foreign_origin_post(self):
        decision = self._post({'Origin': 'https://boese.example'})
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, 403)

    def test_allows_same_origin_post(self):
        self.assertTrue(
            self._post({'Origin': 'http://schloss.fdog.de',
                        'Sec-Fetch-Site': 'same-origin'}).allowed
        )

    def test_allows_https_origin_on_same_host(self):
        """Ein spaeter vorgeschalteter TLS-Proxy darf nichts brechen."""
        self.assertTrue(self._post({'Origin': 'https://schloss.fdog.de'}).allowed)

    def test_allows_explicitly_configured_origin(self):
        configured = guard(allowed_origins=['https://leitstand.example'])
        self.assertTrue(
            self._post({'Origin': 'https://leitstand.example'}, configured).allowed
        )

    def test_allows_client_without_browser_headers(self):
        """curl und Deploy-Skripte senden keinen Origin und bleiben erlaubt."""
        self.assertTrue(self._post({}).allowed)

    def test_get_is_never_blocked_by_origin(self):
        decision = guard().authorize(
            'GET',
            {'Authorization': basic('ugv', 'geheim'),
             'Sec-Fetch-Site': 'cross-site'},
            'schloss.fdog.de', '203.0.113.5',
        )
        self.assertTrue(decision.allowed)


class ThrottleTest(unittest.TestCase):
    def test_locks_out_after_configured_failures(self):
        protected = guard(throttle=LoginThrottle(max_failures=3, lockout_s=30.0))
        wrong = {'Authorization': basic('ugv', 'falsch')}

        for _ in range(3):
            decision = protected.authorize('GET', wrong, 'host', '203.0.113.9')
            self.assertEqual(decision.status, 401)

        decision = protected.authorize('GET', wrong, 'host', '203.0.113.9')
        self.assertEqual(decision.status, 429)
        self.assertGreater(decision.retry_after, 0)

    def test_lockout_is_per_source_address(self):
        protected = guard(throttle=LoginThrottle(max_failures=2, lockout_s=30.0))
        wrong = {'Authorization': basic('ugv', 'falsch')}
        for _ in range(3):
            protected.authorize('GET', wrong, 'host', '203.0.113.9')

        decision = protected.authorize(
            'GET', {'Authorization': basic('ugv', 'geheim')}, 'host', '198.51.100.4',
        )
        self.assertTrue(decision.allowed)

    def test_successful_login_clears_failures(self):
        throttle = LoginThrottle(max_failures=3, lockout_s=30.0)
        protected = guard(throttle=throttle)
        protected.authorize('GET', {'Authorization': basic('ugv', 'falsch')},
                            'host', '203.0.113.9')
        protected.authorize('GET', {'Authorization': basic('ugv', 'geheim')},
                            'host', '203.0.113.9')
        self.assertEqual(throttle.remaining_lockout_s('203.0.113.9'), 0.0)


if __name__ == '__main__':
    unittest.main()
