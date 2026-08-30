"""Sprachansagen ueber den USB-Audiostick.

Das Lichtrelais sagt, *dass* etwas passiert ist - eine Ansage sagt, *was*. Wer
neben dem Fahrzeug steht, sieht das Blinken nur, wenn er hinschaut; die Ansage
hoert er auch mit dem Ruecken zum Fahrzeug. Die Dateien sind vorgeneriert
(``tools/voice/``), auf dem Fahrzeug wird nichts synthetisiert: kein Netz, kein
Rechenaufwand, keine Wartezeit vor der Warnung.

Grundsatz wie beim Melden: Ansagen sind Nebensache. Kein Aufruf darf einen
Steuer- oder Sicherheitsthread aufhalten oder eine Ausnahme nach oben
durchreichen. ``say()`` reiht nur ein, ein eigener Thread spielt ab.
"""

import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, Optional


class VoiceAnnouncer:
    """Spielt vorgenerierte Ansagen ab, ohne den Aufrufer aufzuhalten."""

    def __init__(self, config, logger=None, player=None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        # Einspeisbar, damit Tests ohne Soundkarte auskommen.
        self._player = player or self._play_file

        self.enabled = bool(getattr(config, 'enabled', False))
        self._device = str(getattr(config, 'device', '') or '')
        self._audio_dir = self._resolve_audio_dir()
        self._timeout_s = max(1.0, float(getattr(config, 'timeout_s', 15.0)))

        self._queue: queue.Queue = queue.Queue(
            maxsize=max(1, int(getattr(config, 'queue_size', 8)))
        )
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._abort = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.running = False

        self._last_said: Dict[str, float] = {}
        self._playing = False
        self._spoken = 0
        self._dropped = 0
        self._missing: set = set()
        self._last_error: Optional[str] = None
        self._disabled_reason: Optional[str] = None

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Prueft Abspielprogramm und Dateien, bevor der erste Anlass da ist.

        Eine Ansage faellt sonst genau dann aus, wenn sie gebraucht wird, und
        der Grund stuende erst im Journal. Lieber jetzt einmal nachsehen.
        """
        if not self.enabled:
            self.logger.info('Sprachansagen sind abgeschaltet')
            return False
        if not os.path.isdir(self._audio_dir):
            self._disable(f'Ansageverzeichnis fehlt: {self._audio_dir}')
            return False
        files = [n for n in os.listdir(self._audio_dir) if n.endswith('.wav')]
        if not files:
            self._disable(f'keine Ansagen in {self._audio_dir}')
            return False
        binary = str(getattr(self.config, 'player', 'aplay') or 'aplay')
        if shutil.which(binary) is None:
            self._disable(f'{binary} ist nicht installiert')
            return False
        self.logger.info(
            'Sprachansagen bereit: %d Dateien in %s auf %s',
            len(files), self._audio_dir, self._device or 'Standardgeraet',
        )
        return True

    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker, name='voice-announcer', daemon=True
        )
        self._thread.start()

    def flush(self, timeout_s: float = 6.0) -> bool:
        """Wartet, bis die Warteschlange leer und nichts mehr am Laufen ist.

        Ein Transporthaenger beendet den Prozess mit ``os._exit``; ohne diesen
        Aufruf brechen genau die Ansagen ab, die den Neustart erklaeren. Die
        Wartezeit ist gedeckelt - lieber eine abgeschnittene Ansage als ein
        Fahrzeug, das wegen der Ansage nicht anhaelt.
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            with self._lock:
                idle = self._queue.empty() and not self._playing
            if idle:
                return True
            time.sleep(0.05)
        return False

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self._stop_event.set()
        self._abort.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self.logger.info('Sprachansagen gestoppt')

    # ------------------------------------------------------------------
    # Ansagen
    # ------------------------------------------------------------------

    def say(self, key: str, urgent: bool = False, force: bool = False) -> bool:
        """Reiht eine Ansage ein. Blockiert nie, wirft nie.

        Args:
            key: Dateiname ohne Endung, siehe ``tools/voice/announcements.json``
            urgent: bricht die laufende Ansage ab und leert die Warteschlange.
                Fuer Stopps und Warnungen: die Meldung ueber den fertigen
                Maehplan darf einen Sicherheitsstopp nicht um Sekunden
                verzoegern.
            force: umgeht die Wiederholsperre

        Returns:
            True, wenn die Ansage eingereiht wurde.
        """
        if not self.enabled or not self.running:
            return False
        try:
            path = os.path.join(self._audio_dir, f'{key}.wav')
            if not os.path.isfile(path):
                # Nur einmal je fehlender Ansage meckern - der Anlass kann
                # sich im Sekundentakt wiederholen.
                with self._lock:
                    unknown = key not in self._missing
                    self._missing.add(key)
                if unknown:
                    self.logger.warning('Ansage fehlt: %s', path)
                return False

            now = time.monotonic()
            if not force:
                min_interval_s = max(
                    0.0, float(getattr(self.config, 'min_interval_s', 10.0))
                )
                with self._lock:
                    last = self._last_said.get(key)
                    if last is not None and (now - last) < min_interval_s:
                        return False
            with self._lock:
                self._last_said[key] = now

            if urgent:
                self._drain()
                self._abort.set()
            self._put_dropping_oldest({'key': key, 'path': path})
            return True
        except Exception as exc:  # noqa: BLE001 - Ansagen duerfen nie hochschlagen
            self.logger.error('Ansage "%s" nicht einreihbar: %s', key, exc)
            return False

    # ------------------------------------------------------------------
    # Interna
    # ------------------------------------------------------------------

    def _put_dropping_oldest(self, item: Dict[str, Any]) -> None:
        """Haelt die Warteschlange kurz; die juengste Lage zaehlt mehr.

        Eine Ansage, die erst in einer halben Minute an der Reihe waere,
        beschreibt einen Zustand, den es dann womoeglich nicht mehr gibt.
        """
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

    def _drain(self) -> None:
        while True:
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
            # Der Abbruch galt der Ansage, die beim Vordraengeln lief - nicht
            # dieser hier. Sonst schnitte eine dringende Ansage sich selbst ab.
            self._abort.clear()
            with self._lock:
                self._playing = True
            try:
                self._player(item['path'])
                with self._lock:
                    self._spoken += 1
                    self._last_error = None
                self.logger.info('Ansage: %s', item['key'])
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._last_error = str(exc)
                self.logger.warning(
                    'Ansage "%s" fehlgeschlagen: %s', item['key'], exc
                )
            finally:
                with self._lock:
                    self._playing = False

    def _play_file(self, path: str) -> None:
        command = [str(getattr(self.config, 'player', 'aplay') or 'aplay')]
        if self._device:
            # plughw statt hw: der Stick nimmt nur Stereo an, und ohne die
            # plug-Schicht rechnet ALSA Mono und andere Raten nicht um.
            command += ['-D', self._device]
        command += ['-q', path]
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                _, stderr = process.communicate(timeout=0.2)
            except subprocess.TimeoutExpired:
                # Eine dringende Ansage wartet nicht das Ende der laufenden ab.
                if self._abort.is_set() or self._stop_event.is_set():
                    process.terminate()
                    process.wait(timeout=2.0)
                    return
                # Ein haengendes aplay blockiert sonst jede weitere Ansage.
                if time.monotonic() > deadline:
                    process.kill()
                    process.wait(timeout=2.0)
                    raise RuntimeError('Wiedergabe haengt, abgebrochen')
                continue
            if process.returncode != 0:
                raise RuntimeError(
                    (stderr or b'').decode(errors='replace').strip()
                    or f'Rueckgabewert {process.returncode}'
                )
            return

    def _resolve_audio_dir(self) -> str:
        configured = str(getattr(self.config, 'audio_dir', '') or '').strip()
        if configured:
            return os.path.abspath(os.path.expanduser(configured))
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'audio'
        )

    def _disable(self, reason: str) -> None:
        self.enabled = False
        self._disabled_reason = reason
        # Stumm ist aergerlich, aber nicht gefaehrlich. Der Dienst laeuft
        # weiter, die Ursache steht im Journal.
        self.logger.error('Sprachansagen abgeschaltet: %s', reason)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'enabled': self.enabled,
                'running': self.running,
                'device': self._device,
                'audio_dir': self._audio_dir,
                'disabled_reason': self._disabled_reason,
                'queued': self._queue.qsize(),
                'playing': self._playing,
                'spoken': self._spoken,
                'dropped': self._dropped,
                'missing': sorted(self._missing),
                'last_error': self._last_error,
            }
