#!/usr/bin/env python3
"""
Quassel UGV Motor Controller - Configuration
Zentrale Konfigurationsverwaltung mit YAML-Support
"""

import yaml
import logging
import os
import secrets
from dataclasses import dataclass, field
from typing import List, Dict, Any


# ----------------------------------------------------------------------
# Uebergang von der Bus- auf die lokale GNSS-Zeit
# ----------------------------------------------------------------------
# Der CAN-Bus und der SensorHub sind ausgebaut, ihre YAML-Abschnitte stehen
# aber noch in jeder Datei, die vorher aufs Fahrzeug kopiert wurde. Die
# Dataclasses lehnen unbekannte Schluessel ab, und ein Dienst, der deshalb
# nicht startet, laesst das Fahrzeug im Feld stehen. Darum werden die
# ueberholten Schluessel hier stillgelegt statt abgewiesen - laut genug im
# Log, dass die Datei irgendwann nachgezogen wird.

logger = logging.getLogger(__name__)

# Was den SensorHub-Abschnitt beschrieb und mit ihm verschwunden ist.
_OBSOLETE_POSE_KEYS = (
    'transport', 'wifi_url', 'wifi_urls', 'auth_username', 'auth_password',
    'poll_interval_s', 'request_timeout_s',
)


def _drop_obsolete(section: str, data: Dict[str, Any], obsolete) -> Dict[str, Any]:
    """Entfernt ueberholte Schluessel eines Abschnitts und meldet sie."""
    cleaned = dict(data or {})
    entfernt = [key for key in obsolete if key in cleaned]
    for key in entfernt:
        cleaned.pop(key)
    if entfernt:
        logger.warning(
            "config: %s.%s ist entfallen und wird ignoriert",
            section, ', '.join(entfernt),
        )
    return cleaned


def _migrate_safety_section(data: Dict[str, Any]) -> Dict[str, Any]:
    """Uebernimmt ``can_watchdog_*`` als ``link_watchdog_*``."""
    cleaned = dict(data or {})
    for suffix in ('enabled', 'startup_grace_s', 'interval_s'):
        alt = f'can_watchdog_{suffix}'
        neu = f'link_watchdog_{suffix}'
        if alt in cleaned:
            wert = cleaned.pop(alt)
            cleaned.setdefault(neu, wert)
            logger.warning("config: safety.%s heisst jetzt %s", alt, neu)
    return cleaned


def _migrate_pose_section(data: Dict[str, Any]):
    """Liest ``pose`` oder den alten ``sensor_hub``-Abschnitt.

    Gibt ``None`` zurueck, wenn die Datei keinen der beiden Abschnitte hat -
    dann bleibt es bei den Vorgaben.
    """
    if 'can' in data:
        logger.warning("config: der Abschnitt can ist entfallen und wird ignoriert")

    if 'pose' in data:
        if 'sensor_hub' in data:
            logger.warning(
                "config: sensor_hub wird ignoriert, weil pose vorhanden ist"
            )
        return _drop_obsolete('pose', data['pose'], _OBSOLETE_POSE_KEYS)

    if 'sensor_hub' in data:
        logger.warning("config: der Abschnitt sensor_hub heisst jetzt pose")
        return _drop_obsolete('sensor_hub', data['sensor_hub'], _OBSOLETE_POSE_KEYS)

    return None



@dataclass
class PWMConfig:
    """PWM-Konfiguration"""
    enabled: bool = False
    pins: Dict[str, int] = field(default_factory=lambda: {'left': 19, 'right': 18})
    frequency: int = 50  # Hz
    neutral_value: int = 1500  # μs
    min_value: int = 1000  # μs
    max_value: int = 2000  # μs
    
    # Skid Steering Faktoren
    forward_factor: float = 500.0
    turn_factor: float = 300.0


@dataclass
class RampingConfig:
    """Ramping-Konfiguration"""
    enabled: bool = True
    acceleration_rate: int = 25  # μs/s
    deceleration_rate: int = 800  # μs/s
    brake_rate: int = 1500  # μs/s
    update_interval: float = 0.02  # 50Hz


@dataclass
class SafetyConfig:
    """Sicherheits-Konfiguration"""
    pin: int = 17
    enabled: bool = True
    debounce_time: float = 0.2  # Sekunden
    command_timeout: float = 2.0  # Sekunden
    joystick_timeout: float = 1.0  # Sekunden
    # Wacht ueber Pose und Maehdeck. Hiess ``can_watchdog``, solange beide
    # ueber den Bus kamen.
    link_watchdog_enabled: bool = True
    link_watchdog_startup_grace_s: float = 5.0
    link_watchdog_interval_s: float = 0.1


@dataclass
class LightConfig:
    """Licht-Relais und die Lebenszeichen, die darueber laufen.

    Am Fahrzeug steht man ohne Laptop davor. Ob der Dienst hochgekommen ist
    und ob das Netz steht, war sonst nur ueber die Oberflaeche zu sehen - also
    ueber genau den Weg, der noch fehlt, solange das Netz nicht da ist.
    """
    enabled: bool = True
    pin: int = 22
    # Einmal kurz an, sobald der Dienst steht.
    boot_signal_enabled: bool = True
    boot_on_s: float = 1.0
    # Zweimal blinken, sobald die Netzverbindung eine IP-Adresse hat. Der
    # Mobilfunkrouter braucht nach dem Einschalten laenger als der Pi, deshalb
    # ein eigenes, spaeteres Signal statt eines gemeinsamen.
    network_signal_enabled: bool = True
    network_blinks: int = 2
    network_on_s: float = 0.25
    network_off_s: float = 0.25
    # Kommt bis dahin kein Netz, bleibt es still. Ohne diese Grenze koennte
    # das Signal Stunden spaeter mitten im Maehen losblinken.
    network_wait_timeout_s: float = 600.0
    network_poll_interval_s: float = 2.0


