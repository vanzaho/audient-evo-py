# Done

## Task 17.5: Codex agent docs

State:
- `AGENTS.md` now contains the current agent-facing project facts.
- `CLAUDE.md` now only points to `AGENTS.md`, matching Claude convention.
- The agent docs cover the important directory structure, Python and pipx command examples, build/install commands, test commands and markers, language-server/type-check commands, Ruff formatting commands, and the simplicity/readability conventions.

Why:
- Task 17 had already refreshed `CLAUDE.md` with the current EVO 4/EVO 8 project facts.
- Task 17.5 needed that content moved into the agent-standard `AGENTS.md` file while keeping `CLAUDE.md` as a lightweight pointer.

Changed:
- Added `AGENTS.md`.
- Replaced the detailed `CLAUDE.md` body with `See [AGENTS.md](AGENTS.md).`
- Removed Task 17.5 from the remaining plan and left Task 18 as the only open task.

Verified:
- `git diff --check -- AGENTS.md CLAUDE.md IMPROVEMENT_PLAN.md IMPROVEMENT_PLAN_DONE.md`
- Re-read `AGENTS.md`, `CLAUDE.md`, `IMPROVEMENT_PLAN.md`, and this done entry.

Reassessed:
- Task 18 remains valid but was tightened: `dev/probe.py` and `dev/probe_mixer.py` already import from `evo`, but still hard-code EVO 4 paths and EVO 4 wording. `dev/README.md` does not exist yet.

## Task 17: Architecture docs refresh

State:
- Architecture docs now describe the shared `evo_raw` module and the current `evo` package instead of the old EVO 4-only names.
- The architecture diagram shows both `/dev/evo4` and `/dev/evo8`, and names `EVOController`.
- Status blob docs now describe the variable per-device packing decoded through `DeviceSpec`, rather than the old fixed 12-byte EVO 4 layout.
- EVO 8 implementation notes include the current `DeviceSpec.has_monitor=False` field.
- `CLAUDE.md` now points to `dev/DESIGN.md`, uses current CLI/TUI examples, and documents current opt-in test flags.

Why:
- Task 16 refreshed user docs, leaving the developer/agent-facing docs as the remaining stale surface.
- Tasks 1-6.5 and EVO 8 work changed module/package names, device paths, controller naming, status packing, and test opt-in behavior.

Changed:
- Updated `dev/DESIGN.md` architecture, ioctl, module, device-node, and status blob sections.
- Updated `dev/evo8-implementation.md` `DeviceSpec` snippet.
- Rewrote `CLAUDE.md` around the current shared EVO 4/EVO 8 package layout and commands.
- Reassessed the remaining plan: Task 17.5 should now copy the renewed `CLAUDE.md` into `AGENTS.md`; Task 18 is unaffected.

Verified:
- `git diff --check -- dev/DESIGN.md dev/evo8-implementation.md CLAUDE.md`
- `rg -n "evo4_raw|EVO4Controller|evo4/controller|evo4/kmod|kmod/evo4_raw|Status Struct|EVO4_CTRL_TRANSFER|struct evo4_ctrl|12 bytes in format|<hhhBBBBBB" dev/DESIGN.md dev/evo8-implementation.md CLAUDE.md` returned no matches.
- `python -B evoctl.py --device evo8 set volume --help`
- `python -B evoctl.py --device evo8 mixer output3_4 --help`
- `python -B evoctl.py --device evo8 --help`
- Confirmed `AGENTS.md` does not exist yet, so Task 17.5 remains needed.

## Task 16: User docs refresh

State:
- User docs now use current dB-based volume/gain examples.
- README documents `--device`, mixer source keys, EVO 8 mixer destinations, and EVO 8 output/loopback routing.
- WirePlumber docs cover both EVO 4 and EVO 8, reference the real `wireplumber/install.sh`, and describe the main-output default sink strategy.
- WirePlumber reconnect scripts set the explicit `evo4_main_output` / `evo8_main_output` sinks as defaults, matching the docs and installer strategy.
- EVO 8 testing docs keep the presumed single-EVO setup, mention `--device evo8` only for multi-device setups, and use the current opt-in hardware/audio/manual pytest flags.

Why:
- Tasks 11-13 changed dependency and test opt-in commands.
- Tasks 1-3 changed mixer naming to `output1_2`, `output3_4`, `output5_6`, with `--mix-output` selecting the destination bus.
- Current WirePlumber config defines explicit main-output nodes for both devices, so the docs should not describe the old EVO 4-only setup.

Changed:
- Updated README install, WirePlumber, usage, mixer, and test command sections.
- Rewrote `wireplumber/README.md` around the current per-device configs and installer.
- Updated `wireplumber/evo4/evo4-setup.sh` and `wireplumber/evo8/evo8-setup.sh` to use the explicit main-output nodes.
- Updated `dev/EVO8-TESTING.md` install, mixer, and test-suite commands.

Verified:
- `python -B evoctl.py --help`
- `python -B evoctl.py --device evo4 --help`
- `python -B evoctl.py --device evo8 mixer --help`
- `python -B evoctl.py --device evo8 mixer input1 --help`
- `python -B evoctl.py --device evo8 mixer output1_2 --help`
- `python -B evoctl.py --device evo8 mixer output5_6 --help`
- `python -B evoctl.py --device evo4 mixer output3_4 --help`
- `bash -n wireplumber/install.sh wireplumber/uninstall.sh wireplumber/evo4/evo4-setup.sh wireplumber/evo8/evo8-setup.sh`
- `git diff --check`

## Task 14: TUI compaction

State:
- `evotui.py` remains a single-file TUI after user direction to avoid splitting it for now.
- The implementation is shorter and more direct, with no intentional behavior change.
- Invalid mixer shadow state no longer crashes TUI startup; the TUI keeps defaults and reports a status error.

Why:
- The planned split was superseded by a request to first make clear, low-risk refactor/shortening wins while preserving behavior.
- Keeping it single-file avoided package/install churn while still reducing the largest obvious duplication.

Changed:
- Removed unused drawing constants, helper methods, and slider-map state.
- Added shared clamp and hint-rendering helpers.
- Consolidated file-picker movement, two-column controls rendering, tab selection rendering, and demo-controller state setup.
- Kept the `evotui` entry point stable.

Verified:
- `python -B -m py_compile evotui.py`
- `python -B -c "from evotui import DemoController, EvoTUI; from evo.devices import DEVICES; [EvoTUI(DemoController(DEVICES[name])) for name in ('evo4','evo8')]; print('ok')"`
- `python -B -c "import ast, pathlib; ast.parse(pathlib.Path('evotui.py').read_text(), filename='evotui.py'); print('ast ok')"`
- `python -B -m pytest -p no:cacheprovider tests/test_evoctl.py`
- `python -B evotui.py --help`
- `python -B evotui.py --demo --device evo4` and `python -B evotui.py --demo --device evo8` started, showed the expected too-small-terminal message in the 80x24 test TTY, and exited cleanly with `q`.
- `git diff --check`

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
