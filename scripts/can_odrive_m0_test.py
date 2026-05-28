#!/usr/bin/env python3
"""Small PC-side CAN test for an ODrive/ODESC V3.6 axis0.

Tested with a candleLight/gs_usb USB-CAN adapter on Windows and a legacy
ODrive V3.x SimpleCAN firmware at 250 kbit/s.
"""

from __future__ import annotations

import argparse
import struct
import time

import can


CMD_HEARTBEAT = 0x001
CMD_SET_AXIS_STATE = 0x007
CMD_SET_INPUT_VEL = 0x00D

AXIS_STATE_IDLE = 1
AXIS_STATE_STARTUP_SEQUENCE = 2
# This legacy clone reports sensorless operation as state 5. It is not named in
# odrive.enums 0.5.4, but it was verified on the bus with this controller.
AXIS_STATE_SENSORLESS_LEGACY = 5


def patch_gs_usb_backend() -> None:
    """Make python-can's gs_usb backend find libusb on this Windows setup."""
    try:
        import libusb_package
        import usb.backend.libusb1 as libusb1
    except ImportError:
        return

    backend = libusb_package.get_libusb1_backend()
    libusb1.get_backend = lambda *args, **kwargs: backend


def arbitration_id(node_id: int, command_id: int) -> int:
    return (node_id << 5) | command_id


def send_axis_state(bus: can.BusABC, node_id: int, state: int) -> None:
    bus.send(
        can.Message(
            arbitration_id=arbitration_id(node_id, CMD_SET_AXIS_STATE),
            data=struct.pack("<I", state),
            is_extended_id=False,
        )
    )
    print(f"tx node={node_id} Set_Axis_State state={state}")


def send_input_vel(bus: can.BusABC, node_id: int, velocity: float) -> None:
    bus.send(
        can.Message(
            arbitration_id=arbitration_id(node_id, CMD_SET_INPUT_VEL),
            data=struct.pack("<fhh", float(velocity), 0, 0),
            is_extended_id=False,
        )
    )
    print(f"tx node={node_id} Set_Input_Vel vel={velocity}")


def decode_message(msg: can.Message) -> str:
    node_id = msg.arbitration_id >> 5
    command_id = msg.arbitration_id & 0x1F

    if command_id == CMD_HEARTBEAT and msg.dlc >= 8:
        axis_error, axis_state = struct.unpack("<II", msg.data[:8])
        return (
            f"heartbeat node={node_id} error=0x{axis_error:08X} "
            f"state={axis_state}"
        )

    return (
        f"rx id=0x{msg.arbitration_id:03X} node={node_id} "
        f"cmd=0x{command_id:02X} dlc={msg.dlc} data={msg.data.hex(' ')}"
    )


def listen(bus: can.BusABC, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        msg = bus.recv(timeout=0.2)
        if msg is not None:
            print(decode_message(msg))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=int, default=0, help="ODrive CAN node ID")
    parser.add_argument("--bitrate", type=int, default=250000, help="CAN bitrate")
    parser.add_argument("--velocity", type=float, default=12.0, help="turns/s")
    parser.add_argument("--duration", type=float, default=5.0, help="run time in seconds")
    parser.add_argument(
        "--state",
        type=int,
        default=AXIS_STATE_SENSORLESS_LEGACY,
        help="axis state to enter; default 5 = legacy sensorless",
    )
    parser.add_argument(
        "--startup-sequence",
        action="store_true",
        help="send STARTUP_SEQUENCE=2 instead of legacy sensorless state 5",
    )
    parser.add_argument(
        "--listen-only",
        action="store_true",
        help="only print received CAN frames",
    )
    args = parser.parse_args()

    patch_gs_usb_backend()

    bus = can.Bus(interface="gs_usb", channel=0, bitrate=args.bitrate)
    print(f"CAN open: gs_usb channel=0 bitrate={args.bitrate}")

    if args.listen_only:
        try:
            listen(bus, args.duration)
        finally:
            bus.shutdown()
            print("CAN closed")
        return 0

    try:
        print("Pre-run heartbeat check")
        listen(bus, 1.0)

        target_state = AXIS_STATE_STARTUP_SEQUENCE if args.startup_sequence else args.state
        send_input_vel(bus, args.node, args.velocity)
        send_axis_state(bus, args.node, target_state)
        listen(bus, args.duration)
    finally:
        print("Stopping axis")
        try:
            send_input_vel(bus, args.node, 0.0)
            time.sleep(0.1)
            send_axis_state(bus, args.node, AXIS_STATE_IDLE)
            listen(bus, 1.0)
        finally:
            bus.shutdown()
            print("CAN closed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
