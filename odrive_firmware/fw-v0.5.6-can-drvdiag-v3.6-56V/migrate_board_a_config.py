#!/usr/bin/env python3
"""Apply and verify the known-safe UGV configuration for ODrive Board A.

This script is intentionally specific to the v3.6-56V board with USB serial
0x386132523135. It never requests a motor state other than IDLE.
"""

import argparse
import math
import sys

import odrive


EXPECTED_SERIAL = 0x386132523135
EXPECTED_FW = (0, 5, 6)
EXPECTED_HW = (3, 6, 56)


def connect():
    print("Waiting for ODrive Board A over USB ...", flush=True)
    board = odrive.find_any(timeout=30)
    serial = int(board.serial_number)
    firmware = (
        int(board.fw_version_major),
        int(board.fw_version_minor),
        int(board.fw_version_revision),
    )
    hardware = (
        int(board.hw_version_major),
        int(board.hw_version_minor),
        int(board.hw_version_variant),
    )
    print(
        f"Found serial=0x{serial:X}, firmware={firmware}, hardware={hardware}",
        flush=True,
    )
    if serial != EXPECTED_SERIAL:
        raise RuntimeError(
            f"Refusing wrong board: expected 0x{EXPECTED_SERIAL:X}, got 0x{serial:X}"
        )
    if firmware != EXPECTED_FW:
        raise RuntimeError(f"Expected firmware {EXPECTED_FW}, got {firmware}")
    if hardware != EXPECTED_HW:
        raise RuntimeError(f"Expected hardware {EXPECTED_HW}, got {hardware}")
    return board


def require_idle(board):
    for index, axis in enumerate((board.axis0, board.axis1)):
        axis.controller.input_vel = 0.0
        axis.requested_state = 1  # AXIS_STATE_IDLE
        if int(axis.current_state) != 1:
            raise RuntimeError(f"axis{index} is not IDLE: state={int(axis.current_state)}")


def set_lockin(lockin, *, current, ramp_time, ramp_distance, accel, vel,
               finish_distance=None, finish_on_vel=None,
               finish_on_distance=None, finish_on_enc_idx=None):
    lockin.current = current
    lockin.ramp_time = ramp_time
    lockin.ramp_distance = ramp_distance
    lockin.accel = accel
    lockin.vel = vel
    if finish_distance is not None:
        lockin.finish_distance = finish_distance
    if finish_on_vel is not None:
        lockin.finish_on_vel = finish_on_vel
    if finish_on_distance is not None:
        lockin.finish_on_distance = finish_on_distance
    if finish_on_enc_idx is not None:
        lockin.finish_on_enc_idx = finish_on_enc_idx


