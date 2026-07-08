#!/usr/bin/env python3
"""Dauerlauf-Monitor fuer 1h ODrive-Messer-Test. Schweigt wenn ok, Alarm bei Fehler."""
import can, time, struct, sys, signal

NODE = 0  # nur node0 (Messer) ueberwachen
EXPECT_STATE = 5  # CLOSED_LOOP_SENSORLESS
DURATION = 70 * 60  # 70 min
ALARM_LOG = "/home/imperator/ugvtestpi/dauerlauf_alarm.log"
OK_LOG = "/home/imperator/ugvtestpi/dauerlauf_ok.log"


def log(path, msg):
    with open(path, "a") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


def main():
    bus = can.interface.Bus(channel="can0", interface="socketcan")
    start = time.time()
    log(OK_LOG, f"[{time.strftime('%H:%M:%S')}] dauerlauf-monitor start (node{NODE}, {DURATION//60}min)")
    last_ok = 0.0
    while time.time() - start < DURATION:
        msg = bus.recv(timeout=1.0)
        if msg is None:
            continue
        nid = msg.arbitration_id >> 5
        cmd = msg.arbitration_id & 0x1F
        if cmd != 0x01 or nid != NODE:
            continue
        data = bytes(msg.data)
        if len(data) < 8:
            continue
        error = struct.unpack("<I", data[0:4])[0]
        state = struct.unpack("<I", data[4:8])[0]
        ts = time.strftime("%H:%M:%S")
        elapsed = time.time() - start
        if error != 0:
            log(ALARM_LOG, f"[{ts}] ALARM ({elapsed:.0f}s): error=0x{error:08X} state={state}")
            last_ok = 0.0
        elif state != EXPECT_STATE:
            log(ALARM_LOG, f"[{ts}] STATE ({elapsed:.0f}s): error=0 state={state} (erwartet {EXPECT_STATE})")
            last_ok = 0.0
        else:
            now = time.time()
            if now - last_ok > 300.0:  # alle 5 min ein ok
                log(OK_LOG, f"[{ts}] ok ({elapsed:.0f}s): error=0 state={state}")
                last_ok = now
    log(OK_LOG, f"[{time.strftime('%H:%M:%S')}] dauerlauf-monitor ende ({DURATION//60}min)")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
