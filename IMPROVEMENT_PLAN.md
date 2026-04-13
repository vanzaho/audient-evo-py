# Improvement Plan

Rules:
- Minimal simple architecture, code, docs.
- No compatibility unless it makes code simpler.
- Short names, simple flow, self-documenting code.
- Comments only for non-obvious behavior.
- Keep hardware/audio/manual tests opt-in.
- Treat EVO 8 unverified protocol notes as hardware-validation work.
- Refactor and simplify heavily where possible. Less word/lines is better.

## Phase 6 - Code organization

### Task 14: Split TUI

Files: `evotui.py`, new `evo/tui_*.py` or `evo/tui/`.

Do:
- Split layout/state, mixer adapter, rendering, input, file picker, demo controller.
- Keep `evotui` entry point stable.
- Do after mixer schema is stable.
- Refactor for minimal size/readability; comment only when needed.

Check:
- Remember to reinstall evotui using pipx
- `evotui --demo --device evo4` starts.
- `evotui --demo --device evo8` starts.
- No behavior change except imports/structure.

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

1. Task 14.
2. Tasks 16, 17, 17.5, 18.
