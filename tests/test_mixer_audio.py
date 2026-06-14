"""Audio loopback tests for EVO mixer - requires connected hardware.

Tests the MU60 loopback mixer by playing known signals through DAW output,
configuring mixer crosspoints, and capturing/analyzing the loopback return.

Signal path under test:
  Python -> PipeWire -> EVO DAW Out (CH1/2) -> MU60 crosspoints -> Loopback In -> PipeWire -> Python

Requirements:
  - EVO device connected and evo_raw kmod loaded
  - PipeWire running with EVO sinks/sources available
  - No other audio playing through the device during tests
  - pip: sounddevice, numpy
  - Mixer restore uses the saved shadow state because MU60 has no reliable readback

Run with: pytest tests/test_mixer_audio.py --hardware --audio --device evo4
"""

import re
import time

import pytest

np = pytest.importorskip("numpy")
sd = pytest.importorskip("sounddevice")

from evo.config import apply as apply_config
from evo.config import load_or_default_mixer_state
from evo.controller import _MIXER_DB_MIN

pytestmark = [pytest.mark.hardware, pytest.mark.audio]

# -- Audio constants --

SAMPLE_RATE = 48000
TONE_HZ = 1000.0
DURATION = 1.0          # seconds of playback + capture
TRIM = 0.25             # seconds trimmed from each end to skip latency transients

# dBFS thresholds for signal detection
PRESENT = -40.0         # above -> signal present
ABSENT = -60.0          # below -> considered silent

# Device name patterns (regex, fullmatch against PortAudio device name
# before the first comma). For EVO 4 the Line2_source ("Loopback" stereo
# capture) shares its description with the Line1_sink ("Loopback" stereo
# playback), so PortAudio disambiguates the input-only one with a volatile
# "-<node-id>" suffix - hence the optional trailing digits in loop_cap.
# EVO 8 patterns come from dev/wireplumber/evo8/evo8-stereo.conf descriptions
# and may need adjustment based on tester feedback.
_NODE_NAMES = {
    "evo4": {
        "daw_out": r"EVO4 Headphone / Line Out",
        "loop_out": r"EVO4 Loopback",
        "loop_cap": r"EVO4 Loopback-\d+",
    },
    "evo8": {
        "daw_out": r"EVO8 Main Output",
        "loop_out": r"EVO8 Loopback Output",
        "loop_cap": r"EVO8 Loopback",
    },
}


# -- Helpers --

def _find_device(pattern, kind):
    """Find sounddevice index whose description fullmatches `pattern` for `kind`.

    Device names from sounddevice look like 'EVO4 Loopback, JACK Audio ...',
    so we match the part before the first comma. `pattern` is a regex
    (re.fullmatch) to cope with volatile suffixes the JACK backend appends
    when two PipeWire nodes share a description.
    """
    rx = re.compile(pattern)
    key = f"max_{kind}_channels"
    for i, d in enumerate(sd.query_devices()):
        desc = d["name"].split(",")[0]
        if rx.fullmatch(desc) and d[key] > 0:
            return i
    raise RuntimeError(f"No {kind} device matching '{pattern}'")


def sine(freq=TONE_HZ, duration=DURATION):
    """Mono float32 sine at low amplitude.

    Kept well below full-scale so a connected headphone/monitor is not
    painful during long test runs. ~-20 dBFS still gives >20 dB margin
    above PRESENT / ABSENT detection thresholds.
    """
    t = np.arange(int(SAMPLE_RATE * duration), dtype=np.float32) / SAMPLE_RATE
    return np.float32(0.1) * np.sin(np.float32(2 * np.pi * freq) * t)


def stereo(mono, *, left=True, right=True):
    """Pack mono into a 2-channel array, optionally silencing a side."""
    out = np.zeros((len(mono), 2), dtype=np.float32)
    if left:
        out[:, 0] = mono
    if right:
        out[:, 1] = mono
    return out


def rms_dbfs(signal):
    """RMS in dBFS. Returns -120 for digital silence."""
    rms = np.sqrt(np.mean(signal.astype(np.float64) ** 2))
    return 20.0 * np.log10(max(rms, 1e-12))


