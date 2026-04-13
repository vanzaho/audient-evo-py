import argparse
import errno
import sys
from evo import config as cfg
from evo.controller import EVOController
from evo.devices import DEVICES, detect_devices


def _resolve_device():
    """Auto-detect device or error if ambiguous."""
    found = detect_devices()
    if len(found) == 1:
        return found[0]
    if len(found) == 0:
        names = ", ".join(s.dev_path for s in DEVICES.values())
        print(f"error: no EVO device found (checked {names})", file=sys.stderr)
        sys.exit(1)
    names = ", ".join(s.name for s in found)
    print(f"error: multiple devices found ({names}). Use --device to select one.", file=sys.stderr)
    sys.exit(1)


def parse_args(spec):
    input_targets = [f"input{i+1}" for i in range(spec.num_inputs)]
    if spec.num_output_pairs == 1:
        mute_targets = input_targets + ["output"]
    else:
        mute_targets = input_targets + [f"output{i+1}" for i in range(spec.num_output_pairs)]

    parameters = ["volume", "gain", "mute", "phantom"]
    if spec.has_monitor:
        parameters.insert(3, "monitor")
    cf = cfg.config_file(spec.name)

    parser = argparse.ArgumentParser(description=f"Audient {spec.display_name} config tool.")
    parser.add_argument(
        "--device", "-d", choices=list(DEVICES.keys()), default=None,
        help="Device to control (auto-detected if only one connected).",
    )
    sparser = parser.add_subparsers(dest="action", required=True)

    get_p = sparser.add_parser("get", aliases=["g"], help="Get device param.")
    get_p.add_argument("parameter", choices=parameters)
    get_p.add_argument("--target", "-t", choices=mute_targets, default=None)

    set_p = sparser.add_parser("set", aliases=["s"], help="Set device param.")
    set_p.add_argument("parameter", choices=parameters)
    set_p.add_argument("value", type=str)
    set_p.add_argument("--target", "-t", choices=mute_targets, default=None)

    status_p = sparser.add_parser("status", help="Show all device params.")
    status_p.add_argument("--format", "-f", choices=["plain", "json"], default="plain")

    save_p = sparser.add_parser("save", help="Save config to file.")
    save_p.add_argument("path", nargs="?", default=None, help=f"Defa: {cf}.")
    load_p = sparser.add_parser("load", help="Load and apply config from file.")
    load_p.add_argument("path", nargs="?", default=None, help=f"Defa: {cf}.")

    # Mixer
    mixer_p = sparser.add_parser("mixer", aliases=["m"], help="Mixer matrix config.")
    mixer_sp = mixer_p.add_subparsers(dest="mixer_section", required=True)

    _VOLUME_HELP = "dB (mute) <-128,6> (gain). 0 == pass as is."
    mix_choices = range(spec.num_output_pairs)
    mix_help = ", ".join(
        f"{i}=MIX {cfg.mix_output_label(spec, i)}" for i in mix_choices
    )
    _MIX_OUTPUT_HELP = f"Mixer destination ({mix_help}). Default: 0."
    for i in range(spec.num_inputs):
        inp = f"input{i+1}"
        inp_p = mixer_sp.add_parser(inp, help=f"Set {inp} level in mixer output.")
        inp_p.set_defaults(input_num=i + 1)
        inp_p.add_argument("--volume", type=float, required=True, help=_VOLUME_HELP)
        inp_p.add_argument(
            "--pan", type=float, default=0.0,
            help="(left) <-100,100> (right). Default: 0 (center).",
        )
        inp_p.add_argument(
            "--mix-output",
            dest="mix_output",
            type=int,
            choices=mix_choices,
            default=0,
            help=_MIX_OUTPUT_HELP,
        )

    for pair in range(cfg.num_mixer_output_sources(spec)):
        out = cfg.output_key(pair)
        suffix = " (loopback)" if pair >= spec.num_output_pairs else ""
        out_p = mixer_sp.add_parser(
            out,
            help=f"Set OUT {cfg.stereo_pair_label(pair)}{suffix} level in mixer output.",
        )
        out_p.set_defaults(output_pair=pair)
        out_p.add_argument("--volume", type=float, required=True, help=_VOLUME_HELP)
        out_p.add_argument(
            "--pan-l", type=float, default=-100.0,
            help="L channel (left) <-100,100> (right). Default: -100.",
        )
        out_p.add_argument(
            "--pan-r", type=float, default=100.0,
            help="R channel (left) <-100,100> (right). Default: 100.",
        )
        out_p.add_argument(
            "--mix-output",
            dest="mix_output",
            type=int,
            choices=mix_choices,
            default=0,
            help=_MIX_OUTPUT_HELP,
        )

    args = parser.parse_args()

    if args.action in ("status", "save", "load", "mixer", "m"):
        return args

    if args.action in ("set", "s"):
        if args.parameter in ("volume", "gain", "monitor"):
            if args.parameter in ("volume", "gain"):
                try:
                    args.value = float(args.value)
                except ValueError:
                    parser.error(f"{args.parameter} value must be a number.")
                if args.parameter == "volume" and not (spec.vol_db_min <= args.value <= spec.vol_db_max):
                    parser.error(f"Volume must be between {spec.vol_db_min:.0f} and {spec.vol_db_max:.0f} dB.")
                if args.parameter == "gain" and not (spec.gain_db_min <= args.value <= spec.gain_db_max):
                    parser.error(f"Gain must be between {spec.gain_db_min:.0f} and {spec.gain_db_max:.0f} dB.")
            else:  # monitor
                try:
                    args.value = int(args.value)
                except ValueError:
                    parser.error(f"{args.parameter} value must be an integer.")
                if not (0 <= args.value <= 100):
                    parser.error(f"{args.parameter.capitalize()} must be between 0 and 100.")
        else:
            if args.parameter in ["mute", "phantom"]:
                if args.value not in ("1", "0"):
                    parser.error(f"{args.parameter} value must be 1/0.")
                args.value = args.value == "1"

    for p, ts in [
        ("gain", input_targets),
        ("mute", mute_targets),
        ("phantom", input_targets),
    ]:
        if args.parameter == p:
            if not args.target or args.target not in ts:
                parser.error(f"{p} requires --target/-t <{'|'.join(ts)}>.")

    return args


