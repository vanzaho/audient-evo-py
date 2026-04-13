# Completed Improvement Tasks

## Phase 1 - Stabilize Shared Contracts

### Task 1: Define one mixer state schema

Implemented a single versioned mixer shadow schema in `evo.config`:

- top-level `version`
- top-level `buses`
- per bus: `inputs`, `outputs`, and `loopback`
- per output: explicit zero-based `output_pair`, `volume`, `pan_l`, and `pan_r`

Why:
- The previous persisted mixer state had three incompatible forms: EVO 4 flat keys,
  EVO 8 TUI `bus_*` keys, and CLI `name:bus` keys.
- The canonical schema makes the bus and output-pair identity explicit, so config
  save/load, auto-load, CLI, and TUI have one contract to target.
- Backwards compatibility was intentionally not preserved because the active plan
  called for dropping the legacy mixer state formats.

Actual changes:
- Added `MIXER_STATE_VERSION`, `default_mixer_state()`, and schema checks to
  `evo/config.py`.
- Made `save_mixer_state()` and `load_mixer_state()` round-trip only the canonical
  mixer state.
- Updated `config.apply()` to apply canonical mixer state across all buses and
  output pairs.
- Updated the current CLI mixer save path to write the canonical schema.
- Updated the TUI load/save adapters to read/write the canonical schema while
  keeping its existing internal UI state names.
- Added no-hardware config tests for schema shape and round-trip persistence.

Verified:
- `python -m pytest tests/test_config.py`
- `python -m pytest tests/test_config.py tests/test_devices.py`
- `python -m py_compile evo/config.py evoctl.py evotui.py tests/test_config.py`

### Task 2: Use shared mixer state in CLI and TUI

Implemented the shared mixer state work, adjusted to remove `loopback` as a
separate mixer route:

- The mixer shadow schema is now version 2.
- Top-level mixer state uses `mix_outputs` for mixer destinations.
- Each mix output contains `inputs` and `outputs`.
- `outputs` are stereo USB output source pairs such as `output1_2`, `output3_4`,
  and `output5_6`.
- EVO 4's single mixer destination is keyed by its loopback capture pair
  (`mix3_4`); EVO 8 destinations are `mix1_2` and `mix3_4`.

Why:
- The previous Task 1 schema still treated `loopback` as a separate peer of
  `outputs`, but the hardware model is simpler: the device loopback path is just
  the final stereo USB output source pair (`output3_4` on EVO 4, `output5_6` on
  EVO 8).
- Separating `outputs` from `mix_outputs` avoids the old mixer-destination ambiguity:
  output source identity and mixer destination identity are now explicit.

Actual changes:
- Added shared mixer helpers to `evo/config.py` for output source keys,
  mix-output keys, default state, loading defaults, flat views, and route updates.
- Updated `config.apply()` to restore `mix_outputs[*].inputs` and
  `mix_outputs[*].outputs` without a special loopback branch.
- Changed `EVOController.set_mixer_output()` to route every stereo USB output
  source pair, including the final loopback-labeled pair.
- Removed the old loopback-specific controller wrapper.
- Updated `evoctl mixer` to expose `output1_2`, `output3_4`, and `output5_6`
  commands, with `--mix-output` as the only mixer destination selector.
- Updated `evotui` to hold canonical mixer state directly instead of translating
  through private `main` / `loopback` adapter keys.
- Updated no-hardware config tests, hardware test call sites, and EVO 8 dev notes
  to use the new output-source model.

Verified:
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_config.py`
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider tests/test_controller.py -k TestDbConversions`
- `python -m py_compile evo/config.py evo/controller.py evoctl.py evotui.py tests/test_config.py tests/test_controller.py tests/test_mixer_audio.py`
- `PYTHONDONTWRITEBYTECODE=1 python evoctl.py --device evo8 mixer --help`
- `PYTHONDONTWRITEBYTECODE=1 python evoctl.py --device evo8 mixer output5_6 --help`
- `PYTHONDONTWRITEBYTECODE=1 python evoctl.py --device evo4 mixer --help`
