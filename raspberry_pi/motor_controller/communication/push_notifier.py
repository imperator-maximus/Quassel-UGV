#!/usr/bin/env python3
"""Push-Meldungen ueber ntfy fuer Stoerungen, die das Fahrzeug stehen lassen.

Die Weboberflaeche faerbt einen Fehlerzustand rot - aber nur, solange jemand
hinsieht. Ein Fahrzeug, das im Garten steht, bleibt so stundenlang unbemerkt.
Dieses Modul schickt dieselbe Information als Push-Nachricht aufs Telefon.

Grundsatz: Melden ist Nebensache. Kein Aufruf darf einen Steuer- oder
Sicherheitsthread aufhalten oder eine Ausnahme nach oben durchreichen. Deshalb
nimmt ``fault()`` nur in eine Warteschlange auf, ein eigener Thread sendet, und
jeder Fehler des Sendewegs bleibt hier haengen.
"""

import json
import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional, Sequence
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class PushNotifier:
    """Sendet Stoerungsmeldungen an ein ntfy-Topic.

    ``fault``/``recovery``/``info`` sind die einzigen Aufrufe fuer die
    Fahrzeuglogik. Sie sind nicht blockierend und geben nur zurueck, ob die
    Meldung angenommen wurde - nicht, ob sie zugestellt wurde.
    """

    # Backoff zwischen Zustellversuchen. Das Fahrzeug steht im Garten hinter
    # duenner WLAN-Abdeckung; genau dann faellt die Stoerung an, die gemeldet
    # werden soll. Ein einzelner Fehlversuch darf die Meldung nicht verlieren.
    _RETRY_DELAYS_S = (2.0, 5.0, 15.0, 30.0, 60.0)

    def __init__(
        self,
        config,
        sender: Optional[Callable[[str, bytes, Dict[str, str], float], None]] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.config = config
        self._sender = sender or self._http_post

        self._topic = str(getattr(config, 'topic', '') or '').strip()
        self._token = str(getattr(config, 'token', '') or '').strip()
        self._click_url = str(getattr(config, 'click_url', '') or '').strip()
        self._server = self._normalise_server(getattr(config, 'server', ''))

        self._queue: queue.Queue = queue.Queue(
            maxsize=max(1, int(getattr(config, 'queue_size', 32)))
        )
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.running = False

        # Zustand fuer Entprellung und Entwarnung
        self._last_sent_monotonic: Dict[str, float] = {}
        self._announced: set = set()
        self._in_flight = False

        # Zaehler fuer die Statusanzeige
        self._delivered = 0
        self._dropped = 0
        self._failed_attempts = 0
        self._last_error: Optional[str] = None
        self._last_delivery_epoch: Optional[float] = None

        self.enabled = bool(getattr(config, 'enabled', False))
        self._disabled_reason: Optional[str] = None
        if self.enabled and not self._topic:
            self._disable('notifications.topic fehlt (UGV_NTFY_TOPIC)')
        elif self.enabled and not self._server:
            self._disable(f"notifications.server ist unbrauchbar: "
                          f"{getattr(config, 'server', '')!r}")

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker, name='push-notifier', daemon=True
        )
        self._thread.start()
        self.logger.info('Push-Meldungen aktiv: %s (Topic gesetzt)', self._server)

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.logger.info('Push-Meldungen gestoppt')

    def flush(self, timeout_s: float = 2.0) -> bool:
        """Wartet kurz auf offene Meldungen, bevor der Prozess endet.

        Ein Transporthaenger beendet den Prozess mit ``os._exit``; ohne diesen
        Aufruf ginge genau die Meldung verloren, die den Neustart erklaert.
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            with self._lock:
                if self._queue.empty() and not self._in_flight:
                    return True
            time.sleep(0.05)
        return False

    # ------------------------------------------------------------------
    # Meldewege
    # ------------------------------------------------------------------

    def fault(self, event: str, title: str, message: str) -> bool:
        """Meldet eine Stoerung und merkt sich, dass sie offen ist."""
        priority = int(getattr(self.config, 'fault_priority', 5))
        queued = self._enqueue(event, title, message, priority, ('rotating_light',))
        if queued:
            with self._lock:
                self._announced.add(event)
        return queued

    def recovery(self, event: str, title: str, message: str) -> bool:
        """Meldet Entwarnung - nur, wenn die Stoerung vorher gemeldet wurde.

        Sonst bekaeme man Entwarnungen fuer Ereignisse, von denen man nie
        erfahren hat. Der Eintrag verfaellt dabei, damit dieselbe Stoerung
        danach sofort wieder gemeldet werden darf und nicht in die
        Wiederholsperre laeuft.
        """
        with self._lock:
            known = event in self._announced
            self._announced.discard(event)
            self._last_sent_monotonic.pop(event, None)
        if not known:
            return False
        if not bool(getattr(self.config, 'notify_recovery', True)):
            return False
        priority = int(getattr(self.config, 'recovery_priority', 3))
        return self._enqueue(
            f'{event}:ok', title, message, priority, ('white_check_mark',),
            deduplicate=False,
        )

    def info(self, event: str, title: str, message: str) -> bool:
        priority = int(getattr(self.config, 'recovery_priority', 3))
        return self._enqueue(event, title, message, priority, ('information_source',))

    # ------------------------------------------------------------------
    # Interna
    # ------------------------------------------------------------------

    def _enqueue(
        self,
        event: str,
        title: str,
        message: str,
        priority: int,
        tags: Sequence[str],
        deduplicate: bool = True,
    ) -> bool:
        if not self.enabled:
            return False
        try:
            now = time.monotonic()
            if deduplicate:
                min_interval_s = max(
                    0.0, float(getattr(self.config, 'min_interval_s', 120.0))
                )
                with self._lock:
                    last = self._last_sent_monotonic.get(event)
                    if last is not None and (now - last) < min_interval_s:
                        return False
                    self._last_sent_monotonic[event] = now
            else:
                with self._lock:
                    self._last_sent_monotonic[event] = now

            item = {
                'event': event,
                'title': str(title),
                # Die Uhrzeit gehoert in die Nachricht, nicht nur in die
                # Zustellung: nach einem WLAN-Ausfall kommt die Meldung
                # womoeglich erst Minuten spaeter an.
                'message': f"{time.strftime('%H:%M:%S')} · {message}",
                'priority': max(1, min(5, int(priority))),
                'tags': tuple(tags),
                'created_monotonic': now,
            }
            self._put_dropping_oldest(item)
            return True
        except Exception as exc:  # noqa: BLE001 - Melden darf nie hochschlagen
            self.logger.error('Push-Meldung konnte nicht eingereiht werden: %s', exc)
            return False

    def _put_dropping_oldest(self, item: Dict[str, Any]) -> None:
        """Haelt die Warteschlange kurz; die juengste Stoerung zaehlt mehr."""
        while True:
            try:
                self._queue.put_nowait(item)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    with self._lock:
                        self._dropped += 1
                except queue.Empty:
                    return

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            with self._lock:
                self._in_flight = True
            try:
                self._deliver(item)
            except Exception as exc:  # noqa: BLE001
                self.logger.error('Push-Sendethread: %s', exc)
            finally:
                with self._lock:
                    self._in_flight = False

    def _deliver(self, item: Dict[str, Any]) -> None:
        max_age_s = max(0.0, float(getattr(self.config, 'retry_max_age_s', 900.0)))
        attempt = 0
        while not self._stop_event.is_set():
            if (time.monotonic() - item['created_monotonic']) > max_age_s:
                with self._lock:
                    self._dropped += 1
                self.logger.warning(
                    'Push-Meldung "%s" nach %.0fs ohne Zustellung verworfen',
                    item['title'], max_age_s,
                )
                return
            try:
                self._send(item)
                with self._lock:
                    self._delivered += 1
                    self._last_error = None
                    self._last_delivery_epoch = time.time()
                self.logger.info('Push-Meldung zugestellt: %s', item['title'])
                return
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._failed_attempts += 1
                    self._last_error = str(exc)
                delay = self._RETRY_DELAYS_S[
                    min(attempt, len(self._RETRY_DELAYS_S) - 1)
                ]
                attempt += 1
                self.logger.warning(
                    'Push-Meldung "%s" fehlgeschlagen (%s); erneut in %.0fs',
                    item['title'], exc, delay,
                )
                if self._stop_event.wait(delay):
                    return

    def _send(self, item: Dict[str, Any]) -> None:
        payload: Dict[str, Any] = {
            'topic': self._topic,
            'title': item['title'],
            'message': item['message'],
            'priority': item['priority'],
        }
        if item['tags']:
            payload['tags'] = list(item['tags'])
        if self._click_url:
            payload['click'] = self._click_url
        headers = {'Content-Type': 'application/json'}
        if self._token:
            headers['Authorization'] = f'Bearer {self._token}'
        self._sender(
            self._server,
            json.dumps(payload).encode('utf-8'),
            headers,
            float(getattr(self.config, 'request_timeout_s', 5.0)),
        )

    @staticmethod
    def _http_post(
        url: str, body: bytes, headers: Dict[str, str], timeout_s: float
    ) -> None:
        request = Request(url, data=body, headers=headers, method='POST')
        with urlopen(request, timeout=timeout_s) as response:
            status = getattr(response, 'status', None)
            if status is None:
                status = response.getcode()
            if int(status) >= 300:
                raise RuntimeError(f'HTTP {status}')
            response.read(4096)

    def _normalise_server(self, server: Any) -> str:
        text = str(server or '').strip().rstrip('/')
        if not text:
            return ''
        parts = urlsplit(text)
        if parts.scheme not in ('http', 'https') or not parts.netloc:
            return ''
        return text

    def _disable(self, reason: str) -> None:
        self.enabled = False
        self._disabled_reason = reason
        # Keine Push-Meldungen sind aergerlich, aber nicht gefaehrlich. Der
        # Dienst laeuft weiter, die Ursache steht im Journal.
        self.logger.error('Push-Meldungen deaktiviert: %s', reason)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'enabled': self.enabled,
                'running': self.running,
                'server': self._server,
                'disabled_reason': self._disabled_reason,
                'queued': self._queue.qsize(),
                'delivered': self._delivered,
                'dropped': self._dropped,
                'failed_attempts': self._failed_attempts,
                'last_error': self._last_error,
                'last_delivery': self._last_delivery_epoch,
                'open_faults': sorted(self._announced),
            }
