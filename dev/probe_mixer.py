#!/usr/bin/env python3
"""Brute-force MU60 cross-point probe.

Sweeps all possible CN values (0-255) setting each to 0 dB one at a time,
with all others muted. Watch OBS loopback capture meter — when it jumps,
that CN is active.

Usage:
  1. Play YouTube → EVO4 Loopback Output
  2. Open OBS monitoring EVO4 Loopback (capture)
  3. Run: python dev/probe_mixer.py
  4. Press Enter to advance through CNs, note which ones show signal
"""

import sys
import time
sys.path.insert(0, ".")

from evo import kmod
from evo.controller import _db_to_usb, _MU60, _CS_MIXER, _MIXER_DB_MIN
from evo.devices import EVO4

MUTE = _db_to_usb(_MIXER_DB_MIN)   # -128 dB = silence
UNITY = _db_to_usb(0.0)            # 0 dB

MAX_CN = 64  # UAC2 allows up to 255 but EVO4 likely uses far fewer


def set_cn(fd, cn, raw):
    kmod.set_cur(fd, wValue=(_CS_MIXER << 8) | cn, wIndex=_MU60,
                 data=raw.to_bytes(2, "little"))


def mute_all(fd):
    """Mute all cross-points [0, MAX_CN-1]."""
    for cn in range(MAX_CN):
        try:
            set_cn(fd, cn, MUTE)
        except OSError:
            pass  # device may reject high CNs


def probe_single(fd, cn):
    """Set one CN to 0 dB, all others muted."""
    set_cn(fd, cn, UNITY)


def main():
    print("MU60 Cross-Point Probe")
    print("=" * 50)
    print(f"Sweeping CN [0, {MAX_CN - 1}], setting each to 0 dB")
    print("Watch OBS loopback capture meter for signal.")
    print()
    print("Commands:")
    print("  Enter  = next CN")
    print("  b      = back one CN")
    print("  NUMBER = jump to that CN")
    print("  s      = set current CN to 0 dB (re-activate)")
    print("  m      = mute current CN")
    print("  a      = activate ALL [0, current] (find cumulative effect)")
    print("  r      = read-back current CN (test GET_CUR)")
    print("  q      = quit")
    print()

    with kmod.open_device(EVO4.dev_path) as fd:
        print("Muting all cross-points...")
        mute_all(fd)
        print("Done. Starting probe.\n")

        cn = 0
        active = set()

        while cn < MAX_CN:
            # Mute previous active CNs, activate only current
            for a in active:
                try:
                    set_cn(fd, a, MUTE)
                except OSError:
                    pass
            active.clear()

            try:
                probe_single(fd, cn)
                active.add(cn)
                print(f"[CN {cn:3d}]  0 dB  -- watching for signal...", end="  ", flush=True)
            except OSError as e:
                print(f"[CN {cn:3d}]  ERROR: {e}", end="  ", flush=True)

            cmd = input().strip().lower()

            if cmd == "q":
                break
            elif cmd == "b":
                cn = max(0, cn - 1)
            elif cmd == "s":
                set_cn(fd, cn, UNITY)
                active.add(cn)
                continue
            elif cmd == "m":
                set_cn(fd, cn, MUTE)
                active.discard(cn)
                continue
            elif cmd == "a":
                # Activate all from 0 to current
                for i in range(cn + 1):
                    try:
                        set_cn(fd, i, UNITY)
                        active.add(i)
                    except OSError:
                        pass
                print(f"  Activated CN [0, {cn}]")
                continue
            elif cmd == "r":
                try:
                    data = kmod.get_cur(fd, wValue=(_CS_MIXER << 8) | cn,
                                        wIndex=_MU60, length=2)
                    raw = int.from_bytes(data[:2], "little", signed=True)
                    print(f"  GET_CUR CN {cn}: raw=0x{raw & 0xFFFF:04X} ({raw / 256.0:+.2f} dB)")
                except OSError as e:
                    print(f"  GET_CUR CN {cn}: STALL ({e})")
                continue
            elif cmd.isdigit():
                cn = int(cmd)
                continue
            else:
                cn += 1

        # Cleanup: mute everything
        print("\nMuting all cross-points...")
        mute_all(fd)
        print("Done.")


if __name__ == "__main__":
    main()
