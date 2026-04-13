# Improvement Implementation Plan

This plan converts the project assessment into implementation-ready tasks. The
order is intentional: fix shared contracts first, then user-facing behavior,
then tooling and documentation.

VERY IMPORTANT!: The architecture, code and documentation needs to be as unambiguous, minimal and readable as it can be with respect to the implemented features.

VERY IMPORTANT!: No backwards compatibility - make implementation as clean and minimal as possible. Breaking changes are encouraged if final solution is simpler.

## Phase 1 - Stabilize Shared Contracts

### Task 3: Add controller validation for mixer addressing

Goal: prevent invalid mixer destination or USB output source values from writing
valid but wrong crosspoints.

Files:
- `evo/controller.py`
- `tests/test_controller.py`

Implementation:
- Validate `mix_output` in `set_mixer_input()` and `set_mixer_output()`.
- Validate `output_pair` in `set_mixer_output()` against all mixer output sources
  (`output1_2`, `output3_4`, and `output5_6` on EVO 8).
- Do not add compatibility wrappers for removed route names.
- Validate pan and volume consistently, or document and test clamping behavior.
- Add no-hardware unit tests for invalid `mix_output`, invalid `output_pair`, and
  boundary values.

Acceptance checks:
- Invalid `mix_output` raises `ValueError` for input and output methods.
- Invalid `output_pair` raises `ValueError`.
- Existing valid mixer calls still compute the same crosspoints.

## Phase 2 - Fix User-Facing CLI and Runtime Behavior

### Task 4: Make global CLI help work without hardware

Goal: `evoctl --help` should not require `/dev/evo*`.

Files:
- `evoctl.py`
- tests for CLI parsing, if added

Implementation:
- Split global parser construction from device-specific parser construction.
- Detect `--help`, `-h`, before device resolution.
- Keep device-specific subcommand choices after `--device` or autodetection.
- Consider adding `evoctl --device evo4 --help` and `evoctl --device evo8 --help`
  examples to docs.

Acceptance checks:
- `python evoctl.py --help` succeeds without hardware.
- `python evoctl.py --device evo4 --help` still shows EVO 4-specific commands.
- `python evoctl.py --device evo8 --help` still shows EVO 8-specific commands.

### Task 5: Use a shared fd for CLI operations

Goal: reduce open/close churn and avoid the transfer-storm issue described in
the design notes.

Files:
- `evoctl.py`

Implementation:
- Replace `evo = EVOController(spec); _run(args, evo)` with:
  - `with EVOController(spec) as evo: _run(args, evo)`
- Review save/load/mixer commands for multi-transfer paths and keep them inside
  the controller context.

Acceptance checks:
- Existing CLI commands still work.
- Multi-transfer operations such as `status`, `save`, `load`, and `mixer output`
  reuse one open device fd.

### Task 6: Finish CLI mixer route documentation and parser tests

Goal: make the new explicit mixer route syntax documented and protected by tests.

Files:
- `evoctl.py`
- `README.md`
- tests, if CLI parsing tests are added

Implementation:
- Add CLI parser tests for the explicit stereo output source commands:
  `output1_2`, `output3_4`, and `output5_6`.
- Document `--mix-output` as the mixer destination selector.
- Update README examples to use stereo-pair names instead of the removed
  `mixer output` / `mixer loopback` commands.

Acceptance checks:
- `evoctl --device evo8 mixer output1_2 --volume 0 --mix-output 0` routes OUT 1|2.
- `evoctl --device evo8 mixer output3_4 --volume 0 --mix-output 1` routes OUT 3|4.
- `evoctl --device evo8 mixer output5_6 --volume 0 --mix-output 0` routes OUT 5|6.
- Saved mixer state represents output source and mixer destination identity explicitly.

IMPORTANT NOTE: The implementation now distinguishes USB output sources
(`output1_2`, `output3_4`, `output5_6`) from mixer destinations (`--mix-output`).
Do not reintroduce a standalone `loopback` mixer section; use the stereo output
source label with explanatory text only where needed.

### Task 6.5: Remove diag command from evoctl and all docs

Should be implemented as dev/ shell script, not cluttering python codebase.

## Phase 3 - Kernel Module Safety

### Task 7: Fix open-file lifetime on disconnect

Goal: avoid use-after-free when a process keeps `/dev/evo*` open and the USB
device disconnects.

Files:
- `kmod/evo_raw.c`
- kernel-module test notes/docs

Implementation:
- Add `.release` file operation.
- Add reference counting or equivalent lifetime management for `struct evo_device`.
- On disconnect, deregister the misc device and set `udev = NULL`, but do not free
  the structure until all open files are released.
- Keep ioctl returning `-ENODEV` after disconnect.

