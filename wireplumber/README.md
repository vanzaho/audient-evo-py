# EVO Audio Setup - PipeWire + WirePlumber

Arch Linux, PipeWire 1.6+, WirePlumber 0.5+.

## Problem

EVO devices expose extra USB audio channels for output pairs and loopback. Without
configuration, PipeWire can expose the raw ALSA device as surround and send stereo
app audio to channels that should stay available for routing.

| Device | Playback USB channels | Capture USB channels |
|--------|-----------------------|----------------------|
| EVO 4 | CH1/2 main output, CH3/4 loopback output | CH1/2 mic/line, CH3/4 loopback capture |
| EVO 8 | CH1/2 main output, CH3/4 output 3+4, CH5/6 loopback output | CH1/2 mic/line 1+2, CH3/4 mic/line 3+4, CH5/6 loopback capture |

## Strategy

`wireplumber/install.sh` prompts for `evo4` or `evo8`, installs the matching
PipeWire loopback config, installs WirePlumber ALSA rules, restarts the audio
stack, and sets default devices.

Default sink strategy:

- EVO 4: `evo4_main_output` is the default app sink.
- EVO 8: `evo8_main_output` is the default app sink.
- Secondary output sinks and loopback sinks are explicit, not defaults.
- `51-evo*.conf` disables upmix on the raw ALSA sink so direct connections do not fill extra channels.

## Nodes

| Device | Main sink | Extra sinks | Sources |
|--------|-----------|-------------|---------|
| EVO 4 | `evo4_main_output` | `evo4_loopback_output` | `evo4_mic`, `evo4_loopback_capture` |
| EVO 8 | `evo8_main_output` | `evo8_output_3_4`, `evo8_loopback_output` | `evo8_mic_1_2`, `evo8_mic_3_4`, `evo8_loopback_capture` |

## Files

| Source | Install location | Purpose |
|--------|------------------|---------|
| `wireplumber/evo4/evo4-stereo.conf` or `wireplumber/evo8/evo8-stereo.conf` | `~/.config/pipewire/pipewire.conf.d/` | Defines the main, extra output, mic, and loopback nodes |
| `wireplumber/evo4/51-evo4.conf` or `wireplumber/evo8/51-evo8.conf` | `~/.config/wireplumber/wireplumber.conf.d/` | Disables idle suspension, disables upmix, renames raw ALSA nodes |
| `wireplumber/alsa-soft-mixer.conf` | `~/.config/wireplumber/wireplumber.conf.d/` | Software volume on ALSA devices |
| `wireplumber/evo4/evo4-setup.sh` or `wireplumber/evo8/evo8-setup.sh` | `~/.local/bin/` | Re-applies default sink/source after reconnect |
| `wireplumber/evo4/evo4-setup.service` or `wireplumber/evo8/evo8-setup.service` | `~/.config/systemd/user/` | Runs the setup script at login |

## Install

```bash
bash wireplumber/install.sh
```

The installer backs up existing config to `~/.config/evo-audio-backup/`, installs
the selected device files, restarts PipeWire/WirePlumber, and sets defaults. Run
the installed setup script again after reconnecting the device if defaults are
missing:

```bash
evo4-setup.sh
evo8-setup.sh
```

## Volume

Two independent layers:

- PipeWire software volume: `wpctl set-volume`, `pavucontrol`.
- EVO hardware volume: physical knob or `evoctl set volume -20`.

For best quality, keep PipeWire near 100% and use the EVO hardware volume for
normal listening level.

## Troubleshooting

```bash
wpctl status                      # check default sink/source, marked with *
pactl info | grep 'Default Sink'  # check the default sink name
pw-cli dump Node | grep -A5 evo   # verify node properties
pw-top                            # live PipeWire graph activity
lsusb | grep Audient              # confirm USB connection
aplay -l | grep EVO               # confirm ALSA sees the device
```
