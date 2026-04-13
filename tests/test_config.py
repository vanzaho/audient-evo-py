"""Config persistence tests - no hardware required."""

from pathlib import Path

import pytest

from evo import config as cfg
from evo.config import (
    MIXER_STATE_VERSION,
    apply,
    default_mixer_state,
    load,
    load_mixer_state,
    mix_output_key,
    num_mixer_output_sources,
    output_key,
    save_mixer_state,
)
from evo.devices import EVO4, EVO8


@pytest.mark.parametrize("spec", [EVO4, EVO8])
def test_default_mixer_state_shape(spec):
    state = default_mixer_state(spec)

    assert state["version"] == MIXER_STATE_VERSION
    assert list(state["mix_outputs"]) == [
        mix_output_key(spec, mix_output) for mix_output in range(spec.num_output_pairs)
    ]

    for mix_output, mix in enumerate(state["mix_outputs"].values()):
        assert set(mix) == {"mix_output", "inputs", "outputs"}
        assert mix["mix_output"] == mix_output
        assert list(mix["inputs"]) == [f"input{i + 1}" for i in range(spec.num_inputs)]
        assert list(mix["outputs"]) == [
            output_key(pair) for pair in range(num_mixer_output_sources(spec))
        ]
        for pair, output in enumerate(mix["outputs"].values()):
            assert output["output_pair"] == pair


@pytest.mark.parametrize("spec", [EVO4, EVO8])
def test_mixer_state_round_trips(tmp_path, spec):
    state = default_mixer_state(spec)
    mix = state["mix_outputs"][mix_output_key(spec, spec.num_output_pairs - 1)]
    mix["inputs"][f"input{spec.num_inputs}"].update({"volume": -3.0, "pan": 25.0})
    mix["outputs"][output_key(num_mixer_output_sources(spec) - 1)].update(
        {"volume": -6.0, "pan_l": -75.0, "pan_r": 75.0}
    )

    path = tmp_path / spec.name / ".mixer-state.json"
    save_mixer_state(spec.name, state, path)

    assert load_mixer_state(spec.name, path) == state


def test_corrupt_json_error_includes_path(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{")

    with pytest.raises(ValueError, match=str(path)):
        load(EVO4.name, path)


def test_mixer_state_write_uses_temp_file_then_replace(tmp_path, monkeypatch):
    path = tmp_path / EVO4.name / ".mixer-state.json"
    calls = []
    replace = cfg.os.replace

    def fake_replace(src, dst):
        src = Path(src)
        dst = Path(dst)
        calls.append((src, dst, src.exists()))
        replace(src, dst)

    monkeypatch.setattr(cfg.os, "replace", fake_replace)
    save_mixer_state(EVO4.name, default_mixer_state(EVO4), path)

    assert calls
    tmp, dst, existed = calls[0]
    assert existed
    assert tmp.parent == path.parent
    assert tmp.name.startswith(f".{path.name}.")
    assert dst == path
    assert load_mixer_state(EVO4.name, path) == default_mixer_state(EVO4)


def test_apply_allows_partial_config():
    class FakeEVO:
        spec = EVO4

        def __init__(self):
            self.calls = []

        def set_volume(self, *args, **kwargs):
            self.calls.append(("set_volume", args, kwargs))

    evo = FakeEVO()

    apply(evo, {"output": {"volume": -12.0}})

    assert evo.calls == [("set_volume", (-12.0,), {})]
