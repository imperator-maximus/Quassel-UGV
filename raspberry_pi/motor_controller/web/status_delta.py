#!/usr/bin/env python3
"""Statusuebertragung als Aenderungsdifferenz.

Die Oberflaeche bekam den vollstaendigen Systemstatus zehnmal pro Sekunde -
gut 5,5 kB je Sendung, also rund 200 MB in der Stunde. Ueber die SIM-Karte des
Fahrzeugs ist das der groesste Einzelposten des Datenverbrauchs, obwohl sich
zwischen zwei Sendungen fast nichts aendert: Grenzwerte, Knotenlisten und
Betriebsarten stehen still, es wandern nur ein paar Messwerte.

Deshalb geht ab jetzt nur noch die Differenz zum zuletzt gesendeten Stand ueber
die Leitung. Damit die Differenz nicht durch Rauschen aufgeblaeht wird - eine
Spannung, die in der vierten Nachkommastelle zappelt, ist keine Aenderung -
werden Zahlen vorher auf die Genauigkeit gerundet, die die Anzeige ueberhaupt
darstellt.
"""

from typing import Any, Dict, Optional

# Schluessel, unter denen Loeschungen mitgeteilt werden. Ein fehlender Schluessel
# in der Differenz bedeutet "unveraendert", nicht "entfallen" - sonst koennte
# der Empfaenger beides nicht auseinanderhalten.
DELETED_KEY = '__del__'

# Rundung nach Schluesselnamen. Erster Treffer gewinnt, deshalb stehen
# Sonderfaelle vor den allgemeinen Endungen.
_EXACT_DIGITS = {
    'lat': 7,
    'latitude': 7,
    'lon': 7,
    'longitude': 7,
    'altitude': 2,
    'heading': 1,
    'heading_deg': 1,
    'pitch': 1,
    'roll': 1,
    'yaw': 1,
    'rpm': 0,
    'latency_ms': 0,
    'soc_percent': 1,
    'time_left_min': 0,
    'internal_resistance_mohm': 1,
}

# Alterswerte und Zeitstempel wandern in jeder Sendung weiter, ohne dass es
# jemanden interessiert: Angezeigt werden sie nur in Sprechblasen, entschieden
# wird ueber die dazugehoerigen Ja/Nein-Felder (``fresh``, ``online``,
# ``stale``). Auf ganze Sekunden gerundet stehen sie meist still und fallen aus
# der Differenz heraus - das war ein Viertel des verbleibenden Datenstroms.
# Geprueft wird auf die Endung, nicht auf das blosse Vorkommen von "age":
# ``voltage_v`` enthaelt es auch und ist keine Altersangabe.
_COARSE_SUFFIXES = ('age_s', '_ages')

_SUFFIX_DIGITS = (
    ('_time', 0),
    ('_monotonic', 0),
    ('timestamp', 0),
    ('_s', 1),
    ('_a', 2),
    ('_v', 2),
    ('_w', 1),
    ('_ah', 3),
    ('_m', 2),
    ('_deg', 1),
    ('_percent', 1),
    ('_ms', 0),
)

_DEFAULT_DIGITS = 3


def _digits_for(key: str) -> int:
    if key in _EXACT_DIGITS:
        return _EXACT_DIGITS[key]
    if key.endswith(_COARSE_SUFFIXES):
        return 0
    for suffix, digits in _SUFFIX_DIGITS:
        if key.endswith(suffix):
            return digits
    return _DEFAULT_DIGITS


def quantize(value: Any, key: str = '') -> Any:
    """Rundet Gleitkommazahlen auf die angezeigte Genauigkeit.

    Ohne diesen Schritt erzeugt jeder Messwert in jeder Sendung eine
    Aenderung, und die Differenz waere so gross wie der volle Status.
    """
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        digits = _digits_for(key)
        rounded = round(value, digits)
        # Ganzzahlig gerundete Werte als int senden spart die ".0" je Wert.
        return int(rounded) if digits <= 0 else rounded
    if isinstance(value, dict):
        # Karten ueber Knotennummern (``odrive_heartbeat_ages: {"0": 1.17}``)
        # tragen ihre Bedeutung im Namen des Elternteils, nicht im Schluessel.
        # Ohne diesen Durchgriff wuerde ein Alter dort auf drei Nachkommastellen
        # gerundet und stuende in jeder Differenz.
        return {
            k: quantize(v, key if str(k).isdigit() else k)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [quantize(v, key) for v in value]
    return value


def diff(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
    """Differenz von ``old`` nach ``new``.

    Verschachtelte Objekte werden rekursiv verglichen, Listen dagegen als
    Ganzes ersetzt: Wegpunkt- und Punktlisten aendern sich selten, aber wenn,
    dann meist an mehreren Stellen gleichzeitig. Eine Positionsdifferenz waere
    dort groesser als die Liste selbst.
    """
    if old is None:
        return dict(new)

    patch: Dict[str, Any] = {}
    for key, value in new.items():
        if key not in old:
            patch[key] = value
            continue
        previous = old[key]
        if isinstance(value, dict) and isinstance(previous, dict):
            nested = diff(previous, value)
            if nested:
                patch[key] = nested
            continue
        if previous != value or type(previous) is not type(value):
            patch[key] = value

    removed = [key for key in old if key not in new]
    if removed:
        patch[DELETED_KEY] = removed
    return patch


def apply_patch(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Wendet eine Differenz an - dieselbe Regel wie in der Oberflaeche.

    Die Oberflaeche fuehrt diesen Schritt in JavaScript aus. Hier steht er
    nochmal, damit Tests belegen koennen, dass Differenz und Anwendung
    zusammen wieder den vollen Status ergeben.
    """
    result = dict(base)
    for key, value in patch.items():
        if key == DELETED_KEY:
            for removed in value:
                result.pop(removed, None)
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = apply_patch(result[key], value)
        else:
            result[key] = value
    return result
