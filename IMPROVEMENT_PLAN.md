# Improvement Plan

Rules:
- Minimal architecture, code, docs.
- No compatibility unless it makes code simpler.
- Short names, simple flow, self-documenting code.
- Comments only for non-obvious behavior.
- Keep hardware/audio/manual tests opt-in.
- Treat EVO 8 unverified protocol notes as hardware-validation work.

## Task 0: Compactness pass

Files: all touched code/docs.

Do:
- Refactor for smaller, clearer code.
- Remove redundant comments/docs.
- Prefer direct data flow over adapters/wrappers.
- Use plain words, lists, examples.

Check:
- Less code/text for same behavior.
- No stale docs.
- Tests still cover changed behavior.

## Phase 5 - Tests/tooling

### Task 11: Reproducible deps

Files: `pyproject.toml`, `README.md`, test docs.

Do:
- Optional deps: `dev = pytest`; `audio-test = numpy, sounddevice`.
- Docs: `pipx inject` or `python -m pip install -e .[dev]`.
- README test matrix.

Check:
- `python -m pip install -e .[dev]` installs unit-test tooling.
- `python -m pytest tests/test_kmod.py tests/test_devices.py` works without hardware.

### Task 12: Isolate hardware/audio/manual tests

Files: `pyproject.toml`, `tests/conftest.py`, `tests/test_controller.py`, `tests/test_mixer_audio.py`, `tests/test_mixer_mic.py`.

Do:
- Markers: `unit`, `hardware`, `audio`, `manual`.
- Skip missing audio deps at collection or via `pytest.importorskip()`.
- Require explicit flag/marker for manual mic tests, especially phantom power.
- Docs: safe test commands.

Check:
- Unit tests collect/run without `numpy`, `sounddevice`, hardware.
- Hardware tests opt-in.
- Manual tests never block unattended run.

### Task 13: Preserve mixer state in audio tests

Files: `tests/test_mixer_audio.py`, `tests/test_mixer_mic.py`, maybe `evo/config.py`.

Do:
- Snapshot mixer shadow state.
- Apply test state.
- Restore after each test/module.
- If no hardware readback, restore from shadow file and document limit.

Check:
- Audio tests do not leave crosspoints muted.
- Cleanup runs after failures.

## Phase 6 - Code organization

### Task 14: Split TUI

Files: `evotui.py`, new `evo/tui_*.py` or `evo/tui/`.

Do:
- Split layout/state, mixer adapter, rendering, input, file picker, demo controller.
- Keep `evotui` entry point stable.
- Do after mixer schema is stable.
- Refactor for minimal size/readability; comment only when needed.

Check:
- `evotui --demo --device evo4` starts.
- `evotui --demo --device evo8` starts.
- No behavior change except imports/structure.

### Task 15: Atomic config writes/errors

Files: `evo/config.py`, tests.

Do:
- Write JSON temp file, then rename.
- JSON decode errors include path.
- Validate required keys before apply, or document/test partial configs.

Check:
- Corrupt JSON error useful.
- Writes atomic on same filesystem.
- Partial config behavior consistent/tested.

## Phase 7 - Docs/dev tools

### Task 16: User docs refresh

Files: `README.md`, `wireplumber/README.md`, `dev/EVO8-TESTING.md`.

Do:
- Fix command examples, especially volume units.
- Document `--device`, mixer buses, EVO 8 output-pair routing.
- Document WirePlumber default sink strategy.
- Add safe test/dependency commands.

Check:
- README commands map to real parser commands.
- WirePlumber docs reference real installer.
- EVO 8 notes match current CLI syntax.

### Task 17: Architecture docs refresh

Files: `dev/DESIGN.md`, `dev/evo8-implementation.md`, `CLAUDE.md`.

Do:
- Current-code refs: `evo_raw`, not `evo4_raw`.
- Diagrams: `/dev/evo4` and `/dev/evo8`.
- `EVOController`, not `EVO4Controller`.
- Status blob docs: variable per-device packing.

Check:
- Docs match current package/module names.
- No stale `evo4/` package refs outside historical notes.

### Task 17.5: Codex agent docs

Files: `CLAUDE.md`, `AGENTS.md` or current Codex default.

Do:
- After Task 17, copy renewed `CLAUDE.md` to Codex default file.

### Task 18: Dev probe scripts

Files: `dev/probe.py`, `dev/probe_mixer.py`, maybe `dev/README.md`.

Do:
- Update imports from `evo4` to `evo`.
- Add `--device`.
- Use `DeviceSpec` for `/dev/evo4` and `/dev/evo8`.
- Move/mark historical-only scripts.

Check:
- `python dev/probe.py --device evo4 ...` imports.
- `python dev/probe_mixer.py --device evo4` imports.
- Historical tools not presented as current commands.

## Order

1. Task 0.
4. Tasks 11, 12, 13.
7. Task 15.
8. Task 14.
9. Tasks 16, 17, 17.5, 18.
