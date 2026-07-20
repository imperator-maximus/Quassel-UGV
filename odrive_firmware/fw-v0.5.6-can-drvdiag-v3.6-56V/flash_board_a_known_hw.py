#!/usr/bin/env python3
"""Run ODrive DFU with Board A's verified v3.6-56V identity pinned.

Early v3.x boards can have an unreadable hardware-version field in OTP while
in STM32 DFU mode. The stock updater then declines to write even though the
hardware was identified correctly before entering DFU. This wrapper changes
only that fallback and still uses the stock erase/write/readback verification.
"""

import runpy
import sys

import odrive.dfu


EXPECTED_HW = (3, 6, 56)
EXPECTED_SERIAL = "386132523135"
FIRMWARE = "/home/nicolay/ODriveFirmware-v3.6-56V-fw0.5.6-can-drvdiag.hex"

original_get_hw_version = odrive.dfu.get_hw_version_in_dfu_mode


def get_verified_hw_version(dfu_device):
    detected = original_get_hw_version(dfu_device)
    if detected is None:
        print(
            "DFU OTP hardware field is unavailable; using the pre-DFU verified "
            "identity v3.6-56V.",
            flush=True,
        )
        return EXPECTED_HW
    if detected != EXPECTED_HW:
        raise RuntimeError(
            f"Refusing hardware mismatch: expected {EXPECTED_HW}, detected {detected}"
        )
    return detected


odrive.dfu.get_hw_version_in_dfu_mode = get_verified_hw_version
sys.argv = [
    "odrivetool",
    "--serial-number",
    EXPECTED_SERIAL,
    "dfu",
    FIRMWARE,
]
runpy.run_path("/home/nicolay/.venvs/odrive056/bin/odrivetool", run_name="__main__")
