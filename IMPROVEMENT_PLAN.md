# Improvement Plan

Rules:
- Minimal simple architecture, code, docs.
- No compatibility unless it makes code simpler.
- Short names, simple flow, self-documenting code.
- Comments only for non-obvious behavior.
- Keep hardware/audio/manual tests opt-in.
- Treat EVO 8 unverified protocol notes as hardware-validation work.
- Refactor and simplify heavily where possible. Less word/lines is better.

### Task 18: Dev probe scripts

Files: `dev/probe.py`, `dev/probe_mixer.py`, maybe `dev/README.md`.

Do:
- Imports already use `evo`; remove stale EVO 4-only aliases/wording where needed.
- Add `--device`.
- Use `DeviceSpec` for `/dev/evo4` and `/dev/evo8`.
- Move/mark historical-only scripts.

Check:
- `python dev/probe.py --device evo4 ...` imports.
- `python dev/probe_mixer.py --device evo4` imports.
- Historical tools not presented as current commands.

## Order

1. Task 18.