Acceptance checks:
- With `evotui` running, unplugging the device does not crash or warn in dmesg.
- Subsequent ioctl calls after unplug return a device-disconnected error.
- Replugging creates the misc device again.

### Task 8: Review zero-length and ioctl edge cases

Goal: harden the kernel/userspace boundary.

Files:
- `kmod/evo_raw.c`
- `evo/kmod.py`
- `tests/test_kmod.py`

Implementation:
- Decide how zero-length transfers should behave; avoid treating `kmalloc(0)` as
  an allocation failure if zero-length transfers are allowed.
- Ensure userspace refuses payloads over 256 bytes before ioctl.
- Add tests for oversize payloads and explicit zero-length behavior.

Acceptance checks:
- Oversize transfers fail with a clear userspace error before ioctl.
- Kernel behavior for zero-length requests is documented and tested where possible.

## Phase 4 - WirePlumber and Audio Routing

### Task 9: Pick one default sink strategy and apply it everywhere

Goal: stop install-time and login-time setup from choosing different sinks.

Files:
- `wireplumber/install.sh`
- `wireplumber/evo4/evo4-setup.sh`
- `wireplumber/evo8/evo8-setup.sh`
- `wireplumber/evo4/evo4-stereo.conf`
- `wireplumber/evo8/evo8-stereo.conf`
- `wireplumber/README.md`

Implementation:
- Decide whether the default sink should be the virtual stereo sink
  (`evo4_main_output` / `evo8_main_output`) or the raw ALSA sink with upmix
  disabled.
- Update setup scripts and installer to target the same sink.
- Update comments and docs to match the chosen strategy.

Acceptance checks:
- `wireplumber/install.sh` and login setup produce the same default sink.
- `wpctl status` shows the intended default sink and source.
- Loopback output remains a separate sink.

IMPORTANT NOTE: Before proceeding with implementation, explain in detail what's the problem here and what is the proposed solution.

### Task 10: Make WirePlumber node matching less brittle

Goal: reduce failures across kernel, ALSA, and PipeWire naming variations.

Files:
- `wireplumber/evo4/*.conf`
- `wireplumber/evo8/*.conf`
- setup scripts
- audio tests

Implementation:
- Replace hardcoded exact node targets where possible with stable matching or
  generated target discovery.
- Verify EVO 8 `analog-surround-51` naming on hardware and document confirmed
  behavior.
- Keep test node names in one shared location or derive them from installed config.

Acceptance checks:
- EVO 4 and EVO 8 setup scripts find the expected nodes after reconnect.
- Audio tests use the same node naming contract as installed configs.

IMPORTANT NOTE: Before proceeding with implementation, explain in detail what's the problem here and what is the proposed solution.


## Phase 5 - Tests and Tooling

### Task 11: Add reproducible dev/test dependencies

Goal: let a new contributor run the test suite from project metadata.

Files:
- `pyproject.toml`
- `README.md`
- test docs

Implementation:
- Add optional dependency groups:
  - `dev`: `pytest`
  - `audio-test`: `numpy`, `sounddevice`
- Document install commands such as `pipx inject` or `python -m pip install -e .[dev]`.
- Add a short test matrix to README.

Acceptance checks:
- `python -m pip install -e .[dev]` installs unit-test tooling.
- `python -m pytest tests/test_kmod.py tests/test_devices.py` runs without hardware.

### Task 12: Mark and isolate hardware/audio/manual tests

Goal: prevent accidental invasive test runs. Especially phantom power tests should be very explicit and require manual approval.

Files:
- `pyproject.toml`
- `tests/conftest.py`
- `tests/test_controller.py`
- `tests/test_mixer_audio.py`
- `tests/test_mixer_mic.py`

Implementation:
- Add pytest markers: `unit`, `hardware`, `audio`, `manual`.
- Make optional audio dependencies use `pytest.importorskip()` or skip at collection.
- Require an explicit flag or marker selection for manual mic tests.
- Add docs for safe test commands.

Acceptance checks:
- Unit tests can be collected/run without `numpy`, `sounddevice`, or hardware.
- Hardware tests are clearly opt-in.
- Manual tests cannot block an unattended test run.

### Task 13: Preserve user mixer state in audio tests

Goal: avoid leaving the device in a modified mixer state after tests.

Files:
- `tests/test_mixer_audio.py`
- `tests/test_mixer_mic.py`
- possibly `evo/config.py`

Implementation:
- Snapshot current mixer shadow state before tests.
- Apply a test-specific mixer state.
- Restore the previous mixer state after each test or module.
- If hardware readback is impossible, restore from the shadow file and document the
  limitation.

Acceptance checks:
- Running audio tests does not leave all crosspoints muted.
- Test cleanup runs even after assertion failures.

## Phase 6 - Code Organization

### Task 14: Split the TUI into smaller modules

