#!/usr/bin/env python3
"""HTTP-Basic-Auth und Origin-Schutz fuer das oeffentlich erreichbare Web-Interface.

Das Web-Interface haengt ueber eine Portfreigabe direkt am Internet und kann
Fahrantrieb und Maehdeck starten. Ohne Zugangsschutz genuegt die blosse Kenntnis
der Adresse, um das Fahrzeug zu bewegen.

Das Modul kommt bewusst ohne Flask-Import aus, damit die Zugangslogik auf jedem
Rechner testbar bleibt und nicht erst mit einem laufenden Webserver.

Basic-Auth ueber unverschluesseltes HTTP uebertraegt das Passwort bei jedem
Request mitlesbar. Der Guard ist deshalb so gebaut, dass ein spaeter
vorgeschalteter TLS-Reverse-Proxy keine Codeaenderung erfordert: Ein
``Origin``-Header mit ``https`` auf denselben Host gilt als gleichwertig.
"""

import base64
import binascii
import hmac
import logging
import threading
import time
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple
from urllib.parse import urlsplit

try:
    from werkzeug.security import check_password_hash
    _WERKZEUG_AVAILABLE = True
except ImportError:  # pragma: no cover - nur auf Systemen ohne Flask-Stack
    check_password_hash = None
    _WERKZEUG_AVAILABLE = False


# Praefixe, an denen ein Werkzeug-Passwort-Hash erkennbar ist. Alles andere
# wird als Klartext-Passwort behandelt.
HASH_PREFIXES = ('pbkdf2:', 'scrypt:', 'argon2:')

# Methoden, die den Fahrzeugzustand nicht veraendern. Nur fuer die uebrigen
# laeuft die Origin-Pruefung, damit Statusabfragen aus Skripten frei bleiben.
SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})


def looks_like_hash(secret: str) -> bool:
    """Erkennt einen Werkzeug-Passwort-Hash am Praefix."""
    return any(secret.startswith(prefix) for prefix in HASH_PREFIXES)


class AuthDecision(NamedTuple):
    """Ergebnis einer Zugangspruefung.

    ``challenge`` entscheidet, ob die Antwort einen ``WWW-Authenticate``-Header
    traegt und der Browser damit seinen Anmeldedialog oeffnet.
    """
    allowed: bool
    status: int = 200
    message: str = ''
    challenge: bool = False
    retry_after: int = 0


ALLOW = AuthDecision(allowed=True)


class LoginThrottle:
    """Bremst das Durchprobieren von Passwoertern pro Quell-IP aus.

    Ohne Bremse ist ein oeffentlich erreichbares Basic-Auth nur so stark wie die
    Rate, mit der jemand raten darf. Die Sperre ist absichtlich kurz: Sie soll
    Rateversuche unwirtschaftlich machen, dich aber nicht dauerhaft aussperren,
    wenn du dich selbst zweimal vertippst.
    """

    def __init__(self, max_failures: int = 8, lockout_s: float = 60.0,
                 window_s: float = 300.0):
        self.max_failures = max(1, int(max_failures))
        self.lockout_s = max(0.0, float(lockout_s))
        self.window_s = max(1.0, float(window_s))
        self._lock = threading.Lock()
        # key -> (Fehlversuche, Zeitpunkt des letzten Fehlversuchs)
        self._failures: Dict[str, Tuple[int, float]] = {}

    def remaining_lockout_s(self, key: str) -> float:
        """Verbleibende Sperrzeit in Sekunden, 0.0 wenn nicht gesperrt."""
        now = time.monotonic()
        with self._lock:
            entry = self._failures.get(key)
            if not entry:
                return 0.0
            count, last = entry
            if now - last > self.window_s:
                self._failures.pop(key, None)
                return 0.0
            if count < self.max_failures:
                return 0.0
            remaining = self.lockout_s - (now - last)
            return remaining if remaining > 0.0 else 0.0

    def record_failure(self, key: str) -> int:
        """Zaehlt einen Fehlversuch und liefert den neuen Zaehlerstand."""
        now = time.monotonic()
        with self._lock:
            count, last = self._failures.get(key, (0, now))
            if now - last > self.window_s:
                count = 0
            count += 1
            self._failures[key] = (count, now)
            self._prune_locked(now)
            return count

    def record_success(self, key: str) -> None:
        """Loescht die Fehlversuche nach erfolgreicher Anmeldung."""
        with self._lock:
            self._failures.pop(key, None)

    def _prune_locked(self, now: float) -> None:
        """Entfernt abgelaufene Eintraege, damit die Tabelle nicht waechst."""
        stale = [k for k, (_, last) in self._failures.items()
                 if now - last > self.window_s]
        for key in stale:
            self._failures.pop(key, None)