def _format_status_plain(state: dict, spec) -> str:
    W = 10
    lines = []
    for i in range(spec.num_inputs):
        ch = f"input{i+1}"
        label = f"Input {i+1}"
        inp = state[ch]
        lines.append(f"{label}:")
        lines.append(f"  {'gain:':<{W}}{inp['gain']:+.1f} dB")
        lines.append(f"  {'mute:':<{W}}{'on' if inp['mute'] else 'off'}")
        lines.append(f"  {'phantom:':<{W}}{'on' if inp['phantom'] else 'off'}")
        lines.append("")

    if spec.num_output_pairs == 1:
        out = state["output"]
        lines.append("Main output 1|2:")
        lines.append(f"  {'volume:':<{W}}{out['volume']:+.1f} dB")
        lines.append(f"  {'mute:':<{W}}{'on' if out['mute'] else 'off'}")
    else:
        for pair in range(spec.num_output_pairs):
            key = f"output{pair+1}"
            out = state[key]
            ch1 = pair * 2 + 1
            ch2 = ch1 + 1
            lines.append(f"Output {ch1}|{ch2}:")
            lines.append(f"  {'volume:':<{W}}{out['volume']:+.1f} dB")
            lines.append(f"  {'mute:':<{W}}{'on' if out['mute'] else 'off'}")
    if "monitor" in state:
        lines.append("")
        lines.append(f"Monitor mix: {state['monitor']}%")
    return "\n".join(lines)


def _get_output_pair(args, spec) -> int | None:
    """Extract output_pair from args if applicable. Returns 0-based index or None."""
    if spec.num_output_pairs == 1:
        return None
    target = getattr(args, "target", None)
    if not target or not target.startswith("output"):
        return None
    try:
        return int(target[len("output"):]) - 1
    except (ValueError, IndexError):
        return None


