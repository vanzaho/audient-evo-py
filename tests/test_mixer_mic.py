"""Interactive mic input -> loopback mixer tests - requires a connected microphone.

Tests the MU60 input crosspoints by asking the user to make sound
into a physical mic, then verifying the signal appears on the correct
loopback channel(s) based on pan setting.

Signal path under test:
  Microphone -> EVO Input -> MU60 crosspoints -> Loopback In -> PipeWire -> Python

Run with:  pytest tests/test_mixer_mic.py -s --hardware --audio --manual --device evo4
The -s flag is required so interactive prompts are visible.

Requirements:
  - EVO device connected and evo_raw kmod loaded
  - PipeWire running with EVO sinks/sources available
  - A microphone connected to one of the inputs
  - pip: sounddevice, numpy
  - Mixer restore uses the saved shadow state because MU60 has no reliable readback
"""

import time

import pytest

np = pytest.importorskip("numpy")
sd = pytest.importorskip("sounddevice")

from evo.config import apply as apply_config
from evo.config import load_or_default_mixer_state
from evo.controller import _MIXER_DB_MIN

pytestmark = [pytest.mark.hardware, pytest.mark.audio, pytest.mark.manual]

SAMPLE_RATE = 48000
CAPTURE_DURATION = 3.0      # seconds to capture while user makes noise
SETTLE = 0.1                # seconds after mixer changes before capture

# dBFS thresholds (looser than automated tests - analog path adds loss/noise)
PRESENT = -50.0
ABSENT = -60.0

# PipeWire node names by device
# NOTE: EVO 8 names may need adjustment based on tester feedback
_LOOP_CAP_NAMES = {
    "evo4": "EVO4 Loopback",
    "evo8": "EVO8 Loopback",
}


def _find_device(name, kind):
    """Find sounddevice index by exact device description and 'input'/'output'."""
    key = f"max_{kind}_channels"
    for i, d in enumerate(sd.query_devices()):
        desc = d["name"].split(",")[0]
        if desc == name and d[key] > 0:
            return i
    raise RuntimeError(f"No {kind} device named '{name}'")


def rms_dbfs(signal):
    """RMS in dBFS. Returns -120 for digital silence."""
    rms = np.sqrt(np.mean(signal.astype(np.float64) ** 2))
    return 20.0 * np.log10(max(rms, 1e-12))


def trim(captured, trim_s=0.25):
    """Strip leading/trailing samples to avoid transients."""
    n = int(trim_s * SAMPLE_RATE)
    return captured[n:-n] if len(captured) > 2 * n else captured


def levels(captured):
    """Return (left_dBFS, right_dBFS) from stereo capture, after trimming."""
    t = trim(captured)
    return rms_dbfs(t[:, 0]), rms_dbfs(t[:, 1])


def capture_loopback(loop_cap):
    """Record from loopback capture source."""
    frames = int(SAMPLE_RATE * CAPTURE_DURATION)
    cap = sd.rec(frames, samplerate=SAMPLE_RATE, channels=2,
                 device=loop_cap, dtype="float32")
    sd.wait()
    return cap


def prompt_and_capture(pan_desc, loop_cap):
    """Prompt user to make noise, capture loopback, return levels."""
    input(f"\n  Ready to test pan={pan_desc}."
          f" Make continuous sound into the mic, then press Enter...")
    print(f"  Capturing {CAPTURE_DURATION:.0f}s - keep making sound...")
    cap = capture_loopback(loop_cap)
    l, r = levels(cap)
    print(f"  Captured levels: L={l:.1f} dBFS, R={r:.1f} dBFS")
    return l, r


@pytest.fixture(scope="module")
def loop_cap(device_spec):
    name = _LOOP_CAP_NAMES.get(device_spec.name)
    if name is None:
        pytest.skip(f"No loopback capture name configured for {device_spec.name}")
    return _find_device(name, "input")


@pytest.fixture(scope="module")
def input_num(device_spec):
    """Ask the user which input has a mic connected."""
    print()
    options = [str(i + 1) for i in range(device_spec.num_inputs)]
    prompt = f"Which input has a mic connected? [{'/'.join(options)}]: "
    while True:
        ans = input(prompt).strip()
        if ans in options:
            return int(ans)
        print(f"Please enter one of: {', '.join(options)}")


@pytest.fixture(autouse=True)
def preserve_mixer_state(evo, device_spec):
    """Restore the saved mixer shadow after each test."""
    saved = load_or_default_mixer_state(device_spec)

    def _silence_all():
        total = device_spec.mixer_inputs * device_spec.mixer_outputs
        for cn in range(total):
            evo.set_mixer_crosspoint(cn, _MIXER_DB_MIN)
        time.sleep(0.05)

    _silence_all()
    try:
        yield
    finally:
        apply_config(evo, {"mixer": saved})


class TestMicInput:
    """Verify mic/line input routing through MU60 at different pan positions."""

    def test_pan_full_left(self, evo, input_num, loop_cap):
        """Pan=-100: input should appear on loopback LEFT only."""
        evo.set_mixer_input(input_num, 0.0, pan=-100.0)
        time.sleep(SETTLE)
        l, r = prompt_and_capture("-100 (full left)", loop_cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"

    def test_pan_center(self, evo, input_num, loop_cap):
        """Pan=0: input should appear on BOTH loopback channels equally."""
        evo.set_mixer_input(input_num, 0.0, pan=0.0)
        time.sleep(SETTLE)
        l, r = prompt_and_capture("0 (center)", loop_cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"
        assert abs(l - r) < 6.0, \
            f"Channels should be roughly equal: L={l:.1f}, R={r:.1f} dBFS"

    def test_pan_full_right(self, evo, input_num, loop_cap):
        """Pan=+100: input should appear on loopback RIGHT only."""
        evo.set_mixer_input(input_num, 0.0, pan=100.0)
        time.sleep(SETTLE)
        l, r = prompt_and_capture("+100 (full right)", loop_cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"
