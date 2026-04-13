# Design - Audient EVO4 Linux Controller

Architecture and reverse-engineered findings.

---

## Problem

The Audient EVO4 exposes its mixer controls (volume, gain, mute, monitor mix)
through USB control transfers on endpoint 0. On Linux, `snd-usb-audio` claims
the audio interfaces and the usbfs layer blocks userspace from sending control
transfers to a kernel-owned device. The vendor control app is Windows/macOS only.

## Solution

`evo4_raw` is a minimal out-of-tree kernel module that:

1. Binds to **interface 3** (DFU, left unclaimed by `snd-usb-audio`)
2. Uses that binding solely to obtain a `usb_device` handle
3. Exposes `/dev/evo4` as a misc device with a single ioctl
4. Forwards USB control transfers through `usb_control_msg()`

This works because `usb_control_msg()` operates on endpoint 0 (the default
control pipe), which is device-global. The module never touches audio
interfaces, so `snd-usb-audio` continues streaming undisturbed.

## Architecture

```
+----------------------------------------------------------+
|                      Userspace                           |
|                                                          |
| +----------+     +----------------+     +--------------+ |
| | evoctl.py|---->|controller.py   |---->|kmod.py       | |
| | (CLI)    |     |(EVO4Controller)|     |(ioctl wrapper| |
| +----------+     +----------------+     +------+-------+ |
|                                              |           |
|                                  ioctl(fd, EVO4_CTRL_TRANSFER, buf)
|                                              |           |
+----------------------------------------------+-----------+
|                      Kernel                  |           |
|                                              v           |
|                                      +--------------+    |
|                                      |  /dev/evo4   |    |
|                                      |  (misc dev)  |    |
|                                      +------+-------+    |
|                                             |            |
|                                             v            |
|                                   +-------------------+  |
|                                   |    evo4_raw.ko    |  |
| +----------------+                | usb_control_msg() |  |
| | snd-usb-audio  |                | on endpoint 0     |  |
| | (iface 0-2)    |                +----------+--------+  |
| +-------+--------+                           |           |
|         |  claims iface 0-2     claims iface 3 (DFU)    |
+---------+-------------------------------------+-----------+
|         v              USB Bus               v           |
| +---------------------------------------------------+    |
| |              Audient EVO4 (USB Device)            |    |
| |  Endpoint 0 (Control) <-- all control transfers   |    |
| |  Interface 0 - Audio Control (UAC2 descriptors)   |    |
| |  Interface 1 - Audio Streaming (playback)         |    |
| |  Interface 2 - Audio Streaming (capture)          |    |
| |  Interface 3 - DFU (unused, bound by evo4_raw)    |    |
| +---------------------------------------------------+    |
+----------------------------------------------------------+
```

## ioctl Protocol

A single ioctl command `EVO4_CTRL_TRANSFER` carries all communication.
The struct is identical in kernel and userspace (264 bytes, little-endian):

| Field | Type | Description |
|-------|------|-------------|
| bRequestType | u8 | USB bmRequestType (0x21=SET, 0xA1=GET) |
| bRequest | u8 | USB bRequest (0x01 = CUR) |
| wValue | u16 | (ControlSelector << 8) \| ChannelNumber |
| wIndex | u16 | (EntityID << 8) \| InterfaceNumber |
| wLength | u16 | Data length (max 256); kernel updates on IN transfers |
| data | u8[256] | Transfer payload |

Python struct format: `"<BBHHH256s"` (264 bytes total).

ioctl number: `_IOWR('E', 0, struct evo4_ctrl_xfer)` - read+write, type 'E',
number 0, size 264. Python: `(3 << 30) | (264 << 16) | (0x45 << 8) | 0`.

## USB Interfaces

| Interface | Class | Description |
|-----------|-------|-------------|
| 0 | Audio Control | All entities (FU10, FU11, EU50-59, MU60) |
| 1 | Audio Streaming | Output (playback) |
| 2 | Audio Streaming | Input (recording) |
| 3 | DFU | Device Firmware Update - claimed by evo4_raw kmod |

No HID interface. Front panel buttons/knob are internal to the device
microcontroller and not exposed as USB controls.

## Controls Reference

wIndex = `(EntityID << 8) | Interface(0)`, wValue = `(CS << 8) | CN`.
All values little-endian.

### FU10 - Output Volume (wIndex=0x0A00) - CONFIRMED