def configure_axis(axis, node_id, phase_resistance, phase_inductance):
    cfg = axis.config

    # No autonomous movement at boot.
    cfg.startup_motor_calibration = False
    cfg.startup_encoder_index_search = False
    cfg.startup_encoder_offset_calibration = False
    cfg.startup_closed_loop_control = False
    cfg.startup_homing = False
    cfg.enable_step_dir = False
    cfg.step_dir_always_on = False
    # Set_Input_Vel is refreshed by the Raspberry Pi every 100 ms. If CAN or
    # the host dies, the axis must disarm locally because an IDLE frame can no
    # longer reach the board.
    cfg.watchdog_timeout = 1.0
    cfg.enable_watchdog = True
    cfg.enable_sensorless_mode = True

    cfg.can.node_id = node_id
    cfg.can.is_extended = False
    cfg.can.heartbeat_rate_ms = 100
    cfg.can.encoder_rate_ms = 0
    cfg.can.motor_error_rate_ms = 0
    cfg.can.encoder_error_rate_ms = 0
    cfg.can.controller_error_rate_ms = 0
    cfg.can.sensorless_error_rate_ms = 0
    cfg.can.encoder_count_rate_ms = 0
    cfg.can.iq_rate_ms = 0
    cfg.can.sensorless_rate_ms = 0
    cfg.can.bus_vi_rate_ms = 0

    set_lockin(
        cfg.calibration_lockin,
        current=10.0,
        ramp_time=0.4,
        ramp_distance=math.pi,
        accel=20.0,
        vel=40.0,
    )
    set_lockin(
        cfg.general_lockin,
        current=10.0,
        ramp_time=0.4,
        ramp_distance=math.pi,
        accel=20.0,
        vel=40.0,
        finish_distance=100.0,
        finish_on_vel=False,
        finish_on_distance=False,
        finish_on_enc_idx=False,
    )
    set_lockin(
        cfg.sensorless_ramp,
        current=10.0,
        ramp_time=1.0,
        ramp_distance=10.0,
        accel=50.0,
        vel=30.0,
        finish_distance=10.0,
        finish_on_vel=True,
        finish_on_distance=True,
        finish_on_enc_idx=False,
    )

    motor = axis.motor.config
    # Set calibration results before marking the motor pre-calibrated.
    motor.pre_calibrated = False
    motor.motor_type = 0
    motor.pole_pairs = 7
    motor.calibration_current = 5.0
    motor.resistance_calib_max_voltage = 4.0
    motor.phase_resistance = phase_resistance
    motor.phase_inductance = phase_inductance
    motor.torque_constant = 0.04
    motor.current_lim = 30.0
    motor.current_lim_margin = 8.0
    motor.requested_current_range = 60.0
    motor.current_control_bandwidth = 100.0
    motor.inverter_temp_limit_lower = 100.0
    motor.inverter_temp_limit_upper = 120.0
    motor.pre_calibrated = True

    axis.motor.fet_thermistor.config.enabled = True
    axis.motor.fet_thermistor.config.temp_limit_lower = 100.0
    axis.motor.fet_thermistor.config.temp_limit_upper = 120.0
    axis.motor.motor_thermistor.config.enabled = False

    encoder = axis.encoder.config
    encoder.mode = 0
    encoder.use_index = False
    encoder.find_idx_on_lockin_only = False
    encoder.cpr = 42
    encoder.phase_offset = 0
    encoder.phase_offset_float = 0.0
    encoder.direction = 0
    encoder.pre_calibrated = False
    encoder.enable_phase_interpolation = True
    encoder.bandwidth = 100.0
    encoder.calib_range = 0.05
    encoder.calib_scan_distance = 150.0
    encoder.calib_scan_omega = 6.283
    encoder.ignore_illegal_hall_state = False

    estimator = axis.sensorless_estimator.config
    estimator.observer_gain = 1000.0
    estimator.pll_bandwidth = 1000.0
    estimator.pm_flux_linkage = 0.002386

    controller = axis.controller.config
    controller.control_mode = 2
    controller.input_mode = 1
    controller.enable_vel_limit = True
    controller.enable_torque_mode_vel_limit = True
    controller.enable_gain_scheduling = False
    controller.enable_overspeed_error = True
    controller.pos_gain = 20.0
    controller.vel_gain = 0.005
    controller.vel_integrator_gain = 0.03
    controller.vel_limit = 120.0
    controller.vel_limit_tolerance = 1.2
    controller.vel_ramp_rate = 1.0
    controller.torque_ramp_rate = 0.01
    controller.input_filter_bandwidth = 2.0
    controller.inertia = 0.0


