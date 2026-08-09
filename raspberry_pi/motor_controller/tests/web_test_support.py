"""Gemeinsame Bausteine fuer Tests gegen den Webserver.

Der Webserver verlangt seit der Absicherung eine Anmeldung. Tests, die seine
HTTP-Schnittstelle benutzen, sollen sich wie ein angemeldeter Browser verhalten
statt den Schutz abzuschalten - so belegen sie nebenbei, dass er den regulaeren
Betrieb nicht behindert.
"""

import base64
from types import SimpleNamespace

TEST_USER = 'ugv'
TEST_PASSWORD = 'testpasswort'


def auth_header(username=TEST_USER, password=TEST_PASSWORD):
    """Basic-Auth-Header, wie ihn der Browser nach der Anmeldung sendet."""
    token = base64.b64encode(f"{username}:{password}".encode('utf-8')).decode('ascii')
    return f'Basic {token}'


def web_config(**overrides):
    """WebConfig-Stub mit aktivem Zugangsschutz."""
    config = dict(
        template_folder='.',
        static_folder='.',
        secret_key='test',
        auth_enabled=True,
        auth_username=TEST_USER,
        auth_password=TEST_PASSWORD,
        allowed_origins=[],
    )
    config.update(overrides)
    return SimpleNamespace(**config)


def authenticated_client(server, username=TEST_USER, password=TEST_PASSWORD):
    """Test-Client, dessen Requests alle angemeldet sind."""
    client = server.app.test_client()
    client.environ_base['HTTP_AUTHORIZATION'] = auth_header(username, password)
    return client
