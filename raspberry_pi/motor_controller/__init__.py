#!/usr/bin/env python3
"""
Quassel UGV Motor Controller Package
Modulare Architektur für PWM-Motorsteuerung mit CAN-Bus und Web-Interface
"""

__version__ = '2.0.0'
__author__ = 'Quassel UGV Team'

from .config import Config
from .hardware.gpio_controller import GPIOController
from .hardware.pwm_controller import PWMController
from .hardware.safety_monitor import SafetyMonitor
from .communication.can_handler import CANHandler
from .control.motor_control import MotorControl
from .web.web_server import WebServer

__all__ = [
    'Config',
    'GPIOController',
    'PWMController',
    'SafetyMonitor',
    'CANHandler',
    'MotorControl',
    'WebServer'
]

