# EVO 8 Audio Setup - PipeWire + WirePlumber

Arch Linux, PipeWire 1.6+, WirePlumber 0.5+.

## Status

- **EVO 4**: Alsa EVO 4 UCM config added in `alsa-ucm-conf >= 1.2.16` (PR
  [alsa-project/alsa-ucm-conf#708](https://github.com/alsa-project/alsa-ucm-conf/pull/708),
  released 2026-06-01 as
  [v1.2.16](https://github.com/alsa-project/alsa-ucm-conf/releases/tag/v1.2.16)).
  UCM exposes the correct stereo output and split mono captures with no extra
  PipeWire/WirePlumber rules required.
- **EVO 8**: no native ALSA UCM exists. This config is a port of the
  pre-UCM EVO 4 hack and is provided as a working stopgap. Treat it as a
  reference, not a long-term solution - the proper fix is an ALSA UCM
  contribution for EVO 8 similar to PR #708.

## Problem

EVO 8 exposes 6 USB channels on playback and capture. Without configuration,
PipeWire treats the raw ALSA device as surround and sends stereo app audio to
channels that should stay available for routing.

| Direction | USB channels |
|-----------|--------------|
| Playback | CH1/2 main output, CH3/4 output 3+4, CH5/6 loopback output |
| Capture  | CH1/2 mic/line 1+2, CH3/4 mic/line 3+4, CH5/6 loopback capture |

## Strategy

`evo8/install.sh` installs the PipeWire loopback config, WirePlumber rules,
restarts the audio stack, and sets default devices.

- `evo8_main_output` is the default app sink.
- Secondary output sinks and loopback sinks are explicit, not defaults.
- `51-evo8.conf` disables upmix on the raw ALSA sink so direct connections do
  not fill extra channels.

## Nodes

| Main sink | Extra sinks | Sources |
|-----------|-------------|---------|
| `evo8_main_output` | `evo8_output_3_4`, `evo8_loopback_output` | `evo8_mic_1_2`, `evo8_mic_3_4`, `evo8_loopback_capture` |

## Files

| Source | Install location | Purpose |
|--------|------------------|---------|
| `evo8/evo8-stereo.conf`     | `~/.config/pipewire/pipewire.conf.d/`   | Main, extra output, mic, and loopback nodes |
| `evo8/51-evo8.conf`         | `~/.config/wireplumber/wireplumber.conf.d/` | Disables idle suspension, disables upmix, renames raw ALSA nodes |
| `evo8/alsa-soft-mixer.conf` | `~/.config/wireplumber/wireplumber.conf.d/` | Software volume on ALSA devices |
| `evo8/evo8-setup.sh`        | `~/.local/bin/`                         | Re-applies default sink/source after reconnect |
| `evo8/evo8-setup.service`   | `~/.config/systemd/user/`               | Runs the setup script at login |

## Install

```bash
bash dev/wireplumber/evo8/install.sh
```

Backs up existing config to `~/.config/evo-audio-backup/`, installs files,
restarts PipeWire/WirePlumber, and sets defaults. Run the installed setup
script again after reconnecting the device if defaults are missing:

```bash
evo8-setup.sh
```

## Uninstall

```bash
bash dev/wireplumber/evo8/uninstall.sh
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
