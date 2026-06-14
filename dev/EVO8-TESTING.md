# EVO 8 Testing Manual

Help test EVO 8 step-by-step.

## Prerequisites

- Audient EVO 8.
- Run commands from the repository root unless a section says otherwise.
- See `README.md` in root for requirements and install guide. Treat all recommendations except DKMS as requirements.
- If you have more than one EVO connected, add `--device evo8` to `evoctl` and pytest commands.

## Install

```bash
# Kernel module
cd kmod && sudo ./install.sh    # select EVO 8 when prompted
ls -la /dev/evo8                # should exist
lsmod | grep evo_raw            # should be loaded

# evoctl
pipx install .                  # provides evoctl and evotui commands
pipx inject audient-evo pytest
pipx inject audient-evo numpy sounddevice  # audio tests only

# WirePlumber config (needed for mixer audio tests)
bash dev/wireplumber/evo8/install.sh
wpctl status | grep -i evo      # should show EVO 8 nodes and defaults
```

## Controls

### Volume - output1

```bash
evoctl get volume
evoctl set volume -20
evoctl get volume
evoctl set volume 0
evoctl get volume
```

### Volume - output2

```bash
evoctl get volume -t output2
evoctl set volume -20 -t output2
evoctl get volume -t output2
evoctl set volume 0 -t output2
evoctl get volume -t output2
```

### Gain - all 4 inputs

```bash
for i in input1 input2 input3 input4; do
  evoctl set gain 29 -t $i && evoctl get gain -t $i
done
```

Expected: each reports ~29 dB independently.


### Mute - all 6 targets

```bash
for t in input1 input2 input3 input4 output1 output2; do
  evoctl set mute 1 -t $t && evoctl get mute -t $t
  evoctl set mute 0 -t $t && evoctl get mute -t $t
done
```

Expected: each toggles independently; muting output1 should not affect output2.

### Phantom power - all 4 inputs

**WARNING:** Only enable if you have condenser mics or no mics connected. Phantom can damage ribbon mics.

```bash
for i in input1 input2 input3 input4; do
  evoctl set phantom 1 -t $i && evoctl get phantom -t $i
  evoctl set phantom 0 -t $i && evoctl get phantom -t $i
done
```

Expected: each toggles independently.

### Monitor (should fail)

```bash
evoctl set monitor 50
```

Expected: error - EVO 8 has no direct monitor control.

## Mixer

### Basic crosspoint

```bash
evoctl mixer input1 --volume 0 --pan 0
evoctl mixer output1_2 --volume 0
evoctl mixer output5_6 --volume -128
```

Expected: mix is present on MIX 1|2.

### Second mixer destination (MIX 3|4 / OUT 3|4)

```bash
evoctl mixer input1 --volume 0 --pan 0 --mix-output 1
evoctl mixer output1_2 --volume 0 --mix-output 1
evoctl mixer output3_4 --volume 0 --mix-output 1
```

Expected: mix is present on MIX 3|4.

### Loopback source

```bash
evoctl mixer output5_6 --volume 0 --mix-output 0
```

Expected: USB playback CH5/CH6 is routed into MIX 1|2.

## Status

```bash
evoctl status
evoctl status -f json
```

JSON should show all 4 inputs, both output pairs, no monitor field.

## Config Save/Load

```bash
evoctl set volume -30
evoctl set gain 25 -t input1
evoctl save
cat ~/.config/audient-evo-py/evo8/config.json

evoctl set volume -10
evoctl set gain 0 -t input1
evoctl load
evoctl status
```

Expected: after load, volume back to -30 dB, gain back to 25 dB.

## Test Suite

```bash
python -m pytest tests/test_controller.py -v --hardware

# Mixer DAW test (requires WirePlumber config + sounddevice + numpy)
python -m pytest tests/test_mixer_audio.py -v --hardware --audio

# Mixer mic test (manual - needs mic connected, records 3s voice samples)
python -m pytest tests/test_mixer_mic.py -vs --hardware --audio --manual
```

## Uninstall

```bash
bash dev/wireplumber/evo8/uninstall.sh
cd kmod && sudo ./uninstall.sh
pipx uninstall audient-evo-py
```

Verify: `wpctl status | grep -i evo` shows nothing, `/dev/evo8` is gone.