def apply_configuration(board):
    require_idle(board)

    board.config.enable_can_a = True
    board.config.enable_i2c_a = False
    board.config.enable_uart_a = True
    board.config.uart_a_baudrate = 115200
    board.can.config.baud_rate = 250000
    # fw-v0.5.6 changed this from the legacy enum value 0 to a bit flag.
    board.can.config.protocol = 1  # PROTOCOL_SIMPLE

    board.config.enable_brake_resistor = False
    board.config.brake_resistance = 0.0
    board.config.dc_bus_overvoltage_trip_level = 32.0
    board.config.dc_bus_undervoltage_trip_level = 20.0
    board.config.enable_dc_bus_overvoltage_ramp = False
    board.config.max_regen_current = 0.0
    board.config.dc_max_negative_current = -2.0
    board.config.dc_max_positive_current = 40.0

    configure_axis(board.axis0, 0, 0.05119955539703369, 1.4818512681813445e-05)
    configure_axis(board.axis1, 1, 0.053092747926712036, 1.473599058954278e-05)

    require_idle(board)
    verify_configuration(board, require_clean_errors=False)
    print("Configuration is valid in RAM. Saving and rebooting Board A ...", flush=True)
    success = board.save_configuration()
    if success is False:
        raise RuntimeError("ODrive rejected save_configuration()")


def close(actual, expected, tolerance=1e-5):
    return math.isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance)


def verify_configuration(board, require_clean_errors=True):
    require_idle(board)
    checks = [
        (bool(board.config.enable_can_a), True, "CAN enabled"),
        (bool(board.config.enable_i2c_a), False, "I2C disabled"),
        (int(board.can.config.baud_rate), 250000, "CAN bitrate"),
        (int(board.can.config.protocol), 1, "CANSimple protocol"),
        (bool(board.config.enable_brake_resistor), False, "brake resistor disabled"),
    ]
    failures = []
    for actual, expected, label in checks:
        if actual != expected:
            failures.append(f"{label}: expected {expected!r}, got {actual!r}")

    expected_phases = (
        (0, 0.05119955539703369, 1.4818512681813445e-05),
        (1, 0.053092747926712036, 1.473599058954278e-05),
    )
    for index, (node_id, resistance, inductance) in enumerate(expected_phases):
        axis = (board.axis0, board.axis1)[index]
        axis_checks = [
            (int(axis.current_state) == 1, f"axis{index} IDLE"),
            (int(axis.config.can.node_id) == node_id, f"axis{index} node ID"),
            (int(axis.config.can.heartbeat_rate_ms) == 100, f"axis{index} heartbeat"),
            (bool(axis.config.enable_watchdog), f"axis{index} watchdog enabled"),
            (close(axis.config.watchdog_timeout, 1.0), f"axis{index} watchdog timeout"),
            (bool(axis.config.enable_sensorless_mode), f"axis{index} sensorless enabled"),
            (not bool(axis.config.startup_motor_calibration), f"axis{index} no startup calibration"),
            (not bool(axis.config.startup_closed_loop_control), f"axis{index} no startup closed loop"),
            (bool(axis.motor.config.pre_calibrated), f"axis{index} motor pre-calibrated"),
            (close(axis.motor.config.phase_resistance, resistance), f"axis{index} phase resistance"),
            (close(axis.motor.config.phase_inductance, inductance), f"axis{index} phase inductance"),
            (close(axis.motor.config.current_lim, 30.0), f"axis{index} current limit"),
            (close(axis.controller.config.vel_limit, 120.0), f"axis{index} velocity limit"),
        ]
        if require_clean_errors:
            axis_checks.extend(
                [
                    (int(axis.error) == 0, f"axis{index} axis error=0"),
                    (int(axis.motor.error) == 0, f"axis{index} motor error=0"),
                ]
            )
        failures.extend(label for passed, label in axis_checks if not passed)

    if failures:
        raise RuntimeError("Configuration verification failed:\n  - " + "\n  - ".join(failures))

    print(
        f"Verified: Vbus={float(board.vbus_voltage):.2f} V, CAN=250000, "
        "nodes=0/1, both axes IDLE, sensorless enabled, startup movement disabled",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("erase", "apply", "verify"))
    args = parser.parse_args()
    board = connect()
    if args.mode == "erase":
        require_idle(board)
        print("Erasing configuration and rebooting to fw-v0.5.6 defaults ...", flush=True)
        board.erase_configuration()
    elif args.mode == "apply":
        apply_configuration(board)
    else:
        verify_configuration(board)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