**wValue**: `(CS=2 << 8) | CN`, where CN=1 (left) and CN=2 (right), both ganged.

| CS | CN | Function | Range |
|----|----|----------|-------|
| 2 | 1-2 | Volume | [-96.0, 0.0] dB (software limit; UAC2 descriptor reports -127) |

- Payload: 2-byte signed UAC2 (1/256 dB steps). `raw = round(dB * 256) & 0xFFFF`
- Both channels are always written together (ganged).
- UAC descriptor reports 4 channels but CH3-4 are fixed at defaults and ignore SET_CUR.

Default state (from USB captures): `0x0000` (0 dB) for CH1-2, `0x8080` (-127.5 dB) for CH3-4.

### FU11 - Input Gain (wIndex=0x0B00) - CONFIRMED

**wValue**: `(CS=2 << 8) | CN`, where CN=1 (input1) and CN=2 (input2).

| CS | CN | Function | Range |
|----|----|----------|-------|
| 2 | 1 | Input 1 gain | [-8.0, 50.0] dB |
| 2 | 2 | Input 2 gain | [-8.0, 50.0] dB |

- Payload: 2-byte signed UAC2 (1/256 dB steps). Device quantizes to 1 dB steps.
- Per-channel; CH1-2 are independent. CH3-4 fixed at -8 dB, ignore SET_CUR.

Default state: `0x00F8` (-8 dB) for CH3-4 (internal).

### EU50 (wIndex=0x3200) - NOT PRESENT

All GET_CUR and SET_CUR STALL. No accessible controls.

### EU56 - Monitor Mix (wIndex=0x3800) - CONFIRMED

**wValue**: `(CS=0 << 8) | CN=0` = `0x0000`. Only CS=0 CN=0 is safe to use.

| CS | CN | Function | Range |
|----|----|----------|-------|
| 0 | 0 | Monitor mix ratio | [0, 127] device / [0, 100]% API |

- Payload: 2-byte unsigned LE. 0 = full input, 127 = full playback.
- API maps to 0-100%: `raw = round(ratio * 127 / 100)`.

**WARNING:** Probing higher CS values can put EU56 into an error state
requiring USB re-plug. Only use CS=0 CN=0.

### EU57 (wIndex=0x3900) - NOT PRESENT

All GET_CUR and SET_CUR STALL. No accessible controls.

### EU58 - Input Config (wIndex=0x3A00)

Extension Unit 58 handles both phantom power and input mute.

| CS | CN | wValue | Function | Payload | Status |
|----|----|--------|----------|---------|--------|
| 0 | 0 | 0x0000 | Phantom 48V input1 | 4B LE (0=off, 1=on) | CONFIRMED |
| 0 | 1 | 0x0001 | Phantom 48V input2 | 4B LE (0=off, 1=on) | CONFIRMED |
| 0 | 2 | 0x0002 | - | always 0 | no channel 3 |
| 1 | 0-2 | - | Gain mirror | read-only | mirrors FU11 CS=2, first 2 bytes |
| 2 | 0 | 0x0200 | Input mute ch1 | 4B LE (0=unmuted, 1=muted) | CONFIRMED |
| 2 | 1 | 0x0201 | Input mute ch2 | 4B LE (0=unmuted, 1=muted) | CONFIRMED |
| 2 | 2 | 0x0202 | - | always 0 | |
| 5 | 0 | - | Unknown | writable, default 0x00000000 | UNCONFIRMED |
| 5 | 1 | - | Unknown | writable, default 0xFFFFFFFF | UNCONFIRMED |
| 7 | 0-1 | - | Capability flags | 0x03000000, read-only | static bitfield |

**Phantom power:** Relay click audible on toggle. Readback via GET_CUR confirmed.

**CS=5 (unconfirmed):** SET/GET roundtrip works. Default is CN=0=0, CN=1=0xFFFF.
May control input impedance/gain staging for XLR/TRS combo jacks, but no audible
or visible effect confirmed. Not implemented in controller.py.

**CS=7 (read-only):** Value 0x03 for CN=0,1. Does not change when CS=5 is toggled.
Likely a static capability bitfield.

**Must send full 4 bytes** or the device ignores the request.

### EU59 - Output Config (wIndex=0x3B00)

