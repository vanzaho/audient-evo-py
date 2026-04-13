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
