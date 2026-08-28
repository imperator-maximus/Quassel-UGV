"""Minimaler NMEA-0183-Parser fuer die Saetze, die der UM982 liefert.

Auf dem SensorHub uebernahm ``pynmea2`` diese Aufgabe. Auf dem Raspberry ist
das Paket weder als Debian-Paket verfuegbar noch per pip installierbar (PEP
668 sperrt das System-Python, und der Dienst laeuft ohne venv). Statt das
Fahrzeug von einer nachtraeglichen pip-Installation abhaengig zu machen, die
beim naechsten Neuaufsetzen fehlt, parsen wir die drei benoetigten Saetze
selbst. Der Umfang ist klein und vollstaendig hier sichtbar:

    GGA  Fix-Qualitaet, Position, Hoehe, Satellitenzahl
    HDT  Heading true (Dual-Antenne)
    THS  Heading true mit Statuskennung

Alles andere - insbesondere die proprietaeren ``#UNIHEADINGA``-Bloecke des
UM982 - wird verworfen.
"""

from typing import Dict, List, Optional


def verify_checksum(sentence: str) -> bool:
    """Prueft die NMEA-Pruefsumme ``*HH`` am Satzende.

    Saetze ohne Pruefsumme werden abgelehnt. Auf einer 230400-Baud-Leitung,
    die parallel RTCM-Korrekturen in die Gegenrichtung traegt, sind
    verstuemmelte Zeilen normal; eine halb gelesene Position darf niemals in
    die Navigation gelangen.
    """
    if not sentence.startswith('$'):
        return False
    star = sentence.rfind('*')
    if star < 0 or star + 3 > len(sentence):
        return False
    body = sentence[1:star]
    try:
        expected = int(sentence[star + 1:star + 3], 16)
    except ValueError:
        return False
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return checksum == expected


def split_sentence(sentence: str) -> Optional[List[str]]:
    """Zerlegt einen geprueften Satz in seine Felder.

    Rueckgabe ist ``[satz_id, feld1, feld2, ...]``; ``None`` wenn die
    Pruefsumme nicht stimmt.
    """
    if not verify_checksum(sentence):
        return None
    star = sentence.rfind('*')
    return sentence[1:star].split(',')


def parse_latlon(value: str, hemisphere: str) -> Optional[float]:
    """Wandelt NMEA ``ddmm.mmmm`` plus Himmelsrichtung in Dezimalgrad.

    Der UM982 liefert bei RTK acht Nachkommastellen an den Minuten. Die
    Trennung von Grad und Minuten richtet sich deshalb nach der Position des
    Dezimalpunkts, nicht nach einer festen Feldbreite.
    """
    if not value or not hemisphere:
        return None
    dot = value.find('.')
    if dot < 3:
        return None
    try:
        degrees = int(value[:dot - 2])
        minutes = float(value[dot - 2:])
    except ValueError:
        return None
    if minutes >= 60.0:
        return None
    result = degrees + minutes / 60.0
    if hemisphere.upper() in ('S', 'W'):
        result = -result
    return result


def parse_gga(fields: List[str]) -> Optional[Dict[str, object]]:
    """Liest die fuer Pose und NTRIP noetigen Felder aus einem GGA-Satz.

    Ohne gueltige Fix-Qualitaet oder ohne Position wird ``None`` geliefert -
    ein GGA mit Qualitaet 0 traegt keine brauchbare Position.
    """
    # ``fields`` ist der Satz OHNE Kennung, wie ihn ``split_sentence`` hinter
    # ``fields[0]`` liefert:
    #   0=zeit 1=lat 2=N/S 3=lon 4=E/W 5=qual 6=sats 7=hdop 8=hoehe 9=M ...
    if len(fields) < 9:
        return None
    try:
        quality = int(fields[5]) if fields[5] else 0
    except ValueError:
        return None
    if quality == 0:
        return None
    latitude = parse_latlon(fields[1], fields[2])
    longitude = parse_latlon(fields[3], fields[4])
    if latitude is None or longitude is None:
        return None
    try:
        satellites = int(fields[6]) if fields[6] else 0
    except ValueError:
        satellites = 0
    try:
        altitude = float(fields[8]) if fields[8] else 0.0
    except ValueError:
        altitude = 0.0
    return {
        'quality': quality,
        'latitude': latitude,
        'longitude': longitude,
        'satellites': satellites,
        'altitude': altitude,
    }


def parse_heading(sentence_id: str, fields: List[str]) -> Optional[float]:
    """Liest das wahre Heading aus einem HDT- oder THS-Satz.

    Beim THS-Satz entscheidet die Statuskennung: ``V`` heisst ungueltig und
    wird verworfen. Beim HDT-Satz gibt es keine Kennung; ein leeres Feld ist
    dort das Signal, dass der Empfaenger keine Loesung hat.
    """
    if sentence_id.endswith('HDT'):
        if fields and fields[0]:
            try:
                return float(fields[0])
            except ValueError:
                return None
        return None
    if sentence_id.endswith('THS'):
        if len(fields) >= 2 and fields[0]:
            mode = (fields[1] or '').strip().upper()
            if mode in ('A', 'E', 'M', 'S'):
                try:
                    return float(fields[0])
                except ValueError:
                    return None
        return None
    return None