def trim(captured):
    """Strip leading/trailing samples to avoid latency and fade transients."""
    n = int(TRIM * SAMPLE_RATE)
    return captured[n:-n] if len(captured) > 2 * n else captured


def levels(captured):
    """Return (left_dBFS, right_dBFS) from stereo capture, after trimming."""
    t = trim(captured)
    return rms_dbfs(t[:, 0]), rms_dbfs(t[:, 1])


# -- Fixtures --

@pytest.fixture(scope="module")
def node_names(device_spec):
    """PipeWire node names for the device under test."""
    names = _NODE_NAMES.get(device_spec.name)
    if names is None:
        pytest.skip(f"No PipeWire node names configured for {device_spec.name}")
    return names


@pytest.fixture(scope="module")
def daw_out(node_names):
    """EVO Main Output sink - plays to DAW CH1/2."""
    return _find_device(node_names["daw_out"], "output")


@pytest.fixture(scope="module")
def loop_out(node_names):
    """EVO Loopback Output sink - plays to Loopback Out."""
    return _find_device(node_names["loop_out"], "output")


@pytest.fixture(scope="module")
def loop_cap(node_names):
    """EVO Loopback capture source - records Loopback In."""
    return _find_device(node_names["loop_cap"], "input")


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


SETTLE = 0.1  # seconds after mixer changes before starting audio


def playrec(signal, capture_dev, playback_dev):
    """Simultaneous play + record via sounddevice. Returns captured ndarray."""
    time.sleep(SETTLE)
    # Pad to full duration if shorter
    needed = int(SAMPLE_RATE * DURATION)
    if len(signal) < needed:
        pad = np.zeros((needed, signal.shape[1]), dtype=np.float32)
        pad[:len(signal)] = signal
        signal = pad

    captured = sd.playrec(
        signal,
        samplerate=SAMPLE_RATE,
        channels=2,
        device=(capture_dev, playback_dev),
        dtype="float32",
    )
    sd.wait()
    return captured


def _daw_l_cn(device_spec, mix_output=0):
    """CN index for DAW L -> Loopback L on the given mixer output."""
    return device_spec.num_inputs * device_spec.mixer_outputs + mix_output * 2


# -- Tests: baseline --

