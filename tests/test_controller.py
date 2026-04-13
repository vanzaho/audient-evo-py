"""Integration tests for EVO controller - requires a connected Audient EVO device.

Each test saves the current value, sets a new value, verifies it, then restores.
Device-agnostic: use --device evo4|evo8|auto to select the target.
"""

import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from evo.controller import EVOController, _db_to_usb, _usb_to_db, _MIXER_DB_MIN, _MIXER_DB_MAX
from evo.devices import EVO4, EVO8


SETTLE_TIME = 0.05  # seconds to wait after SET before GET


def _controller(spec):
    with patch("evo.controller.exists", return_value=True):
        return EVOController(spec)


# --- Conversion helpers ---

class TestDbConversions:
    def test_db_to_usb_zero(self):
        assert _db_to_usb(0.0) == 0x0000

    def test_db_to_usb_negative(self):
        # -1 dB = -256 in 1/256 steps = 0xFF00 as unsigned 16-bit
        assert _db_to_usb(-1.0) == 0xFF00

    def test_db_to_usb_min(self):
        # -127 dB - should not overflow 16-bit
        raw = _db_to_usb(-127.0)
        assert 0 <= raw <= 0xFFFF

    def test_usb_to_db_zero(self):
        assert _usb_to_db(0x0000) == 0.0

    def test_usb_to_db_negative(self):
        assert _usb_to_db(0xFF00) == -1.0

    def test_usb_to_db_large_negative(self):
        # 0x8080 - signed = -32640 - -127.5 dB
        assert _usb_to_db(0x8080) == pytest.approx(-127.5)

    def test_roundtrip(self):
        for db in [0.0, -1.0, -20.0, -96.0]:
            assert _usb_to_db(_db_to_usb(db)) == pytest.approx(db, abs=1/256)


# --- Hardware integration tests ---

@pytest.mark.hardware
class TestVolume:
    def test_set_and_get(self, evo):
        original = evo.get_volume()
        target = -20.0 if abs(original - (-20.0)) > 1.0 else -30.0

        try:
            evo.set_volume(target)
            time.sleep(SETTLE_TIME)
            result = evo.get_volume()
            assert abs(result - target) <= 0.5, \
                f"Volume: expected ~{target} dB, got {result} dB"
        finally:
            evo.set_volume(original)

    def test_volume_boundaries(self, evo):
        original = evo.get_volume()
        try:
            for target in (-96.0, 0.0):
                evo.set_volume(target)
                time.sleep(SETTLE_TIME)
                result = evo.get_volume()
                assert abs(result - target) <= 0.5, \
                    f"Volume at boundary {target} dB: got {result} dB"
        finally:
            evo.set_volume(original)

    def test_set_returns_raw_and_db(self, evo):
        original = evo.get_volume()
        try:
            raw, db = evo.set_volume(-20.0)
            assert isinstance(raw, int)
            assert isinstance(db, float)
            assert db == pytest.approx(-20.0, abs=0.5)
        finally:
            evo.set_volume(original)

    def test_debug_format(self, evo):
        raw, db = evo.get_volume_debug()
        assert isinstance(raw, int)
        assert isinstance(db, float)
        assert -96.0 <= db <= 0.0

    def test_output_pair_2(self, evo, device_spec):
        """Test volume on second output pair (EVO 8 only)."""
        if device_spec.num_output_pairs < 2:
            pytest.skip("Single output pair device")
        original = evo.get_volume(output_pair=1)
        target = -25.0 if abs(original - (-25.0)) > 1.0 else -35.0
        try:
            evo.set_volume(target, output_pair=1)
            time.sleep(SETTLE_TIME)
            result = evo.get_volume(output_pair=1)
            assert abs(result - target) <= 0.5, \
                f"Volume pair 2: expected ~{target} dB, got {result} dB"
        finally:
            evo.set_volume(original, output_pair=1)


