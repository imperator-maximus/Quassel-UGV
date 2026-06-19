#!/usr/bin/env python3
"""Small PC-side CAN test for an ODrive/ODESC V3.6 axis0.

Tested with a candleLight/gs_usb USB-CAN adapter on Windows and a legacy
ODrive V3.x SimpleCAN firmware at 250 kbit/s.

On Linux/Raspberry Pi, prefer SocketCAN with a candleLight/gs_usb adapter:

    sudo ip link set can0 up type can bitrate 250000
    python scripts/can_odrive_m0_test.py --interface socketcan --channel can0 --listen-only
"""

from __future__ import annotations

import argparse
import struct
import time

import can


CMD_HEARTBEAT = 0x001
CMD_SET_AXIS_STATE = 0x007
CMD_SET_INPUT_VEL = 0x00D
CMD_CLEAR_ERRORS = 0x018

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
        ),
        timeout=1.0,
    )
    print(f"tx node={node_id} Set_Axis_State state={state}")


def send_input_vel(bus: can.BusABC, node_id: int, velocity: float) -> None:
    bus.send(
        can.Message(
            arbitration_id=arbitration_id(node_id, CMD_SET_INPUT_VEL),
            data=struct.pack("<fhh", float(velocity), 0, 0),
            is_extended_id=False,
        ),
        timeout=1.0,
    )
    print(f"tx node={node_id} Set_Input_Vel vel={velocity}")


def send_clear_errors(bus: can.BusABC, node_id: int) -> None:
    bus.send(
        can.Message(
            arbitration_id=arbitration_id(node_id, CMD_CLEAR_ERRORS),
            data=b"",
            is_extended_id=False,
        ),
        timeout=1.0,
    )
    print(f"tx node={node_id} Clear_Errors")


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
    parser.add_argument(
        "--interface",
        default="gs_usb",
        choices=("gs_usb", "socketcan"),
        help="python-can interface; use socketcan on Linux/Raspberry Pi",
    )
    parser.add_argument(
        "--channel",
        default=None,
        help="CAN channel; default: 0 for gs_usb, can0 for socketcan",
    )
    parser.add_argument("--node", type=int, default=0, help="ODrive CAN node ID")
    parser.add_argument("--bitrate", type=int, default=250000, help="CAN bitrate")
    parser.add_argument("--velocity", type=float, default=12.0, help="turns/s")
    parser.add_argument("--duration", type=float, default=5.0, help="run time in seconds")
    parser.add_argument(
        "--coast-delay",
        type=float,
        default=1.0,
        help="seconds between velocity=0 and IDLE during stop",
    )
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
    parser.add_argument(
        "--clear-errors",
        action="store_true",
        help="send Clear_Errors before running or listening",
    )
    args = parser.parse_args()

    patch_gs_usb_backend()

    channel = args.channel
    if channel is None:
        channel = "can0" if args.interface == "socketcan" else 0

    bus_kwargs = {"interface": args.interface, "channel": channel}
    if args.interface != "socketcan":
        bus_kwargs["bitrate"] = args.bitrate
    bus = can.Bus(**bus_kwargs)
    print(f"CAN open: {args.interface} channel={channel} bitrate={args.bitrate}")

    if args.listen_only:
        try:
            if args.clear_errors:
                send_clear_errors(bus, args.node)
            listen(bus, args.duration)
        finally:
            bus.shutdown()
            print("CAN closed")
        return 0

    run_started = False
    try:
        print("Pre-run heartbeat check")
        if args.clear_errors:
            send_clear_errors(bus, args.node)
            time.sleep(0.2)
        listen(bus, 1.0)

        target_state = AXIS_STATE_STARTUP_SEQUENCE if args.startup_sequence else args.state
        send_input_vel(bus, args.node, args.velocity)
        send_axis_state(bus, args.node, target_state)
        run_started = True
        listen(bus, args.duration)
    except can.CanError as exc:
        print(f"CAN send/receive error: {exc}")
    finally:
        print("Stopping axis")
        try:
            if run_started:
                send_input_vel(bus, args.node, 0.0)
                if args.coast_delay > 0:
                    print(f"Waiting {args.coast_delay:.2f}s before IDLE")
                    listen(bus, args.coast_delay)
                send_axis_state(bus, args.node, AXIS_STATE_IDLE)
                listen(bus, 1.0)
            else:
                print("Run did not start; skipping CAN stop commands")
        except can.CanError as exc:
            print(f"Stop command failed: {exc}")
        finally:
            bus.shutdown()
            print("CAN closed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
