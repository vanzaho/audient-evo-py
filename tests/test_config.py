"""Config persistence tests - no hardware required."""

import pytest

from evo.config import MIXER_STATE_VERSION, default_mixer_state, load_mixer_state, save_mixer_state
from evo.devices import EVO4, EVO8


@pytest.mark.parametrize("spec", [EVO4, EVO8])
def test_default_mixer_state_shape(spec):
    state = default_mixer_state(spec)

    assert state["version"] == MIXER_STATE_VERSION
    assert len(state["buses"]) == spec.num_output_pairs

    for bus in state["buses"]:
        assert set(bus) == {"inputs", "outputs", "loopback"}
        assert list(bus["inputs"]) == [f"input{i + 1}" for i in range(spec.num_inputs)]
        assert list(bus["outputs"]) == [
            f"output_pair{pair + 1}" for pair in range(spec.num_output_pairs)
        ]
        for pair, output in enumerate(bus["outputs"].values()):
            assert output["output_pair"] == pair
        assert "output_pair" not in bus["loopback"]


@pytest.mark.parametrize("spec", [EVO4, EVO8])
def test_mixer_state_round_trips(tmp_path, spec):
    state = default_mixer_state(spec)
    bus = state["buses"][-1]
    bus["inputs"][f"input{spec.num_inputs}"].update({"volume": -3.0, "pan": 25.0})
    bus["outputs"][f"output_pair{spec.num_output_pairs}"].update(
        {"volume": -6.0, "pan_l": -75.0, "pan_r": 75.0}
    )
    bus["loopback"].update({"volume": -12.0, "pan_l": -50.0, "pan_r": 50.0})

    path = tmp_path / spec.name / ".mixer-state.json"
    save_mixer_state(spec.name, state, path)

    assert load_mixer_state(spec.name, path) == state