@dataclass
class VoiceConfig:
    """Sprachansagen ueber den USB-Audiostick.

    Dieselbe Lage wie beim Licht, nur deutlicher: Das Blinken sagt, *dass*
    etwas ist, die Ansage sagt, *was*. Die Dateien liegen fertig im Paket
    (``audio/``) und werden mit ``tools/voice/generate_voice.py`` erzeugt.
    """
    enabled: bool = False
    # plughw statt hw: Der Stick nimmt nur Stereo an, und die Kartennummer
    # wandert beim Umstecken - der Name bleibt.
    device: str = 'plughw:CARD=Device,DEV=0'
    player: str = 'aplay'
    # Leer heisst: das Verzeichnis ``audio`` neben dem Paket.
    audio_dir: str = ''
    # Kurz halten. Eine Ansage, die erst in einer halben Minute an der Reihe
    # waere, beschreibt einen Zustand, den es dann womoeglich nicht mehr gibt.
    queue_size: int = 8
    # Dieselbe Ansage nicht im Sekundentakt - ein Anlass kann dauerhaft
    # anliegen, etwa eine schwache Batterie.
    min_interval_s: float = 30.0
    # Ein haengendes aplay blockiert sonst jede weitere Ansage.
    timeout_s: float = 15.0
    # Die beiden Startsignale des Lichts als Ansage. Sie haengen an denselben
    # Stellen und sagen zusaetzlich, was das Blinken bedeutet.
    boot_announcements: bool = True


@dataclass
class BatteryConfig:
    """Junctek KG110F Coulomb-Zähler über BLE.

    Der Zähler sendet von sich aus, deshalb wird nur zugehört. Die Schwellen
    sind gestaffelt: erst warnen, dann das Mähdeck als größten Verbraucher
    abschalten, erst zuletzt die Fahrt beenden.
    """
    enabled: bool = False
    address: str = ''
    notify_uuid: str = '0000ffe1-0000-1000-8000-00805f9b34fb'
    capacity_ah: float = 50.0
    # Nullpunkt des Ladezustands. Der Zähler zählt in seinem eigenen Speicher
    # weiter und merkt nichts davon, wenn die Batterien getauscht oder geladen
    # wurden - beschreiben lässt er sich von hier aus nicht. Deshalb wird der
    # Stand, der "voll" bedeutet, auf dieser Seite festgehalten. Die Datei
    # überlebt den Neustart, den ein Batteriewechsel ohnehin auslöst.
    #
    # Der Pfad gehört *neben* das Anwendungsverzeichnis, nicht hinein: Das
    # Deploy-Skript löscht dort alles außer config.yaml und audio/. Am
    # 31.08.2026 lag der Nullpunkt drin und war nach dem nächsten Ausrollen
    # weg - die Anzeige stand danach wieder auf dem alten Zählerstand, ohne
    # dass irgendwo ein Fehler aufgetaucht wäre.
    zero_point_path: str = ''
    warn_percent: float = 30.0
    mow_stop_percent: float = 25.0
    drive_stop_percent: float = 20.0
    rearm_hysteresis_percent: float = 3.0
    # Der Ladezustand bewegt sich über Minuten, nicht Sekunden. Ein Ausfall
    # von einer Minute ist deshalb kein Grund, den Wert zu verwerfen.
    stale_timeout_s: float = 120.0
    scan_timeout_s: float = 25.0
    connect_timeout_s: float = 30.0
    reconnect_delay_s: float = 5.0
    reconnect_max_delay_s: float = 60.0
    # Der Zaehler laesst nur eine Verbindung zu und schweigt, sobald eine
    # besteht. Bleibt nach einem Neustart eine im Betriebssystem haengen,
    # findet ihn kein Scan mehr. Dann wird sie aktiv getrennt - sonst steht
    # die Ladezustandsueberwachung endlos still.
    stale_link_recovery_enabled: bool = True
    stale_link_min_interval_s: float = 60.0


@dataclass
class NetworkConfig:
    """WLAN-Zustand des Fahrzeugs, gelesen ueber NetworkManager.

    Das Fahrzeug kennt zwei Netze: den Mobilfunkrouter als Regelweg und das
    alte WLAN als Notweg. Faellt es unbemerkt zurueck, laeuft der Betrieb
    ueber den Notweg weiter - deshalb wird der Stand angezeigt und der Rueckweg
    bedienbar gemacht.
    """
    enabled: bool = True
    interface: str = 'wlan0'
    preferred_profile: str = 'HUAWEI'
    fallback_profile: str = 'UGV'
    poll_interval_s: float = 10.0
    command_timeout_s: float = 10.0
    switch_timeout_s: float = 45.0
    # Kommt das Wunschnetz nicht zustande, holt dieser Rueckfall das Fahrzeug
    # von allein ins alte WLAN zurueck, statt es unerreichbar zu lassen.
    fallback_unit: str = 'ugv-netz-rueckfall'
    fallback_delay_min: int = 10
    # Der Mobilfunkrouter braucht nach dem Einschalten laenger als der Pi.
    # Beim Hochfahren ist seine SSID deshalb regelmaessig noch nicht da,
    # NetworkManager nimmt das naechstbeste Netz - und bleibt dort, denn eine
    # stehende Verbindung wird nie zugunsten eines hoeher priorisierten
    # Profils aufgegeben. Ohne Nachfassen haengt das Fahrzeug bis zum
    # naechsten Neustart im falschen Netz.
    auto_switch_enabled: bool = True
    # Abstand zwischen zwei tatsaechlichen Umschaltversuchen. Gezaehlt wird
    # nur, was auch versucht wurde - beim Hochfahren wartet also niemand.
    auto_switch_interval_s: float = 60.0
    # Die Anzeige liest die zwischengespeicherte Scan-Liste, damit sie die
    # Verbindung nicht dauernd fuer ein, zwei Sekunden lahmlegt. Haengt das
    # Fahrzeug aber im falschen Netz, ist genau dieser Cache das Problem:
    # NetworkManager frischt ihn von allein nur alle paar Minuten auf, und
    # solange taucht der gerade hochgefahrene Router dort nicht auf. Dann
    # wird gezielt gesucht - hoechstens so oft wie hier angegeben.
    auto_rescan_interval_s: float = 45.0


