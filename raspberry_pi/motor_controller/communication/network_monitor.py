#!/usr/bin/env python3
"""Which WLAN the vehicle is really on - and a one-click way back.

Am 27.08.2026 ist das Fahrzeug zweimal unbemerkt aus dem Mobilfunknetz ins
alte HaLow-WLAN zurueckgefallen (jeweils `ssid-not-found`), und der
NetworkManager kehrt von selbst nicht zurueck. Der ganze Betrieb des Abends
lief deshalb ueber den Notweg statt ueber Mobilfunk, ohne dass die Oberflaeche
etwas davon zeigte.

Dieses Modul liest deshalb regelmaessig nach, welches Profil tatsaechlich
aktiv ist, und macht den Rueckweg zu einem Knopf. Der Rueckweg sichert sich
selbst ab: Vor dem Umschalten wird ein Rueckfall ins alte Netz scharf
gestellt, der nur dann wieder entschaerft wird, wenn das Wunschnetz danach
wirklich steht. Bleibt die Verbindung aus, holt der Rueckfall das Fahrzeug von
allein zurueck, statt es unerreichbar zu lassen.

Am 28.08.2026 kam der zweite Fall dazu: Der Mobilfunkrouter braucht nach dem
Einschalten laenger als der Pi. Beim Hochfahren stand seine SSID noch nicht in
der Scan-Liste, NetworkManager nahm das Hausnetz - und blieb dort, obwohl das
Wunschprofil die hoechste Prioritaet hat. Eine stehende Verbindung wird eben
nie zugunsten eines besseren Profils aufgegeben. Deshalb fasst der Waechter
jetzt von allein nach, wenn das Fahrzeug auf einem Netz haengt, das weder das
Wunsch- noch das Notnetz ist.
"""

import logging
import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# Was nmcli in der Spalte ACTIVE fuer "dieses Netz ist verbunden" schreibt.
ACTIVE_MARKERS = ('yes', 'ja', '*')


def split_terse(line: str) -> List[str]:
    """Zerlegt eine Zeile aus `nmcli -t`, das ':' im Wert mit '\\' schuetzt."""
    fields: List[str] = []
    current: List[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            fields.append(''.join(current))
            current = []
        else:
            current.append(char)
    fields.append(''.join(current))
    return fields


def _run_command(args: List[str], timeout: float) -> Tuple[int, str, str]:
    """Fuehrt einen Befehl aus und gibt (Rueckgabewert, stdout, stderr).

    `LC_ALL=C` haelt die Ausgabe englisch. Auf dem Fahrzeug ist die Oberflaeche
    deutsch, dort steht in der Spalte ACTIVE ein "ja" statt "yes" - ausgewertet
    wird trotzdem beides, damit ein anderer Aufrufweg die Anzeige nicht
    stillschweigend leert.
    """
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, 'LC_ALL': 'C'},
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return 127, '', f'{args[0]} nicht gefunden'
    except subprocess.TimeoutExpired:
        return 124, '', f'{args[0]} hat nicht innerhalb von {timeout:.0f} s geantwortet'


