# audient-evo-py

Audient EVO (4/8) Linux controller.

Audient software is Win/macOS only. CLI `evoctl` and TUI `evotui` implement the same controls for Linux without interrupting audio flow.

**How?** A small kernel module `evo_raw` binds EVO's unused DFU interface to obtain device handle without detaching `snd-usb-audio`.

#### EVO 4
| Controls | Loopback Mixer |
|----------|----------------|
| ![EVO 4 controls](screenshots/evo4_controls.png) | ![EVO 4 mixer](screenshots/evo4_mixer.png) |

#### EVO 8
| Controls | Loopback Mixer |
|----------|----------------|
| ![EVO 8 controls](screenshots/evo8_controls.png) | ![EVO 8 mixer](screenshots/evo8_mixer.png) |

## Requirements

- `snd-usb-audio` (standard linux kernel audio)
- `linux-headers` (kernel header files) and `make` - to build kernel module
- `dkms` (Dynamic Kernel Module Support) - optional but without it the module stops loading after a kernel update until reinstalled with kmod/install.sh
- `python3` (>=v3.10)
  - `pipx` to install (optional but recommended)

## Install

### CLI evoctl / TUI evotui

Recommended install using `pipx` for `evoctl` & `evotui` commands:

```bash
python3 -m pip install --user pipx
pipx ensurepath
pipx install path/to/audient-evo-py
```

### Kernel module

Builds and installs kernel module, adds udev rule loads the module.

Optional steps (prompted by install.sh):
- Install using DKMS (to auto-rebuild after kernel update)
- Setup systemd service for automatic config loading (e.g. system start, device reconnect).

```bash
cd kmod
sudo ./install.sh
```

### WirePlumber config (optional, recommended)

Without explicit configuration, EVO devices expose extra USB audio channels (loopback bus) that PipeWire treats as surround. The `wireplumber/install.sh` script prompts for your device and sets up:

- Stereo-only output (disables upmix to loopback channels)
- Explicit sinks/sources for loopback routing
- Idle suspension disabled (prevents clicks on stream start)
- Default sink/source at login

```bash
bash wireplumber/install.sh
```

See [wireplumber/README.md](wireplumber/README.md) for signal flow diagrams and details.

## Uninstall

```bash
# Kernel module
sudo ./kmod/uninstall.sh

# Wireplumber config
./wireplumber/uninstall.sh

# evoctl & evotui
pipx uninstall audient-evo-py
```

## Usage

```bash
evoctl set volume -20
evoctl get volume
evoctl set gain 50 -t input1
evoctl set mute 1 -t output
evoctl set phantom 1 -t input1
evoctl set monitor 50              # EVO 4 only - 0=input, 100=playback
evoctl mixer input1 --volume -6 --pan 0
evoctl mixer output1_2 --volume 0 --mix-output 0
evoctl --device evo8 mixer output5_6 --volume 0 --mix-output 0
evoctl status
evoctl save / load
evoctl --help
evoctl --device evo4 --help
evoctl --device evo8 --help
evoctl --device evo8 set volume -20  # when multiple devices connected
evotui                             # TUI
```

Use `-t` to target specific channels (e.g. `-t input3`, `-t output2`).
See `evoctl --help` for all options.

Mixer settings are write-only and auto-saved to `~/.config/audient-evo-py/`.
Mixer `inputN` and `outputN_M` commands select a USB output source; `--mix-output`
selects the mixer destination bus. Device controls can be saved/loaded via
`evoctl save/load` or TUI.

## Design

See [DESIGN.md](dev/DESIGN.md) for architecture, protocol, and USB entity details.

## Related Projects

Partially working, with quirks, written for other platforms, ... - very helpful nonetheless.

- [subsubl/Evo4mixer](https://github.com/subsubl/Evo4mixer)
- [vijay-prema/audient-evo-linux-tools](https://github.com/vijay-prema/audient-evo-linux-tools/tree/main)
- [soerenbnoergaard/evoctl](https://github.com/soerenbnoergaard/evoctl)
- [TheOnlyJoey/MixiD](https://github.com/TheOnlyJoey/MixiD)
- [charlesmulder/alsa-audient-id14](https://github.com/charlesmulder/alsa-audient-id14)
- [r00tman/mymixer](https://github.com/r00tman/mymixer)
- [hoskere/audient-evo8-rp2350](https://github.com/hoskere/audient-evo8-rp2350-arduino/tree/main)

## Notice

EVO 4 is fully tested. EVO 8 needs testing with hardware - see [dev/EVO8-TESTING.md](dev/EVO8-TESTING.md) if you can help. Open an issue if you own an EVO device and are willing to cooperate.


## License

Public domain. Free for all. Give credit as you see fit :-). See [LICENSE](LICENSE).