@dataclass
class ODriveMowerConfig:
    """ODrive/ODESC-Mähdeck über direkte USB-Verbindungen."""
    enabled: bool = False
    node_id: int = 0
    node_ids: List[int] = field(default_factory=list)
    usb_axes: List[Dict[str, Any]] = field(default_factory=list)
    usb_connect_timeout_s: float = 5.0
    usb_reconnect_interval_s: float = 1.0
    usb_idle_poll_interval_s: float = 0.5
    usb_startup_hang_timeout_s: float = 8.0
    # Native USB/Fibre calls are synchronous and can occasionally stall for
    # more than one second. Keep the local ODrive fail-safe armed, but allow a
    # short transport hiccup without dropping all blades.
    usb_watchdog_timeout_s: float = 3.0
    axis_state: int = 5
    min_rpm: int = 300
    max_rpm: int = 1200
    default_rpm: int = 300
    ramp_rate_rpm_s: int = 300
    command_interval_s: float = 0.1
    coast_delay_s: float = 0.5
    start_stagger_s: float = 0.3
    sequential_start_enabled: bool = True
    startup_timeout_s: float = 2.5
    startup_retries: int = 1
    startup_current_limit_a: float = 12.0
    startup_abort_current_a: float = 12.5
    startup_min_sensorless_rpm: float = 120.0
    startup_stable_duration_s: float = 0.4
    operating_current_limit_a: float = 30.0
    heartbeat_timeout_s: float = 1.0
    # Native USB/Fibre reads are synchronous and all axes are sampled in
    # sequence. This host-side status timeout is independent from the local
    # ODrive hardware watchdog, which remains the blade fail-safe.
    usb_status_timeout_s: float = 4.0
    current_monitor_enabled: bool = True
    current_poll_interval_s: float = 0.1
    current_poll_while_idle: bool = False
    # GET_IQ is supplementary software monitoring.  A short lost RTR response
    # must not stop the whole vehicle while ODrive heartbeats and the local
    # hardware watchdog remain healthy.
    current_response_timeout_s: float = 10.0
    current_startup_grace_s: float = 2.0
    current_trip_a: float = 25.0
    current_trip_duration_s: float = 0.5
    current_critical_trip_a: float = 29.0
    current_critical_trip_duration_s: float = 0.1
    # A synchronous libfibre call blocks its thread without any timeout. These
    # limits are evaluated by the central safety watchdog, which never touches
    # the transport and therefore cannot be parked by the same fault.
    #
    # A healthy native call occasionally needs more than a second, so the host
    # stop is aligned with ``usb_status_timeout_s``: by then the local ODrive
    # watchdog has disarmed the blades anyway. Only a call that is still
    # unanswered well beyond that counts as permanently stuck and forces the
    # process restart.
    command_loop_timeout_s: float = 3.0
    usb_call_stall_timeout_s: float = 5.0
    # Blade rotation is verified during the whole run, not only at start-up.
    runtime_rpm_monitor_enabled: bool = True
    runtime_sensorless_poll_interval_s: float = 0.5
    runtime_sensorless_timeout_s: float = 3.0
    runtime_min_rpm: float = 150.0
    runtime_rpm_fault_duration_s: float = 1.5


@dataclass
class PoseConfig:
    """GNSS-Empfaenger am Raspberry und die Alterung seiner Pose.

    Bis August 2026 kam die Pose von einem eigenen SensorHub - erst ueber den
    CAN-Bus, spaeter per HTTP. Beides ist ausgebaut; der UM982 haengt jetzt
    direkt per USB am Raspberry. Die Zeitgrenzen darunter sind geblieben,
    denn sie beschreiben nicht den Transport, sondern wie alt eine Pose
    werden darf, bevor das Fahrzeug stehen bleibt.
    """
    # Der Port wird ueber /dev/serial/by-id angegeben, weil die Nummer hinter
    # /dev/ttyUSB von der Aufzaehlreihenfolge beim Booten abhaengt und mit den
    # beiden ODrives am selben Bus wandern kann.
    gps_port: str = '/dev/serial/by-id/usb-FTDI_FT231X_USB_UART_D30JJBSU-if00-port0'
    gps_baudrate: int = 230400
    gps_read_timeout_s: float = 1.0
    # Aelter als das, gilt die Position nicht mehr als Pose. Die Quelle
    # schweigt dann, statt einen alten Wert erneut einzuspeisen - nur so
    # altert die Pose und die Fahrpause greift. Der Empfaenger liefert
    # mehrmals je Sekunde; zwei Sekunden sind reichlich Luft.
    gps_max_fix_age_s: float = 2.0
    gps_max_heading_age_s: float = 2.0
    # Leer heisst: neben dem Modul liegende vehicle_geometry.json.
    vehicle_geometry_path: str = ''

    # Ab diesem Alter pausiert der Fahrantrieb.
    pause_timeout_s: float = 1.0
    # Erst eine wirklich stabile Pose setzt einen Plan wieder in Gang. Ein
    # einzelner Treffer zwischen zwei Luecken darf das Fahrzeug nicht
    # wiederholt anfahren und stoppen lassen.
    resume_stable_s: float = 2.0
    # Ab diesem Alter gilt die Pose fuer den Sicherheitsstopp als verloren.
    telemetry_timeout_s: float = 30.0

    # NTRIP: Open RTK-Dienst M-V. Mountpoint openrtk_mv deckt GPS, GLONASS,
    # Galileo und BeiDou ab; openrtk_mv_2G nur GPS und GLONASS.
    # Passwort gehoert in UGV_NTRIP_PASSWORD, nicht in die YAML.
    ntrip_enabled: bool = True
    ntrip_host: str = 'openrtk-mv.de'
    ntrip_port: int = 2101
    ntrip_mountpoint: str = 'openrtk_mv'
    ntrip_username: str = ''
    ntrip_password: str = ''
    ntrip_timeout_s: float = 10.0
    ntrip_reconnect_interval_s: float = 15.0
    # Ein offener Socket ohne Daten ist der gefaehrliche Fall: der Empfaenger
    # faellt still auf GPS FIX zurueck. Einmal hat das sieben Minuten Fahrt
    # gekostet, bevor es auffiel.
    ntrip_stale_timeout_s: float = 10.0


