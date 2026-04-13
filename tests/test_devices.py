"""Unit tests for device specification and detection - no hardware required."""

from unittest.mock import patch

import pytest

from evo.devices import DeviceSpec, EVO4, EVO8, DEVICES, detect_devices


class TestDeviceSpec:
    def test_evo4_fields(self):
        assert EVO4.name == "evo4"
        assert EVO4.usb_pid == 0x0006
        assert EVO4.num_inputs == 2
        assert EVO4.num_output_pairs == 1
        assert EVO4.gain_db_min == -8.0
        assert EVO4.gain_db_max == 50.0
        assert EVO4.mixer_inputs == 6
        assert EVO4.mixer_outputs == 2
        assert EVO4.num_mute_targets == 3
        assert EVO4.has_monitor is True

    def test_evo8_fields(self):
        assert EVO8.name == "evo8"
        assert EVO8.usb_pid == 0x0007
        assert EVO8.num_inputs == 4
        assert EVO8.num_output_pairs == 2
        assert EVO8.gain_db_min == 0.0
        assert EVO8.gain_db_max == 58.0
        assert EVO8.mixer_inputs == 10
        assert EVO8.mixer_outputs == 4
        assert EVO8.num_mute_targets == 6
        assert EVO8.has_monitor is False

    def test_frozen(self):
        with pytest.raises(AttributeError):
            setattr(EVO4, "name", "modified")

    def test_registry_contains_both(self):
        assert "evo4" in DEVICES
        assert "evo8" in DEVICES
        assert DEVICES["evo4"] is EVO4
        assert DEVICES["evo8"] is EVO8


class TestDetectDevices:
    def test_no_devices(self):
        with patch("evo.devices.exists", return_value=False):
            assert detect_devices() == []

    def test_evo4_only(self):
        with patch("evo.devices.exists", side_effect=lambda p: p == "/dev/evo4"):
            result = detect_devices()
            assert len(result) == 1
            assert result[0] is EVO4

    def test_evo8_only(self):
        with patch("evo.devices.exists", side_effect=lambda p: p == "/dev/evo8"):
            result = detect_devices()
            assert len(result) == 1
            assert result[0] is EVO8

    def test_both_devices(self):
        with patch("evo.devices.exists", return_value=True):
            result = detect_devices()
            assert len(result) == 2