@pytest.mark.hardware
class TestGain:
    @pytest.mark.parametrize("target", ["input1", "input2", "input3", "input4"])
    def test_set_and_get(self, evo, target):
        if target not in evo._gain_targets:
            pytest.skip(f"{target} not available on {evo.spec.display_name}")
        original = evo.get_gain(target)
        mid = (evo.spec.gain_db_min + evo.spec.gain_db_max) / 2
        goal = mid if abs(original - mid) > 1.0 else mid + 5.0

        try:
            evo.set_gain(target, goal)
            time.sleep(SETTLE_TIME)
            result = evo.get_gain(target)
            assert abs(result - goal) <= 0.5, \
                f"Gain {target}: expected ~{goal} dB, got {result} dB"
        finally:
            evo.set_gain(target, original)

    def test_per_input_independence(self, evo, device_spec):
        inputs = [f"input{i+1}" for i in range(min(2, device_spec.num_inputs))]
        lo = device_spec.gain_db_min + 3.0
        hi = device_spec.gain_db_max - 20.0
        originals = {t: evo.get_gain(t) for t in inputs}
        try:
            evo.set_gain(inputs[0], lo)
            evo.set_gain(inputs[1], hi)
            time.sleep(SETTLE_TIME)
            r0 = evo.get_gain(inputs[0])
            r1 = evo.get_gain(inputs[1])
            assert abs(r0 - lo) <= 0.5, f"{inputs[0]}: expected ~{lo} dB, got {r0}"
            assert abs(r1 - hi) <= 0.5, f"{inputs[1]}: expected ~{hi} dB, got {r1}"
        finally:
            for t, val in originals.items():
                evo.set_gain(t, val)

    @pytest.mark.parametrize("target", ["input1", "input2", "input3", "input4"])
    def test_gain_boundaries(self, evo, device_spec, target):
        if target not in evo._gain_targets:
            pytest.skip(f"{target} not available on {evo.spec.display_name}")
        original = evo.get_gain(target)
        try:
            for goal in (device_spec.gain_db_min, device_spec.gain_db_max):
                evo.set_gain(target, goal)
                time.sleep(SETTLE_TIME)
                result = evo.get_gain(target)
                assert abs(result - goal) <= 0.5, \
                    f"Gain {target} at boundary {goal} dB: got {result} dB"
        finally:
            evo.set_gain(target, original)

    def test_set_returns_raw_and_db(self, evo, device_spec):
        original = evo.get_gain("input1")
        try:
            _, db = evo.set_gain("input1", device_spec.gain_db_min)
            assert db == pytest.approx(device_spec.gain_db_min)
            _, db = evo.set_gain("input1", device_spec.gain_db_max)
            assert db == pytest.approx(device_spec.gain_db_max)
        finally:
            evo.set_gain("input1", original)

    @pytest.mark.parametrize("target", ["input1", "input2", "input3", "input4"])
    def test_debug_format(self, evo, device_spec, target):
        if target not in evo._gain_targets:
            pytest.skip(f"{target} not available on {evo.spec.display_name}")
        raw, db = evo.get_gain_debug(target)
        assert isinstance(raw, int)
        assert isinstance(db, float)
        assert device_spec.gain_db_min <= db <= device_spec.gain_db_max


@pytest.mark.hardware
class TestMute:
    @pytest.mark.parametrize("target", [
        "input1", "input2", "input3", "input4",
        "output", "output1", "output2",
    ])
    def test_toggle_mute(self, evo, target):
        if target not in evo._mute_targets:
            pytest.skip(f"{target} not available on {evo.spec.display_name}")
        original = evo.get_mute(target)
        new_state = not original

        try:
            evo.set_mute(target, new_state)
            time.sleep(SETTLE_TIME)
            result = evo.get_mute(target)
            assert result == new_state, \
                f"Mute {target}: expected {new_state}, got {result}"
        finally:
            evo.set_mute(target, original)

    @pytest.mark.parametrize("target", [
        "input1", "input2", "input3", "input4",
        "output", "output1", "output2",
    ])
    def test_mute_on_off(self, evo, target):
        """Explicitly test both on and off states."""
        if target not in evo._mute_targets:
            pytest.skip(f"{target} not available on {evo.spec.display_name}")
        original = evo.get_mute(target)
        try:
            evo.set_mute(target, True)
            time.sleep(SETTLE_TIME)
            assert evo.get_mute(target) is True, f"{target} should be muted"

            evo.set_mute(target, False)
            time.sleep(SETTLE_TIME)
            assert evo.get_mute(target) is False, f"{target} should be unmuted"
        finally:
            evo.set_mute(target, original)

    def test_mute_targets_independent(self, evo):
        """Muting one target should not affect others."""
        targets = list(evo._mute_targets.keys())
        originals = {t: evo.get_mute(t) for t in targets}
        try:
            for t in targets:
                evo.set_mute(t, False)
            time.sleep(SETTLE_TIME)

            # Mute only the first target
            evo.set_mute(targets[0], True)
            time.sleep(SETTLE_TIME)

            assert evo.get_mute(targets[0]) is True
            for t in targets[1:]:
                assert evo.get_mute(t) is False, f"{t} should still be unmuted"
        finally:
            for t, val in originals.items():
                evo.set_mute(t, val)

    def test_invalid_target(self, evo):
        with pytest.raises(KeyError):
            evo.get_mute("nonexistent")
        with pytest.raises(KeyError):
            evo.set_mute("nonexistent", True)


