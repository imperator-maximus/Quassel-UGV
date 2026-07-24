#!/usr/bin/env python3
"""Run one ODrive mower axis briefly while observing CAN health."""

import argparse
import json
import struct
import time

import can


CMD_HEARTBEAT = 0x01
CMD_SET_AXIS_STATE = 0x07
CMD_SET_INPUT_VEL = 0x0D
CMD_GET_IQ = 0x14
CMD_GET_SENSORLESS_ESTIMATES = 0x15
CMD_GET_BUS_VOLTAGE_CURRENT = 0x17
CMD_CLEAR_ERRORS = 0x18
CMD_GET_DRV_FAULT = 0x1E

AXIS_STATE_IDLE = 1
AXIS_STATE_CLOSED_LOOP_SENSORLESS = 5


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("node", type=int)
    parser.add_argument("--rpm", type=float, default=500.0)
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--interface", default="can0")
    parser.add_argument("--sensor-id", type=lambda value: int(value, 0), default=None)
    parser.add_argument("--current-limit", type=float, default=15.0)
    args = parser.parse_args()

    bus = can.Bus(interface="socketcan", channel=args.interface)
    node = args.node
    result = {
        "node": node,
        "rpm": args.rpm,
        "max_abs_iq_a": 0.0,
        "max_abs_sensorless_rpm": 0.0,
        "last_sensorless_rpm": None,
        "min_vbus_v": None,
        "max_vbus_v": None,
        "last_ibus_a": None,
        "drv_fault": None,
        "fet_temperature_c": None,
        "samples": 0,
        "heartbeat_error": 0,
        "states": [],
        "sensor_seen": args.sensor_id is None,
        "error_frames": 0,
        "stop_reason": "duration",
    }

    def send(command: int, data: bytes = b"", *, remote: bool = False) -> None:
        bus.send(
            can.Message(
                arbitration_id=(node << 5) | command,
                data=data,
                is_extended_id=False,
                is_remote_frame=remote,
                dlc=8 if remote else len(data),
            ),
            timeout=0.25,
        )

    started = time.monotonic()
    last_sensor = started
    last_heartbeat = started
    try:
        send(CMD_CLEAR_ERRORS)
        time.sleep(0.2)
        velocity = struct.pack("<fhh", args.rpm / 60.0, 0, 0)
        send(CMD_SET_INPUT_VEL, velocity)
        send(CMD_SET_AXIS_STATE, struct.pack("<I", AXIS_STATE_CLOSED_LOOP_SENSORLESS))
        started = time.monotonic()
        last_sensor = started
        last_heartbeat = started
        next_tx = started

        while time.monotonic() - started < args.duration:
            now = time.monotonic()
            if now >= next_tx:
                send(CMD_SET_INPUT_VEL, velocity)
                send(CMD_GET_IQ, remote=True)
                send(CMD_GET_SENSORLESS_ESTIMATES, remote=True)
                send(CMD_GET_BUS_VOLTAGE_CURRENT, remote=True)
                if node in (0, 1):
                    send(CMD_GET_DRV_FAULT, remote=True)
                next_tx = now + 0.1

            message = bus.recv(timeout=0.02)
            if message is not None:
                if message.is_error_frame:
                    result["error_frames"] += 1
                elif message.arbitration_id == args.sensor_id:
                    last_sensor = time.monotonic()
                    result["sensor_seen"] = True
                elif (
                    message.arbitration_id == ((node << 5) | CMD_HEARTBEAT)
                    and len(message.data) >= 5
                ):
                    error = struct.unpack_from("<I", message.data, 0)[0]
                    state = message.data[4]
                    last_heartbeat = time.monotonic()
                    result["heartbeat_error"] = error
                    if state not in result["states"]:
                        result["states"].append(state)
                    if error:
                        result["stop_reason"] = "heartbeat_error"
                        break
                elif (
                    message.arbitration_id == ((node << 5) | CMD_GET_IQ)
                    and len(message.data) >= 8
                ):
                    _, measured = struct.unpack("<ff", bytes(message.data[:8]))
                    result["samples"] += 1
                    result["last_iq_a"] = round(measured, 3)
                    result["max_abs_iq_a"] = max(
                        result["max_abs_iq_a"], abs(measured)
                    )
                    if abs(measured) >= args.current_limit:
                        result["stop_reason"] = "overcurrent"
                        break
                elif (
                    message.arbitration_id
                    == ((node << 5) | CMD_GET_SENSORLESS_ESTIMATES)
                    and len(message.data) >= 8
                ):
                    _, velocity_tps = struct.unpack("<ff", bytes(message.data[:8]))
                    velocity_rpm = velocity_tps * 60.0
                    result["last_sensorless_rpm"] = round(velocity_rpm, 2)
                    result["max_abs_sensorless_rpm"] = max(
                        result["max_abs_sensorless_rpm"], abs(velocity_rpm)
                    )
                elif (
                    message.arbitration_id
                    == ((node << 5) | CMD_GET_BUS_VOLTAGE_CURRENT)
                    and len(message.data) >= 8
                ):
                    vbus, ibus = struct.unpack("<ff", bytes(message.data[:8]))
                    result["min_vbus_v"] = round(
                        vbus
                        if result["min_vbus_v"] is None
                        else min(result["min_vbus_v"], vbus),
                        3,
                    )
                    result["max_vbus_v"] = round(
                        vbus
                        if result["max_vbus_v"] is None
                        else max(result["max_vbus_v"], vbus),
                        3,
                    )
                    result["last_ibus_a"] = round(ibus, 3)
                elif (
                    message.arbitration_id == ((node << 5) | CMD_GET_DRV_FAULT)
                    and len(message.data) >= 8
                ):
                    drv_fault, temperature = struct.unpack(
                        "<If", bytes(message.data[:8])
                    )
                    result["drv_fault"] = drv_fault
                    result["fet_temperature_c"] = round(temperature, 2)

            now = time.monotonic()
            if args.sensor_id is not None and now - last_sensor > 0.5:
                result["stop_reason"] = "sensor_timeout"
                break
            if now - last_heartbeat > 0.5:
                result["stop_reason"] = "heartbeat_timeout"
                break
    except Exception as exc:
        result["stop_reason"] = "exception"
        result["exception"] = str(exc)
    finally:
        try:
            send(CMD_SET_AXIS_STATE, struct.pack("<I", AXIS_STATE_IDLE))
        except Exception as exc:
            result["idle_send_error"] = str(exc)
        bus.shutdown()

    result["max_abs_iq_a"] = round(result["max_abs_iq_a"], 3)
    result["max_abs_sensorless_rpm"] = round(
        result["max_abs_sensorless_rpm"], 2
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["stop_reason"] == "duration" else 2


if __name__ == "__main__":
    raise SystemExit(main())
