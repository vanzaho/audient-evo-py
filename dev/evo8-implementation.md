# EVO 8 Implementation Notes

EVO 8 specifics - hardware differences, USB protocol, mixer matrix, and PipeWire
routing. Read `DESIGN.md` first for the general architecture.

---

## Device Identification

| Field | Value |
|-------|-------|
| USB VID | 0x2708 (Audient) |
| USB PID | 0x0007 |
| Kernel device | `/dev/evo8` |
| Config dir | `~/.config/audient-evo-py/evo8/` |
| Mixer shadow | `~/.config/audient-evo-py/evo8/.mixer-state.json` |

---

## Differences from EVO 4

| Parameter | EVO 4 | EVO 8 |
|-----------|-------|-------|
| USB PID | 0x0006 | 0x0007 |
| Mic/line inputs | 2 | 4 |
| Stereo output pairs | 1 | 2 |
| Gain range | -8 to +50 dB | 0 to +58 dB |
| Mute targets | 3 (in1, in2, output) | 6 (in1-4, output1, output2) |
| USB playback channels | 4 | 6 |
| USB capture channels | 4 | 6 |
| Mixer matrix | 6 × 2 = 12 cross-points | 10 × 4 = 40 cross-points |
| Direct monitor (EU56) | Yes (blend knob) | No (use mixer matrix) |
| ALSA node suffix | (stereo) | `analog-surround-51` |

The USB protocol is the same (same entity IDs, same encoding, same ioctl). The
`DeviceSpec` dataclass in `evo/devices.py` captures all numeric differences so the
`EVOController` class handles both devices without branching.

---

## USB Interface Layout

Identical to EVO 4. Interface 3 (DFU) is left unclaimed by `snd-usb-audio`, so
`evo_raw` binds to it to obtain a `usb_device` handle. All control transfers go to
endpoint 0 (the global control pipe).

| Interface | Class | Claimed by |
|-----------|-------|------------|
| 0 | Audio Control | snd-usb-audio |
| 1 | Audio Streaming (playback) | snd-usb-audio |
| 2 | Audio Streaming (capture) | snd-usb-audio |
| 3 | DFU | evo_raw.ko |

---

## USB Channel Layout

The EVO 8 exposes **6 channels** in each direction (ALSA 5.1 surround layout,
not 8-channel as the name might imply).

### Playback (host → device)

| USB channels | ALSA position | Function | Mixer source label |
|---|---|---|---|
| CH1 / CH2 | FL / FR | Main output 1+2 | PC 1+2 |
| CH3 / CH4 | FC / LFE | Output 3+4 | PC 3+4 |
| CH5 / CH6 | RL / RR | Loopback output | LOOP-BACK 1+2 |

### Capture (device → host)

| USB channels | ALSA position | Function | PipeWire node |
|---|---|---|---|
| CH1 / CH2 | FL / FR | Mic/line 1+2 | `evo8_mic_1_2` |
| CH3 / CH4 | FC / LFE | Mic/line 3+4 | `evo8_mic_3_4` |
| CH5 / CH6 | RL / RR | Loopback bus output | `evo8_loopback_capture` |

ALSA reports this as `analog-surround-51` (5.1 surround class) because 6 channels
maps to that format. The FL/FR/FC/LFE/RL/RR position names are used directly in
PipeWire loopback modules to target individual channel pairs.

---

## Control Reference

All entity IDs and the ioctl protocol are identical to EVO 4. Only channel counts
and ranges change.

### FU10 - Output Volume (wIndex=0x0A00)

EVO 8 has **two stereo output pairs**. Each pair uses its own FU10 channel numbers:

| Output pair | CN (L) | CN (R) | wValue (L) | wValue (R) |
|---|---|---|---|---|
| OUT 1+2 | 1 | 2 | 0x0201 | 0x0202 |
| OUT 3+4 | 3 | 4 | 0x0203 | 0x0204 |

`set_volume(db, output_pair=0)` writes to CN 1+2; `output_pair=1` writes to CN 3+4.
`output_pair=None` sets all pairs. Both channels of a pair are always written
together (ganged). Range: [-96.0, 0.0] dB.

### FU11 - Input Gain (wIndex=0x0B00)

Four independent input channels (CN 1-4). Gain range: **0 to +58 dB** (vs -8 to
+50 dB on EVO 4).

| Target | CN | wValue |
|---|---|---|
| input1 | 1 | 0x0201 |
| input2 | 2 | 0x0202 |
| input3 | 3 | 0x0203 |
| input4 | 4 | 0x0204 |

### EU56 - Monitor Mix (wIndex=0x3800)