@pytest.mark.hardware
@pytest.mark.manual
class TestPhantom:
    @pytest.mark.parametrize("target", ["input1", "input2", "input3", "input4"])
    def test_toggle_phantom(self, evo, target):
        if target not in evo._phantom_targets:
            pytest.skip(f"{target} not available on {evo.spec.display_name}")
        original = evo.get_phantom(target)
        new_state = not original

        try:
            evo.set_phantom(target, new_state)
            time.sleep(SETTLE_TIME)
            result = evo.get_phantom(target)
            assert result == new_state, \
                f"Phantom {target}: expected {new_state}, got {result}"
        finally:
            evo.set_phantom(target, original)

    @pytest.mark.parametrize("target", ["input1", "input2", "input3", "input4"])
    def test_phantom_on_off(self, evo, target):
        """Explicitly test both on and off states."""
        if target not in evo._phantom_targets:
            pytest.skip(f"{target} not available on {evo.spec.display_name}")
        original = evo.get_phantom(target)
        try:
            evo.set_phantom(target, True)
            time.sleep(SETTLE_TIME)
            assert evo.get_phantom(target) is True, f"{target} phantom should be on"

            evo.set_phantom(target, False)
            time.sleep(SETTLE_TIME)
            assert evo.get_phantom(target) is False, f"{target} phantom should be off"
        finally:
            evo.set_phantom(target, original)

    def test_phantom_targets_independent(self, evo, device_spec):
        """Setting phantom on one input should not affect the other."""
        inputs = [f"input{i+1}" for i in range(min(2, device_spec.num_inputs))]
        originals = {t: evo.get_phantom(t) for t in inputs}
        try:
            for t in inputs:
                evo.set_phantom(t, False)
            time.sleep(SETTLE_TIME)

            evo.set_phantom(inputs[0], True)
            time.sleep(SETTLE_TIME)

            assert evo.get_phantom(inputs[0]) is True
            assert evo.get_phantom(inputs[1]) is False
        finally:
            for t, val in originals.items():
                evo.set_phantom(t, val)

    def test_invalid_target(self, evo):
        with pytest.raises(KeyError):
            evo.get_phantom("nonexistent")
        with pytest.raises(KeyError):
            evo.set_phantom("nonexistent", True)


@pytest.mark.hardware
class TestMonitor:
    @pytest.fixture(autouse=True)
    def _require_monitor(self, device_spec):
        if not device_spec.has_monitor:
            pytest.skip(f"{device_spec.display_name} does not have direct monitor control")

    def test_set_and_get(self, evo):
        original = evo.get_monitor()
        target = 65 if original != 65 else 66

        try:
            evo.set_monitor(target)
            time.sleep(SETTLE_TIME)
            result = evo.get_monitor()
            assert abs(result - target) <= 1, \
                f"Monitor: expected ~{target}, got {result}"
        finally:
            evo.set_monitor(original)

    def test_monitor_boundaries(self, evo):
        original = evo.get_monitor()
        try:
            for target in (0, 100):
                evo.set_monitor(target)
                time.sleep(SETTLE_TIME)
                result = evo.get_monitor()
                assert abs(result - target) <= 1, \
                    f"Monitor at boundary {target}: got {result}"
        finally:
            evo.set_monitor(original)

    def test_monitor_midpoint(self, evo):
        original = evo.get_monitor()
        try:
            evo.set_monitor(50)
            time.sleep(SETTLE_TIME)
            result = evo.get_monitor()
            assert abs(result - 50) <= 1
        finally:
            evo.set_monitor(original)

    def test_monitor_returns_int(self, evo):
        result = evo.get_monitor()
        assert isinstance(result, int)
        assert 0 <= result <= 100


