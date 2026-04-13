# AGENTS.md

## Project

Linux controller for Audient EVO 4 and EVO 8.

Controls:
- `evoctl`: CLI.
- `evotui`: TUI.
- `evo_raw`: kernel module for USB control transfers while `snd-usb-audio` handles audio.

Device nodes:
- EVO 4: `/dev/evo4`.
- EVO 8: `/dev/evo8`.

Reference docs:
- User docs: `README.md`.
- Architecture and protocol notes: `dev/DESIGN.md`.
- EVO 8 validation notes: `dev/EVO8-TESTING.md`.

EVO 8 IS NOT PROPERLY TESTED ON REAL HARDWARE.

## Structure

- `dev/`: reverse-engineering notes, probes, hardware validation notes.
- `evo/`: Python package; controller, device specs, config, kmod ioctl wrapper.
- `kmod/`: `evo_raw` out-of-tree kernel module, udev rules, install scripts.
- `tests/`: unit tests plus opt-in hardware, audio, and manual tests.
- `wireplumber/`: optional PipeWire/WirePlumber routing configs.
- `evoctl.py`: CLI entry point.
- `evotui.py`: TUI entry point.

## Run

From the repo:

```bash
python evoctl.py --help
python evoctl.py set volume -20
python evoctl.py get volume
python evoctl.py --device evo8 set volume -20 -t output2
python evoctl.py mixer input1 --volume -6 --pan 0
python evoctl.py --device evo8 mixer output3_4 --volume 0 --mix-output 1
python evoctl.py set monitor 50  # EVO 4 only
python evotui.py --device evo8
```

After `pipx install path/to/audient-evo-py`:

```bash
evoctl --help
evoctl set volume -20
evoctl --device evo8 mixer output5_6 --volume 0 --mix-output 0
evotui --device evo4
```

Use `--device evo4` or `--device evo8` when both devices are installed and connected.

## Build And Install

Python commands:

```bash
python -m pip install -e .[dev]
python -m pip install -e .[dev,audio-test]  # audio tests only
pipx install path/to/audient-evo-py
```

Kernel module:

```bash
sudo ./kmod/install.sh
```

Optional WirePlumber config:

```bash
bash wireplumber/install.sh
```

## Tests

Default tests do not touch hardware, audio devices, or manual prompts:

```bash
python -m pytest
python -m pytest -m unit
```

Focused unit tests:

```bash
python -m pytest tests/test_kmod.py tests/test_devices.py tests/test_config.py tests/test_evoctl.py
```

Opt-in hardware tests:

```bash
python -m pytest --hardware --device evo4 -m hardware
python -m pytest tests/test_mixer_audio.py --hardware --audio --device evo4
python -m pytest tests/test_controller.py --hardware --manual --device evo4 -m manual
python -m pytest tests/test_mixer_mic.py -s --hardware --audio --manual --device evo4
```

Markers:
- `unit`: no hardware, audio stack, or manual input.
- `hardware`: connected EVO device and `evo_raw`.
- `audio`: optional `numpy` and `sounddevice`, PipeWire audio devices.
- `manual`: interactive input or hardware-risk checks.

## Language Server And Formatting

Pyright/basedpyright language server:

```bash
pyright-langserver --stdio
```

Type check:

```bash
pyright .
```

Format and lint with Ruff:

```bash
ruff format .
ruff check .
```

`pyproject.toml` contains `tool.basedpyright` and `tool.ruff` settings.

## Conventions

Code:
- Prefer simple flow and short names.
- Prefer less code when behavior stays clear.
- Use comments for non-obvious behavior only.
- Keep hardware, audio, and manual tests opt-in.
- Refactors should strive to leave less code and fewer comments than before.

Docs:
- Use short phrases over descriptive sentences.
- Use examples over long descriptions.
- Keep facts current with the code.
- Avoid speculative EVO 8 claims unless they are marked as validation notes.
