#!/usr/bin/env python3
"""Heartbeat-Monitor (quiet). Alarm NUR bei error!=0 oder unerwartetem state.
state=5+error=0 = running-ok (alle 15s eine Zeile)."""
import can, time, struct, sys, signal

EXPECT = {0: (1, 5), 1: (1,)}   # node0 darf IDLE(1) oder RUNNING(5), node1 nur IDLE

def main():
    bus = can.interface.Bus(channel="can0", interface="socketcan")
    print(f"[{time.strftime('%H:%M:%S')}] monitor start (quiet), lausche can0", flush=True)
    last_log = {0: 0.0, 1: 0.0}
    while True:
        msg = bus.recv(timeout=1.0)
        if msg is None:
            continue
        nid = msg.arbitration_id >> 5
        cmd = msg.arbitration_id & 0x1F
        if cmd != 0x01 or nid not in (0, 1):
            continue
        data = bytes(msg.data)
        if len(data) < 8:
            continue
        error = struct.unpack("<I", data[0:4])[0]
        state = struct.unpack("<I", data[4:8])[0]
        ts = time.strftime("%H:%M:%S")
        allowed = EXPECT.get(nid, ())
        if error != 0:
            print(f"[{ts}] ALARM node{nid}: error=0x{error:08X} state={state}", flush=True)
            last_log[nid] = time.time()
        elif state not in allowed:
            print(f"[{ts}] STATE node{nid}: error=0 state={state} (unerwartet)", flush=True)
            last_log[nid] = time.time()
        else:
            now = time.time()
            if now - last_log[nid] > 15.0:
                tag = "running" if state == 5 else "idle"
                print(f"[{ts}] ok node{nid}: error=0 state={state} ({tag})", flush=True)
                last_log[nid] = now

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