@dataclass
class NavigationConfig:
    """Autonome Wegpunktnavigation (S1-Bearing-Hold).

    Die Pose kommt aus dem Zwischenspeicher, den ``PoseConfig`` speist.
    """
    enabled: bool = True
    # Muss spaeter ausloesen als pose.pause_timeout_s (1 s). Die
    # zentrale Safety-Logik pausiert und setzt den Plan nach einer kurzen
    # WiFi-Luecke fort; der lokale Navigations-Watchdog bleibt nur als
    # nachgelagerter Fallback bestehen.
    watchdog_timeout_s: float = 3.0
    # Baeume am Feldrand druecken den RTK-Fix fuer ein paar Sekunden auf
    # FLOAT. Den kompletten Maehplan dafuer abzubrechen ist unverhaeltnis-
    # maessig: der Plan haelt an und macht weiter, sobald der Fix wirklich
    # zurueck ist. Auf einer FLOAT-Loesung zu fahren bleibt verboten - diese
    # Werte entscheiden nur, wie lange gewartet wird, bevor aufgegeben wird.
    rtk_resume_stable_s: float = 2.0
    rtk_lost_timeout_s: float = 90.0
    geofence_radius_m: float = 50.0
    # 0.30 reichte fuer die Bahnverfolgung nicht: der Deckel begrenzt nicht
    # nur die Fahrt, sondern ueber die Innen-Rad-Garantie auch den Lenkanteil
    # auf |x| <= max_joystick·(1 - min_inner_wheel_speed·heading_factor)/ratio,
    # bei 0.30/0.50 also rund 0.30 = 90 us PWM-Unterschied. Im Handtest vom
    # 09.08. drehte das Fahrzeug bei 60 us gar nicht und bei 150 us nach links
    # gerade eben - die Autonomie lenkte also dauerhaft unterhalb der
    # Losbrechgrenze. 0.45 hebt den Lenkanteil auf rund 138 us, ohne die
    # Innen-Rad-Garantie aufzugeben (vgl. min_inner_wheel_speed).
    max_joystick: float = 0.45
    # A 25 cm target circle was too tight for a heavy skid-steer mower: in a
    # real run it missed by 1 cm, overshot, and then pivoted back toward the
    # now lateral target. 40 cm still preserves RTK path accuracy while
    # allowing a positioning segment to hand over cleanly to the mow track.
    acceptance_radius_m: float = 0.40
    slowdown_radius_m: float = 0.5
    turn_kp: float = 0.02
    track_lookahead_m: float = 0.8
    pivot_heading_threshold_deg: float = 70.0
    goto_divergence_limit_m: float = 0.75
    goto_divergence_samples: int = 5
    # So viele Posen in Folge muss der Winkelfehler ueber der Sperre liegen.
    # Bewusst kurz: Ein grosser Winkel gehoert nicht in den Ausrichtbogen,
    # sondern in ein Rangiermanoever - die Planausfuehrung baut daraufhin eine
    # neue Anfahrt, statt die Fahrt zu beenden.
    track_heading_block_samples: int = 3
    track_cross_track_limit_m: float = 1.0
    # Oberhalb dieses Abstands wird nicht mehr auf Annaeherung gewartet: Dort
    # koennen Sperrzonen und Grenzen zwischen Fahrzeug und Bahn liegen.
    track_cross_track_max_m: float = 8.0
    # So lange darf die Abweichung ueber der Grenze bleiben, ohne kleiner zu
    # werden. Wer sich naehert, bekommt die Zeit immer wieder neu.
    track_cross_track_recover_s: float = 10.0
    # Um so viel muss es naeher geworden sein, damit es als Annaeherung zaehlt -
    # sonst setzt schon das Rauschen der Pose die Uhr zurueck.
    track_cross_track_progress_m: float = 0.1
    # Gleichzeitiges Drehen und Vorwaertsfahren (_calculate_command)
    # konvergiert auf diesem Fahrzeug nicht, sobald der Turn-Anteil
    # saettigt (~15° bei turn_kp=0.02): der Vorwaertsschub laeuft
    # schneller von der Bahn weg, als die Drehung aufholen kann (real,
    # 25.07.: -18.7° -> -26.3° unter vollem x/y-Mix, xtrack 0.01->0.16 m).
    # Oberhalb von track_alignment_enter_deg wird deshalb zuerst ohne
    # Vorwaertsschub um ein nahezu stehendes Kettenpaar gerollt (fuer
    # reverse am selben Tag bewaehrt: 29.7° -> 1.3° in 11s), erst
    # unterhalb von track_alignment_exit_deg normal weitergefahren. Ein
    # Gegenlauf-Pivot als Alternative dreht das reale UGV unter Last gar
    # nicht (Stillstand >4 Min, selbes Datum).
    track_alignment_enter_deg: float = 10.0
    track_alignment_exit_deg: float = 5.0
    # Oberhalb dieser Schwelle ist selbst der Roll-Bogen nicht mehr
    # sicher (urspruenglicher Brunnen-Stall: -51.7° wachsend bis -62.3°,
    # Cross-Track 0.19->1.01 m) - dort deterministisch stoppen statt zu
    # raten, statt automatisch anzufahren.
    track_heading_block_deg: float = 45.0
    # Der Fehler wird gegen die Bahnrichtung gemessen und muss ueber so viele
    # aufeinanderfolgende Posen anhalten. Ein einzelner Ausreisser darf keine
    # laufende Mahd stoppen: beim Ausrichtbogen am Segmentanfang schwenkt die
    # GNSS-Antenne um den Drehpunkt, was kurzzeitig grosse Scheinfehler
    # erzeugt (real 07.08.: 16.4° -> 48.4° in 1 s bei 11 cm Querabstand).
    # In Posen statt Sekunden, damit dieselbe Regel im zeitraffenden
    # Pfadsimulator gilt wie auf dem Fahrzeug (5 Hz Telemetrie -> ~0.6 s).
    # Der Ausrichtbogen macht bewusst kaum Bahnfortschritt, deshalb ruht dort
    # der Track-Waechter. Damit war dieser Zweig unbegrenzt: dreht sich das
    # Fahrzeug nicht, rollte es ewig weiter, ohne Fehler, alles gruen
    # (real 07.08.: 7° Fehler, Kurs konstant, PWM 1405/1500). Verbessert sich
    # der Winkelfehler so lange nicht um mindestens
    # track_align_min_progress_deg, wird deterministisch gestoppt.
    track_align_timeout_s: float = 10.0
    # Fein genug, um eine langsam konvergierende Ausrichtung nicht zu stoppen.
    track_align_min_progress_deg: float = 0.5
    # Untere Schranke des Drehanteils, solange ausgerichtet wird. Das
    # proportionale Kommando faellt sonst unter die Losbrechgrenze, bevor die
    # Austrittsschwelle erreicht ist (gemessen 07.08. auf Gras: x=0.236 dreht
    # mit 1.3 Grad/s, x=0.155 mit 0.4 Grad/s, x=0.125 gar nicht mehr).
    track_align_min_turn: float = 0.22
    # Dreht sich der Kurs trotzdem nicht, wird der Drehanteil ueber diese
    # Dauer bis max_joystick hochgefahren. Die Losbrechgrenze auf Gras haengt
    # von Bewuchs, Naesse und Last ab und ist nicht vorhersagbar; 0.22 liess
    # das Fahrzeug am 07.08. 14 s lang unbewegt.
    track_align_escalate_s: float = 3.0
    # Bei weniger als 15 cm Track-Fortschritt in 10 s neutral stoppen und
    # den Stillstand sichtbar melden, statt wirkungslose PWM weiterzusenden.
    track_stall_timeout_s: float = 10.0
    track_stall_min_progress_m: float = 0.15
    # Innen-Rad-Garantie gegen reine Pivots: untere Schranke der Vorwärts-
    # Geschwindigkeit des inneren (kurveninneren) Skid-Rads, ausgedrückt
    # als Bruchteil von ``max_joystick``. 0.0 = legacy (Pivot erlaubt),
    # 0.50 = inneres Rad rollt mit mind. 50% des max. Joystick-Levels →
    # PWM-Offset typisch 75 μs über Neutral, sicher außerhalb der ESC-
    # Totzone (~±50 μs). Fahrzeug fährt einen mittleren Bogen statt zu
    # pivotieren, schont Rasen. Skaliert in der Slowdown-Zone proportional
    # mit ``distance_factor``.
    min_inner_wheel_speed: float = 0.50
    # Der Antrieb laeuft ueber PWM ohne jede Rueckmeldung: dass ein Links-
    # befehl schwaecher wirkt als der gleich grosse Rechtsbefehl, kann die
    # Software nicht messen, sie kann es nur vorhalten. Gemessen am 09.08.:
    # bei neutralem Lenkbefehl zieht das Fahrzeug vorwaerts mit 0.42 Grad/s
    # nach rechts, und ein Rechtsbefehl wirkt etwa doppelt so stark wie ein
    # gleich grosser Linksbefehl. 1.0 = keine Kompensation; der Wert gehoert
    # ins Fahrzeug-YAML, nicht in den Default, weil er die Eigenheit eines
    # bestimmten Antriebs beschreibt.
    turn_gain_left: float = 1.0