@pytest.mark.hardware
class TestMonitorUnavailable:
    """Verify monitor raises on devices without it."""

    @pytest.fixture(autouse=True)
    def _require_no_monitor(self, device_spec):
        if device_spec.has_monitor:
            pytest.skip("Device has monitor control - testing absence only")

    def test_get_monitor_raises(self, evo):
        with pytest.raises(RuntimeError):
            evo.get_monitor()

    def test_set_monitor_raises(self, evo):
        with pytest.raises(RuntimeError):
            evo.set_monitor(50)


# --- Pan law unit tests (no hardware) ---

class TestPanLaw:
    def test_center_minus_3db(self):
        """At center pan, both channels should be volume - 3.01 dB."""
        for vol in [0.0, -6.0, -20.0, -60.0]:
            l, r = EVOController._pan_to_lr_db(vol, 0.0)
            assert l == pytest.approx(vol - 3.0103, abs=0.01), f"Left at center, vol={vol}"
            assert r == pytest.approx(vol - 3.0103, abs=0.01), f"Right at center, vol={vol}"

    def test_full_left(self):
        """Full left: left = volume, right = -128 dB (silence)."""
        l, r = EVOController._pan_to_lr_db(0.0, -100.0)
        assert l == pytest.approx(0.0, abs=0.01)
        assert r == _MIXER_DB_MIN

    def test_full_right(self):
        """Full right: left = -128 dB (silence), right = volume."""
        l, r = EVOController._pan_to_lr_db(0.0, 100.0)
        assert l == _MIXER_DB_MIN
        assert r == pytest.approx(0.0, abs=0.01)

    def test_monotonic(self):
        """As pan goes left to right, left decreases and right increases."""
        pans = list(range(-100, 101, 5))
        lefts = []
        rights = []
        for p in pans:
            l, r = EVOController._pan_to_lr_db(0.0, float(p))
            lefts.append(l)
            rights.append(r)
        for i in range(1, len(lefts)):
            assert lefts[i] <= lefts[i - 1] + 0.001, f"Left not monotonic at pan={pans[i]}"
            assert rights[i] >= rights[i - 1] - 0.001, f"Right not monotonic at pan={pans[i]}"

    def test_symmetric(self):
        """Pan law should be symmetric: L at pan=+X equals R at pan=-X."""
        for p in [25.0, 50.0, 75.0]:
            l_pos, r_pos = EVOController._pan_to_lr_db(0.0, p)
            l_neg, r_neg = EVOController._pan_to_lr_db(0.0, -p)
            assert l_pos == pytest.approx(r_neg, abs=0.01)
            assert r_pos == pytest.approx(l_neg, abs=0.01)

    def test_clamps_to_range(self):
        """Volume near silence should clamp to _MIXER_DB_MIN."""
        l, r = EVOController._pan_to_lr_db(_MIXER_DB_MIN, 0.0)
        assert l == _MIXER_DB_MIN
        assert r == _MIXER_DB_MIN

    def test_pan_clamps_to_range(self):
        assert EVOController._pan_to_lr_db(0.0, -200.0) == EVOController._pan_to_lr_db(
            0.0, -100.0
        )
        assert EVOController._pan_to_lr_db(0.0, 200.0) == EVOController._pan_to_lr_db(
            0.0, 100.0
        )


