"""Shared test fixtures for device-agnostic testing."""

import pytest

from evo.devices import DEVICES, DeviceSpec, detect_devices


def pytest_addoption(parser):
    group = parser.getgroup("audient-evo")
    group.addoption(
        "--device",
        choices=["evo4", "evo8", "auto"],
        default="auto",
        help="Device to test: evo4, evo8, or auto (detect from /dev/evo*).",
    )
    group.addoption(
        "--hardware",
        action="store_true",
        help="Run tests that require a connected EVO device.",
    )
    group.addoption(
        "--audio",
        action="store_true",
        help="Run tests that require optional audio deps and PipeWire devices.",
    )
    group.addoption(
        "--manual",
        action="store_true",
        help="Run interactive tests that require user input.",
    )


def pytest_collection_modifyitems(config, items):
    gates = {
        "hardware": config.getoption("--hardware"),
        "audio": config.getoption("--audio"),
        "manual": config.getoption("--manual"),
    }
    for item in items:
        if not any(mark in item.keywords for mark in gates):
            item.add_marker(pytest.mark.unit)
        for mark, enabled in gates.items():
            if mark in item.keywords and not enabled:
                item.add_marker(pytest.mark.skip(reason=f"needs --{mark}"))


@pytest.fixture(scope="session")
def device_spec(request) -> DeviceSpec:
    """Resolve the device spec to test against."""
    choice = request.config.getoption("--device")
    if choice != "auto":
        return DEVICES[choice]
    found = detect_devices()
    if len(found) == 1:
        return found[0]
    if len(found) == 0:
        pytest.skip("No EVO device detected (use --device to specify)")
    names = ", ".join(s.name for s in found)
    pytest.skip(f"Multiple devices detected ({names}) - use --device to select one")


@pytest.fixture(scope="module")
def evo(device_spec):
    """EVOController instance for the target device."""
    from evo.controller import EVOController
    return EVOController(device_spec)