@dataclass
class MappingConfig:
    """Drive-around Kartierung und GeoJSON-Speicher."""
    enabled: bool = True
    maps_dir: str = '/home/nicolay/raspberrycan/maps'
    min_point_distance_m: float = 0.25


@dataclass
class WebConfig:
    """Web-Interface-Konfiguration.

    Das Interface haengt ueber eine Portfreigabe am Internet und kann Fahrantrieb
    und Maehdeck ausloesen. ``auth_enabled`` ist deshalb standardmaessig aktiv;
    ohne gesetztes Passwort antwortet der Server mit 503 statt ungeschuetzt zu
    laufen.
    """
    enabled: bool = False
    host: str = '0.0.0.0'
    port: int = 80
    secret_key: str = ''
    template_folder: str = 'templates'
    static_folder: str = 'static'
    max_speed_percent: float = 100.0

    # Sendetakt des Statusstroms. Das Fahrzeug haengt an einer SIM-Karte, und
    # der Status ist der groesste Dauerposten im Datenverbrauch. Im Stillstand
    # genuegt ein Stand je Sekunde; sobald etwas faehrt, maeht oder gestoert
    # ist, wird schneller gesendet, damit die Anzeige der Eingabe folgt.
    # Gesendet wird ohnehin nur die Aenderung zum letzten Stand.
    status_interval_idle_s: float = 1.0
    status_interval_active_s: float = 0.25
    # Textantworten ab dieser Groesse werden gzip-komprimiert. Die Oberflaeche
    # allein sind 90 kB Quelltext, komprimiert etwa ein Fuenftel davon.
    compress_min_bytes: int = 1024

    # Ein haengender USB-Aufruf am Maehdeck ist bekannt und harmlos: Der
    # Prozess beendet sich, systemd startet neu. Danach stand das Fahrzeug
    # bisher und wartete auf einen Menschen - bei einem Fehler, der regelmaessig
    # auftritt und mit dem Maehen nichts zu tun hat.
    #
    # Automatisch fortgesetzt wird ausschliesslich dieser Fall. Jeder andere
    # Sicherheitsstopp hat eine andere Ursache und wartet weiterhin.
    auto_resume_after_usb_stall: bool = True
    # Bremse gegen das Endlosdrehen: Ist das Maehdeck wirklich defekt, waere
    # die Kette sonst Neustart, Messer an, Haenger, Neustart - ohne Ende. Nach
    # so vielen Anlaeufen ohne Fortschritt uebernimmt wieder der Mensch.
    auto_resume_max_attempts: int = 3
    # So lange wird auf gesunde Verhaeltnisse gewartet (Pose, RTK, ODrive),
    # bevor der Anlauf aufgegeben wird.
    auto_resume_health_timeout_s: float = 120.0

    # Zugangsschutz. Passwort und secret_key gehoeren nicht in die YAML,
    # sondern in UGV_WEB_PASSWORD bzw. UGV_WEB_SECRET_KEY.
    auth_enabled: bool = True
    auth_username: str = 'ugv'
    auth_password: str = ''
    auth_realm: str = 'Quassel UGV'
    # Zusaetzliche Origins, die schreibende Requests stellen duerfen. Die
    # eigene Adresse ist immer erlaubt und muss hier nicht stehen.
    allowed_origins: List[str] = field(default_factory=list)
    auth_max_failures: int = 8
    auth_lockout_s: float = 60.0


