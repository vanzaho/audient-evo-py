# Done

## Task 15: Atomic config writes/errors

State:
- Config and mixer-state saves now write JSON to a same-directory temp file, then replace the target path.
- Corrupt config or mixer-state JSON raises `ValueError` with the path included.
- Partial non-mixer configs remain supported and tested.
- Mixer configs keep the existing lightweight schema check instead of adding full preflight validation.

Why:
- Task 13 restores mixer state through `config.apply()`, so `.mixer-state.json` rewrites need the same atomic write path as normal config saves.
- Keeping partial configs preserves the current load behavior without adding extra schema machinery.

Changed:
- Added small `_read_json()` and `_write_json()` helpers in `evo/config.py`.
- Reused `_write_json()` from `save()` and `save_mixer_state()`.
- Reused `_read_json()` from `load()` and `load_mixer_state()`.
- Added tests for corrupt JSON path errors, same-directory temp replacement, and partial config apply behavior.

Verified:
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_config.py`

## Task 13: Preserve mixer state in audio tests

State:
- Opt-in mixer audio and mic tests now load the canonical mixer shadow before each test, falling back to the default muted state when no shadow exists.
- Each test still starts from a muted MU60 matrix.
- Fixture cleanup restores that loaded/default mixer state through `config.apply()`, so cleanup runs even when a test assertion fails.
- The test docs state the important limit: MU60 has no reliable hardware readback, so restore is only as accurate as the saved shadow state.

Why:
- Task 12 made these tests explicitly opt-in, but running them still should not leave the user's mixer crosspoints muted.
- Direct MU60 test writes do not update the shadow file, so the fixture keeps the saved shadow separate from the temporary test matrix.

Changed:
- Replaced post-test mute cleanup in `tests/test_mixer_audio.py` with an autouse fixture that loads `load_or_default_mixer_state()`, mutes all crosspoints for the test, and restores that state in a `finally` block.
- Applied the same restore fixture pattern in `tests/test_mixer_mic.py`.
- Documented the shadow-state restore limit in both mixer test module docstrings.

Verified:
- `python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(), filename=p) for p in ['tests/test_mixer_audio.py','tests/test_mixer_mic.py']]"`
- `python -B -m pytest -p no:cacheprovider tests/test_mixer_audio.py tests/test_mixer_mic.py` (23 skipped without `--hardware --audio --manual`, as expected)

## Task 12: Isolate hardware/audio/manual tests

State:
- Pytest now has registered `unit`, `hardware`, `audio`, and `manual` markers.
- Hardware, audio, and manual tests are skipped unless their explicit flags are passed.
- Unmarked tests are marked as `unit` during collection, so `-m unit` selects the no-hardware suite.
- Audio test modules use `pytest.importorskip()` for `numpy` and `sounddevice`, so missing optional deps skip instead of failing import.
- Manual mic tests and phantom-power controller tests require `--manual`.
- README and test module docstrings document safe opt-in commands.

Why:
- The default test run must not open hardware, require PipeWire/audio deps, prompt for input, or toggle phantom power.
- Task 11 made audio dependencies optional, so collection needed to tolerate environments without `numpy` and `sounddevice`.

Changed:
- Added `[tool.pytest.ini_options]` marker registration in `pyproject.toml`.
- Added `--hardware`, `--audio`, `--manual`, and collection-time skip/unit marking in `tests/conftest.py`.
- Marked hardware controller classes in `tests/test_controller.py`; marked phantom-power tests as manual.
- Marked mixer audio tests as `hardware` + `audio`; marked mic tests as `hardware` + `audio` + `manual`.
- Replaced top-level `numpy`/`sounddevice` imports with `pytest.importorskip()` in mixer audio/mic tests.
- Updated README test commands to include the explicit opt-in flags.

Verified:
- `python -B -m pytest -p no:cacheprovider`
- `python -B -m pytest -p no:cacheprovider -m unit`

## Task 11: Reproducible deps

State:
- Test dependencies are declared as package extras.
- README documents pipx and editable-install commands for dev and audio-test dependencies.
- README has a compact test matrix for no-hardware, hardware, audio, and manual mic tests.
- Test isolation markers and unattended collection behavior remain for Task 12.

Why:
- Tests previously depended on whatever happened to be installed in the developer environment.
- Audio dependencies are optional because `numpy` and `sounddevice` are only needed for mixer audio/mic tests.

Changed:
- Added `[project.optional-dependencies]` in `pyproject.toml`: `dev = ["pytest"]`, `audio-test = ["numpy", "sounddevice"]`.
- Added README commands for `pipx inject audient-evo pytest`, `pipx inject audient-evo numpy sounddevice`, `python -m pip install -e .[dev]`, and `python -m pip install -e .[dev,audio-test]`.
- Added README test matrix with dependency and hardware requirements.

Verified:
- `python -B -c "import pathlib, tomllib; data=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); print(data['project']['optional-dependencies'])"`
- `python -m pip install -e .[dev]`
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_kmod.py tests/test_devices.py`
- `git diff --check`

## Task 0: Compactness pass

State:
- Recently changed mixer schema, controller, and CLI paths are smaller and a bit more direct.
- No behavior change intended.
- Later work is unchanged: dependency/test isolation, atomic writes, TUI split, docs, and dev tools still remain.

Why:
- Completed Tasks 1-6.5 left duplicated range checks, status packing loops, and redundant comments in hot paths.
- The compactness pass was scoped to those touched areas instead of doing a broad repo rewrite.

Changed:
- `default_mixer_state()` now builds the versioned mixer state directly.
- Added small config validation helpers for mixer destination, input number, and USB output source pair.
- Simplified controller target setup, signed raw conversion, output volume writes, status packing, and mixer route bounds checks.
- Renamed the private mixer output-count field for clarity.
- Fixed `evoctl save/load --help` path text from `Defa` to `Default`.

Verified:
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_config.py`
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_controller.py -k 'DbConversions or PanLaw or MixerValidation'`
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_evoctl.py`
- `python -B -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(), filename=p) for p in ['evo/config.py','evo/controller.py','evoctl.py']]"`
- `python -B -c "from unittest.mock import patch; from evo.controller import EVOController; from evo.devices import EVO8; p=patch('evo.controller.exists', return_value=True); p.start(); calls=[]; e=EVOController(EVO8); e._set_fu_raw=lambda unit, cn, raw: calls.append((unit, cn, raw)); e.set_volume(-12.0); p.stop(); print(calls)"`
- `git diff --check`

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