class TestBaseline:
    """All crosspoints silenced - loopback must be quiet."""

    def test_silence(self, daw_out, loop_cap):
        """Playing audio with all crosspoints muted -> loopback silent."""
        sig = stereo(sine(), left=True, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left not silent: {l:.1f} dBFS"
        assert r < ABSENT, f"Right not silent: {r:.1f} dBFS"


# -- Tests: individual crosspoint routing --

class TestDawCrosspoints:
    """Verify each DAW->Loopback crosspoint routes to the correct channel."""

    def test_daw_l_to_loop_l(self, evo, device_spec, daw_out, loop_cap):
        """DAW L -> Loopback L only."""
        cn = _daw_l_cn(device_spec)
        evo.set_mixer_crosspoint(cn, 0.0)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"

    def test_daw_l_to_loop_r(self, evo, device_spec, daw_out, loop_cap):
        """DAW L -> Loopback R only."""
        cn = _daw_l_cn(device_spec) + 1
        evo.set_mixer_crosspoint(cn, 0.0)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"

    def test_daw_r_to_loop_l(self, evo, device_spec, daw_out, loop_cap):
        """DAW R -> Loopback L only."""
        cn = _daw_l_cn(device_spec) + device_spec.mixer_outputs
        evo.set_mixer_crosspoint(cn, 0.0)
        sig = stereo(sine(), left=False, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"

    def test_daw_r_to_loop_r(self, evo, device_spec, daw_out, loop_cap):
        """DAW R -> Loopback R only."""
        cn = _daw_l_cn(device_spec) + device_spec.mixer_outputs + 1
        evo.set_mixer_crosspoint(cn, 0.0)
        sig = stereo(sine(), left=False, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"

    def test_stereo_passthrough(self, evo, device_spec, daw_out, loop_cap):
        """DAW stereo -> Loopback stereo."""
        cn_ll = _daw_l_cn(device_spec)
        cn_rr = _daw_l_cn(device_spec) + device_spec.mixer_outputs + 1
        evo.set_mixer_crosspoint(cn_ll, 0.0)
        evo.set_mixer_crosspoint(cn_rr, 0.0)
        sig = stereo(sine(), left=True, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"

    def test_cross_routing(self, evo, device_spec, daw_out, loop_cap):
        """DAW L->Loop R, DAW R->Loop L (swap channels)."""
        cn_lr = _daw_l_cn(device_spec) + 1
        cn_rl = _daw_l_cn(device_spec) + device_spec.mixer_outputs
        evo.set_mixer_crosspoint(cn_lr, 0.0)
        evo.set_mixer_crosspoint(cn_rl, 0.0)
        # Play left only - should appear on right only
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"


# -- Tests: loopback output routing --

class TestLoopbackCrosspoints:
    """Verify Loopback Out -> Loopback In crosspoint routing."""

    def _loop_base(self, device_spec):
        """First CN for loopback-out inputs."""
        return (device_spec.num_inputs + device_spec.num_output_pairs * 2) * device_spec.mixer_outputs

    def test_loopout_l_to_loop_l(self, evo, device_spec, loop_out, loop_cap):
        cn = self._loop_base(device_spec)
        evo.set_mixer_crosspoint(cn, 0.0)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, loop_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"

    def test_loopout_r_to_loop_r(self, evo, device_spec, loop_out, loop_cap):
        cn = self._loop_base(device_spec) + device_spec.mixer_outputs + 1
        evo.set_mixer_crosspoint(cn, 0.0)
        sig = stereo(sine(), left=False, right=True)
        cap = playrec(sig, loop_cap, loop_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"

    def test_loopout_stereo(self, evo, device_spec, loop_out, loop_cap):
        base = self._loop_base(device_spec)
        cn_ll = base
        cn_rr = base + device_spec.mixer_outputs + 1
        evo.set_mixer_crosspoint(cn_ll, 0.0)
        evo.set_mixer_crosspoint(cn_rr, 0.0)
        sig = stereo(sine(), left=True, right=True)
        cap = playrec(sig, loop_cap, loop_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"


# -- Tests: convenience methods --

class TestMixerOutput:
    """Test set_mixer_output() high-level routing."""

    def test_default_stereo(self, evo, daw_out, loop_cap):
        """Default pans (L=-100, R=+100) produce clean L/R separation."""
        evo.set_mixer_output(0.0)
        sig = stereo(sine(), left=True, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left: {l:.1f} dBFS"
        assert r > PRESENT, f"Right: {r:.1f} dBFS"

    def test_left_only_playback(self, evo, daw_out, loop_cap):
        """With default stereo routing, left-only playback -> left-only loopback."""
        evo.set_mixer_output(0.0)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"

    def test_right_only_playback(self, evo, daw_out, loop_cap):
        """With default stereo routing, right-only playback -> right-only loopback."""
        evo.set_mixer_output(0.0)
        sig = stereo(sine(), left=False, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"

    def test_center_pan_spreads_mono(self, evo, daw_out, loop_cap):
        """Center pan for DAW L: left-only signal appears on both loopback channels equally."""
        evo.set_mixer_output(0.0, pan_l=0.0, pan_r=0.0)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left: {l:.1f} dBFS"
        assert r > PRESENT, f"Right: {r:.1f} dBFS"
        assert abs(l - r) < 3.0, f"Channels should be ~equal: L={l:.1f}, R={r:.1f} dBFS"


class TestMixerFinalOutputSource:
    """Test high-level routing for the final USB output source pair."""

    def _final_output_pair(self, device_spec):
        return (device_spec.mixer_inputs - device_spec.num_inputs) // 2 - 1

    def test_default_stereo(self, evo, device_spec, loop_out, loop_cap):
        """Default pans produce stereo routing for the final output source pair."""
        evo.set_mixer_output(0.0, output_pair=self._final_output_pair(device_spec))
        sig = stereo(sine(), left=True, right=True)
        cap = playrec(sig, loop_cap, loop_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left: {l:.1f} dBFS"
        assert r > PRESENT, f"Right: {r:.1f} dBFS"

    def test_left_only(self, evo, device_spec, loop_out, loop_cap):
        """Left-only final output source -> left-only capture."""
        evo.set_mixer_output(0.0, output_pair=self._final_output_pair(device_spec))
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, loop_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"


# -- Tests: gain / volume behavior --

class TestMixerGain:
    """Verify crosspoint gain affects captured level correctly."""

    def _measure_at_gain(self, evo, device_spec, daw_out, loop_cap, gain_db):
        """Set DAW L->Loop L to gain_db, play left sine, return left channel dBFS."""
        cn = _daw_l_cn(device_spec)
        evo.set_mixer_crosspoint(cn, gain_db)
        time.sleep(0.05)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        return rms_dbfs(trim(cap)[:, 0])

    def test_gain_ordering(self, evo, device_spec, daw_out, loop_cap):
        """Higher crosspoint gain -> louder capture."""
        lev_0 = self._measure_at_gain(evo, device_spec, daw_out, loop_cap, 0.0)
        lev_12 = self._measure_at_gain(evo, device_spec, daw_out, loop_cap, -12.0)
        lev_24 = self._measure_at_gain(evo, device_spec, daw_out, loop_cap, -24.0)
        assert lev_0 > lev_12 > lev_24, \
            f"Levels should decrease: 0dB={lev_0:.1f}, -12dB={lev_12:.1f}, -24dB={lev_24:.1f}"

    def test_6db_step(self, evo, device_spec, daw_out, loop_cap):
        """0 dB vs -6 dB crosspoint should differ by ~6 dB in capture."""
        lev_0 = self._measure_at_gain(evo, device_spec, daw_out, loop_cap, 0.0)
        lev_6 = self._measure_at_gain(evo, device_spec, daw_out, loop_cap, -6.0)
        diff = lev_0 - lev_6
        assert 3.0 < diff < 9.0, \
            f"Expected ~6 dB difference, got {diff:.1f} (0dB={lev_0:.1f}, -6dB={lev_6:.1f})"

    def test_silence_at_min_gain(self, evo, device_spec, daw_out, loop_cap):
        """Crosspoint at -128 dB should produce silence."""
        lev = self._measure_at_gain(evo, device_spec, daw_out, loop_cap, _MIXER_DB_MIN)
        assert lev < ABSENT, f"Should be silent at min gain: {lev:.1f} dBFS"


# -- Tests: summation (multiple crosspoints active) --

class TestMixerSummation:
    """Verify that multiple active crosspoints sum into the loopback bus."""

    def test_both_daw_channels_sum_to_mono(self, evo, device_spec, daw_out, loop_cap):
        """DAW L + DAW R both routed to Loopback L - level should be higher than one alone."""
        total = device_spec.mixer_inputs * device_spec.mixer_outputs
        sig = stereo(sine(), left=True, right=True)

        cn_ll = _daw_l_cn(device_spec)
        cn_rl = _daw_l_cn(device_spec) + device_spec.mixer_outputs

        # Single source
        evo.set_mixer_crosspoint(cn_ll, 0.0)
        cap_single = playrec(sig, loop_cap, daw_out)
        lev_single = rms_dbfs(trim(cap_single)[:, 0])

        # Both sources
        for cn in range(total):
            evo.set_mixer_crosspoint(cn, _MIXER_DB_MIN)
        evo.set_mixer_crosspoint(cn_ll, 0.0)   # DAW L -> Loop L
        evo.set_mixer_crosspoint(cn_rl, 0.0)   # DAW R -> Loop L
        cap_both = playrec(sig, loop_cap, daw_out)
        lev_both = rms_dbfs(trim(cap_both)[:, 0])

        # Two correlated sources at 0dB should sum to ~+6dB (voltage doubling)
        diff = lev_both - lev_single
        assert 2.0 < diff < 9.0, \
            f"Sum should be louder: single={lev_single:.1f}, both={lev_both:.1f}, diff={diff:.1f} dB"