class NetworkMonitor:
    """Liest das aktive WLAN-Profil und schaltet auf Wunsch zurueck."""

    def __init__(self, config, logger=None, runner=None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.enabled = bool(getattr(config, 'enabled', True))
        self._run = runner or _run_command
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._switch_thread: Optional[threading.Thread] = None
        self._switching = False
        # Sprachansagen am Fahrzeug, optional.
        self.voice = None
        self._last_switch: Optional[Dict[str, Any]] = None
        self._reading: Dict[str, Any] = {
            'profile': None,
            'ssid': None,
            'signal_percent': None,
            'ipv4': None,
            'state': None,
        }
        self._reading_monotonic: Optional[float] = None
        self._error: Optional[str] = None
        self._visible_ssids: List[str] = []
        self._preferred_ssid: Optional[str] = None
        self._preferred_ssid_resolved = False
        self._last_auto_attempt: Optional[float] = None
        self._last_rescan: Optional[float] = None
        self._auto_skip_reason: Optional[str] = None
        self._busy_probe = None

    # -- Betrieb ---------------------------------------------------------

    def start(self):
        if not self.enabled or self._thread:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker, name='network-monitor', daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        thread = self._thread
        self._thread = None
        if thread:
            thread.join(timeout=2.0)

    def _worker(self):
        while not self._stop_event.is_set():
            try:
                self.refresh()
                self.nudge_if_stranded()
            except Exception as error:  # pragma: no cover - Schutz des Threads
                self.logger.warning(f"Netzabfrage fehlgeschlagen: {error}")
            self._stop_event.wait(float(self.config.poll_interval_s))

    def set_busy_probe(self, probe):
        """Hinterlegt die Frage "faehrt das Fahrzeug gerade?".

        Ein Netzwechsel kappt die Verbindung fuer Sekunden. Solange ein Plan
        laeuft, traegt sie die Pose - dann wird nicht von allein umgeschaltet,
        auch wenn das Fahrzeug im falschen Netz haengt. Der Knopf in der
        Oberflaeche bleibt davon unberuehrt: Wer ihn drueckt, weiss, was er
        tut.
        """
        self._busy_probe = probe

    # -- Lesen -----------------------------------------------------------

    def refresh(self) -> Dict[str, Any]:
        """Fragt NetworkManager nach dem aktuellen Stand der Schnittstelle."""
        reading = {
            'profile': None,
            'ssid': None,
            'signal_percent': None,
            'ipv4': None,
            'state': None,
        }
        timeout = float(self.config.command_timeout_s)
        code, out, err = self._run(
            ['nmcli', '-t', '-f', 'GENERAL.CONNECTION,GENERAL.STATE,IP4.ADDRESS',
             'device', 'show', self.config.interface],
            timeout,
        )
        if code != 0:
            with self._lock:
                self._error = (err or out).strip() or f'nmcli endete mit {code}'
            return self.get_status()

        for line in out.splitlines():
            fields = split_terse(line)
            if len(fields) < 2:
                continue
            key, value = fields[0], fields[1]
            if key == 'GENERAL.CONNECTION':
                reading['profile'] = value if value and value != '--' else None
            elif key == 'GENERAL.STATE':
                reading['state'] = value or None
            elif key.startswith('IP4.ADDRESS') and not reading['ipv4']:
                reading['ipv4'] = value.split('/')[0] or None

        # Der Netzname und die Feldstaerke kommen aus der Liste der bekannten
        # Netze. `--rescan no` ist wichtig: Ein Suchlauf legt die Verbindung
        # fuer ein bis zwei Sekunden lahm, und genau das darf eine reine
        # Anzeige nicht ausloesen.
        code, out, _err = self._run(
            ['nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL', 'device', 'wifi', 'list',
             '--rescan', 'no'],
            timeout,
        )
        visible: List[str] = []
        if code == 0:
            for line in out.splitlines():
                fields = split_terse(line)
                if len(fields) < 2:
                    continue
                if fields[1]:
                    visible.append(fields[1])
                if fields[0] not in ACTIVE_MARKERS or reading['ssid']:
                    continue
                reading['ssid'] = fields[1] or None
                if len(fields) > 2 and fields[2].isdigit():
                    reading['signal_percent'] = int(fields[2])

        with self._lock:
            had_address = bool((self._reading or {}).get('ipv4'))
            self._reading = reading
            self._reading_monotonic = time.monotonic()
            self._error = None
            self._visible_ssids = visible
        self._announce_link_change(had_address, bool(reading['ipv4']))
        return self.get_status()

    def _announce_link_change(self, had_address: bool, has_address: bool):
        """Sagt an, wenn die Verbindung kippt - und nur dann.

        Geprueft wird die Adresse, nicht die reine Verbindung: mit SSID, aber
        ohne Adresse ist die Oberflaeche nicht erreichbar. Das ist dieselbe
        Schwelle, an der beim Start zweimal geblinkt wird.
        """
        if had_address == has_address or not self.voice:
            return
        try:
            self.voice.say('funk_zurueck' if has_address else 'funk_verloren')
        except Exception as exc:  # noqa: BLE001 - Ansagen sind Nebensache
            self.logger.error('Ansage zum Netzstatus fehlgeschlagen: %s', exc)

    def set_voice(self, voice):
        """Setzt den Ansager fuer die Sprachausgabe am Fahrzeug."""
        self.voice = voice

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            reading = dict(self._reading)
            skip_reason = self._auto_skip_reason
            age = (
                None if self._reading_monotonic is None
                else time.monotonic() - self._reading_monotonic
            )
            status = {
                'enabled': self.enabled,
                'interface': self.config.interface,
                'preferred_profile': self.config.preferred_profile,
                'fallback_profile': self.config.fallback_profile,
                'switching': self._switching,
                'last_switch': dict(self._last_switch) if self._last_switch else None,
                'error': self._error,
                # Ganze Sekunden: Der Statusstrom rundet Altersangaben
                # ohnehin darauf, und ein Wert mit Nachkommastelle wuerde sich
                # nur zwischen HTTP- und WebSocket-Weg unterscheiden.
                'age_s': None if age is None else round(age),
                **reading,
            }
        status['on_preferred'] = bool(
            status['profile'] and status['profile'] == self.config.preferred_profile
        )
        status['auto_switch_enabled'] = bool(
            getattr(self.config, 'auto_switch_enabled', True)
        )
        status['stranded'] = self._is_stranded(status['profile'])
        status['auto_switch_skipped'] = skip_reason
        return status

    def _is_stranded(self, profile) -> bool:
        """Haengt das Fahrzeug auf einem Netz, das so nicht vorgesehen ist?

        Das Notnetz zaehlt ausdruecklich nicht dazu. Es wird von Hand
        angesteckt, wenn der Mobilfunk nicht geht - da waere ein selbsttaetiger
        Wechsel zurueck genau das Falsche.
        """
        if not profile:
            return False
        return profile not in (
            self.config.preferred_profile,
            self.config.fallback_profile,
        )

    # -- Umschalten ------------------------------------------------------

    def nudge_if_stranded(self) -> Optional[Dict[str, Any]]:
        """Holt das Fahrzeug von allein ins Wunschnetz, wenn es dort hingehoert.

        Angefasst wird nur der Fall, der sonst bis zum naechsten Neustart
        bestehen bleibt: Das Fahrzeug haengt auf einem fremden Netz, das
        Wunschnetz ist inzwischen in Reichweite, und niemand faehrt gerade.
        Ist die SSID nicht zu sehen, wird es gar nicht erst versucht - ein
        `nmcli connection up` ins Leere kappt die bestehende Verbindung fuer
        nichts.
        """
        if not self.enabled or not getattr(self.config, 'auto_switch_enabled', True):
            return None

        status = self.get_status()
        if not status['stranded'] or status['switching']:
            return self._note_auto_skip(None)

        probe = self._busy_probe
        if probe is not None:
            try:
                if probe():
                    return self._note_auto_skip('Fahrt laeuft')
            except Exception as error:  # pragma: no cover - Schutz des Threads
                self.logger.warning(f"Fahrtabfrage fehlgeschlagen: {error}")
                return self._note_auto_skip('Fahrtabfrage fehlgeschlagen')

        now = time.monotonic()
        interval = float(getattr(self.config, 'auto_switch_interval_s', 300.0))
        with self._lock:
            last = self._last_auto_attempt
        if last is not None and now - last < interval:
            return self._note_auto_skip('Wartezeit laeuft noch')

        ssid = self._resolve_preferred_ssid()
        with self._lock:
            visible = list(self._visible_ssids)
        if ssid and ssid not in visible:
            # Die Liste oben ist der Zwischenspeicher von NetworkManager, und
            # der wird von allein nur alle paar Minuten aufgefrischt. Beim
            # Hochfahren ist das genau der Fall: Der Router sendet laengst,
            # steht dort aber noch nicht. Also gezielt nachsehen - das kostet
            # ein bis zwei Sekunden Verbindung, was in dieser Lage der
            # bessere Preis ist als eine Nacht im falschen Netz.
            if not self._rescan_now(now):
                return self._note_auto_skip(f'{ssid} nicht in Reichweite')
            with self._lock:
                visible = list(self._visible_ssids)
            if ssid not in visible:
                return self._note_auto_skip(f'{ssid} nicht in Reichweite')

        with self._lock:
            self._last_auto_attempt = now
        self.logger.warning(
            "Fahrzeug haengt auf '%s' statt auf '%s' - schalte selbsttaetig um",
            status['profile'],
            self.config.preferred_profile,
        )
        self._note_auto_skip(None)
        # Ohne scharfen Rueckfall: Wir kommen aus einem Netz, das erreichbar
        # ist. Scheitert der Wechsel, holt NetworkManager es von selbst
        # zurueck - ein Timer ins Notnetz waere hier das groessere Risiko.
        return self.switch_to_preferred(arm_fallback=False, automatic=True)

    def _rescan_now(self, now: float) -> bool:
        """Sucht aktiv nach Netzen und aktualisiert die Sichtbarkeitsliste.

        Gibt zurueck, ob gesucht wurde - zu dicht hintereinander waere es
        weder noetig noch harmlos.
        """
        interval = float(getattr(self.config, 'auto_rescan_interval_s', 45.0))
        with self._lock:
            last = self._last_rescan
        if last is not None and now - last < interval:
            return False
        with self._lock:
            self._last_rescan = now
        code, out, _err = self._run(
            ['nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL', 'device', 'wifi', 'list',
             '--rescan', 'yes'],
            float(self.config.switch_timeout_s),
        )
        if code != 0:
            return False
        found: List[str] = []
        for line in out.splitlines():
            fields = split_terse(line)
            if len(fields) >= 2 and fields[1]:
                found.append(fields[1])
        with self._lock:
            self._visible_ssids = found
        return True

    def _note_auto_skip(self, reason: Optional[str]) -> None:
        with self._lock:
            self._auto_skip_reason = reason
        return None

    def _resolve_preferred_ssid(self) -> Optional[str]:
        """Liest einmalig, welche SSID hinter dem Wunschprofil steht.

        Profilname und Netzname sind zwei verschiedene Dinge - das Profil
        heisst `HUAWEI`, das Netz `HUAWEI-E5180-E406`. Ohne diese Aufloesung
        liesse sich die Reichweite nicht pruefen.
        """
        if self._preferred_ssid_resolved:
            return self._preferred_ssid
        code, out, _err = self._run(
            ['nmcli', '-t', '-f', '802-11-wireless.ssid', 'connection', 'show',
             self.config.preferred_profile],
            float(self.config.command_timeout_s),
        )
        self._preferred_ssid_resolved = True
        if code != 0:
            return None
        for line in out.splitlines():
            fields = split_terse(line)
            if len(fields) >= 2 and fields[1] and fields[1] != '--':
                self._preferred_ssid = fields[1]
                break
        return self._preferred_ssid

    def switch_to_preferred(self, arm_fallback: bool = True,
                            automatic: bool = False) -> Dict[str, Any]:
        """Stoesst den Wechsel ins Wunschnetz an und kehrt sofort zurueck.

        Der Wechsel dauert Sekunden bis zu einer halben Minute und kappt dabei
        die Verbindung, ueber die der Aufruf kam. Er laeuft deshalb im
        Hintergrund - die Antwort auf den Knopfdruck haengt nicht daran.
        """
        if not self.enabled:
            return {'success': False, 'error': 'Netzueberwachung ist abgeschaltet'}
        with self._lock:
            if self._switching:
                return {'success': False, 'error': 'Ein Wechsel laeuft bereits'}
            self._switching = True
            self._last_switch = {
                'profile': self.config.preferred_profile,
                'finished': False,
                'success': None,
                'error': None,
                'fallback_armed': False,
                'automatic': automatic,
                'started_at': time.time(),
            }
        self._switch_thread = threading.Thread(
            target=self._switch_worker, name='network-switch', daemon=True,
            kwargs={'arm_fallback': arm_fallback},
        )
        self._switch_thread.start()
        return {'success': True, 'switching': True}

    def _switch_worker(self, arm_fallback: bool = True):
        armed = self._arm_fallback() if arm_fallback else False
        with self._lock:
            if self._last_switch is not None:
                self._last_switch['fallback_armed'] = armed

        code, out, err = self._run(
            ['nmcli', 'connection', 'up', self.config.preferred_profile],
            float(self.config.switch_timeout_s),
        )
        error = None if code == 0 else ((err or out).strip() or f'nmcli endete mit {code}')

        try:
            self.refresh()
        except Exception as refresh_error:  # pragma: no cover - Schutz des Threads
            self.logger.warning(f"Netzabfrage nach dem Wechsel fehlgeschlagen: {refresh_error}")

        arrived = self.get_status().get('on_preferred', False)
        if arrived and armed:
            # Erst jetzt darf der Rueckfall weg: Das Wunschnetz steht, und der
            # Bediener soll nicht in zehn Minuten ohne Vorwarnung im alten Netz
            # landen.
            self._disarm_fallback()
        elif error is None:
            error = 'Der Wechsel meldete Erfolg, das Wunschnetz ist aber nicht aktiv'

        with self._lock:
            self._switching = False
            if self._last_switch is not None:
                self._last_switch.update({
                    'finished': True,
                    'success': arrived,
                    'error': error,
                    'fallback_armed': armed and not arrived,
                    'finished_at': time.time(),
                })
        if arrived:
            self.logger.info(f"Netzwechsel auf {self.config.preferred_profile} erfolgreich")
        else:
            self.logger.warning(f"Netzwechsel fehlgeschlagen: {error}")

    def _arm_fallback(self) -> bool:
        """Stellt den Rueckfall ins alte Netz scharf, bevor umgeschaltet wird."""
        if not self.config.fallback_profile:
            return False
        # Ein Rest aus einem frueheren Versuch wuerde `systemd-run` mit
        # "unit already exists" abweisen.
        self._disarm_fallback()
        code, out, err = self._run(
            ['systemd-run', f'--unit={self.config.fallback_unit}',
             f'--on-active={int(self.config.fallback_delay_min)}min',
             'nmcli', 'connection', 'up', self.config.fallback_profile],
            float(self.config.command_timeout_s),
        )
        if code != 0:
            self.logger.warning(
                f"Rueckfall konnte nicht scharf gestellt werden: {(err or out).strip()}"
            )
            return False
        return True

    def _disarm_fallback(self):
        self._run(
            ['systemctl', 'stop', f'{self.config.fallback_unit}.timer'],
            float(self.config.command_timeout_s),
        )
