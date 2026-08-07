#!/usr/bin/env python3
"""Set the DC bus positive current limit on an ODrive board.

An unmigrated board carries the factory default of INFINITY, which lets it
draw whatever the packs deliver. Two 24 V LiFePO4 packs in parallel are capped
by their BMS at 50 A each; if one BMS opens, the remaining pack sees the whole
load and trips as well. A finite per-board limit keeps that single-pack case
survivable.

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

# Board B drives a single mower axis whose phase limit is 30 A and whose
# software trip fires at 25 A, so 30 A DC is generous for that axis while
# still bounding the draw.
DEFAULT_LIMIT_A = 30.0

# Below 5 A even a single axis cannot start; above 100 A the pair of 50 A BMS
# units is the binding limit anyway, so a larger value protects nothing.
MIN_LIMIT_A = 5.0
MAX_LIMIT_A = 100.0


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


def verify(board, limit_a: float) -> None:
    actual = float(board.config.dc_max_positive_current)
    if not math.isclose(actual, limit_a, rel_tol=1e-5, abs_tol=1e-3):
        raise RuntimeError(
            f"DC current limit verification failed: limit={actual:.3f} A, "
            f"expected {limit_a:.3f} A"
        )
    require_idle(board)
    print(
        f"Verified board 0x{int(board.serial_number):X}: "
        f"dc_max_positive_current={limit_a:.2f} A, both axes IDLE",
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


def apply(board, limit_a: float) -> int:
    serial = int(board.serial_number)
    require_idle(board)
    previous = float(board.config.dc_max_positive_current)
    board.config.dc_max_positive_current = limit_a
    print(f"DC current limit {previous:.2f} A -> {limit_a:.2f} A", flush=True)
    verify(board, limit_a)
    save_configuration(board)
    return serial


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("apply", "verify"))
    parser.add_argument("--limit", type=float, default=DEFAULT_LIMIT_A)
    parser.add_argument("--serial", type=lambda value: int(value, 0))
    args = parser.parse_args()
    if not MIN_LIMIT_A <= args.limit <= MAX_LIMIT_A:
        raise RuntimeError(
            f"limit must be between {MIN_LIMIT_A} and {MAX_LIMIT_A} amperes"
        )

    board = connect(args.serial)
    if args.mode == "verify":
        verify(board, args.limit)
        return

    serial = apply(board, args.limit)
    # Reboot plus USB re-enumeration; connect() then still waits up to 30 s.
    time.sleep(5.0)
    board = connect(serial)
    verify(board, args.limit)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