| CS | CN | wValue | Function | Payload | Status |
|----|----|--------|----------|---------|--------|
| 0 | 0-1 | - | Volume mirror | read-only, mirrors FU10 CH1-2 | read-only |
| 1 | 0 | 0x0100 | Output mute | 4B LE (0=unmuted, 1=muted) | CONFIRMED |
| 1 | 1 | - | Tracks CN=0 | same mute state | |
| 2 | 0-1 | - | Unknown boolean | 0x01000000, UNCONFIRMED | not implemented |

**EU59 CS=0 is NOT a separate headphone volume.** Tested: setting FU10 to -20 dB
and reading EU59 CS=0 yields the same value. The `0xFFFF` padding in bytes 3-4 is
the EU data format. Other projects (vijay-prema, Evo4mixer) write to EU59 CS=0 for
volume, which works but is the same underlying register as FU10.

**Must send full 4 bytes** or the device ignores the request.

### MU60 - Mixer Unit (wIndex=0x3C00) - DECODED

Single 6-input x 2-output **loopback-only** mixer. All 12 cross-points
route into the loopback bus (USB capture CH3/4). This mixer does NOT control
headphone/main output - that is handled by EU56 (monitor mix) + FU10 (volume).

**Write-only** (all GET_CUR STALL). Uses CS=1 (Mixer Control, UAC2 standard),
2-byte signed UAC2 (1/256 dB steps). Range: -128 dB (0x8000, silence) to +6 dB
(0x0600, software limit; hardware may accept up to +8 dB per captures).

CN addressing: `CN = out_idx + in_idx * num_outputs` (UAC2 standard).

**Full matrix** (6 inputs x 2 outputs, CN 0-11):

| CN | wValue | Source | Destination | in_idx | out_idx |
|----|--------|--------|-------------|--------|---------|
| 0 | 0x0100 | Input 1 | Loopback L | 0 | 0 |
| 1 | 0x0101 | Input 1 | Loopback R | 0 | 1 |
| 2 | 0x0102 | Input 2 | Loopback L | 1 | 0 |
| 3 | 0x0103 | Input 2 | Loopback R | 1 | 1 |
| 4 | 0x0104 | DAW L (Main) | Loopback L | 2 | 0 |
| 5 | 0x0105 | DAW L (Main) | Loopback R | 2 | 1 |
| 6 | 0x0106 | DAW R (Main) | Loopback L | 3 | 0 |
| 7 | 0x0107 | DAW R (Main) | Loopback R | 3 | 1 |
| 8 | 0x0108 | LoopOut L (CH3) | Loopback L | 4 | 0 |
| 9 | 0x0109 | LoopOut L (CH3) | Loopback R | 4 | 1 |
| 10 | 0x010A | LoopOut R (CH4) | Loopback L | 5 | 0 |
| 11 | 0x010B | LoopOut R (CH4) | Loopback R | 5 | 1 |

**Inputs 0-1** (Input 1/2): mic/line preamp signals after FU11 gain.
**Inputs 2-3** (DAW L/R): USB playback CH1/2 - the main stereo output.
**Inputs 4-5** (LoopOut L/R): USB playback CH3/4 - a second stereo playback
stream that only appears in the loopback mix (not in the headphone output).

Default state (from USB captures): diagonal cross-points active (CN 0,3,4,7,8,11),
cross pairs muted at -128 dB (CN 1,2,5,6,9,10).

Since MU60 is write-only, controller state is maintained in a shadow dict and
persisted to `~/.config/audient-evo-py/mixer-state.json`.

Cross-referenced with soerenbnoergaard/evoctl (EVO8): same protocol
(wIndex=0x3C00, CS=1, 2-byte Q8.8 dB), same write-only behavior. EVO8 uses a
larger matrix (10x4=40 cross-points) but same addressing formula.

## Pan Law

`set_mixer_input()` and `set_mixer_output()` use equal-power panning:

```
p = (pan + 100) / 200        # normalize to [0, 1]
angle = p * (pi / 2)
L_linear = cos(angle)
R_linear = sin(angle)
L_dB = volume_dB + 20*log10(L_linear)
R_dB = volume_dB + 20*log10(R_linear)
```

- Center (pan=0): both channels at volume_dB - 3.01 dB
- Full left (pan=-100): L = volume_dB, R = -128 dB (silence)
- Full right (pan=+100): R = volume_dB, L = -128 dB (silence)

## Status Struct