Goal: reduce the maintenance cost of `evotui.py`.

Files:
- `evotui.py`
- new `evo/tui_*.py` modules or `evo/tui/`

Implementation:
- Split into:
  - layout/state construction
  - mixer state adapter
  - rendering primitives
  - input handling
  - file picker
  - demo controller
- Keep the `evotui` console entry point stable.
- Do this after mixer schema stabilization to avoid moving unstable code twice.

Acceptance checks:
- `evotui --demo --device evo4` still starts.
- `evotui --demo --device evo8` still starts.
- No behavior changes beyond imports and structure.

IMPORTANT NOTE: while doing this, I want to refactor for minimal code size and maximal
readability. Code should be self-documenting, comment only when neccessary.

### Task 15: Add atomic config writes and clearer config errors

Goal: make config files harder to corrupt and easier to troubleshoot.

Files:
- `evo/config.py`
- tests

Implementation:
- Write JSON to a temporary file and rename atomically.
- Catch JSON decode errors and include the file path in the exception message.
- Validate required keys before applying partial configs, or explicitly document
  partial config support.

Acceptance checks:
- Corrupt JSON reports a useful error.
- Config writes are atomic on the same filesystem.
- Partial configs behave consistently and are tested.

## Phase 7 - Documentation and Dev Tools

### Task 16: Refresh user-facing docs

Goal: make docs match the current EVO 4/8 codebase.

Files:
- `README.md`
- `wireplumber/README.md`
- `dev/EVO8-TESTING.md`

Implementation:
- Correct command examples, especially hardware volume units.
- Document `--device` behavior, mixer buses, and EVO 8 output pair routing.
- Document the chosen WirePlumber default sink strategy.
- Add safe test commands and dependency installation commands.

Acceptance checks:
- Every command in the README maps to a real parser command.
- WirePlumber install instructions reference the actual installer.
- EVO 8 testing notes match current CLI syntax.

### Task 17: Refresh architecture docs

Goal: remove EVO 4-only names from docs that now describe shared EVO series code.

Files:
- `dev/DESIGN.md`
- `dev/evo8-implementation.md`
- `CLAUDE.md`

Implementation:
- Rename `evo4_raw` references to `evo_raw` where describing current code.
- Update `/dev/evo4`-only diagrams to show `/dev/evo4` and `/dev/evo8`.
- Replace `EVO4Controller` with `EVOController`.
- Update status-blob documentation to explain variable per-device packing.

Acceptance checks:
- Architecture docs match current package/module names.
- No stale `evo4/` package references remain outside historical notes.

### Task 17.5: Add ChatGPT Codex equivalent of CLAUDE.md

After renewing CLAUDE.md, make copy of it as AGENTS.md or whatever the default file is for Codex. 


### Task 18: Repair or archive dev probe scripts

Goal: make reverse-engineering tools either runnable or clearly historical.

Files:
- `dev/probe.py`
- `dev/probe_mixer.py`
- `dev/README.md` if added

Implementation:
- Update imports from `evo4` to `evo`.
- Add device selection via `--device`.
- Use `DeviceSpec` for `/dev/evo4` and `/dev/evo8`.
- If a script is intentionally historical, move it under a clearly named archive
  or mark it as such in its header.

Acceptance checks:
- `python dev/probe.py --device evo4 ...` imports successfully.
- `python dev/probe_mixer.py --device evo4` imports successfully.
- Historical-only tools are not presented as current commands.

## Suggested Implementation Order

1. Task 3 - Add controller validation for mixer addressing.
2. Task 4 - Make global CLI help work without hardware.
3. Task 5 - Use a shared fd for CLI operations.
4. Task 6 and 6.5 - Finish CLI mixer route documentation/parser tests and remove diag.
5. Task 11 - Add reproducible dev/test dependencies.
6. Task 12 - Mark and isolate hardware/audio/manual tests.
7. Task 13 - Preserve user mixer state in audio tests.
8. Task 9 - Pick one WirePlumber default sink strategy and apply it everywhere.
9. Task 10 - Make WirePlumber node matching less brittle.
10. Task 7 - Fix open-file lifetime on disconnect.
11. Task 8 - Review zero-length and ioctl edge cases.
12. Task 15 - Add atomic config writes and clearer config errors.
13. Task 14 - Split the TUI into smaller modules.
14. Task 16 - Refresh user-facing docs.
15. Task 17 - Refresh architecture docs.
16. Task 18 - Repair or archive dev probe scripts.

## Notes

- Do not run invasive hardware/audio tests by default.
- Do not keep backwards compatibility for existing mixer state files.
- Treat EVO 8 protocol areas marked unverified in `dev/evo8-protocol-discrepancies.md`
  as hardware-validation tasks, not pure refactors.