**Not present on EVO 8.** The EVO 4 uses EU56 as a single-knob blend between
direct input monitoring and DAW playback. The EVO 8 has no equivalent register -
monitoring is configured entirely through the mixer matrix (MU60). Any attempt to
read or write EU56 on EVO 8 will STALL. `EVOController.get_monitor()` /
`set_monitor()` raise `RuntimeError` when called on an EVO 8 spec.

### EU58 - Input Config (wIndex=0x3A00)

**Phantom power** (CS=0): one register per input, CN=0-3 for inputs 1-4.

| Target | CS | CN | wValue |
|---|---|---|---|
| input1 phantom | 0 | 0 | 0x0000 |
| input2 phantom | 0 | 1 | 0x0001 |
| input3 phantom | 0 | 2 | 0x0002 |
| input4 phantom | 0 | 3 | 0x0003 |

**Input mute** (CS=2): CN=0-3 for inputs 1-4, then CN=4-5 for output pairs.

| Target | CS | CN | wValue |
|---|---|---|---|
| input1 mute | 2 | 0 | 0x0200 |
| input2 mute | 2 | 1 | 0x0201 |
| input3 mute | 2 | 2 | 0x0202 |
| input4 mute | 2 | 3 | 0x0203 |
| output1 mute | 2 | 4 | 0x0204 |
| output2 mute | 2 | 5 | 0x0205 |

EVO 8 consolidates both input and output mutes in EU58 (unlike EVO 4 where output
mute lives in EU59). The controller builds `_mute_targets` dynamically from the spec:
for multi-output-pair devices, output mutes start at `CS=2, CN=num_inputs`.

Payload: 4-byte little-endian boolean (0=unmuted, 1=muted). All 4 bytes must be sent.

### EU59 - Output Config (wIndex=0x3B00)

Not used for muting on EVO 8 (mutes are in EU58 CS=2 as above). EU59 CS=0 is still
a read-only mirror of FU10 output volume.

### MU60 - Mixer Unit (wIndex=0x3C00)

See the mixer section below.

---

## Mixer Matrix (MU60) - 10 × 4

The EVO 8 loopback mixer has **10 inputs × 4 outputs = 40 cross-points**.

### Mixer inputs

| in_idx | Source | Type |
|--------|--------|------|
| 0 | Mic/line 1 | Mono |
| 1 | Mic/line 2 | Mono |
| 2 | Mic/line 3 | Mono |
| 3 | Mic/line 4 | Mono |
| 4 | PC 1 (DAW main L) | Mono |
| 5 | PC 2 (DAW main R) | Mono |
| 6 | PC 3 (DAW out 3+4 L) | Mono |
| 7 | PC 4 (DAW out 3+4 R) | Mono |
| 8 | LOOP-BACK L (CH5) | Mono |
| 9 | LOOP-BACK R (CH6) | Mono |

### Mixer outputs

The EVO 8 mixer has **two independent stereo mixer outputs**, one per output pair.
Each mixer output can be mixed independently (e.g. mic 1+2 at full level to
output 0, silent to output 1).

| out_idx | Mixer output | Destination |
|---------|---------|-------------|
| 0 | Output 0 L | OUT1+2 context (loopback / monitoring) |
| 1 | Output 0 R | OUT1+2 context |
| 2 | Output 1 L | OUT3+4 context |
| 3 | Output 1 R | OUT3+4 context |

Cross-referenced from Arduino reference: `output_num=0` ("Main 1+2") maps to
out_idx 0,1 and `output_num=1` ("Main 3+4") maps to out_idx 2,3.

### Cross-point addressing

CN formula (UAC2 standard): `CN = in_idx * num_outputs + out_idx`

With `num_outputs = 4`:

| in_idx | CN (out 0) | CN (out 1) | CN (out 2) | CN (out 3) |
|--------|-----------|-----------|-----------|-----------|
| 0 (mic1) | 0 | 1 | 2 | 3 |
| 1 (mic2) | 4 | 5 | 6 | 7 |
| 2 (mic3) | 8 | 9 | 10 | 11 |
| 3 (mic4) | 12 | 13 | 14 | 15 |
| 4 (PC1) | 16 | 17 | 18 | 19 |
| 5 (PC2) | 20 | 21 | 22 | 23 |
| 6 (PC3) | 24 | 25 | 26 | 27 |
| 7 (PC4) | 28 | 29 | 30 | 31 |
| 8 (loop L) | 32 | 33 | 34 | 35 |
| 9 (loop R) | 36 | 37 | 38 | 39 |

`wValue = (CS=1 << 8) | CN`. Data: 2-byte signed Q8.8 dB, range -128 to +6 dB.
**Write-only** - GET_CUR STALLs. State is tracked in the mixer shadow file.

### Controller methods

The high-level mixer methods accept a `mix_output` parameter (0-based, default 0). For EVO 4
(one output pair) only `mix_output=0` is valid. For EVO 8, `mix_output=0` targets
OUT1+2 and `mix_output=1` targets OUT3+4.

