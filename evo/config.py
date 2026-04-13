"""EVO configuration save/load (JSON).

Per-device config paths:
  ~/.config/audient-evo-py/evo4/config.json
  ~/.config/audient-evo-py/evo8/config.json
"""

import json
from pathlib import Path

from evo.devices import DeviceSpec

CONFIG_DIR = Path.home() / ".config" / "audient-evo-py"
MIXER_STATE_VERSION = 2


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


def num_mixer_output_sources(spec: DeviceSpec) -> int:
    """Return stereo USB output pairs that can be mixed as MU60 inputs."""
    return (spec.mixer_inputs - spec.num_inputs) // 2


def _pair_key(prefix: str, left_channel: int) -> str:
    return f"{prefix}{left_channel}_{left_channel + 1}"


def _pair_index(key: str, prefix: str) -> int:
    if not key.startswith(prefix):
        raise ValueError(f"{key!r} does not start with {prefix!r}")
    parts = key[len(prefix):].split("_", 1)
    if len(parts) != 2:
        raise ValueError(f"{key!r} is not a stereo pair key")
    left = int(parts[0])
    right = int(parts[1])
    if left < 1 or left % 2 == 0 or right != left + 1:
        raise ValueError(f"{key!r} is not a stereo pair key")
    return (left - 1) // 2


def output_key(output_pair: int) -> str:
    """Return the key for a USB output source pair, e.g. output1_2."""
    return _pair_key("output", output_pair * 2 + 1)


def output_pair_index(key: str) -> int:
    """Return the zero-based USB output source pair index for output1_2 keys."""
    return _pair_index(key, "output")


def _mix_output_left_channel(spec: DeviceSpec, mix_output: int) -> int:
    if spec.num_output_pairs == 1:
        return spec.num_inputs + 1
    return mix_output * 2 + 1


def mix_output_key(spec: DeviceSpec, mix_output: int) -> str:
    """Return the key for a mixer destination, e.g. mix1_2 or mix3_4."""
    return _pair_key("mix", _mix_output_left_channel(spec, mix_output))


def mix_output_index(spec: DeviceSpec, key: str) -> int:
    for mix_output in range(spec.num_output_pairs):
        if key == mix_output_key(spec, mix_output):
            return mix_output
    raise ValueError(f"{key!r} is not a valid mixer output for {spec.display_name}")


def stereo_pair_label(pair: int) -> str:
    left = pair * 2 + 1
    return f"{left}|{left + 1}"


def mix_output_label(spec: DeviceSpec, mix_output: int) -> str:
    left = _mix_output_left_channel(spec, mix_output)
    return f"{left}|{left + 1}"


def default_mixer_state(spec: DeviceSpec) -> dict:
    """Return the canonical shadow state for the device mixer."""
    mix_outputs = {}
    for mix_output in range(spec.num_output_pairs):
        mix_outputs[mix_output_key(spec, mix_output)] = (
            {
                "mix_output": mix_output,
                "inputs": {
                    f"input{i + 1}": _input_state()
                    for i in range(spec.num_inputs)
                },
                "outputs": {
                    output_key(pair): _output_state(pair)
                    for pair in range(num_mixer_output_sources(spec))
                },
            }
        )
    return {"version": MIXER_STATE_VERSION, "mix_outputs": mix_outputs}


def _require_mixer_state(state: dict) -> None:
    if state.get("version") != MIXER_STATE_VERSION or not isinstance(state.get("mix_outputs"), dict):
        raise ValueError(f"Unsupported mixer state schema: {state.get('version')!r}")


def load_or_default_mixer_state(spec: DeviceSpec, path=None) -> dict:
    """Load the canonical mixer shadow state, or return defaults if it is absent."""
    return load_mixer_state(spec.name, path) or default_mixer_state(spec)


def mixer_output_state(state: dict, spec: DeviceSpec, mix_output: int = 0) -> dict:
    """Return a mutable canonical mixer destination state."""
    _require_mixer_state(state)
    return state["mix_outputs"][mix_output_key(spec, mix_output)]


def flat_mixer_output_state(state: dict, spec: DeviceSpec, mix_output: int = 0) -> dict:
    """Return a flat view whose values are the canonical mutable section dicts."""
    mix = mixer_output_state(state, spec, mix_output)
    flat = {}
    flat.update(mix["inputs"])
    flat.update(mix["outputs"])
    return flat


def mixer_section_state(state: dict, spec: DeviceSpec, key: str, mix_output: int = 0) -> dict:
    """Return a mutable per-section state dict from canonical mixer state."""
    mix = mixer_output_state(state, spec, mix_output)
    if key.startswith("input"):
        return mix["inputs"][key]
    if key.startswith("output"):
        return mix["outputs"][key]
    raise KeyError(key)


def update_mixer_input_state(
    state: dict,
    spec: DeviceSpec,
    input_num: int,
    volume: float,
    pan: float,
    mix_output: int = 0,
) -> None:
    """Update a mic/line input route in canonical mixer state."""
    if not 0 <= mix_output < spec.num_output_pairs:
        raise ValueError(f"mix_output must be 0 to {spec.num_output_pairs - 1}, got {mix_output}")
    if not 1 <= input_num <= spec.num_inputs:
        raise ValueError(f"input_num must be 1 to {spec.num_inputs}, got {input_num}")
    mixer_section_state(state, spec, f"input{input_num}", mix_output).update(
        {"volume": volume, "pan": pan}
    )


def update_mixer_output_state(
    state: dict,
    spec: DeviceSpec,
    output_pair: int,
    volume: float,
    pan_l: float = -100.0,
    pan_r: float = 100.0,
    mix_output: int = 0,
) -> None:
    """Update a USB output source pair route in canonical mixer state."""
    if not 0 <= mix_output < spec.num_output_pairs:
        raise ValueError(f"mix_output must be 0 to {spec.num_output_pairs - 1}, got {mix_output}")
    if not 0 <= output_pair < num_mixer_output_sources(spec):
        raise ValueError(
            f"output_pair must be 0 to {num_mixer_output_sources(spec) - 1}, got {output_pair}"
        )
    mixer_section_state(state, spec, output_key(output_pair), mix_output).update(
        {
            "output_pair": output_pair,
            "volume": volume,
            "pan_l": pan_l,
            "pan_r": pan_r,
        }
    )


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
        for mix_key, mix in mx["mix_outputs"].items():
            mix_output = mix["mix_output"] if "mix_output" in mix else mix_output_index(spec, mix_key)
            inputs = mix.get("inputs", {})
            for i in range(spec.num_inputs):
                key = f"input{i+1}"
                if key in inputs:
                    inp = inputs[key]
                    evo.set_mixer_input(
                        i + 1,
                        inp["volume"],
                        inp.get("pan", 0.0),
                        mix_output=mix_output,
                    )

            for output in mix.get("outputs", {}).values():
                evo.set_mixer_output(
                    output["volume"],
                    output.get("pan_l", -100.0),
                    output.get("pan_r", 100.0),
                    output_pair=output["output_pair"],
                    mix_output=mix_output,
                )
        save_mixer_state(evo.spec.name, mx)


def load_and_apply(evo, path=None) -> dict:
    """Load config from file and apply to device."""
    data = load(evo.spec.name, path)
    apply(evo, data)
    return data