`get_status_raw()` returns 12 bytes in format `"<hhhBBBBBB"`:

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| 0 | int16 | vol_raw | FU10 CH1 raw USB value |
| 2 | int16 | gain1_raw | FU11 CH1 raw USB value |
| 4 | int16 | gain2_raw | FU11 CH2 raw USB value |
| 6 | uint8 | mix_raw | EU56 raw value (0-127) |
| 7 | uint8 | in1_mute | 0/1 |
| 8 | uint8 | in2_mute | 0/1 |
| 9 | uint8 | out_mute | 0/1 |
| 10 | uint8 | in1_phantom | 0/1 |
| 11 | uint8 | in2_phantom | 0/1 |

`decode_status()` converts to the same dict format as `config.snapshot()`.

## Protocol Summary

| Control | Entity | wValue | wIndex | Payload | Access |
|---------|--------|--------|--------|---------|--------|
| Output Volume | FU10 | CS=2, CN=1-2 | 0x0A00 | 2B signed (1/256 dB) | R/W |
| Input Gain | FU11 | CS=2, CN=1-2 | 0x0B00 | 2B signed (1/256 dB) | R/W |
| Monitor Mix | EU56 | CS=0, CN=0 | 0x3800 | 2B unsigned (0-127) | R/W |
| Phantom 48V | EU58 | CS=0, CN=0-1 | 0x3A00 | 4B LE boolean | R/W |
| Input Mute | EU58 | CS=2, CN=0-1 | 0x3A00 | 4B LE boolean | R/W |
| Output Mute | EU59 | CS=1, CN=0 | 0x3B00 | 4B LE boolean | R/W |
| Mixer Matrix | MU60 | CS=1, CN=0-11 | 0x3C00 | 2B signed (1/256 dB) | W only |
| Input Mode? | EU58 | CS=5, CN=0-1 | 0x3A00 | 4B LE | UNCONFIRMED |
| Volume alias | EU59 | CS=0, CN=0-1 | 0x3B00 | 4B (=FU10 mirror) | read-only |

## Module Safety

- **Mutex** serializes all ioctl calls and protects against concurrent disconnect
- **DMA buffer**: `kmalloc`'d per transfer (stack memory can't be used for USB)
- **Device check**: every ioctl verifies device is still connected under the lock
- **Size limit**: `wLength` capped at 256 bytes

## Known Quirks

1. **EU56 error state** - Sending GET_CUR to invalid CS/CN on EU56 can lock
   the unit. Only recoverable by USB re-plug. Use only CS=0 CN=0.

2. **Rapid transfer storms** - Opening/closing `/dev/evo4` many times in
   fast succession (e.g., scan with per-command open) can cause USB STALL
   on all subsequent transfers. Use a single fd with delays between transfers.

3. **CH3-4 are internal** - Both FU10 and FU11 report 4 channels in their USB
   descriptors, but CH3-4 are fixed at defaults and ignore SET_CUR.

4. **Mute/phantom data size** - EU58/59 controls use 4-byte values despite
   being boolean. Must send full 4 bytes or the device ignores the request.

5. **No front panel USB access** - The physical buttons (input1, input2,
   volume, mixer, 48V) and rotary encoder are handled by the device's
   internal microcontroller. Button state is not readable or writable via
   USB control transfers. There is no HID interface.

6. **MU60 write-only** - GET_CUR on any MU60 cross-point STALLs. State must
   be tracked in software (shadow dict, persisted to mixer-state.json).

## Cross-Reference: Other Projects

| Control | This project | vijay-prema | Evo4mixer | evoctl (EVO8) |
|---------|-------------|-------------|-----------|---------------|
| Output Volume | FU10 CS=2 | EU59 CS=0 (alias) | EU59 CS=0 (alias) | - |
| Input Gain | FU11 CS=2 | EU58 CS=1 (alias) | EU58 CS=1 (alias) | - |
| Monitor Mix | EU56 CS=0 | - | MU60 | MU60 (matrix) |
| Input Mute | EU58 CS=2 | - | - | - |
| Output Mute | EU59 CS=1 | - | - | - |
| Phantom 48V | EU58 CS=0 | EU58 CS=0 | EU58 CS=0 | - |
| HP Volume | N/A (= FU10) | EU59 CS=0 (= FU10) | - | - |
| Mixer Matrix | MU60 CS=1 (decoded) | - | MU60 | MU60 (matrix) |
