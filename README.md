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

For test dependencies in a pipx install:

```bash
pipx inject audient-evo pytest
pipx inject audient-evo numpy sounddevice  # audio tests only
```

For editable development:

```bash
python -m pip install -e .[dev]
python -m pip install -e .[dev,audio-test]  # audio tests only
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

### WirePlumber config

EVO 4 needs none - covered by `alsa-ucm-conf >= 1.2.16`. An EVO 8 reference
config lives under [dev/wireplumber/](dev/wireplumber/README.md).

### 96 kHz playback

PipeWire defaults to 48 kHz; to allow native 96 kHz, follow [Arch wiki -
PipeWire: Changing the allowed sample rate(s)](https://wiki.archlinux.org/title/PipeWire#Changing_the_allowed_sample_rate(s)).

## Uninstall

```bash
# Kernel module
sudo ./kmod/uninstall.sh

# evoctl & evotui
pipx uninstall audient-evo-py
```

## Usage

```bash
evoctl set volume -20             # output volume in dB
evoctl get volume                 # output volume in dB
evoctl set gain 50 -t input1
evoctl set mute 1 -t output
evoctl set phantom 1 -t input1
evoctl set monitor 50              # EVO 4 only - 0=input, 100=playback
evoctl mixer input1 --volume -6 --pan 0
evoctl mixer output1_2 --volume 0 --mix-output 0
evoctl --device evo8 mixer output3_4 --volume 0 --mix-output 1
evoctl --device evo8 mixer output5_6 --volume 0 --mix-output 0  # loopback source
evoctl status
evoctl save
evoctl load
evoctl --help
evoctl --device evo4 --help
evoctl --device evo8 --help
evoctl --device evo8 set volume -20  # when multiple devices connected
evotui                             # TUI
```

Use `--device evo4` or `--device evo8` when more than one EVO is connected.
Use `-t` to target specific controls (for example `-t input3`, `-t output2`).
Volume and gain values are dB. Direct monitor is percent-like, from 0=input to
100=playback. See `evoctl --help` for all options.

Mixer settings are write-only and auto-saved to `~/.config/audient-evo-py/`.
Mixer `inputN` commands route hardware inputs. Mixer `output1_2`, `output3_4`,
and `output5_6` commands route stereo USB output sources. `--mix-output` selects
the mixer destination bus: EVO 4 has `0=MIX 3|4`; EVO 8 has `0=MIX 1|2` and
`1=MIX 3|4`. Device controls can be saved/loaded via `evoctl save`, `evoctl load`,
or TUI.

## Design

See [DESIGN.md](dev/DESIGN.md) for architecture, protocol, and USB entity details.

## Tests

| Command | Needs |
|---------|-------|
| `python -m pytest tests/test_kmod.py tests/test_devices.py tests/test_config.py tests/test_evoctl.py` | `[dev]` |
| `python -m pytest` | `[dev]`; hardware, audio, and manual tests are skipped |
| `python -m pytest --hardware --device evo4 -m hardware` | `[dev]`, kernel module, connected EVO; skips manual phantom-power tests unless `--manual` is also set |
| `python -m pytest tests/test_mixer_audio.py --hardware --audio --device evo4` | `[dev,audio-test]`, kernel module, connected EVO, WirePlumber config |
| `python -m pytest tests/test_controller.py --hardware --manual --device evo4 -m manual` | `[dev]`, connected EVO, safe phantom-power setup |
| `python -m pytest tests/test_mixer_mic.py -s --hardware --audio --manual --device evo4` | `[dev,audio-test]`, connected mic, manual prompts |

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
