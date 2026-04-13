#!/usr/bin/env python3
"""USB control transfer probe for Audient EVO4 reverse engineering.

This tool was used to reverse-engineer the EVO4's USB control protocol:

1. SCAN: Send GET_CUR to every combination of USB entity, control selector,
   and channel number. The device STALLs invalid combinations and returns
   data for valid ones. This maps out which entities exist and what controls
   they expose.

2. GET: Read the current value of a specific entity/CS/CN combination.
   Identify what each control does by comparing values to the physical
   device state.

3. SET: Write a value to a specific entity/CS/CN, then observe the effect
   (audible change, readback confirmation, behavior in the vendor app).
   This confirms what each control actually does.

USB Audio Class 2.0 addressing:
  wIndex = (EntityID << 8) | InterfaceNumber
  wValue = (ControlSelector << 8) | ChannelNumber

Run from the project root:
  python dev/probe.py scan
  python dev/probe.py get 0x0A00 2 1
  python dev/probe.py set 0x0A00 2 1 0x1234

See dev/FINDINGS.md for the complete probe results.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from evo import kmod as evo4_kmod
from evo.devices import EVO4

# Known entities from USB descriptors
KNOWN_UNITS = {
    "fu10": (0x0A00, "Output Volume"),
    "fu11": (0x0B00, "Input Gain"),
    "eu50": (0x3200, "Unknown"),
    "eu56": (0x3800, "Monitor Mix"),
    "eu57": (0x3900, "Unknown"),
    "eu58": (0x3A00, "Input Mute/Config"),
    "eu59": (0x3B00, "Output Mute"),
    "mu60": (0x3C00, "Mixer Unit"),
}


def parse_int(s):
    """Parse int from hex (0x...) or decimal string."""
    return int(s, 16) if s.startswith("0x") or s.startswith("0X") else int(s)


def cmd_scan(fd):
    """Scan all known entities for valid CS/CN combinations."""
    for name, (wIndex, desc) in KNOWN_UNITS.items():
        print(f"\n=== {name.upper()} — {desc} (wIndex=0x{wIndex:04X}) ===")
        for cs in range(8):
            for cn in range(5):
                wValue = (cs << 8) | cn
                for length in (2, 4, 1):
                    try:
                        data = evo4_kmod.get_cur(fd, wValue=wValue,
                                                 wIndex=wIndex, length=length)
                        print(f"  CS={cs} CN={cn} len={length}: {data.hex()}")
                        break
                    except OSError:
                        continue


def cmd_get(fd, wIndex, cs, cn, length=2):
    """Read a single value."""
    wValue = (cs << 8) | cn
    data = evo4_kmod.get_cur(fd, wValue=wValue, wIndex=wIndex, length=length)
    raw = int.from_bytes(data[:length], "little", signed=True)
    print(f"GET wIndex=0x{wIndex:04X} CS={cs} CN={cn}: "
          f"raw={raw} (0x{raw & 0xFFFF:04X})  bytes={data.hex()}")


def cmd_set(fd, wIndex, cs, cn, value, length=2):
    """Write a value and read it back."""
    wValue = (cs << 8) | cn

    # Read current
    try:
        cur = evo4_kmod.get_cur(fd, wValue=wValue, wIndex=wIndex, length=length)
        cur_raw = int.from_bytes(cur[:length], "little", signed=True)
        print(f"Current: {cur_raw} (0x{cur_raw & ((1 << length*8) - 1):0{length*2}X})  "
              f"bytes={cur[:length].hex()}")
    except OSError as e:
        print(f"GET failed: {e}")

    # Set new value
    mask = (1 << length * 8) - 1
    data = (value & mask).to_bytes(length, "little")
    evo4_kmod.set_cur(fd, wValue=wValue, wIndex=wIndex, data=data)
    print(f"Sent: bytes={data.hex()}")

    # Read back
    try:
        rb = evo4_kmod.get_cur(fd, wValue=wValue, wIndex=wIndex, length=length)
        rb_raw = int.from_bytes(rb[:length], "little", signed=True)
        print(f"Readback: {rb_raw} (0x{rb_raw & mask:0{length*2}X})  "
              f"bytes={rb[:length].hex()}")
    except OSError as e:
        print(f"Readback failed: {e}")


def cmd_scan_set(fd, wIndex_filter=None):
    """Blind SET_CUR scan — for entities that STALL on GET_CUR (e.g. MU60).

    Writes zero to each CS/CN and checks for STALL vs acceptance.
    """
    targets = KNOWN_UNITS.items()
    if wIndex_filter is not None:
        targets = [(k, v) for k, v in targets if v[0] == wIndex_filter]

    for name, (wIndex, desc) in targets:
        print(f"\n=== {name.upper()} — {desc} (wIndex=0x{wIndex:04X}) ===")
        for cs in range(8):
            for cn in range(5):
                wValue = (cs << 8) | cn
                for length in (2, 4):
                    data = b'\x00' * length
                    try:
                        evo4_kmod.set_cur(fd, wValue=wValue, wIndex=wIndex, data=data)
                        print(f"  CS={cs} CN={cn} len={length}: ACCEPTED (set zero)")
                        break
                    except OSError:
                        continue


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  probe.py scan                                # discover all entities")
        print("  probe.py scan-set [wIndex]                   # blind SET_CUR scan")
        print("  probe.py get <wIndex> <cs> <cn> [len]        # read a value")
        print("  probe.py set <wIndex> <cs> <cn> <val> [len]  # write a value")
        print()
        print("wIndex and val accept hex (0x0A00) or decimal.")
        print("len defaults to 2; use 4 for Extension Unit controls.")
        print(f"Known units: {', '.join(f'{k}=0x{v[0]:04X}' for k, v in KNOWN_UNITS.items())}")
        sys.exit(1)

    with evo4_kmod.open_device(EVO4.dev_path) as fd:
        cmd = sys.argv[1]

        if cmd == "scan":
            cmd_scan(fd)

        elif cmd == "scan-set":
            wIndex = parse_int(sys.argv[2]) if len(sys.argv) > 2 else None
            cmd_scan_set(fd, wIndex)

        elif cmd == "get":
            wIndex = parse_int(sys.argv[2])
            cs = int(sys.argv[3])
            cn = int(sys.argv[4])
            length = int(sys.argv[5]) if len(sys.argv) > 5 else 2
            cmd_get(fd, wIndex, cs, cn, length)

        elif cmd == "set":
            wIndex = parse_int(sys.argv[2])
            cs = int(sys.argv[3])
            cn = int(sys.argv[4])
            value = parse_int(sys.argv[5])
            length = int(sys.argv[6]) if len(sys.argv) > 6 else 2
            cmd_set(fd, wIndex, cs, cn, value, length)

        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)


if __name__ == "__main__":
    main()