@dataclass
class NotificationsConfig:
    """Push-Meldungen ueber ntfy, wenn eine Stoerung das Fahrzeug stoppt.

    Ein roter Zustand in der Weboberflaeche faellt nur auf, solange jemand
    hinsieht. Topic und Token gehoeren nicht in die YAML, sondern in
    UGV_NTFY_TOPIC bzw. UGV_NTFY_TOKEN: bei ntfy.sh ist der Topic-Name das
    einzige Geheimnis, das fremde Mitleser fernhaelt.
    """
    enabled: bool = False
    server: str = 'https://ntfy.sh'
    topic: str = ''
    token: str = ''
    # Beim Antippen der Meldung zu oeffnen, z.B. die eigene Weboberflaeche.
    click_url: str = ''
    request_timeout_s: float = 5.0
    # Dieselbe Stoerung nicht oefter melden. Ein Fehler, den man einmal
    # kennt, muss nicht im Minutentakt wiederholt werden.
    min_interval_s: float = 120.0
    # Solange wird eine unzustellbare Meldung weiter versucht. Danach ist sie
    # ueberholt: das Fahrzeug steht dann schon lange sichtbar still.
    retry_max_age_s: float = 900.0
    queue_size: int = 32
    fault_priority: int = 5  # ntfy 1-5; 5 klingelt auch im Stummmodus
    recovery_priority: int = 3
    notify_recovery: bool = True
    # Eine kurze Telemetrieluecke pausiert das Fahrzeug staendig und loest
    # sich meist in Sekunden. Erst eine Pause ueber diese Dauer ist eine
    # Stoerung, die jemand erfahren muss.
    motion_hold_after_s: float = 20.0


@dataclass
class LoggingConfig:
    """Logging-Konfiguration"""
    level: str = 'INFO'  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    format: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    file: str = '/var/log/motor_controller.log'
    console: bool = True
    file_enabled: bool = False


