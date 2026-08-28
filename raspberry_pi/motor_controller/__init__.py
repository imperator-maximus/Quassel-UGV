#!/usr/bin/env python3
"""
Quassel UGV Motor Controller Package
Modulare Architektur für PWM-Motorsteuerung mit lokaler GNSS-Pose und Web-Interface
"""

__version__ = '2.0.0'
__author__ = 'Quassel UGV Team'

from .config import Config
from .hardware.gpio_controller import GPIOController
from .hardware.pwm_controller import PWMController
from .hardware.safety_monitor import SafetyMonitor
from .control.motor_control import MotorControl
from .web.web_server import WebServer

# Der Pose-Zwischenspeicher steht bewusst nicht hier: ``sensors`` zieht beim
# Import die GNSS-Kette und damit pyserial nach. Wer ihn braucht, holt ihn
# ueber ``motor_controller.sensors.pose_cache``.

__all__ = [
    'Config',
    'GPIOController',
    'PWMController',
    'SafetyMonitor',
    'MotorControl',
    'WebServer'
]
