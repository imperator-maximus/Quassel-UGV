#!/usr/bin/env python3
"""
Quassel UGV Motor Controller - Configuration
Zentrale Konfigurationsverwaltung mit YAML-Support
"""

import yaml
import os
import secrets
from dataclasses import dataclass, field
from typing import List, Dict, Any


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
    can_watchdog_enabled: bool = True
    can_watchdog_startup_grace_s: float = 5.0
    can_watchdog_interval_s: float = 0.1


@dataclass
class LightConfig:
    """Licht-Konfiguration"""
    enabled: bool = True
    pin: int = 22


@dataclass
class MowerConfig:
    """Mäher-Konfiguration"""
    enabled: bool = True
    relay_pin: int = 23
    pwm_pin: int = 12
    pwm_frequency: int = 1000  # Hz
    duty_min: int = 16  # %
    duty_max: int = 84  # %
    duty_off: int = 0  # %


@dataclass
class ODriveMowerConfig:
    """ODrive/ODESC-Mähdeck über CAN oder direkte USB-Verbindungen."""
    enabled: bool = False
    transport: str = 'can'
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
class CANConfig:
    """CAN-Bus-Konfiguration"""
    enabled: bool = True
    interface: str = 'can0'
    bitrate: int = 250000
    motor_controller_id: int = 0x200
    sensor_hub_id: int = 0x100
    max_frame_size: int = 6  # Bytes Nutzdaten pro Frame
    frame_timeout: float = 1.0  # Sekunden


@dataclass
class SensorHubConfig:
    """Transport der SensorHub-Telemetrie zum Hauptrechner.

    Ist der SensorHub durch Basic-Auth geschuetzt, muessen hier dieselben
    Zugangsdaten stehen. Fehlen sie, bleibt die Pose aus und der Watchdog
    pausiert nach etwa einer Sekunde den Fahrantrieb.
    """
    transport: str = 'can'  # can, shadow oder wifi
    wifi_url: str = 'http://192.168.178.20/api/telemetry'
    # Passwort gehoert in SENSOR_HUB_TELEMETRY_PASSWORD, nicht in die YAML.
    auth_username: str = ''
    auth_password: str = ''
    poll_interval_s: float = 0.2
    request_timeout_s: float = 1.5
    pause_timeout_s: float = 1.0
    # Require a genuinely stable return before restarting an autonomous plan.
    # A single successful HTTP response between outages must not start/stop
    # the vehicle repeatedly.
    resume_stable_s: float = 2.0
    telemetry_timeout_s: float = 30.0


@dataclass
class NavigationConfig:
    """Autonome Wegpunktnavigation (S1-Bearing-Hold).

    Pose-Daten kommen ueber den in ``SensorHubConfig`` gewaehlten Transport.
    """
    enabled: bool = True
    # Muss spaeter ausloesen als SensorHub.pause_timeout_s (1 s). Die
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
    track_cross_track_limit_m: float = 1.0
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
    track_heading_block_samples: int = 3
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
    mower: MowerConfig = field(default_factory=MowerConfig)
    odrive_mower: ODriveMowerConfig = field(default_factory=ODriveMowerConfig)
    can: CANConfig = field(default_factory=CANConfig)
    sensor_hub: SensorHubConfig = field(default_factory=SensorHubConfig)
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
            config.safety = SafetyConfig(**data['safety'])
        if 'light' in data:
            config.light = LightConfig(**data['light'])
        if 'mower' in data:
            config.mower = MowerConfig(**data['mower'])
        if 'odrive_mower' in data:
            odrive_data = dict(data['odrive_mower'])
            if 'node_ids' in odrive_data and odrive_data['node_ids'] is None:
                odrive_data['node_ids'] = []
            if 'usb_axes' in odrive_data and odrive_data['usb_axes'] is None:
                odrive_data['usb_axes'] = []
            config.odrive_mower = ODriveMowerConfig(**odrive_data)
        if 'can' in data:
            config.can = CANConfig(**data['can'])
        if 'sensor_hub' in data:
            config.sensor_hub = SensorHubConfig(**data['sensor_hub'])
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

        hub_password = os.getenv('SENSOR_HUB_TELEMETRY_PASSWORD')
        if hub_password:
            self.sensor_hub.auth_password = hub_password

        hub_user = os.getenv('SENSOR_HUB_TELEMETRY_USER')
        if hub_user:
            self.sensor_hub.auth_username = hub_user

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
                'can_watchdog_enabled': self.safety.can_watchdog_enabled,
                'can_watchdog_startup_grace_s': self.safety.can_watchdog_startup_grace_s,
                'can_watchdog_interval_s': self.safety.can_watchdog_interval_s
            },
            'light': {
                'enabled': self.light.enabled,
                'pin': self.light.pin
            },
            'mower': {
                'enabled': self.mower.enabled,
                'relay_pin': self.mower.relay_pin,
                'pwm_pin': self.mower.pwm_pin,
                'pwm_frequency': self.mower.pwm_frequency,
                'duty_min': self.mower.duty_min,
                'duty_max': self.mower.duty_max,
                'duty_off': self.mower.duty_off
            },
            'odrive_mower': {
                'enabled': self.odrive_mower.enabled,
                'transport': self.odrive_mower.transport,
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
            'can': {
                'enabled': self.can.enabled,
                'interface': self.can.interface,
                'bitrate': self.can.bitrate,
                'motor_controller_id': self.can.motor_controller_id,
                'sensor_hub_id': self.can.sensor_hub_id,
                'max_frame_size': self.can.max_frame_size,
                'frame_timeout': self.can.frame_timeout
            },
            'sensor_hub': {
                'transport': self.sensor_hub.transport,
                'wifi_url': self.sensor_hub.wifi_url,
                'auth_username': self.sensor_hub.auth_username,
                'poll_interval_s': self.sensor_hub.poll_interval_s,
                'request_timeout_s': self.sensor_hub.request_timeout_s,
                'pause_timeout_s': self.sensor_hub.pause_timeout_s,
                'telemetry_timeout_s': self.sensor_hub.telemetry_timeout_s
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