class TestMixerValidation:
    @pytest.mark.parametrize("spec", [EVO4, EVO8])
    def test_invalid_mix_output(self, spec):
        evo = _controller(spec)
        for mix_output in (-1, spec.num_output_pairs):
            with pytest.raises(ValueError, match="mix_output"):
                evo.set_mixer_input(1, 0.0, mix_output=mix_output)
            with pytest.raises(ValueError, match="mix_output"):
                evo.set_mixer_output(0.0, mix_output=mix_output)

    @pytest.mark.parametrize("spec", [EVO4, EVO8])
    def test_invalid_output_pair(self, spec):
        evo = _controller(spec)
        for output_pair in (-1, (spec.mixer_inputs - spec.num_inputs) // 2):
            with pytest.raises(ValueError, match="output_pair"):
                evo.set_mixer_output(0.0, output_pair=output_pair)

    @pytest.mark.parametrize(
        ("spec", "mix_output", "expected"),
        [(EVO4, 0, [0, 1]), (EVO8, 1, [2, 3])],
    )
    def test_input_crosspoints(self, spec, mix_output, expected):
        evo = _controller(spec)
        calls = []
        evo.set_mixer_crosspoint = lambda cn, db: calls.append((cn, db))

        evo.set_mixer_input(1, -6.0, 0.0, mix_output=mix_output)

        assert [cn for cn, _ in calls] == expected
        assert [db for _, db in calls] == pytest.approx([-9.0103, -9.0103], abs=0.01)

    @pytest.mark.parametrize(
        ("spec", "output_pair", "mix_output", "expected"),
        [
            (EVO4, 0, 0, [4, 5, 6, 7]),
            (EVO4, 1, 0, [8, 9, 10, 11]),
            (EVO8, 2, 1, [34, 35, 38, 39]),
        ],
    )
    def test_output_crosspoints(self, spec, output_pair, mix_output, expected):
        evo = _controller(spec)
        calls = []
        evo.set_mixer_crosspoint = lambda cn, db: calls.append((cn, db))

        evo.set_mixer_output(-6.0, output_pair=output_pair, mix_output=mix_output)

        assert [cn for cn, _ in calls] == expected
        assert [db for _, db in calls] == pytest.approx(
            [-6.0, _MIXER_DB_MIN, _MIXER_DB_MIN, -6.0]
        )

    @pytest.mark.parametrize(
        ("db", "clamped"),
        [(999.0, _MIXER_DB_MAX), (-999.0, _MIXER_DB_MIN)],
    )
    def test_crosspoint_volume_clamps(self, db, clamped):
        evo = _controller(EVO4)

        @contextmanager
        def device():
            yield object()

        evo._device = device
        with patch("evo.controller.kmod.set_cur") as mock_set_cur:
            evo.set_mixer_crosspoint(0, db)

        assert mock_set_cur.call_args.kwargs["data"] == _db_to_usb(clamped).to_bytes(
            2, "little"
        )


# --- Mixer integration tests (hardware) ---

@pytest.mark.hardware
class TestMixer:
    def test_set_crosspoint(self, evo):
        """Set CN=0 to 0 dB - should not error."""
        evo.set_mixer_crosspoint(0, 0.0)

    def test_get_crosspoint_stall(self, evo):
        """GET_CUR on MU60 is expected to STALL (write-only)."""
        try:
            db = evo.get_mixer_crosspoint(0)
            # If it succeeds, that's fine too
            assert isinstance(db, float)
        except OSError:
            pass  # expected STALL

    def test_set_mixer_input(self, evo):
        """Set input1 to 0 dB center - should not error."""
        evo.set_mixer_input(1, 0.0, 0.0)

    def test_set_mixer_output(self, evo):
        """Set output to 0 dB with default pans - should not error."""
        evo.set_mixer_output(0.0)

    def test_set_mixer_final_output_source(self, evo):
        """Set the final USB output source pair to -6 dB - should not error."""
        output_pair = (evo.spec.mixer_inputs - evo.spec.num_inputs) // 2 - 1
        evo.set_mixer_output(-6.0, output_pair=output_pair)

    def test_crosspoint_invalid_cn(self, evo):
        with pytest.raises(ValueError):
            evo.set_mixer_crosspoint(evo._mixer_max_cn, 0.0)
        with pytest.raises(ValueError):
            evo.set_mixer_crosspoint(-1, 0.0)

    def test_input_invalid_num(self, evo):
        with pytest.raises(ValueError):
            evo.set_mixer_input(evo.spec.num_inputs + 1, 0.0)

    def test_mix_output(self, evo, device_spec):
        """Test mixer operations on second mixer output (multi-output devices)."""
        if device_spec.num_output_pairs < 2:
            pytest.skip("Single output pair device")
        evo.set_mixer_input(1, 0.0, 0.0, mix_output=1)
        evo.set_mixer_output(0.0, mix_output=1)
        output_pair = (device_spec.mixer_inputs - device_spec.num_inputs) // 2 - 1
        evo.set_mixer_output(-6.0, output_pair=output_pair, mix_output=1)
