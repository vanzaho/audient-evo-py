"""Audient EVO controller - all controls via evo_raw kernel module.

Controls go through /dev/evo* (USB control transfers) without
disrupting snd-usb-audio streaming.

Controls (same entity IDs across EVO 4/8):
  Feature Unit 10: output volume, [-96.0, 0.0] dB
  Feature Unit 11: input gain (range varies by device)
  Extension Unit 56: monitor mix, [0, 127] (EVO 4 only)
  Extension Unit 58: input mute, phantom power (48V)
  Extension Unit 59: output mute
  Mixer Unit 60: output-source mixer (dimensions vary by device)
"""

import math
import struct
from contextlib import contextmanager
from os.path import exists

from evo import kmod
from evo.devices import DeviceSpec


# UAC2 Feature Unit control selectors
_CS_VOLUME = 2

# Feature Unit wIndex values: (EntityID << 8) | Interface
_FU10 = 0x0A00  # Output volume
_FU11 = 0x0B00  # Input gain

# Gain step (device quantizes to 1 dB steps on all models)
_GAIN_DB_STEP = 1.0

# Mixer Unit 60 (MU60) - output-source mixer.
# Write-only (GET_CUR STALLs). Uses UAC2 Q8.8 dB values.
_MU60 = 0x3C00  # (EntityID=60 << 8) | Interface=0
_CS_MIXER = 1  # Mixer Control selector (UAC2 standard for MU)
_MIXER_DB_MIN = -128.0  # 0x8000 = silence
_MIXER_DB_MAX = 6.0  # 0x0600 (Windows app limit)


def _db_to_usb(db: float) -> int:
    """Convert dB to UAC2 16-bit signed (1/256 dB steps)."""
    return round(db * 256) & 0xFFFF


def _usb_to_db(raw: int) -> float:
    """Convert UAC2 16-bit signed to dB."""
    if raw > 0x7FFF:
        raw -= 0x10000
    return raw / 256.0