class WebAuthGuard:
    """Prueft Basic-Auth-Zugangsdaten und die Herkunft schreibender Requests."""

    def __init__(self, username: str, password: str,
                 realm: str = 'Quassel UGV',
                 allowed_origins: Optional[Iterable[str]] = None,
                 enabled: bool = True,
                 throttle: Optional[LoginThrottle] = None,
                 logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.enabled = bool(enabled)
        self.username = str(username or '')
        self.password = str(password or '')
        self.realm = str(realm or 'Quassel UGV')
        self.throttle = throttle or LoginThrottle()
        self.allowed_origins = self._normalize_origins(allowed_origins)
        self._password_is_hash = looks_like_hash(self.password)

        if self._password_is_hash and not _WERKZEUG_AVAILABLE:
            self.logger.error(
                "Passwort-Hash konfiguriert, aber werkzeug fehlt - "
                "keine Anmeldung moeglich"
            )

    @staticmethod
    def _normalize_origins(origins: Optional[Iterable[str]]) -> List[str]:
        """Reduziert konfigurierte Origins auf einen kleingeschriebenen Host."""
        normalized = []
        for origin in origins or ():
            host = WebAuthGuard._origin_host(str(origin))
            if host:
                normalized.append(host)
        return normalized

    @staticmethod
    def _origin_host(value: str) -> str:
        """Zieht den Hostnamen aus einem Origin, mit oder ohne Schema.

        Ein Port bleibt erhalten: ``schloss.fdog.de:8081`` und
        ``schloss.fdog.de`` sind verschiedene Dienste.
        """
        value = (value or '').strip().lower()
        if not value:
            return ''
        if '//' not in value:
            value = '//' + value
        parsed = urlsplit(value)
        return parsed.netloc or ''

    @property
    def configured(self) -> bool:
        """True, wenn Benutzername und Passwort gesetzt sind."""
        return bool(self.username and self.password)

    def check_credentials(self, username: str, password: str) -> bool:
        """Vergleicht Zugangsdaten ohne verwertbaren Zeitunterschied."""
        if not self.configured:
            return False

        # Beide Vergleiche laufen immer, damit die Antwortzeit nicht verraet,
        # ob schon der Benutzername falsch war.
        user_ok = hmac.compare_digest(
            (username or '').encode('utf-8'),
            self.username.encode('utf-8'),
        )

        if self._password_is_hash:
            if not _WERKZEUG_AVAILABLE:
                return False
            password_ok = bool(check_password_hash(self.password, password or ''))
        else:
            password_ok = hmac.compare_digest(
                (password or '').encode('utf-8'),
                self.password.encode('utf-8'),
            )

        return user_ok and password_ok

    @staticmethod
    def parse_basic_auth(header: str) -> Optional[Tuple[str, str]]:
        """Zerlegt einen ``Authorization: Basic``-Header.

        Liefert None, wenn der Header fehlt, ein anderes Verfahren nennt oder
        nicht dekodierbar ist.
        """
        if not header:
            return None
        parts = header.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != 'basic':
            return None
        try:
            decoded = base64.b64decode(parts[1].strip(), validate=True)
        except (binascii.Error, ValueError):
            return None
        try:
            text = decoded.decode('utf-8')
        except UnicodeDecodeError:
            return None
        if ':' not in text:
            return None
        username, password = text.split(':', 1)
        return username, password

    def check_origin(self, method: str, headers, host: str) -> AuthDecision:
        """Weist zustandsaendernde Requests von fremden Webseiten ab.

        Ein Browser haengt einmal eingegebene Basic-Auth-Zugangsdaten auch an
        Requests an, die eine fremde Seite ausloest. Ohne diese Pruefung koennte
        eine beliebige Webseite, die du nebenbei geoeffnet hast, das Maehdeck
        starten - dein Browser wuerde sich dabei korrekt ausweisen.

        Nicht-Browser-Clients senden weder ``Origin`` noch ``Sec-Fetch-Site``.
        Sie passieren, weil sie keine fremden Zugangsdaten mitbringen koennen
        und das Basic-Auth sie bereits abfaengt.
        """
        if (method or '').upper() in SAFE_METHODS:
            return ALLOW

        fetch_site = (self._header(headers, 'Sec-Fetch-Site') or '').strip().lower()
        if fetch_site in ('cross-site', 'same-site'):
            # 'same-site' erlaubt eine fremde Subdomain - fuer eine Maschine mit
            # Messern ist das zu weit gefasst.
            return AuthDecision(
                allowed=False,
                status=403,
                message='Anfrage von fremder Herkunft abgelehnt',
            )

        origin = (self._header(headers, 'Origin') or '').strip()
        if not origin or origin.lower() == 'null':
            return ALLOW

        origin_host = self._origin_host(origin)
        target_host = self._origin_host(host)
        if origin_host and origin_host == target_host:
            return ALLOW
        if origin_host in self.allowed_origins:
            return ALLOW

        return AuthDecision(
            allowed=False,
            status=403,
            message='Anfrage von fremder Herkunft abgelehnt',
        )

    @staticmethod
    def _header(headers, name: str) -> str:
        """Liest einen Header aus Flask-Headers oder einem einfachen Dict."""
        if headers is None:
            return ''
        getter = getattr(headers, 'get', None)
        if getter is None:
            return ''
        return getter(name, '') or ''

    def authorize(self, method: str, headers, host: str,
                  remote_addr: str) -> AuthDecision:
        """Vollstaendige Pruefung eines eingehenden Requests."""
        if not self.enabled:
            return ALLOW

        if not self.configured:
            # Fail closed: Eine aktivierte, aber unvollstaendig konfigurierte
            # Anmeldung darf nicht stillschweigend zu freiem Zugang werden.
            return AuthDecision(
                allowed=False,
                status=503,
                message='Zugangsschutz aktiv, aber kein Passwort gesetzt',
            )

        throttle_key = remote_addr or 'unknown'
        remaining = self.throttle.remaining_lockout_s(throttle_key)
        if remaining > 0.0:
            return AuthDecision(
                allowed=False,
                status=429,
                message='Zu viele Fehlversuche',
                retry_after=int(remaining) + 1,
            )

        credentials = self.parse_basic_auth(self._header(headers, 'Authorization'))
        if credentials is None:
            return AuthDecision(
                allowed=False,
                status=401,
                message='Anmeldung erforderlich',
                challenge=True,
            )

        username, password = credentials
        if not self.check_credentials(username, password):
            count = self.throttle.record_failure(throttle_key)
            self.logger.warning(
                "Fehlgeschlagene Anmeldung von %s (Benutzer %r, Versuch %d)",
                throttle_key, username, count,
            )
            return AuthDecision(
                allowed=False,
                status=401,
                message='Anmeldung fehlgeschlagen',
                challenge=True,
            )

        self.throttle.record_success(throttle_key)
        return self.check_origin(method, headers, host)
