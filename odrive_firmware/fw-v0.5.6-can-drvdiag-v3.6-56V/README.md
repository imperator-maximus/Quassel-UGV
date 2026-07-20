# ODrive v3.6-56V CAN DRV diagnostics firmware

Build target: ODrive v3.6-56V

Upstream source: `odriverobotics/ODrive` tag `fw-v0.5.6`

Upstream commit: `a308314ed2ca613164b81e7bbdfacc53cd1859ff`

Compiler: `arm-none-eabi-gcc 10.3.1`

Build configuration: debug off, doctest off, LTO off

The firmware adds CANSimple command `0x1e` (`MSG_GET_DRV_FAULT`). Send an RTR
frame to `(node_id << 5) | 0x1e`. The eight-byte response contains:

- bytes 0-3: `uint32` `axis.last_drv_fault`, little-endian
- bytes 4-7: `float32` FET temperature in degrees Celsius, little-endian

Examples for nodes 0 and 1:

```sh
cansend can0 01E#R
cansend can0 03E#R
```

For compatibility with the existing mower controller, requested axis state `5`
is accepted as an alias for closed-loop control. Sensorless operation still
requires `axis.config.enable_sensorless_mode = true`. The heartbeat continues
to report state `5`, so the existing mixed old/new ODrive installation remains
compatible.

Artifact SHA-256:

- HEX: `90362d3863c946b7d0510f20769194b3473752c02e3df281f4a221550f6394bd`
- ELF: `596c108401ba842f971a99e4b8ab121149eb54bed2e8d8281ac9b5d0caadb226`
- BIN: `91d13ebb8e8ac1dbd6120e6572308c2bf1f43faf44d18f00a76ad0f863fcd5e4`

The pre-flash configuration backup for board serial `0x386132523135` is in
`odrive_backups/odrive-node0-1-before-diag-20260720.json`.

## UGV Board A deployment

Flashed and read-back verified on 2026-07-20 on Board A, USB serial
`0x386132523135`. The controlled migration is in
`migrate_board_a_config.py`; `flash_board_a_known_hw.py` documents the required
DFU fallback for this early v3.6 board, whose hardware-version OTP field is not
readable in STM32 DFU mode.

Important migration detail: fw-v0.5.6 represents CANSimple as the bit flag
`PROTOCOL_SIMPLE = 1`. The legacy configuration used protocol value `0`; using
that old value on 0.5.6 leaves CAN electrically enabled but sends no CANSimple
heartbeats or responses.

Post-deployment checks:

- CAN 2.0 at 250 kbit/s
- node IDs 0 and 1, 100 ms heartbeats
- both axes IDLE, no startup movement enabled
- sensorless mode enabled; requested state 5 compatibility patch active
- command `0x1e` returns `last_drv_fault = 0` on both axes

The migration now also enables the 1.0 s axis watchdog. This is intentionally
paired with the Raspberry Pi's continuous 100 ms `GET_IQ` polling: every
CANSimple request feeds the watchdog, while a host or cable failure makes the
axis disarm locally. Boards configured before this change must receive the
one-time USB watchdog update before autonomous mower operation.
