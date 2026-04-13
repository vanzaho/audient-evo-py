"""Diagnostic info collector for remote tester support."""

import glob
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evo.devices import DEVICES, detect_devices  # noqa: E402


def _run(cmd: str, timeout: int = 5) -> str:
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return "<timeout>"
    except Exception as e:
        return f"<error: {e}>"


def _file_exists_info(path: str) -> dict:
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return {"path": expanded, "exists": False}
    try:
        stat = os.stat(expanded)
        return {"path": expanded, "exists": True, "mode": oct(stat.st_mode)}
    except OSError as e:
        return {"path": expanded, "exists": True, "stat_error": str(e)}


def _glob_files(pattern: str) -> list[str]:
    return sorted(glob.glob(os.path.expanduser(pattern)))


def collect_diagnostics() -> dict:
    diag = {
        "system": {
            "kernel": platform.release(),
            "python": sys.version,
            "distro": _run("cat /etc/os-release 2>/dev/null | head -2"),
            "arch": platform.machine(),
        },
        "usb": {
            "lsusb_audient": _run("lsusb -d 2708:"),
            "dev_nodes": {
                spec.dev_path: _file_exists_info(spec.dev_path)
                for spec in DEVICES.values()
            },
        },
        "kmod": {
            "lsmod": _run("lsmod | grep evo_raw"),
            "lsmod_legacy": _run("lsmod | grep evo4_raw"),
            "dkms": _run("dkms status 2>/dev/null | grep evo"),
        },
        "udev": {"rules": _glob_files("/etc/udev/rules.d/99-evo*.rules")},
        "audio": {
            "pipewire": _run("systemctl --user is-active pipewire.service"),
            "wireplumber": _run("systemctl --user is-active wireplumber.service"),
            "wpctl_status": _run("wpctl status 2>/dev/null | grep -i evo"),
        },
        "configs": {
            "pipewire": _glob_files("~/.config/pipewire/pipewire.conf.d/evo*"),
            "wireplumber": (
                _glob_files("~/.config/wireplumber/wireplumber.conf.d/*evo*")
                + _glob_files(
                    "~/.config/wireplumber/wireplumber.conf.d/alsa-soft-mixer.conf"
                )
            ),
            "systemd_setup": _glob_files("~/.config/systemd/user/evo*-setup.service"),
            "systemd_load": _glob_files("~/.config/systemd/user/evo*-load-config.service"),
            "local_bin": _glob_files("~/.local/bin/evo*"),
        },
        "devices": {},
        "saved_configs": {},
    }

    for spec in detect_devices():
        try:
            from evo.controller import EVOController

            evo = EVOController(spec)
            diag["devices"][spec.name] = {"status": evo.decode_status(evo.get_status_raw())}
        except Exception as e:
            diag["devices"][spec.name] = {"error": str(e)}

    for name in DEVICES:
        path = f"~/.config/audient-evo-py/{name}/config.json"
        diag["saved_configs"][name] = _file_exists_info(path)

    return diag


def main() -> None:
    print(json.dumps(collect_diagnostics(), indent=2))


if __name__ == "__main__":
    main()
