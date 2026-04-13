"""EVO configuration save/load (JSON).

Per-device config paths:
  ~/.config/audient-evo-py/evo4/config.json
  ~/.config/audient-evo-py/evo8/config.json
"""

import json
from pathlib import Path

from evo.devices import DeviceSpec

CONFIG_DIR = Path.home() / ".config" / "audient-evo-py"
MIXER_STATE_VERSION = 1


def _device_dir(device_name: str) -> Path:
    return CONFIG_DIR / device_name


def config_file(device_name: str) -> Path:
    return _device_dir(device_name) / "config.json"


def mixer_state_file(device_name: str) -> Path:
    return _device_dir(device_name) / ".mixer-state.json"


def _input_state() -> dict:
    return {"volume": -128.0, "pan": 0.0}


def _output_state(output_pair: int) -> dict:
    return {
        "output_pair": output_pair,
        "volume": -128.0,
        "pan_l": -100.0,
        "pan_r": 100.0,
    }


def _stereo_state() -> dict:
    return {"volume": -128.0, "pan_l": -100.0, "pan_r": 100.0}


def _output_key(output_pair: int) -> str:
    return f"output_pair{output_pair + 1}"


def default_mixer_state(spec: DeviceSpec) -> dict:
    """Return the canonical shadow state for the device mixer."""
    buses = []
    for _ in range(spec.num_output_pairs):
        buses.append(
            {
                "inputs": {
                    f"input{i + 1}": _input_state()
                    for i in range(spec.num_inputs)
                },
                "outputs": {
                    _output_key(pair): _output_state(pair)
                    for pair in range(spec.num_output_pairs)
                },
                "loopback": _stereo_state(),
            }
        )
    return {"version": MIXER_STATE_VERSION, "buses": buses}


def _require_mixer_state(state: dict) -> None:
    if state.get("version") != MIXER_STATE_VERSION or not isinstance(state.get("buses"), list):
        raise ValueError(f"Unsupported mixer state schema: {state.get('version')!r}")


def load_mixer_state(device_name: str, path=None) -> dict | None:
    """Load the canonical MU60 shadow state. Returns None if no shadow exists yet."""
    p = Path(path) if path else mixer_state_file(device_name)
    if not p.exists():
        return None
    state = json.loads(p.read_text())
    _require_mixer_state(state)
    return state


def save_mixer_state(device_name: str, state: dict, path=None):
    """Persist canonical MU60 shadow state to disk."""
    _require_mixer_state(state)
    p = Path(path) if path else mixer_state_file(device_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n")


def snapshot(evo) -> dict:
    """Read all current device settings into a dict."""
    data = evo.decode_status(evo.get_status_raw())
    mixer = load_mixer_state(evo.spec.name)
    if mixer is not None:
        data["mixer"] = mixer
    return data


def save(evo, path=None) -> Path:
    """Save current device state to JSON file."""
    path = Path(path) if path else config_file(evo.spec.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot(evo), indent=2) + "\n")
    return path


def load(device_name: str, path=None) -> dict:
    """Load config dict from JSON file."""
    path = Path(path) if path else config_file(device_name)
    return json.loads(path.read_text())


def apply(evo, data: dict):
    """Apply a config dict to the device."""
    spec = evo.spec
    if "monitor" in data and evo.spec.has_monitor:
        evo.set_monitor(data["monitor"])

    # Output volume/mute
    if spec.num_output_pairs == 1:
        if "output" in data:
            out = data["output"]
            if "volume" in out:
                evo.set_volume(out["volume"])
            if "mute" in out:
                evo.set_mute("output", out["mute"])
    else:
        for pair in range(spec.num_output_pairs):
            key = f"output{pair+1}"
            if key in data:
                out = data[key]
                if "volume" in out:
                    evo.set_volume(out["volume"], output_pair=pair)
                if "mute" in out:
                    evo.set_mute(key, out["mute"])

    # Input gain/mute/phantom
    for i in range(spec.num_inputs):
        ch = f"input{i+1}"
        if ch in data:
            inp = data[ch]
            if "gain" in inp:
                evo.set_gain(ch, inp["gain"])
            if "mute" in inp:
                evo.set_mute(ch, inp["mute"])
            if "phantom" in inp:
                evo.set_phantom(ch, inp["phantom"])

    # Mixer
    if "mixer" in data:
        mx = data["mixer"]
        _require_mixer_state(mx)
        for bus_idx, bus in enumerate(mx["buses"]):
            inputs = bus.get("inputs", {})
            for i in range(spec.num_inputs):
                key = f"input{i+1}"
                if key in inputs:
                    inp = inputs[key]
                    evo.set_mixer_input(
                        i + 1,
                        inp["volume"],
                        inp.get("pan", 0.0),
                        mix_bus=bus_idx,
                    )

            for output in bus.get("outputs", {}).values():
                evo.set_mixer_output(
                    output["volume"],
                    output.get("pan_l", -100.0),
                    output.get("pan_r", 100.0),
                    output_pair=output["output_pair"],
                    mix_bus=bus_idx,
                )

            if "loopback" in bus:
                lb = bus["loopback"]
                evo.set_mixer_loopback(
                    lb["volume"],
                    lb.get("pan_l", -100.0),
                    lb.get("pan_r", 100.0),
                    mix_bus=bus_idx,
                )
        save_mixer_state(evo.spec.name, mx)


def load_and_apply(evo, path=None) -> dict:
    """Load config from file and apply to device."""
    data = load(evo.spec.name, path)
    apply(evo, data)
    return data
