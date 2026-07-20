#!/usr/bin/env python3
"""
Quassel UGV Motor Controller - Configuration
Zentrale Konfigurationsverwaltung mit YAML-Support
"""

import yaml
import os
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
    """ODrive/ODESC-Mähdeck-Teststand über CAN."""
    enabled: bool = False
    node_id: int = 0
    node_ids: List[int] = field(default_factory=list)
    axis_state: int = 5
    min_rpm: int = 300
    max_rpm: int = 1200
    default_rpm: int = 300
    ramp_rate_rpm_s: int = 300
    command_interval_s: float = 0.1
    coast_delay_s: float = 0.5
    start_stagger_s: float = 0.3
    heartbeat_timeout_s: float = 1.0
    current_monitor_enabled: bool = True
    current_poll_interval_s: float = 0.1
    current_response_timeout_s: float = 0.75
    current_startup_grace_s: float = 2.0
    current_trip_a: float = 25.0
    current_trip_duration_s: float = 0.5
    current_critical_trip_a: float = 29.0
    current_critical_trip_duration_s: float = 0.1


@dataclass
class CANConfig:
    """CAN-Bus-Konfiguration"""
    interface: str = 'can0'
    bitrate: int = 250000
    motor_controller_id: int = 0x200
    sensor_hub_id: int = 0x100
    max_frame_size: int = 6  # Bytes Nutzdaten pro Frame
    frame_timeout: float = 1.0  # Sekunden


@dataclass
class NavigationConfig:
    """Autonome Wegpunktnavigation (S1-Bearing-Hold).

    Pose-Daten kommen ausschließlich über den CAN-Telemetrie-Stream vom
    Sensor-Hub. Kein HTTP-Polling, keine Sensor-Hub-URL erforderlich.
    """
    enabled: bool = True
    watchdog_timeout_s: float = 1.0
    geofence_radius_m: float = 50.0
    max_joystick: float = 0.30
    acceptance_radius_m: float = 0.25
    slowdown_radius_m: float = 0.5
    turn_kp: float = 0.02
    track_lookahead_m: float = 0.8
    # Innen-Rad-Garantie gegen reine Pivots: untere Schranke der Vorwärts-
    # Geschwindigkeit des inneren (kurveninneren) Skid-Rads, ausgedrückt
    # als Bruchteil von ``max_joystick``. 0.0 = legacy (Pivot erlaubt),
    # 0.50 = inneres Rad rollt mit mind. 50% des max. Joystick-Levels →
    # PWM-Offset typisch 75 μs über Neutral, sicher außerhalb der ESC-
    # Totzone (~±50 μs). Fahrzeug fährt einen mittleren Bogen statt zu
    # pivotieren, schont Rasen. Skaliert in der Slowdown-Zone proportional
    # mit ``distance_factor``.
    min_inner_wheel_speed: float = 0.50


@dataclass
class MappingConfig:
    """Drive-around Kartierung und GeoJSON-Speicher."""
    enabled: bool = True
    maps_dir: str = '/home/nicolay/raspberrycan/maps'
    min_point_distance_m: float = 0.25


@dataclass
class WebConfig:
    """Web-Interface-Konfiguration"""
    enabled: bool = False
    host: str = '0.0.0.0'
    port: int = 80
    secret_key: str = 'ugv_motor_controller_2024'
    template_folder: str = 'templates'
    static_folder: str = 'static'
    max_speed_percent: float = 100.0


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
    navigation: NavigationConfig = field(default_factory=NavigationConfig)
    mapping: MappingConfig = field(default_factory=MappingConfig)
    web: WebConfig = field(default_factory=WebConfig)
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
            config.odrive_mower = ODriveMowerConfig(**odrive_data)
        if 'can' in data:
            config.can = CANConfig(**data['can'])
        if 'navigation' in data:
            config.navigation = NavigationConfig(**data['navigation'])
        if 'mapping' in data:
            config.mapping = MappingConfig(**data['mapping'])
        if 'web' in data:
            config.web = WebConfig(**data['web'])
        if 'logging' in data:
            config.logging = LoggingConfig(**data['logging'])
        
        config.quiet = data.get('quiet', False)
        config.monitor = data.get('monitor', True)
        
        return config
    
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
                'node_id': self.odrive_mower.node_id,
                'node_ids': self.odrive_mower.node_ids,
                'axis_state': self.odrive_mower.axis_state,
                'min_rpm': self.odrive_mower.min_rpm,
                'max_rpm': self.odrive_mower.max_rpm,
                'default_rpm': self.odrive_mower.default_rpm,
                'ramp_rate_rpm_s': self.odrive_mower.ramp_rate_rpm_s,
                'command_interval_s': self.odrive_mower.command_interval_s,
                'coast_delay_s': self.odrive_mower.coast_delay_s,
                'start_stagger_s': self.odrive_mower.start_stagger_s,
                'heartbeat_timeout_s': self.odrive_mower.heartbeat_timeout_s,
                'current_monitor_enabled': self.odrive_mower.current_monitor_enabled,
                'current_poll_interval_s': self.odrive_mower.current_poll_interval_s,
                'current_response_timeout_s': self.odrive_mower.current_response_timeout_s,
                'current_startup_grace_s': self.odrive_mower.current_startup_grace_s,
                'current_trip_a': self.odrive_mower.current_trip_a,
                'current_trip_duration_s': self.odrive_mower.current_trip_duration_s,
                'current_critical_trip_a': self.odrive_mower.current_critical_trip_a,
                'current_critical_trip_duration_s': self.odrive_mower.current_critical_trip_duration_s
            },
            'can': {
                'interface': self.can.interface,
                'bitrate': self.can.bitrate,
                'motor_controller_id': self.can.motor_controller_id,
                'sensor_hub_id': self.can.sensor_hub_id,
                'max_frame_size': self.can.max_frame_size,
                'frame_timeout': self.can.frame_timeout
            },
            'navigation': {
                'enabled': self.navigation.enabled,
                'watchdog_timeout_s': self.navigation.watchdog_timeout_s,
                'geofence_radius_m': self.navigation.geofence_radius_m,
                'max_joystick': self.navigation.max_joystick,
                'acceptance_radius_m': self.navigation.acceptance_radius_m,
                'slowdown_radius_m': self.navigation.slowdown_radius_m,
                'turn_kp': self.navigation.turn_kp,
                'track_lookahead_m': self.navigation.track_lookahead_m,
                'min_inner_wheel_speed': self.navigation.min_inner_wheel_speed
            },
            'mapping': {
                'enabled': self.mapping.enabled,
                'maps_dir': self.mapping.maps_dir,
                'min_point_distance_m': self.mapping.min_point_distance_m
            },
            'web': {
                'enabled': self.web.enabled,
                'host': self.web.host,
                'port': self.web.port,
                'secret_key': self.web.secret_key,
                'template_folder': self.web.template_folder,
                'static_folder': self.web.static_folder,
                'max_speed_percent': self.web.max_speed_percent
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
        return cls()