@dataclass
class Config:
    """Haupt-Konfiguration"""
    pwm: PWMConfig = field(default_factory=PWMConfig)
    ramping: RampingConfig = field(default_factory=RampingConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    light: LightConfig = field(default_factory=LightConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    odrive_mower: ODriveMowerConfig = field(default_factory=ODriveMowerConfig)
    battery: BatteryConfig = field(default_factory=BatteryConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    pose: PoseConfig = field(default_factory=PoseConfig)
    navigation: NavigationConfig = field(default_factory=NavigationConfig)
    mapping: MappingConfig = field(default_factory=MappingConfig)
    web: WebConfig = field(default_factory=WebConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    quiet: bool = False
    monitor: bool = True
    
    @classmethod
    def from_yaml(cls, filepath: str) -> 'Config':
        """Lädt Konfiguration aus YAML-Datei"""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Config-Datei nicht gefunden: {filepath}")
        
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
        
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Config':
        """Erstellt Config aus Dictionary"""
        config = cls()
        
        if 'pwm' in data:
            config.pwm = PWMConfig(**data['pwm'])
        if 'ramping' in data:
            config.ramping = RampingConfig(**data['ramping'])
        if 'safety' in data:
            config.safety = SafetyConfig(**_migrate_safety_section(data['safety']))
        if 'light' in data:
            config.light = LightConfig(**data['light'])
        if 'voice' in data:
            config.voice = VoiceConfig(**data['voice'])
        if 'odrive_mower' in data:
            odrive_data = _drop_obsolete(
                'odrive_mower', data['odrive_mower'], ('transport',)
            )
            if 'node_ids' in odrive_data and odrive_data['node_ids'] is None:
                odrive_data['node_ids'] = []
            if 'usb_axes' in odrive_data and odrive_data['usb_axes'] is None:
                odrive_data['usb_axes'] = []
            config.odrive_mower = ODriveMowerConfig(**odrive_data)
        if 'battery' in data:
            config.battery = BatteryConfig(**data['battery'])
        if 'network' in data:
            config.network = NetworkConfig(**data['network'])
        # ``can`` und ``sensor_hub`` sind mit dem Bus und dem SensorHub
        # entfallen. Eine mitgereiste YAML darf daran nicht scheitern: das
        # Fahrzeug steht dann irgendwo im Feld und der Dienst startet nicht.
        pose_data = _migrate_pose_section(data)
        if pose_data is not None:
            config.pose = PoseConfig(**pose_data)
        if 'navigation' in data:
            config.navigation = NavigationConfig(**data['navigation'])
        if 'mapping' in data:
            config.mapping = MappingConfig(**data['mapping'])
        if 'web' in data:
            config.web = WebConfig(**data['web'])
        if 'notifications' in data:
            config.notifications = NotificationsConfig(**data['notifications'])
        if 'logging' in data:
            config.logging = LoggingConfig(**data['logging'])
        
        config.quiet = data.get('quiet', False)
        config.monitor = data.get('monitor', True)

        config.apply_environment()

        return config

    def apply_environment(self) -> None:
        """Uebernimmt Zugangsdaten aus Umgebungsvariablen.

        Passwoerter haben in der YAML nichts verloren: Die Datei wird kopiert,
        gesichert und versehentlich committet. Umgebungsvariablen haben Vorrang
        vor allem, was doch in der Datei steht.
        """
        web_password = os.getenv('UGV_WEB_PASSWORD')
        if web_password:
            self.web.auth_password = web_password

        web_user = os.getenv('UGV_WEB_USERNAME')
        if web_user:
            self.web.auth_username = web_user

        secret_key = os.getenv('UGV_WEB_SECRET_KEY')
        if secret_key:
            self.web.secret_key = secret_key
        if not self.web.secret_key:
            # Ohne gesetzten Schluessel bei jedem Start einen neuen erzeugen.
            # Das entwertet alte Sitzungscookies nach einem Neustart und ist
            # allemal besser als ein Wert, der im Repository nachlesbar ist.
            self.web.secret_key = secrets.token_urlsafe(32)

        # NTRIP-Zugangsdaten des Open RTK-Dienstes M-V. Der Dienst erlaubt nur
        # eine Verbindung je Kennung; ein zweiter Client mit denselben Daten
        # wirft den ersten heraus.
        ntrip_user = os.getenv('UGV_NTRIP_USERNAME')
        if ntrip_user:
            self.pose.ntrip_username = ntrip_user

        ntrip_password = os.getenv('UGV_NTRIP_PASSWORD')
        if ntrip_password:
            self.pose.ntrip_password = ntrip_password

        # Bei ntfy.sh darf jeder mitlesen und mitschreiben, der den Topic-Namen
        # kennt. Er ist damit ein Geheimnis und gehoert wie die Passwoerter in
        # die Umgebung, nicht in eine kopierbare YAML.
        ntfy_topic = os.getenv('UGV_NTFY_TOPIC')
        if ntfy_topic:
            self.notifications.topic = ntfy_topic

        ntfy_token = os.getenv('UGV_NTFY_TOKEN')
        if ntfy_token:
            self.notifications.token = ntfy_token

        ntfy_server = os.getenv('UGV_NTFY_SERVER')
        if ntfy_server:
            self.notifications.server = ntfy_server


    def to_yaml(self, filepath: str):
        """Speichert Konfiguration als YAML-Datei"""
        data = {
            'pwm': {
                'enabled': self.pwm.enabled,
                'pins': self.pwm.pins,
                'frequency': self.pwm.frequency,
                'neutral_value': self.pwm.neutral_value,
                'min_value': self.pwm.min_value,
                'max_value': self.pwm.max_value,
                'forward_factor': self.pwm.forward_factor,
                'turn_factor': self.pwm.turn_factor
            },
            'ramping': {
                'enabled': self.ramping.enabled,
                'acceleration_rate': self.ramping.acceleration_rate,
                'deceleration_rate': self.ramping.deceleration_rate,
                'brake_rate': self.ramping.brake_rate,
                'update_interval': self.ramping.update_interval
            },
            'safety': {
                'pin': self.safety.pin,
                'enabled': self.safety.enabled,
                'debounce_time': self.safety.debounce_time,
                'command_timeout': self.safety.command_timeout,
                'joystick_timeout': self.safety.joystick_timeout,
                'link_watchdog_enabled': self.safety.link_watchdog_enabled,
                'link_watchdog_startup_grace_s': self.safety.link_watchdog_startup_grace_s,
                'link_watchdog_interval_s': self.safety.link_watchdog_interval_s
            },
            'light': {
                'enabled': self.light.enabled,
                'pin': self.light.pin
            },
            'voice': {
                'enabled': self.voice.enabled,
                'device': self.voice.device,
                'min_interval_s': self.voice.min_interval_s,
                'boot_announcements': self.voice.boot_announcements
            },
            'odrive_mower': {
                'enabled': self.odrive_mower.enabled,
                'node_id': self.odrive_mower.node_id,
                'node_ids': self.odrive_mower.node_ids,
                'usb_axes': self.odrive_mower.usb_axes,
                'usb_connect_timeout_s': self.odrive_mower.usb_connect_timeout_s,
                'usb_reconnect_interval_s': self.odrive_mower.usb_reconnect_interval_s,
                'usb_idle_poll_interval_s': self.odrive_mower.usb_idle_poll_interval_s,
                'usb_startup_hang_timeout_s': self.odrive_mower.usb_startup_hang_timeout_s,
                'axis_state': self.odrive_mower.axis_state,
                'min_rpm': self.odrive_mower.min_rpm,
                'max_rpm': self.odrive_mower.max_rpm,
                'default_rpm': self.odrive_mower.default_rpm,
                'ramp_rate_rpm_s': self.odrive_mower.ramp_rate_rpm_s,
                'command_interval_s': self.odrive_mower.command_interval_s,
                'coast_delay_s': self.odrive_mower.coast_delay_s,
                'start_stagger_s': self.odrive_mower.start_stagger_s,
                'sequential_start_enabled': self.odrive_mower.sequential_start_enabled,
                'startup_timeout_s': self.odrive_mower.startup_timeout_s,
                'startup_retries': self.odrive_mower.startup_retries,
                'startup_current_limit_a': self.odrive_mower.startup_current_limit_a,
                'startup_abort_current_a': self.odrive_mower.startup_abort_current_a,
                'startup_min_sensorless_rpm': self.odrive_mower.startup_min_sensorless_rpm,
                'startup_stable_duration_s': self.odrive_mower.startup_stable_duration_s,
                'operating_current_limit_a': self.odrive_mower.operating_current_limit_a,
                'heartbeat_timeout_s': self.odrive_mower.heartbeat_timeout_s,
                'usb_status_timeout_s': self.odrive_mower.usb_status_timeout_s,
                'current_monitor_enabled': self.odrive_mower.current_monitor_enabled,
                'current_poll_interval_s': self.odrive_mower.current_poll_interval_s,
                'current_poll_while_idle': self.odrive_mower.current_poll_while_idle,
                'current_response_timeout_s': self.odrive_mower.current_response_timeout_s,
                'current_startup_grace_s': self.odrive_mower.current_startup_grace_s,
                'current_trip_a': self.odrive_mower.current_trip_a,
                'current_trip_duration_s': self.odrive_mower.current_trip_duration_s,
                'current_critical_trip_a': self.odrive_mower.current_critical_trip_a,
                'current_critical_trip_duration_s': self.odrive_mower.current_critical_trip_duration_s
            },
            'battery': {
                'enabled': self.battery.enabled,
                'address': self.battery.address,
                'notify_uuid': self.battery.notify_uuid,
                'capacity_ah': self.battery.capacity_ah,
                'warn_percent': self.battery.warn_percent,
                'mow_stop_percent': self.battery.mow_stop_percent,
                'drive_stop_percent': self.battery.drive_stop_percent,
                'rearm_hysteresis_percent': self.battery.rearm_hysteresis_percent,
                'stale_timeout_s': self.battery.stale_timeout_s,
                'scan_timeout_s': self.battery.scan_timeout_s,
                'connect_timeout_s': self.battery.connect_timeout_s,
                'reconnect_delay_s': self.battery.reconnect_delay_s,
                'reconnect_max_delay_s': self.battery.reconnect_max_delay_s
            },
            'network': {
                'enabled': self.network.enabled,
                'interface': self.network.interface,
                'preferred_profile': self.network.preferred_profile,
                'fallback_profile': self.network.fallback_profile,
                'poll_interval_s': self.network.poll_interval_s,
                'command_timeout_s': self.network.command_timeout_s,
                'switch_timeout_s': self.network.switch_timeout_s,
                'fallback_unit': self.network.fallback_unit,
                'fallback_delay_min': self.network.fallback_delay_min,
                'auto_switch_enabled': self.network.auto_switch_enabled,
                'auto_switch_interval_s': self.network.auto_switch_interval_s,
                'auto_rescan_interval_s': self.network.auto_rescan_interval_s
            },
            # ntrip_password bleibt draussen: es kommt aus UGV_NTRIP_PASSWORD.
            'pose': {
                'gps_port': self.pose.gps_port,
                'gps_baudrate': self.pose.gps_baudrate,
                'gps_read_timeout_s': self.pose.gps_read_timeout_s,
                'gps_max_fix_age_s': self.pose.gps_max_fix_age_s,
                'gps_max_heading_age_s': self.pose.gps_max_heading_age_s,
                'vehicle_geometry_path': self.pose.vehicle_geometry_path,
                'pause_timeout_s': self.pose.pause_timeout_s,
                'resume_stable_s': self.pose.resume_stable_s,
                'telemetry_timeout_s': self.pose.telemetry_timeout_s,
                'ntrip_enabled': self.pose.ntrip_enabled,
                'ntrip_host': self.pose.ntrip_host,
                'ntrip_port': self.pose.ntrip_port,
                'ntrip_mountpoint': self.pose.ntrip_mountpoint,
                'ntrip_username': self.pose.ntrip_username,
                'ntrip_timeout_s': self.pose.ntrip_timeout_s,
                'ntrip_reconnect_interval_s': self.pose.ntrip_reconnect_interval_s,
                'ntrip_stale_timeout_s': self.pose.ntrip_stale_timeout_s
            },
            'navigation': {
                'enabled': self.navigation.enabled,
                'watchdog_timeout_s': self.navigation.watchdog_timeout_s,
                'rtk_resume_stable_s': self.navigation.rtk_resume_stable_s,
                'rtk_lost_timeout_s': self.navigation.rtk_lost_timeout_s,
                'geofence_radius_m': self.navigation.geofence_radius_m,
                'max_joystick': self.navigation.max_joystick,
                'acceptance_radius_m': self.navigation.acceptance_radius_m,
                'slowdown_radius_m': self.navigation.slowdown_radius_m,
                'turn_kp': self.navigation.turn_kp,
                'track_lookahead_m': self.navigation.track_lookahead_m,
                'pivot_heading_threshold_deg': self.navigation.pivot_heading_threshold_deg,
                'goto_divergence_limit_m': self.navigation.goto_divergence_limit_m,
                'goto_divergence_samples': self.navigation.goto_divergence_samples,
                'track_cross_track_limit_m': self.navigation.track_cross_track_limit_m,
                'track_alignment_enter_deg': self.navigation.track_alignment_enter_deg,
                'track_alignment_exit_deg': self.navigation.track_alignment_exit_deg,
                'track_heading_block_deg': self.navigation.track_heading_block_deg,
                'track_stall_timeout_s': self.navigation.track_stall_timeout_s,
                'track_stall_min_progress_m': self.navigation.track_stall_min_progress_m,
                'min_inner_wheel_speed': self.navigation.min_inner_wheel_speed,
                'turn_gain_left': self.navigation.turn_gain_left
            },
            'mapping': {
                'enabled': self.mapping.enabled,
                'maps_dir': self.mapping.maps_dir,
                'min_point_distance_m': self.mapping.min_point_distance_m
            },
            # secret_key, auth_password und die SensorHub-Zugangsdaten werden
            # bewusst nicht geschrieben: to_yaml() erzeugt sonst eine Datei mit
            # Klartext-Geheimnissen. Sie kommen aus der Umgebung.
            'web': {
                'enabled': self.web.enabled,
                'host': self.web.host,
                'port': self.web.port,
                'template_folder': self.web.template_folder,
                'static_folder': self.web.static_folder,
                'max_speed_percent': self.web.max_speed_percent,
                'auth_enabled': self.web.auth_enabled,
                'auth_username': self.web.auth_username,
                'auth_realm': self.web.auth_realm,
                'allowed_origins': list(self.web.allowed_origins),
                'auth_max_failures': self.web.auth_max_failures,
                'auth_lockout_s': self.web.auth_lockout_s
            },
            # topic und token bleiben draussen: bei ntfy.sh ist der Topic-Name
            # das Geheimnis. Beide kommen aus der Umgebung.
            'notifications': {
                'enabled': self.notifications.enabled,
                'server': self.notifications.server,
                'click_url': self.notifications.click_url,
                'request_timeout_s': self.notifications.request_timeout_s,
                'min_interval_s': self.notifications.min_interval_s,
                'retry_max_age_s': self.notifications.retry_max_age_s,
                'queue_size': self.notifications.queue_size,
                'fault_priority': self.notifications.fault_priority,
                'recovery_priority': self.notifications.recovery_priority,
                'notify_recovery': self.notifications.notify_recovery,
                'motion_hold_after_s': self.notifications.motion_hold_after_s
            },
            'logging': {
                'level': self.logging.level,
                'format': self.logging.format,
                'file': self.logging.file,
                'console': self.logging.console,
                'file_enabled': self.logging.file_enabled
            },
            'quiet': self.quiet,
            'monitor': self.monitor
        }
        
        with open(filepath, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    
    @classmethod
    def default(cls) -> 'Config':
        """Erstellt Default-Konfiguration"""
        config = cls()
        config.apply_environment()
        return config
