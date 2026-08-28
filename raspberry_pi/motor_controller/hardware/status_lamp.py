"""Lebenszeichen ueber das Lichtrelais.

Am Fahrzeug steht man ohne Laptop davor und schaltet ein. Ob der Dienst
hochgekommen ist und ob das Netz steht, war bisher nur ueber die Oberflaeche zu
sehen - also genau ueber den Weg, der noch nicht da ist, solange das Netz
fehlt. Diese Klasse gibt beides als kurzes Blinken aus.

Sie kapselt zugleich den Relaispin. Vorher schaltete die Weboberflaeche direkt
auf den GPIO; eine parallel laufende Blinkfolge haette dagegen angearbeitet und
die Anzeige waere anschliessend falsch gewesen. Jetzt geht beides durch
denselben Zustand, und die Handbedienung hat Vorrang: Sobald jemand selbst
schaltet, bleiben die Signale still. Sie sind Beiwerk und duerfen niemals ein
Licht ausknipsen, das jemand absichtlich angemacht hat.
"""

import logging
import threading
from typing import Optional


class StatusLamp:
    """Schaltet das Lichtrelais und spielt kurze Signalfolgen darauf ab."""

    def __init__(self, config, gpio, logger=None):
        self.config = config
        self.gpio = gpio
        self.logger = logger or logging.getLogger(__name__)
        self.enabled = bool(getattr(config, 'enabled', False))
        self.pin = int(getattr(config, 'pin', 0))

        self._state = False
        self._manual = False
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Zustand
    # ------------------------------------------------------------------
    @property
    def state(self) -> bool:
        """Aktueller Zustand des Relais."""
        with self._lock:
            return self._state

    def _write(self, state: bool):
        """Schaltet den Pin, aber nur bei tatsaechlicher Aenderung.

        Hinter dem Pin sitzt ein Relais. Es erneut auf den Zustand zu setzen,
        den es schon hat, bringt nichts und kostet nur Schaltspiele - etwa am
        Ende einer Blinkfolge, die ohnehin ausgeschaltet endet.
        """
        if not self.enabled:
            return
        state = bool(state)
        with self._lock:
            if state == self._state:
                return
        try:
            self.gpio.output(self.pin, state)
        except Exception as exc:
            self.logger.warning("Lichtrelais schaltet nicht: %s", exc)
            return
        with self._lock:
            self._state = state

    def initialize(self) -> bool:
        """Richtet den Pin ein und schaltet aus."""
        if not self.enabled:
            self.logger.info("Licht ist abgeschaltet - keine Signale")
            return False
        try:
            self.gpio.setup_output(self.pin, initial_state=0)
        except Exception as exc:
            self.logger.error("Lichtrelais nicht einrichtbar (GPIO%d): %s", self.pin, exc)
            self.enabled = False
            return False
        with self._lock:
            self._state = False
        self.logger.info("Licht-Relais initialisiert (GPIO%d)", self.pin)
        return True

    # ------------------------------------------------------------------
    # Handbedienung
    # ------------------------------------------------------------------
    def set(self, state: bool) -> bool:
        """Schaltet von Hand. Bricht eine laufende Signalfolge ab.

        Ab dem ersten Griff zur Hand bleiben die Startsignale aus - wer das
        Licht anmacht, will nicht, dass es Sekunden spaeter von selbst ausgeht.
        """
        with self._lock:
            self._manual = True
        self._cancel_running()
        self._write(bool(state))
        return self.state

    def toggle(self) -> bool:
        """Kehrt den Zustand um."""
        return self.set(not self.state)

    # ------------------------------------------------------------------
    # Signalfolgen
    # ------------------------------------------------------------------
    def signal(self, blinks: int = 1, on_s: float = 1.0, off_s: float = 0.25,
               reason: str = '') -> bool:
        """Spielt eine Signalfolge ab, ohne den Aufrufer aufzuhalten.

        Args:
            blinks: Anzahl der Leuchtphasen
            on_s: Dauer je Leuchtphase
            off_s: Pause zwischen zwei Leuchtphasen
            reason: Klartext fuers Log

        Returns:
            True, wenn die Folge gestartet wurde.
        """
        if not self.enabled:
            return False
        with self._lock:
            if self._manual:
                # Handbedienung hatte schon das Wort.
                return False
        self._cancel_running()
        self._abort.clear()
        self._thread = threading.Thread(
            target=self._play,
            args=(int(blinks), float(on_s), float(off_s), reason),
            name='status-lamp',
            daemon=True,
        )
        self._thread.start()
        return True

    def _play(self, blinks: int, on_s: float, off_s: float, reason: str):
        if reason:
            self.logger.info("Lichtsignal: %s (%dx)", reason, blinks)
        try:
            for index in range(max(1, blinks)):
                with self._lock:
                    if self._manual:
                        return
                if self._abort.is_set():
                    return
                self._write(True)
                if self._abort.wait(on_s):
                    return
                self._write(False)
                if index + 1 < blinks and self._abort.wait(off_s):
                    return
        finally:
            # Definiert aus verlassen - ausser die Hand hat inzwischen
            # uebernommen, dann gehoert ihr der Zustand.
            with self._lock:
                manual = self._manual
            if not manual:
                self._write(False)

    def _cancel_running(self):
        """Beendet eine laufende Folge und wartet kurz auf den Thread."""
        thread = self._thread
        if thread is not None and thread.is_alive():
            self._abort.set()
            thread.join(timeout=2.0)
        self._thread = None

    def stop(self):
        """Beendet laufende Signale und schaltet aus."""
        self._cancel_running()
        with self._lock:
            manual = self._manual
        if not manual:
            self._write(False)