def _run(args, evo: EVOController):
    spec = evo.spec

    if args.action in ("get", "g"):
        if args.parameter == "volume":
            pair = _get_output_pair(args, spec) or 0
            raw, db = evo.get_volume_debug(pair)
            suffix = f" (output {pair+1})" if spec.num_output_pairs > 1 else ""
            print(f"[GET] Volume{suffix}: {db:+.2f} dB  (raw=0x{raw & 0xFFFF:04X})")

        elif args.parameter == "gain":
            raw, db = evo.get_gain_debug(args.target)
            print(f"[GET] Gain {args.target}: {db:+.2f} dB  (raw=0x{raw & 0xFFFF:04X})")

        elif args.parameter == "mute":
            muted = evo.get_mute(args.target)
            print(f"[GET] Mute {args.target}: {'on' if muted else 'off'}")

        elif args.parameter == "monitor":
            mix = evo.get_monitor()
            print(f"[GET] Monitor: {mix}% (0=input, 100=playback)")

        elif args.parameter == "phantom":
            state = evo.get_phantom(args.target)
            print(f"[GET] Phantom 48V {args.target}: {'on' if state else 'off'}")

    elif args.action in ("set", "s"):
        if args.parameter == "volume":
            pair = _get_output_pair(args, spec)
            raw, db = evo.set_volume(args.value, output_pair=pair)
            suffix = f" (output {pair+1})" if pair is not None else ""
            print(f"[SET] Volume{suffix}: {db:+.2f} dB  (raw=0x{raw & 0xFFFF:04X})")

        elif args.parameter == "gain":
            raw, db = evo.set_gain(args.target, args.value)
            print(f"[SET] Gain {args.target}: {db:+.2f} dB  (raw=0x{raw & 0xFFFF:04X})")

        elif args.parameter == "mute":
            evo.set_mute(args.target, args.value)
            print(f"[SET] Mute {args.target}: {'1' if args.value else '0'}")

        elif args.parameter == "monitor":
            evo.set_monitor(args.value)
            print(f"[SET] Monitor: {args.value}% (0=input, 100=playback)")

        elif args.parameter == "phantom":
            evo.set_phantom(args.target, args.value)
            print(f"[SET] Phantom 48V {args.target}: {'on' if args.value else 'off'}")

    elif args.action in ("mixer", "m"):
        sec = args.mixer_section
        mix_output = getattr(args, "mix_output", 0)
        state = cfg.load_or_default_mixer_state(spec)
        if hasattr(args, "input_num"):
            evo.set_mixer_input(args.input_num, args.volume, args.pan, mix_output)
            cfg.update_mixer_input_state(
                state, spec, args.input_num, args.volume, args.pan, mix_output
            )
            mix_suffix = f" (mix {cfg.mix_output_label(spec, mix_output)})"
            print(
                f"[SET] Mixer {sec}{mix_suffix}: volume={args.volume:+.1f} dB, "
                f"pan={args.pan:+.0f}"
            )
        elif hasattr(args, "output_pair"):
            evo.set_mixer_output(
                args.volume,
                args.pan_l,
                args.pan_r,
                output_pair=args.output_pair,
                mix_output=mix_output,
            )
            cfg.update_mixer_output_state(
                state,
                spec,
                args.output_pair,
                args.volume,
                args.pan_l,
                args.pan_r,
                mix_output,
            )
            mix_suffix = f" (mix {cfg.mix_output_label(spec, mix_output)})"
            print(
                f"[SET] Mixer {sec}{mix_suffix}: volume={args.volume:+.1f} dB, "
                f"pan_l={args.pan_l:+.0f}, pan_r={args.pan_r:+.0f}"
            )
        cfg.save_mixer_state(spec.name, state)

    elif args.action == "save":
        from evo.config import save

        path = save(evo, args.path)
        print(f"Config saved to {path}")

    elif args.action == "load":
        from evo.config import load_and_apply

        load_and_apply(evo, args.path)
        print("Config loaded and applied.")

    elif args.action == "status":
        state = evo.decode_status(evo.get_status_raw())
        if args.format == "json":
            import json

            print(json.dumps(state, indent=2))
        else:
            print(_format_status_plain(state, spec))


_USB_ERRORS = {
    errno.ENODEV: "Device not connected (or USB device was removed).",
    errno.EPIPE: "USB STALL: device rejected the command.",
    errno.EPROTO: "USB protocol error - try unplugging and replugging the device.",
    errno.ETIMEDOUT: "USB timeout - try unplugging and replugging the device.",
}

def main():
    # Handle 'diag' before device resolution (works without any device)
    if len(sys.argv) > 1 and sys.argv[1] == "diag":
        import json
        from evo.diag import collect_diagnostics
        print(json.dumps(collect_diagnostics(), indent=2))
        return

    # Pre-parse --device before building full parser (need spec for choices)
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--device", "-d", choices=list(DEVICES.keys()), default=None)
    pre_args, _ = pre.parse_known_args()

    if pre_args.device:
        spec = DEVICES[pre_args.device]
    else:
        spec = _resolve_device()

    args = parse_args(spec)
    try:
        evo = EVOController(spec)
        _run(args, evo)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        msg = _USB_ERRORS.get(e.errno if e.errno else -1, f"USB error: {e}")
        print(f"error: {msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