`set_mixer_input(input_num, gain_db, pan, mix_output=0)` - routes one mic/line input
(1-4) to a mixer output. CN base = `(input_num-1) * 4 + mix_output * 2`; writes L and R.

`set_mixer_output(volume_db, pan_l, pan_r, output_pair=0, mix_output=0)` - routes a
stereo USB output source pair to a mixer output. `output_pair` selects which output
source pair to read from: 0=OUT1+2 (in_idx 4+5), 1=OUT3+4 (in_idx 6+7), and
2=OUT5+6 (in_idx 8+9, labeled loopback by the device). Writes four cross-points
(source L and source R each to destination L and destination R).

---

## PipeWire / WirePlumber Audio Routing

### Device node names

| PipeWire node | Direction | Channels | Source/dest |
|---|---|---|---|
| `alsa_output.usb-Audient_EVO8-00.analog-surround-51` | sink | 6ch | All playback |
| `alsa_input.usb-Audient_EVO8-00.analog-surround-51` | source | 6ch | All capture |
| `evo8_output_3_4` | sink | 2ch | Output 3+4 (FC/LFE) |
| `evo8_loopback_output` | sink | 2ch | Loopback output (RL/RR) |
| `evo8_mic_1_2` | source | 2ch | Mic/line 1+2 (FL/FR) |
| `evo8_mic_3_4` | source | 2ch | Mic/line 3+4 (FC/LFE) |
| `evo8_loopback_capture` | source | 2ch | Loopback bus (RL/RR) |

### How channel splitting works

The raw ALSA sink (`analog-surround-51`) is used directly for main output 1+2 -
applications targeting the default audio output land on FL/FR. WirePlumber's
`51-evo8.conf` disables channel upmixing so audio addressed to FL/FR does not bleed
into FC/LFE/RL/RR.

The `evo8-stereo.conf` PipeWire loopback modules create dedicated stereo sinks and
sources for each remaining channel pair. Each loopback module uses `stream.dont-remix
= true` and explicit `audio.position` to pin to the correct ALSA channels.

Capture modules set `node.passive = true` on the ALSA capture side so they do not
keep the device active when nothing is recording.

### Config files

| File | Installed to |
|---|---|
| `dev/wireplumber/evo8/51-evo8.conf` | `~/.config/wireplumber/wireplumber.conf.d/` |
| `dev/wireplumber/evo8/evo8-stereo.conf` | `~/.config/pipewire/pipewire.conf.d/` |
| `dev/wireplumber/evo8/evo8-setup.sh` | `~/.local/bin/evo8-setup.sh` |
| `dev/wireplumber/evo8/evo8-setup.service` | `~/.config/systemd/user/` |

`evo8-setup.service` runs once at login to set the EVO 8 as the default PulseAudio
sink/source via `pactl`.

---

## DeviceSpec Constants (evo/devices.py)

```python
EVO8 = DeviceSpec(
    name="evo8",
    display_name="EVO 8",
    usb_pid=0x0007,
    dev_path="/dev/evo8",
    num_inputs=4,
    num_output_pairs=2,
    gain_db_min=0.0,
    gain_db_max=58.0,
    vol_db_min=-96.0,
    vol_db_max=0.0,
    mixer_inputs=10,
    mixer_outputs=4,
    num_mute_targets=6,
    has_monitor=False,
)
```

---

## Protocol Summary (EVO 8 specific)

| Control | Entity | wValue | wIndex | Payload | Notes |
|---------|--------|--------|--------|---------|-------|
| Output 1+2 volume | FU10 | CS=2, CN=1-2 | 0x0A00 | 2B signed Q8.8 | R/W |
| Output 3+4 volume | FU10 | CS=2, CN=3-4 | 0x0A00 | 2B signed Q8.8 | R/W |
| Input gain (1-4) | FU11 | CS=2, CN=1-4 | 0x0B00 | 2B signed Q8.8, 0-58 dB | R/W |
| Monitor mix | EU56 | - | 0x3800 | - | Not present (use MU60) |
| Phantom (input 1-4) | EU58 | CS=0, CN=0-3 | 0x3A00 | 4B LE bool | R/W |
| Input mute (1-4) | EU58 | CS=2, CN=0-3 | 0x3A00 | 4B LE bool | R/W |
| Output 1+2 mute | EU58 | CS=2, CN=4 | 0x3A00 | 4B LE bool | R/W |
| Output 3+4 mute | EU58 | CS=2, CN=5 | 0x3A00 | 4B LE bool | R/W |
| Mixer crosspoints | MU60 | CS=1, CN=0-39 | 0x3C00 | 2B signed Q8.8 | W only |