class EVOController:
    def __init__(self, spec: DeviceSpec):
        self.spec = spec
        self._require_kmod()
        self._fd = None

        # Build target dicts from spec
        self._gain_targets = {f"input{i+1}": i + 1 for i in range(spec.num_inputs)}

        # Mute targets: inputs use EU58 (0x3A00), outputs use EU59 (0x3B00)
        self._mute_targets = {}
        for i in range(spec.num_inputs):
            self._mute_targets[f"input{i+1}"] = (0x0200 + i, 0x3A00)
        if spec.num_output_pairs == 1:
            self._mute_targets["output"] = (0x0100, 0x3B00)
        else:
            for i in range(spec.num_output_pairs):
                target_idx = spec.num_inputs + i
                self._mute_targets[f"output{i+1}"] = (0x0200 + target_idx, 0x3A00)

        # Phantom targets: one per input, EU58 CS=0
        self._phantom_targets = {
            f"input{i+1}": (0x0000 + i, 0x3A00) for i in range(spec.num_inputs)
        }

        # Mixer dimensions
        self._mixer_max_cn = spec.mixer_inputs * spec.mixer_outputs
        # MU60 inputs are mic/line inputs followed by stereo USB output source pairs.
        self._num_mixer_output_sources = (spec.mixer_inputs - spec.num_inputs) // 2
        self._out_num_outputs = spec.mixer_outputs

    def __enter__(self):
        self._fd = kmod.open_device(self.spec.dev_path)
        return self

    def __exit__(self, *exc):
        if self._fd is not None:
            self._fd.close()
            self._fd = None
        return False

    @contextmanager
    def _device(self):
        """Yield the shared fd (context manager mode) or a temporary one."""
        if self._fd is not None:
            yield self._fd
        else:
            with kmod.open_device(self.spec.dev_path) as fd:
                yield fd

    # --- Output Volume (Feature Unit 10) ---

    def _get_fu_raw(self, unit: int, cn: int) -> int:
        """Read raw 16-bit USB value from a Feature Unit channel."""
        with self._device() as fd:
            data = kmod.get_cur(fd, wValue=(_CS_VOLUME << 8) | cn, wIndex=unit, length=2)
            return int.from_bytes(data[:2], "little", signed=True)

    def _set_fu_raw(self, unit: int, cn: int, raw: int) -> None:
        """Write raw 16-bit USB value to a Feature Unit channel."""
        with self._device() as fd:
            kmod.set_cur(
                fd,
                wValue=(_CS_VOLUME << 8) | cn,
                wIndex=unit,
                data=(raw & 0xFFFF).to_bytes(2, "little"),
            )

    def get_volume(self, output_pair: int = 0) -> float:
        """Get output volume in dB. Both channels of the pair are ganged.
        output_pair: 0-based index (0 for OUT1+2, 1 for OUT3+4 on EVO 8).
        """
        cn = output_pair * 2 + 1
        return _usb_to_db(self._get_fu_raw(_FU10, cn))

    def get_volume_debug(self, output_pair: int = 0) -> tuple[int, float]:
        """Get volume with debug info: (raw, dB)."""
        cn = output_pair * 2 + 1
        raw = self._get_fu_raw(_FU10, cn)
        db = _usb_to_db(raw)
        return (raw, db)

    def set_volume(self, db: float, output_pair: int | None = None) -> tuple[int, float]:
        """Set output volume in dB on both channels of the pair.
        output_pair: 0-based index, or None to set all pairs.
        Returns (raw, dB) sent."""
        db = max(self.spec.vol_db_min, min(self.spec.vol_db_max, db))
        raw = _db_to_usb(db)
        if output_pair is None:
            # Set all output pairs
            for pair in range(self.spec.num_output_pairs):
                base_cn = pair * 2 + 1
                for cn in range(base_cn, base_cn + 2):
                    self._set_fu_raw(_FU10, cn, raw)
        else:
            base_cn = output_pair * 2 + 1
            for cn in range(base_cn, base_cn + 2):
                self._set_fu_raw(_FU10, cn, raw)
        return (raw if raw <= 0x7FFF else raw - 0x10000, db)

    # --- Input Gain (Feature Unit 11) ---

    def get_gain(self, target: str) -> float:
        """Get input gain in dB for target (input1, input2, ...)."""
        cn = self._gain_targets[target]
        return self._snap_gain_db(_usb_to_db(self._get_fu_raw(_FU11, cn)))

    def get_gain_debug(self, target: str) -> tuple[int, float]:
        """Get gain with debug info: (raw, dB) for target."""
        cn = self._gain_targets[target]
        raw = self._get_fu_raw(_FU11, cn)
        db = self._snap_gain_db(_usb_to_db(raw))
        return (raw, db)

    def set_gain(self, target: str, db: float) -> tuple[int, float]:
        """Set target input gain in dB. Returns (raw, dB) sent."""
        cn = self._gain_targets[target]
        db = max(self.spec.gain_db_min, min(self.spec.gain_db_max, db))
        raw = _db_to_usb(db)
        self._set_fu_raw(_FU11, cn, raw)
        return (raw if raw <= 0x7FFF else raw - 0x10000, db)

    # --- Mute (Entity 58 for inputs, Entity 59 for output) ---

    def get_mute(self, target: str) -> bool:
        """Get mute state for target."""
        wValue, wIndex = self._mute_targets[target]
        with self._device() as fd:
            data = kmod.get_cur(fd, wValue=wValue, wIndex=wIndex, length=4)
            return int.from_bytes(data[:4], "little") == 1

    def set_mute(self, target: str, muted: bool) -> None:
        """Set mute state for target."""
        wValue, wIndex = self._mute_targets[target]
        with self._device() as fd:
            data = (1 if muted else 0).to_bytes(4, "little")
            kmod.set_cur(fd, wValue=wValue, wIndex=wIndex, data=data)

    # --- Phantom Power (Extension Unit 58, CS=0) ---

    def get_phantom(self, target: str) -> bool:
        """Get 48V phantom power state for target."""
        wValue, wIndex = self._phantom_targets[target]
        with self._device() as fd:
            data = kmod.get_cur(fd, wValue=wValue, wIndex=wIndex, length=4)
            return int.from_bytes(data[:4], "little") == 1

    def set_phantom(self, target: str, enabled: bool) -> None:
        """Set 48V phantom power for target."""
        wValue, wIndex = self._phantom_targets[target]
        with self._device() as fd:
            data = (1 if enabled else 0).to_bytes(4, "little")
            kmod.set_cur(fd, wValue=wValue, wIndex=wIndex, data=data)

    # --- Monitor Mix (Extension Unit 56) ---

    _EU56_WINDEX = 0x3800
    _EU56_WVALUE = 0x0000

    def get_monitor(self) -> int:
        """Get monitor mix ratio (0=input only, 100=playback only).
        Only available on EVO 4. EVO 8 uses the mixer matrix instead.
        """
        if not self.spec.has_monitor:
            raise RuntimeError(f"{self.spec.display_name} does not have a direct monitor control")
        with self._device() as fd:
            data = kmod.get_cur(fd, wValue=self._EU56_WVALUE, wIndex=self._EU56_WINDEX, length=2)
            raw = int.from_bytes(data[:2], "little")
            return round(raw * 100 / 127)

    def set_monitor(self, ratio: int) -> None:
        """Set monitor mix ratio (0=input only, 100=playback only).
        Only available on EVO 4. EVO 8 uses the mixer matrix instead.
        """
        if not self.spec.has_monitor:
            raise RuntimeError(f"{self.spec.display_name} does not have a direct monitor control")
        with self._device() as fd:
            raw = max(0, min(127, round(ratio * 127 / 100)))
            data = raw.to_bytes(2, "little")
            kmod.set_cur(fd, wValue=self._EU56_WVALUE, wIndex=self._EU56_WINDEX, data=data)

    # --- Full device status ---

    def get_status_raw(self) -> bytes:
        """Read all readable device state as a packed struct.

        Use decode_status() to convert to a config dict.
        """
        already_open = self._fd is not None
        if not already_open:
            self._fd = kmod.open_device(self.spec.dev_path)
        try:
            # Volume: read from first output pair
            vol = self._get_fu_raw(_FU10, 1)

            # Gains: one per input
            gains = [self._get_fu_raw(_FU11, i + 1) for i in range(self.spec.num_inputs)]

            # Monitor mix (EVO 4 only)
            if self.spec.has_monitor:
                with self._device() as fd:
                    mix_bytes = kmod.get_cur(fd, self._EU56_WVALUE, self._EU56_WINDEX, 2)
                    mix_raw = int.from_bytes(mix_bytes[:2], "little")
            else:
                mix_raw = None

            # Additional volumes for extra output pairs
            extra_vols = []
            for pair in range(1, self.spec.num_output_pairs):
                extra_vols.append(self._get_fu_raw(_FU10, pair * 2 + 1))

            # Mutes
            mutes = {t: int(self.get_mute(t)) for t in self._mute_targets}

            # Phantoms
            phantoms = {t: int(self.get_phantom(t)) for t in self._phantom_targets}
        finally:
            if not already_open and self._fd is not None:
                self._fd.close()
                self._fd = None

        # Pack into a dict-based format since struct varies by device
        return self._pack_status(vol, gains, mix_raw, extra_vols, mutes, phantoms)

    def _pack_status(self, vol, gains, mix_raw, extra_vols, mutes, phantoms) -> bytes:
        """Pack status into bytes. Format depends on device.
        mix_raw is None for devices without a direct monitor control (EVO 8).
        """
        # Base: vol(h) + gains(h * num_inputs) [+ mix(B) if has_monitor]
        # + extra_vols(h * (num_output_pairs-1)) + mutes(B * num_mute_targets)
        # + phantoms(B * num_inputs)
        parts = [struct.pack("<h", vol)]
        for g in gains:
            parts.append(struct.pack("<h", g))
        if mix_raw is not None:
            parts.append(struct.pack("<B", mix_raw))
        for ev in extra_vols:
            parts.append(struct.pack("<h", ev))
        for t in sorted(mutes):
            parts.append(struct.pack("<B", mutes[t]))
        for t in sorted(phantoms):
            parts.append(struct.pack("<B", phantoms[t]))
        return b"".join(parts)

    def decode_status(self, data: bytes) -> dict:
        """Decode a raw status blob into a state dict."""
        offset = 0

        def read_h():
            nonlocal offset
            val = struct.unpack_from("<h", data, offset)[0]
            offset += 2
            return val

        def read_B():
            nonlocal offset
            val = struct.unpack_from("<B", data, offset)[0]
            offset += 1
            return val

        vol_raw = read_h()
        gains = [read_h() for _ in range(self.spec.num_inputs)]
        mix_raw = read_B() if self.spec.has_monitor else None
        extra_vols = [read_h() for _ in range(self.spec.num_output_pairs - 1)]
        mute_targets = sorted(self._mute_targets)
        mute_vals = {t: read_B() for t in mute_targets}
        phantom_targets = sorted(self._phantom_targets)
        phantom_vals = {t: read_B() for t in phantom_targets}

        result = {}
        if mix_raw is not None:
            result["monitor"] = round(mix_raw * 100 / 127)

        # Output section
        if self.spec.num_output_pairs == 1:
            result["output"] = {
                "volume": _usb_to_db(vol_raw),
                "mute": bool(mute_vals.get("output", 0)),
            }
        else:
            for pair in range(self.spec.num_output_pairs):
                key = f"output{pair+1}"
                v = vol_raw if pair == 0 else extra_vols[pair - 1]
                result[key] = {
                    "volume": _usb_to_db(v),
                    "mute": bool(mute_vals.get(key, 0)),
                }

        # Input sections
        for i in range(self.spec.num_inputs):
            key = f"input{i+1}"
            result[key] = {
                "gain": self._snap_gain_db(_usb_to_db(gains[i])),
                "mute": bool(mute_vals.get(key, 0)),
                "phantom": bool(phantom_vals.get(key, 0)),
            }

        return result

    @staticmethod
    def _snap_gain_db(db: float) -> float:
        """Snap dB to device's gain grid."""
        return round(db / _GAIN_DB_STEP) * _GAIN_DB_STEP

    def _require_kmod(self) -> None:
        if not exists(self.spec.dev_path):
            raise RuntimeError(
                f"evo_raw kernel module not loaded ({self.spec.dev_path} not found)"
            )

    # --- Mixer Matrix (Mixer Unit 60) ---

    def set_mixer_crosspoint(self, cn: int, db: float) -> None:
        """Set a single MU60 cross-point gain. cn=[0, max_cn-1], db=[-128, 6]."""
        if not 0 <= cn < self._mixer_max_cn:
            raise ValueError(f"Cross-point CN must be [0, {self._mixer_max_cn - 1}], got {cn}")
        db = max(_MIXER_DB_MIN, min(_MIXER_DB_MAX, db))
        with self._device() as fd:
            kmod.set_cur(
                fd,
                wValue=(_CS_MIXER << 8) | cn,
                wIndex=_MU60,
                data=_db_to_usb(db).to_bytes(2, "little"),
            )

    def get_mixer_crosspoint(self, cn: int) -> float:
        """Try GET_CUR on MU60. Raises OSError (EPIPE/STALL) if write-only."""
        if not 0 <= cn < self._mixer_max_cn:
            raise ValueError(f"Cross-point CN must be [0, {self._mixer_max_cn - 1}], got {cn}")
        with self._device() as fd:
            data = kmod.get_cur(fd, wValue=(_CS_MIXER << 8) | cn, wIndex=_MU60, length=2)
            return _usb_to_db(int.from_bytes(data[:2], "little", signed=True))

    @staticmethod
    def _pan_to_lr_db(volume_db: float, pan: float) -> tuple[float, float]:
        """Convert volume + pan to (left_dB, right_dB).
        pan: -100.0 (full left) to 100.0 (full right), 0.0 = center.
        Uses equal-power pan law (cos/sin).
        """
        pan = max(-100.0, min(100.0, pan))
        p = (pan + 100.0) / 200.0  # normalize to [0, 1]
        angle = p * (math.pi / 2)
        l_lin = math.cos(angle)
        r_lin = math.sin(angle)
        l_db = volume_db + (20 * math.log10(l_lin) if l_lin > 1e-10 else _MIXER_DB_MIN)
        r_db = volume_db + (20 * math.log10(r_lin) if r_lin > 1e-10 else _MIXER_DB_MIN)
        return (max(_MIXER_DB_MIN, l_db), max(_MIXER_DB_MIN, r_db))

    def set_mixer_input(
        self, input_num: int, gain_db: float, pan: float = 0.0, mix_output: int = 0
    ) -> None:
        """Route mic/line input to a mixer output with gain and pan.
        input_num: 1-based (1 to num_inputs).
        mix_output: 0-based mixer output (0=OUT1+2, 1=OUT3+4 on EVO 8).
        """
        if not 1 <= input_num <= self.spec.num_inputs:
            raise ValueError(
                f"input_num must be 1 to {self.spec.num_inputs}, got {input_num}"
            )
        if not 0 <= mix_output < self.spec.num_output_pairs:
            raise ValueError(
                f"mix_output must be 0 to {self.spec.num_output_pairs - 1}, got {mix_output}"
            )
        l_db, r_db = self._pan_to_lr_db(gain_db, pan)
        base = (input_num - 1) * self._out_num_outputs + mix_output * 2
        self.set_mixer_crosspoint(base + 0, l_db)
        self.set_mixer_crosspoint(base + 1, r_db)

    def set_mixer_output(
        self, volume_db: float, pan_l: float = -100.0, pan_r: float = 100.0,
        output_pair: int = 0, mix_output: int = 0,
    ) -> None:
        """Route a stereo USB output source pair to a mixer output.
        output_pair: 0-based source pair (0=OUT1+2, 1=OUT3+4, 2=OUT5+6 on EVO 8).
        mix_output: 0-based mixer output (0=OUT1+2, 1=OUT3+4 on EVO 8).
        """
        if not 0 <= output_pair < self._num_mixer_output_sources:
            raise ValueError(
                f"output_pair must be 0 to {self._num_mixer_output_sources - 1}, got {output_pair}"
            )
        if not 0 <= mix_output < self.spec.num_output_pairs:
            raise ValueError(
                f"mix_output must be 0 to {self.spec.num_output_pairs - 1}, got {mix_output}"
            )
        output_l_in = self.spec.num_inputs + output_pair * 2
        output_r_in = output_l_in + 1
        l_db_l, r_db_l = self._pan_to_lr_db(volume_db, pan_l)
        l_db_r, r_db_r = self._pan_to_lr_db(volume_db, pan_r)
        out_off = mix_output * 2
        self.set_mixer_crosspoint(output_l_in * self._out_num_outputs + out_off, l_db_l)
        self.set_mixer_crosspoint(output_l_in * self._out_num_outputs + out_off + 1, r_db_l)
        self.set_mixer_crosspoint(output_r_in * self._out_num_outputs + out_off, l_db_r)
        self.set_mixer_crosspoint(output_r_in * self._out_num_outputs + out_off + 1, r_db_r)
