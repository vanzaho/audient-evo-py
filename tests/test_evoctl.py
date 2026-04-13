"""CLI parser/runtime tests - no hardware required."""

import pytest

import evoctl
from evo.devices import EVO4, EVO8


def test_global_help_does_not_detect_device(monkeypatch, capsys):
    monkeypatch.setattr(evoctl, "_resolve_device", lambda: pytest.fail("detected device"))

    with pytest.raises(SystemExit) as exc:
        evoctl.main(["--help"])

    assert exc.value.code == 0
    assert "--device" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("device", "shown", "hidden"),
    [("evo4", "output3_4", "output5_6"), ("evo8", "output5_6", None)],
)
def test_device_mixer_help_is_specific(device, shown, hidden, monkeypatch, capsys):
    monkeypatch.setattr(evoctl, "EVOController", lambda spec: pytest.fail("opened device"))

    with pytest.raises(SystemExit) as exc:
        evoctl.main(["--device", device, "mixer", "--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert shown in out
    assert "--mix-output" not in out
    if hidden:
        assert hidden not in out


def test_output_source_help_documents_mix_output(monkeypatch, capsys):
    monkeypatch.setattr(evoctl, "EVOController", lambda spec: pytest.fail("opened device"))

    with pytest.raises(SystemExit) as exc:
        evoctl.main(["--device=evo8", "mixer", "output5_6", "--help"])

    assert exc.value.code == 0
    assert "--mix-output" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "output_pair", "mix_output"),
    [
        (["mixer", "output1_2", "--volume", "0", "--mix-output", "0"], 0, 0),
        (["mixer", "output3_4", "--volume", "0", "--mix-output", "1"], 1, 1),
        (["mixer", "output5_6", "--volume", "0", "--mix-output", "0"], 2, 0),
    ],
)
def test_evo8_output_source_routes(argv, output_pair, mix_output):
    args = evoctl.parse_args(EVO8, argv)

    assert args.mixer_section == argv[1]
    assert args.output_pair == output_pair
    assert args.mix_output == mix_output


def test_main_uses_one_controller_context(monkeypatch):
    events = []

    class FakeController:
        def __init__(self, spec):
            self.spec = spec
            events.append(("init", spec.name))

        def __enter__(self):
            events.append("enter")
            return self

        def __exit__(self, *exc):
            events.append("exit")
            return False

    def run(args, evo):
        events.append(("run", args.action, evo.spec.name))

    monkeypatch.setattr(evoctl, "EVOController", FakeController)
    monkeypatch.setattr(evoctl, "_run", run)

    evoctl.main(["--device", "evo4", "status"])

    assert events == [("init", "evo4"), "enter", ("run", "status", "evo4"), "exit"]


def test_diag_is_not_cli_command(capsys):
    with pytest.raises(SystemExit) as exc:
        evoctl.parse_args(EVO4, ["diag"])

    assert exc.value.code == 2
