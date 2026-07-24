#!/usr/bin/env python3
"""Enable the local 1.0 s command watchdog on selected ODrive CAN nodes.

Run this with exactly one dual-axis ODrive connected by USB and both mower
axes mechanically safe. The script only writes watchdog configuration and
requests IDLE; it never starts a motor.
"""

import argparse
import math
import sys
import time

import odrive


AXIS_STATE_IDLE = 1


def parse_nodes(value: str) -> set[int]:
    try:
        nodes = {int(item.strip(), 0) for item in value.split(',') if item.strip()}
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not nodes:
        raise argparse.ArgumentTypeError("at least one node ID is required")
    return nodes


def board_identity(board) -> str:
    return (
        f"serial=0x{int(board.serial_number):X}, "
        f"fw={int(board.fw_version_major)}.{int(board.fw_version_minor)}."
        f"{int(board.fw_version_revision)}, "
        f"hw={int(board.hw_version_major)}.{int(board.hw_version_minor)}."
        f"{int(board.hw_version_variant)}"
    )


def require_idle(axis, index: int) -> None:
    axis.controller.input_vel = 0.0
    axis.requested_state = AXIS_STATE_IDLE
    if int(axis.current_state) != AXIS_STATE_IDLE:
        raise RuntimeError(f"axis{index} is not IDLE: state={int(axis.current_state)}")


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


def selected_axes(board, nodes: set[int]):
    matches = []
    discovered = []
    for index, axis in enumerate((board.axis0, board.axis1)):
        try:
            node_id = int(axis.config.can.node_id)
        except AttributeError:
            # Older unreleased v3.x firmware exposes the legacy flat field.
            node_id = int(axis.config.can_node_id)
        discovered.append(node_id)
        if node_id in nodes:
            matches.append((index, node_id, axis))
    missing = nodes - set(discovered)
    if missing:
        raise RuntimeError(
            f"Requested nodes {sorted(missing)} are not on this board; found {discovered}"
        )
    return matches


def verify(board, nodes: set[int], timeout_s: float) -> None:
    matches = selected_axes(board, nodes)
    failures = []
    for index, node_id, axis in matches:
        require_idle(axis, index)
        if not bool(axis.config.enable_watchdog):
            failures.append(f"node {node_id}: watchdog disabled")
        if not math.isclose(
            float(axis.config.watchdog_timeout), timeout_s, rel_tol=1e-5, abs_tol=1e-5
        ):
            failures.append(
                f"node {node_id}: timeout={float(axis.config.watchdog_timeout):.3f} s"
            )
    if failures:
        raise RuntimeError("Watchdog verification failed: " + "; ".join(failures))
    print(
        f"Verified nodes {sorted(nodes)}: watchdog enabled, timeout={timeout_s:.3f} s, IDLE",
        flush=True,
    )


def apply(board, nodes: set[int], timeout_s: float) -> int:
    serial = int(board.serial_number)
    matches = selected_axes(board, nodes)
    for index, node_id, axis in matches:
        require_idle(axis, index)
        axis.config.watchdog_timeout = timeout_s
        axis.config.enable_watchdog = True
        print(f"Configured node {node_id} (axis{index})", flush=True)
    verify(board, nodes, timeout_s)
    print("Saving configuration; the board will reboot ...", flush=True)
    board.save_configuration()
    return serial


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("apply", "verify"))
    parser.add_argument("--nodes", required=True, type=parse_nodes, help="e.g. 0,1 or 2")
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--serial", type=lambda value: int(value, 0))
    args = parser.parse_args()
    if not 0.2 <= args.timeout <= 5.0:
        raise RuntimeError("timeout must be between 0.2 and 5.0 seconds")

    board = connect(args.serial)
    if args.mode == "verify":
        verify(board, args.nodes, args.timeout)
        return

    serial = apply(board, args.nodes, args.timeout)
    time.sleep(3.0)
    board = connect(serial)
    verify(board, args.nodes, args.timeout)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
