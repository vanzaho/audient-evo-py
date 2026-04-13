# Done

## Task 1: One mixer state schema

State:
- `evo.config` owns versioned mixer shadow schema.
- v1: `version`, `buses`; per bus: `inputs`, `outputs`, `loopback`; per output: `output_pair`, `volume`, `pan_l`, `pan_r`.
- No legacy mixer-state compatibility.

Why:
- Old state forms conflicted: EVO 4 flat keys, EVO 8 TUI `bus_*`, CLI `name:bus`.
- New state makes bus/output identity explicit for save/load/autoload/CLI/TUI.

Changed:
- `MIXER_STATE_VERSION`, `default_mixer_state()`, schema checks.
- Canonical `save_mixer_state()` / `load_mixer_state()`.
- `config.apply()` uses canonical buses/output pairs.
- CLI save path writes canonical state.
- TUI adapters read/write canonical state.
- No-hardware config tests.

Verified:
- `python -m pytest tests/test_config.py`
- `python -m pytest tests/test_config.py tests/test_devices.py`
- `python -m py_compile evo/config.py evoctl.py evotui.py tests/test_config.py`

## Task 2: Shared mixer state in CLI/TUI

State:
- Mixer schema v2.
- Top level: `mix_outputs`.
- Each mix output: `inputs`, `outputs`.
- Output sources: `output1_2`, `output3_4`, `output5_6`.
- Mixer destinations: EVO 4 `mix3_4`; EVO 8 `mix1_2`, `mix3_4`.
- Loopback is final stereo USB output source, not separate route.

Why:
- Removes destination/source ambiguity.
- Matches hardware model better than separate `loopback` branch.

Changed:
- Shared config helpers for output keys, mix-output keys, defaults, load defaults, flat views, route updates.
- `config.apply()` restores `mix_outputs[*].inputs` and `mix_outputs[*].outputs`.
- `EVOController.set_mixer_output()` routes all stereo USB output source pairs.
- Removed loopback-specific controller wrapper.
- `evoctl mixer`: `output1_2`, `output3_4`, `output5_6`, `--mix-output`.
- `evotui`: canonical state directly.
- Tests/dev notes updated for output-source model.

Verified:
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_config.py`
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_controller.py -k TestDbConversions`
- `python -m py_compile evo/config.py evo/controller.py evoctl.py evotui.py tests/test_config.py tests/test_controller.py tests/test_mixer_audio.py`
- `PYTHONDONTWRITEBYTECODE=1 python evoctl.py --device evo8 mixer --help`
- `PYTHONDONTWRITEBYTECODE=1 python evoctl.py --device evo8 mixer output5_6 --help`
- `PYTHONDONTWRITEBYTECODE=1 python evoctl.py --device evo4 mixer --help`

## Task 3: Mixer address validation

State:
- `EVOController` bounds-checks mixer destinations and USB output-source pairs.
- Mixer pan is clamped to `[-100, 100]`.
- Mixer crosspoint volume is clamped to `[-128, 6]` dB.

Changed:
- Added no-hardware controller tests for invalid `mix_output`.
- Added no-hardware controller tests for invalid `output_pair`.
- Added crosspoint tests for EVO 4 `output1_2`, EVO 4 `output3_4`, and EVO 8 `output5_6`.
- Added clamping tests for pan and mixer crosspoint volume.

Verified:
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_controller.py -k 'DbConversions or PanLaw or MixerValidation'`

## Tasks 4, 5, 6, 6.5: CLI help/runtime/routes/diag

State:
- `evoctl --help` prints global help without opening or detecting hardware.
- `evoctl --device evo4 --help` and `evoctl --device evo8 --help` stay device-specific.
- CLI commands run inside one `EVOController` context.
- `diag` is no longer an `evoctl` command; dev diagnostics live under `dev/`.

Changed:
- Split global parser setup from device-specific parser setup.
- Added parser/runtime tests for help, context lifetime, and EVO 8 mixer output-source routes.
- Documented `--mix-output` as mixer destination and removed `evoctl diag` from README.
- Moved diagnostics from `evo/diag.py` to `dev/diag.py` with `dev/diag.sh` wrapper.

Verified:
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_evoctl.py`
- `python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(), filename=p) for p in ['evoctl.py','tests/test_controller.py','tests/test_evoctl.py','dev/diag.py']]"`
- `PYTHONDONTWRITEBYTECODE=1 python evoctl.py --help`
- `PYTHONDONTWRITEBYTECODE=1 python evoctl.py --device evo4 --help`
- `PYTHONDONTWRITEBYTECODE=1 python evoctl.py --device evo8 --help`
- `PYTHONDONTWRITEBYTECODE=1 python evoctl.py --device evo8 mixer output5_6 --help`
- `PYTHONDONTWRITEBYTECODE=1 dev/diag.sh`
