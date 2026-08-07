#!/usr/bin/env python3
"""Raise the DC bus undervoltage trip level on an ODrive board.

The factory default of 20.0 V equals 2.5 V per cell on the 8S LiFePO4 packs,
which is exactly where their BMS opens the MOSFETs. The board would therefore
never fault before the pack cuts power to the whole vehicle. 22.5 V (2.81 V
per cell) leaves the ODrive room to fault cleanly first and costs almost no
usable capacity.

Run this with exactly one board connected by USB and both axes mechanically
safe. The script only writes bus configuration and requests IDLE; it never
starts a motor.
"""

import argparse
import math
import sys
import time

import odrive


AXIS_STATE_IDLE = 1

DEFAULT_TRIP_LEVEL_V = 22.5

# Below 2.5 V per cell the pack BMS cuts anyway, above 3.1 V per cell the trip
# would fire during normal mowing load sag.
MIN_TRIP_LEVEL_V = 20.0
MAX_TRIP_LEVEL_V = 25.0

# Setting a trip level at or above the present bus voltage faults the board
# immediately on the next reboot.
MIN_VBUS_HEADROOM_V = 1.0


def board_identity(board) -> str:
    return (
        f"serial=0x{int(board.serial_number):X}, "
        f"fw={int(board.fw_version_major)}.{int(board.fw_version_minor)}."
        f"{int(board.fw_version_revision)}, "
        f"hw={int(board.hw_version_major)}.{int(board.hw_version_minor)}."
        f"{int(board.hw_version_variant)}, "
        f"vbus={float(board.vbus_voltage):.2f} V"
    )


def require_idle(board) -> None:
    for index, axis in enumerate((board.axis0, board.axis1)):
        axis.controller.input_vel = 0.0
        axis.requested_state = AXIS_STATE_IDLE
        if int(axis.current_state) != AXIS_STATE_IDLE:
            raise RuntimeError(
                f"axis{index} is not IDLE: state={int(axis.current_state)}"
            )


def connect(expected_serial: int | None = None):
    print("Waiting for one ODrive over USB ...", flush=True)
    serial_filter = None if expected_serial is None else f"{expected_serial:012X}"
    board = odrive.find_any(serial_number=serial_filter, timeout=30)
    serial = int(board.serial_number)
    print(f"Found {board_identity(board)}", flush=True)
    if expected_serial is not None and serial != expected_serial:
        raise RuntimeError(
            f"Refusing wrong board: expected 0x{expected_serial:X}, got 0x{serial:X}"
        )
    return board


def require_vbus_headroom(board, level_v: float) -> None:
    vbus = float(board.vbus_voltage)
    if vbus < level_v + MIN_VBUS_HEADROOM_V:
        raise RuntimeError(
            f"vbus={vbus:.2f} V is too close to the requested trip level "
            f"{level_v:.2f} V; charge the pack before configuring"
        )


def verify(board, level_v: float) -> None:
    actual = float(board.config.dc_bus_undervoltage_trip_level)
    if not math.isclose(actual, level_v, rel_tol=1e-5, abs_tol=1e-3):
        raise RuntimeError(
            f"Undervoltage verification failed: trip level={actual:.3f} V, "
            f"expected {level_v:.3f} V"
        )
    require_idle(board)
    print(
        f"Verified board 0x{int(board.serial_number):X}: "
        f"undervoltage trip={level_v:.2f} V, both axes IDLE",
        flush=True,
    )


def save_configuration(board) -> None:
    print("Saving configuration; the board will reboot ...", flush=True)
    try:
        board.save_configuration()
    except Exception as exc:
        # Firmware 0.5.x reboots inside save_configuration, so the USB object
        # disappears before the call returns. Only the reconnect and verify
        # below can tell whether the write reached flash.
        print(f"Board disconnected during save (expected): {exc}", flush=True)


def apply(board, level_v: float) -> int:
    serial = int(board.serial_number)
    require_idle(board)
    require_vbus_headroom(board, level_v)
    previous = float(board.config.dc_bus_undervoltage_trip_level)
    board.config.dc_bus_undervoltage_trip_level = level_v
    print(f"Trip level {previous:.2f} V -> {level_v:.2f} V", flush=True)
    verify(board, level_v)
    save_configuration(board)
    return serial


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("apply", "verify"))
    parser.add_argument("--level", type=float, default=DEFAULT_TRIP_LEVEL_V)
    parser.add_argument("--serial", type=lambda value: int(value, 0))
    args = parser.parse_args()
    if not MIN_TRIP_LEVEL_V <= args.level <= MAX_TRIP_LEVEL_V:
        raise RuntimeError(
            f"level must be between {MIN_TRIP_LEVEL_V} and {MAX_TRIP_LEVEL_V} volts"
        )

    board = connect(args.serial)
    if args.mode == "verify":
        verify(board, args.level)
        return

    serial = apply(board, args.level)
    # Reboot plus USB re-enumeration; connect() then still waits up to 30 s.
    time.sleep(5.0)
    board = connect(serial)
    verify(board, args.level)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
