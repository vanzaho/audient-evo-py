"""Curses TUI for Audient EVO devices"""

import curses
import sys

from evo.controller import (
    EVOController,
    _MIXER_DB_MIN,
    _MIXER_DB_MAX,
)
from evo.devices import DeviceSpec, detect_devices, DEVICES
from evo import config as cfg

C_GREEN, C_RED, C_CYAN, C_YELLOW, C_WHITE, C_BLUE = range(1, 7)

SLIDER_W = 69
BOX_IW = SLIDER_W + 2
SLIDER_OFF = 2
PICKER_LIST_H = 6

PAN_MIN, PAN_MAX, PAN_STEP = -100.0, 100.0, 5.0
MIN_MIXER_SECTION_IW = 17
MIN_MIXER_PAN_HALF = 7
COL_GAP = 1

# Box drawing - active (heavy) / inactive (light)
BOX_TL_A, BOX_H_A, BOX_TR_A = "\u250f", "\u2501", "\u2513"  # ┏ ━ ┓
BOX_V_A, BOX_BL_A, BOX_BR_A = "\u2503", "\u2517", "\u251b"  # ┃ ┗ ┛
BOX_ML_A, BOX_MR_A = "\u2523", "\u252b"  # ┣ ┫
BOX_TL, BOX_H, BOX_TR = "\u250c", "\u2500", "\u2510"  # ┌ ─ ┐
BOX_V, BOX_BL, BOX_BR = "\u2502", "\u2514", "\u2518"  # │ └ ┘
BOX_ML, BOX_MR = "\u251c", "\u2524"  # ├ ┤

# Bus junctions and double-line box drawing
J_CROSS, J_T_UP, J_T_DOWN = "\u253c", "\u2534", "\u252c"  # ┼ ┴ ┬
BUS_TL, BUS_TR, BUS_BL, BUS_BR = "\u2554", "\u2557", "\u255a", "\u255d"
BUS_H, BUS_V = "\u2550", "\u2551"
BUS_J_START, BUS_J_T_UP = "\u2558", "\u2567"  # ╘ ╧
BUS_J_T_DOWN, BUS_J_CROSS = "\u2566", "\u2566"  # ╦ ╦

# Slider / indicator glyphs
SL_FULL, ARROW_R, ARROW_R_EMPTY, ARROW_L = "\u25ac", "\u25b6", "\u25b7", "\u2190"  # ▬ ▶ ▷ ←
ARROW_D, ARROW_U = "\u2193", "\u2191"  # ↓ ↑
ARROWS = "\u2190\u2193\u2191\u2192"  # ←↓↑→
PM, CHEVRON = "\u00b1", "\u276f"  # ± ❯
TAB_SYM = "Tab"
HSEP = " \u00b7 "  # help separator: ·


def _build_elements(spec: DeviceSpec):
    """Build focusable elements list from device spec."""
    elements = [("output", "volume", "OUT", C_GREEN)]
    for i in range(spec.num_inputs):
        elements.append((f"input{i + 1}", "gain", f"IN {i + 1}", C_BLUE))
    if spec.has_monitor:
        elements.append(("monitor", None, "MONITOR", C_CYAN))
    return elements


def _build_element_groups(spec: DeviceSpec):
    """Build grouped element lists for subsection navigation.
    Returns list of (group_name, elements_list) tuples.
    EVO 4: single group with all elements (no subsection nav).
    EVO 8: two groups - Inputs and Outputs.
    """
    if spec.num_output_pairs == 1:
        return [("ALL", _build_elements(spec))]
    inputs = []
    for i in range(spec.num_inputs):
        inputs.append((f"input{i + 1}", "gain", f"IN {i + 1}", C_BLUE))
    outputs = []
    for i in range(spec.num_output_pairs):
        outputs.append((f"output{i + 1}", "volume", f"OUT {i * 2 + 1}|{i * 2 + 2}", C_GREEN))
    return [("INPUTS", inputs), ("OUTPUTS", outputs)]


def _build_ranges(spec: DeviceSpec):
    """Build value ranges dict from device spec."""
    if spec.num_output_pairs == 1:
        ranges = {"output": (spec.vol_db_min, spec.vol_db_max, 1.0)}
    else:
        ranges = {}
        for i in range(spec.num_output_pairs):
            ranges[f"output{i + 1}"] = (spec.vol_db_min, spec.vol_db_max, 1.0)
    for i in range(spec.num_inputs):
        ranges[f"input{i + 1}"] = (spec.gain_db_min, spec.gain_db_max, 1.0)
    if spec.has_monitor:
        ranges["monitor"] = (0, 100, 1)
    return ranges


def _build_mixer_sections(spec: DeviceSpec):
    """Build mixer sections as list of rows.
    EVO 4: single row with all sections.
    EVO 8: row 1 = inputs, row 2 = outputs + loopback.
    Each row is a list of (key, label, color, sliders) tuples.
    """
    output_sliders = [
        ("pan_l", "Pan L", PAN_MIN, PAN_MAX, PAN_STEP),
        ("pan_r", "Pan R", PAN_MIN, PAN_MAX, PAN_STEP),
        ("volume", "Vol", _MIXER_DB_MIN, _MIXER_DB_MAX, 1.0),
    ]
    loopback_sliders = list(output_sliders)

    inputs = []
    for i in range(spec.num_inputs):
        inputs.append(
            (
                f"input{i + 1}",
                f"IN {i + 1}",
                C_BLUE,
                [
                    ("pan", "Pan", PAN_MIN, PAN_MAX, PAN_STEP),
                    ("volume", "Vol", _MIXER_DB_MIN, _MIXER_DB_MAX, 1.0),
                ],
            )
        )

    if spec.num_output_pairs == 1:
        # EVO 4: two rows - inputs on top, outputs on bottom (same layout as EVO 8)
        outputs_row = [
            ("main", "OUT 1|2", C_GREEN, list(output_sliders)),
            ("loopback", "OUT 3|4 (LOOP)", C_YELLOW, loopback_sliders),
        ]
        return [inputs, outputs_row]
    else:
        # EVO 8: two rows
        outputs_row = []
        for i in range(spec.num_output_pairs):
            outputs_row.append(
                (
                    f"output_pair{i + 1}",
                    f"OUT {i * 2 + 1}|{i * 2 + 2}",
                    C_GREEN,
                    list(output_sliders),
                )
            )
        outputs_row.append(("loopback", "OUT 5|6 (LOOP)", C_YELLOW, loopback_sliders))
        return [inputs, outputs_row]


def _build_mixer_state_single(spec: DeviceSpec):
    """Build initial mixer state for a single bus."""
    state = {}
    for i in range(spec.num_inputs):
        state[f"input{i + 1}"] = {"volume": -128.0, "pan": 0.0}
    if spec.num_output_pairs == 1:
        state["main"] = {"volume": -128.0, "pan_l": -100.0, "pan_r": 100.0}
    else:
        for i in range(spec.num_output_pairs):
            state[f"output_pair{i + 1}"] = {"volume": -128.0, "pan_l": -100.0, "pan_r": 100.0}
    state["loopback"] = {"volume": -128.0, "pan_l": -100.0, "pan_r": 100.0}
    return state


def _build_mixer_state(spec: DeviceSpec):
    """Build initial mixer state. Per-bus for multi-output devices."""
    return [_build_mixer_state_single(spec) for _ in range(spec.num_output_pairs)]


class EvoTUI:
    def __init__(self, evo: EVOController):
        self.evo = evo
        self.spec = evo.spec
        self.cursor = 0
        self.status = ""
        self.status_err = False
        self.status_ticks = 0
        self.num_buf = ""
        self._mode = "normal"
        self._window = "controls"
        self._file_list = []
        self._file_cursor = 0
        self._file_scroll = 0
        self._file_input = ""
        self._slider_map = []
        self._box_attr = 0
        self._text_cursor_pos = None  # (row, col) for terminal cursor, or None

        # Build dynamic layout from spec
        self._element_groups = _build_element_groups(self.spec)
        self._ranges = _build_ranges(self.spec)
        self._mixer_rows = _build_mixer_sections(self.spec)
        self._has_subsections = len(self._element_groups) > 1

        # Controls subsection state (EVO 8)
        self._controls_subsection = 0

        # Mixer state
        self._mixer_bus = 0
        self._all_mixer_sections = [sec for row in self._mixer_rows for sec in row]
        self._mixer_section = 0
        self._mixer_param = len(self._all_mixer_sections[0][3]) - 1
        self._mixer_state = _build_mixer_state(self.spec)

        self._max_pan = max(
            sum(1 for s in sec[3] if s[0].startswith("pan")) for sec in self._all_mixer_sections
        )
        self._mixer_section_h = self._max_pan * 2 + 5

        # Per-device mixer section width
        # EVO 4: 2 sections must equal 3 EVO 8 sections (incl. gaps)
        # 3*(17+3)-1=59 => 2*(iw+3)-1=59 => iw=27; pan_half=(27-17)/2+7=12
        if self.spec.num_output_pairs == 1:
            self._mixer_section_iw = MIN_MIXER_SECTION_IW + 10
            self._mixer_pan_half = MIN_MIXER_PAN_HALF + 5
        else:
            self._mixer_section_iw = MIN_MIXER_SECTION_IW
            self._mixer_pan_half = MIN_MIXER_PAN_HALF

        # Compute controls body height
        if self._has_subsections:
            left_n = len(self._element_groups[0][1])
            right_n = len(self._element_groups[1][1])
            self._controls_body_h = max(left_n * 4 + (left_n - 1), right_n * 4 + (right_n - 1)) + 1
        else:
            active_elements = self._active_elements()
            self._controls_body_h = len(active_elements) * 4 + (len(active_elements) - 1)
        self._total_h = 3 + self._controls_body_h + 5

        self._config_dir = cfg._device_dir(self.spec.name)
        self._load_mixer_state()
        self._sync()

    # -- state --

    def _active_elements(self):
        """Return elements list for the active controls subsection."""
        if self._has_subsections:
            return self._element_groups[self._controls_subsection][1]
        return self._element_groups[0][1]

    def _flat_mixer_sections(self):
        """Return cached flat list of all mixer sections across rows."""
        return self._all_mixer_sections

    def _mixer_row_col(self):
        """Return (row_idx, col_idx) of the current mixer section."""
        idx = self._mixer_section
        for r, row in enumerate(self._mixer_rows):
            if idx < len(row):
                return r, idx
            idx -= len(row)
        return 0, 0

    def _mixer_section_at(self, row_idx, col_idx):
        """Return flat section index for given row/col (col clamped to row length)."""
        offset = sum(len(self._mixer_rows[r]) for r in range(row_idx))
        col_idx = max(0, min(len(self._mixer_rows[row_idx]) - 1, col_idx))
        return offset + col_idx

    def _cur_mixer_state(self):
        """Return mixer state dict for the active bus."""
        return self._mixer_state[self._mixer_bus]

    def _sync(self):
        try:
            self.state = self.evo.decode_status(self.evo.get_status_raw())
        except OSError as e:
            self._set_status(f"USB error: {e}", err=True)

    def _set_status(self, msg, err=False):
        self.status, self.status_err, self.status_ticks = msg, err, 150

    def _val(self, idx=None):
        if idx is None:
            idx = self.cursor
        elems = self._active_elements()
        key, sub = elems[idx][:2]
        return self.state[key] if sub is None else self.state[key][sub]

    def _frac(self, idx):
        elems = self._active_elements()
        key = elems[idx][0]
        lo, hi, _ = self._ranges[key]
        return max(0.0, min(1.0, (self._val(idx) - lo) / (hi - lo)))

    def _muted(self, idx):
        elems = self._active_elements()
        key = elems[idx][0]
        return self.state[key].get("mute", False) if key != "monitor" else False

    def _has_mute(self, idx):
        return self._active_elements()[idx][0] != "monitor"

    def _has_phantom(self, idx):
        return self._active_elements()[idx][0].startswith("input")

    def _build_controls_help(self):
        """Return (nav_hints, set_hints) as lists of (key, desc[, color]) tuples."""
        if self._has_subsections:
            nav_hints = [("hjkl", f" {ARROWS}"), (TAB_SYM, " tab")]
        else:
            nav_hints = [("jk", f" {ARROW_D}{ARROW_U}"), (TAB_SYM, " tab")]
        set_hints = [("[]", f" {PM}1"), ("{}", f" {PM}5"), ("0-9", " dial")]
        if self._has_mute(self.cursor):
            set_hints.append(("m", " mute"))
        if self._has_phantom(self.cursor):
            set_hints.append(("P", " 48V"))
        return nav_hints, set_hints

    def _build_mixer_help(self):
        """Return (nav_hints, set_hints) as lists of (key, desc[, color]) tuples."""
        sections = self._flat_mixer_sections()
        param = sections[self._mixer_section][3][self._mixer_param][0]
        step = "1" if param == "volume" else "5"
        big = "5" if param == "volume" else "25"
        nav_hints = [
            ("hjkl", f" {ARROWS}"),
            ("Space", " next"),
            (TAB_SYM, " tab"),
        ]
        set_hints = [("[]", f" {PM}{step}"), ("{}", f" {PM}{big}"), ("0-9", " dial")]
        if self.spec.num_output_pairs > 1:
            set_hints.append(("m", " mix", C_CYAN))
        return nav_hints, set_hints

    def _draw_help_footer(self, scr, row, cx, nav_hints, set_hints):
        """Draw help footer (two lines) with keys highlighted. Returns next row."""
        dim = curses.color_pair(C_WHITE) | curses.A_DIM
        key_attr = curses.color_pair(C_WHITE) | curses.A_BOLD

        def draw_hints(r, hints):
            col = cx + 1
            for i, hint in enumerate(hints):
                key, desc = hint[0], hint[1]
                color = hint[2] if len(hint) > 2 else C_WHITE
                if i:
                    self._safe(scr, r, col, HSEP, dim)
                    col += len(HSEP)
                key_style = curses.color_pair(color) | curses.A_BOLD
                self._safe(scr, r, col, key, key_style)
                col += len(key)
                self._safe(scr, r, col, desc, dim)
                col += len(desc)

        draw_hints(row, nav_hints)
        draw_hints(row + 1, set_hints)
        return row + 2

    def _is_db(self, idx=None):
        return self._active_elements()[self.cursor if idx is None else idx][0] != "monitor"

    def _current_unit(self):
        if self._window == "controls":
            return "dB" if self._is_db() else "%"
        sections = self._flat_mixer_sections()
        param = sections[self._mixer_section][3][self._mixer_param][0]
        return "dB" if param == "volume" else ""

    # -- controls actions --

    def _set_val(self, val):
        elems = self._active_elements()
        key, sub = elems[self.cursor][:2]
        lo, hi, _ = self._ranges[key]
        val = max(lo, min(hi, val))
        try:
            if key == "monitor":
                self.evo.set_monitor(round(val))
            elif key == "output":
                self.evo.set_volume(val)
            elif key.startswith("output"):
                # EVO 8: output1, output2
                pair = int(key[-1]) - 1
                self.evo.set_volume(val, output_pair=pair)
            else:
                self.evo.set_gain(key, val)
            if sub is None:
                self.state[key] = val
            else:
                self.state[key][sub] = val
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    def _adjust(self, delta):
        elems = self._active_elements()
        _, _, step = self._ranges[elems[self.cursor][0]]
        self._set_val(self._val() + delta * step)

    def _toggle_mute(self):
        elems = self._active_elements()
        key = elems[self.cursor][0]
        if key == "monitor":
            return
        try:
            new = not self.state[key]["mute"]
            self.evo.set_mute(key, new)
            self.state[key]["mute"] = new
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    def _toggle_phantom(self):
        elems = self._active_elements()
        key = elems[self.cursor][0]
        if not key.startswith("input"):
            return
        try:
            new = not self.state[key]["phantom"]
            self.evo.set_phantom(key, new)
            self.state[key]["phantom"] = new
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    # -- mixer state persistence --

    def _load_mixer_state(self):
        """Load mixer state from disk into TUI state."""
        data = cfg.load_mixer_state(self.spec.name)
        if data is None:
            return
        for b, bus_data in enumerate(data["buses"][: self.spec.num_output_pairs]):
            bus = self._mixer_state[b]
            for i in range(self.spec.num_inputs):
                key = f"input{i + 1}"
                if key in bus_data["inputs"]:
                    bus[key].update(bus_data["inputs"][key])

            outputs = bus_data["outputs"]
            if self.spec.num_output_pairs == 1:
                if "output_pair1" in outputs:
                    bus["main"].update(outputs["output_pair1"])
            else:
                for pair in range(self.spec.num_output_pairs):
                    key = f"output_pair{pair + 1}"
                    if key in outputs:
                        bus[key].update(outputs[key])

            bus["loopback"].update(bus_data["loopback"])

    def _save_mixer_state(self):
        """Persist TUI mixer state to disk."""
        data = cfg.default_mixer_state(self.spec)
        for b in range(self.spec.num_output_pairs):
            bus = self._mixer_state[b]
            state_bus = data["buses"][b]
            for i in range(self.spec.num_inputs):
                key = f"input{i + 1}"
                state_bus["inputs"][key] = dict(bus[key])

            if self.spec.num_output_pairs == 1:
                state_bus["outputs"]["output_pair1"].update(bus["main"])
            else:
                for pair in range(self.spec.num_output_pairs):
                    key = f"output_pair{pair + 1}"
                    state_bus["outputs"][key].update(bus[key])

            state_bus["loopback"].update(bus["loopback"])
        cfg.save_mixer_state(self.spec.name, data)

    # -- mixer actions --

    def _mixer_val(self):
        sections = self._flat_mixer_sections()
        key = sections[self._mixer_section][0]
        param = sections[self._mixer_section][3][self._mixer_param][0]
        return self._cur_mixer_state()[key][param]

    def _mixer_set_val(self, val):
        sections = self._flat_mixer_sections()
        key, _, _, sliders = sections[self._mixer_section]
        param, _, lo, hi, _ = sliders[self._mixer_param]
        self._cur_mixer_state()[key][param] = max(lo, min(hi, val))
        self._apply_mixer(key)

    def _mixer_adjust(self, delta):
        sections = self._flat_mixer_sections()
        _, _, _, _, step = sections[self._mixer_section][3][self._mixer_param]
        self._mixer_set_val(self._mixer_val() + delta * step)

    def _apply_mixer(self, key):
        try:
            s = self._cur_mixer_state()[key]
            bus = self._mixer_bus
            if key.startswith("input"):
                input_num = int(key[5:])
                self.evo.set_mixer_input(input_num, s["volume"], s["pan"], mix_bus=bus)
            elif key == "main":
                self.evo.set_mixer_output(s["volume"], s["pan_l"], s["pan_r"], mix_bus=bus)
            elif key.startswith("output_pair"):
                pair = int(key[-1]) - 1
                self.evo.set_mixer_output(
                    s["volume"], s["pan_l"], s["pan_r"], output_pair=pair, mix_bus=bus
                )
            elif key == "loopback":
                self.evo.set_mixer_loopback(s["volume"], s["pan_l"], s["pan_r"], mix_bus=bus)
            self._save_mixer_state()
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    # -- file picker --

    def _scan_files(self):
        d = self._config_dir
        return (
            sorted(f for f in d.glob("*.json") if not f.name.startswith(".")) if d.exists() else []
        )

    def _enter_save_mode(self):
        self._file_list = self._scan_files()
        self._file_cursor = self._file_scroll = 0
        self._file_input = "config"
        self._mode = "save"

    def _enter_load_mode(self):
        files = self._scan_files()
        if not files:
            self._set_status(f"No configs in {self._config_dir}", err=True)
            return
        self._file_list = files
        self._file_cursor = self._file_scroll = 0
        self._mode = "load"

    def _picker_move(self, delta, wrap=False):
        n = len(self._file_list)
        if not n:
            return
        if wrap:
            self._file_cursor = (self._file_cursor + delta) % n
        else:
            self._file_cursor = max(0, min(n - 1, self._file_cursor + delta))
        if self._file_cursor < self._file_scroll:
            self._file_scroll = self._file_cursor
        elif self._file_cursor >= self._file_scroll + PICKER_LIST_H:
            self._file_scroll = self._file_cursor - PICKER_LIST_H + 1

    def _picker_key(self, key):
        if key == 27:
            self._mode = "normal"
            return
        if self._mode == "load":
            if key == curses.KEY_UP:
                self._picker_move(-1)
            elif key == curses.KEY_DOWN:
                self._picker_move(1)
            elif key == curses.KEY_BTAB:
                self._picker_move(-1, wrap=True)
            elif key == 9:
                self._picker_move(1, wrap=True)
            elif key == 10 and self._file_list:
                path = self._file_list[self._file_cursor]
                try:
                    cfg.load_and_apply(self.evo, path)
                    self._sync()
                    self._load_mixer_state()
                    self._set_status(f"Loaded {ARROW_L} {path.name}")
                except Exception as e:
                    self._set_status(f"Load error: {e}", err=True)
                self._mode = "normal"
        else:  # save
            if key == curses.KEY_UP:
                self._picker_move(-1)
                if self._file_list:
                    self._file_input = self._file_list[self._file_cursor].stem
            elif key == curses.KEY_DOWN:
                self._picker_move(1)
                if self._file_list:
                    self._file_input = self._file_list[self._file_cursor].stem
            elif key == curses.KEY_BTAB:
                self._picker_move(-1, wrap=True)
                if self._file_list:
                    self._file_input = self._file_list[self._file_cursor].stem
            elif key == 9:
                self._picker_move(1, wrap=True)
                if self._file_list:
                    self._file_input = self._file_list[self._file_cursor].stem
            elif key in (curses.KEY_BACKSPACE, 127):
                self._file_input = self._file_input[:-1]
            elif 32 <= key <= 126:
                max_len = BOX_IW - len("File: ") - len(".json") - 1
                if len(self._file_input) < max_len:
                    self._file_input += chr(key)
            elif key == 10:
                name = self._file_input.strip()
                if name:
                    try:
                        cfg.save(self.evo, self._config_dir / (name + ".json"))
                        self._set_status(f"Saved {ARROW_R} {name}.json")
                    except Exception as e:
                        self._set_status(f"Save error: {e}", err=True)
                self._mode = "normal"

    # -- drawing primitives --

    def _safe(self, scr, row, col, text, *args):
        try:
            h, w = scr.getmaxyx()
            if row < 0 or row >= h or col >= w - 1:
                return
            scr.addnstr(row, col, text, w - col - 1, *args)
        except curses.error:
            pass

    def _box_top(self, scr, row, cx, label, active=False, iw=BOX_IW, attr=None):
        self._box_attr = (
            attr
            if attr is not None
            else (curses.A_BOLD if active else curses.color_pair(C_WHITE) | curses.A_DIM)
        )
        self._box_active = active
        h, d = (BOX_TL_A, BOX_H_A) if active else (BOX_TL, BOX_H)
        e = BOX_TR_A if active else BOX_TR
        dashes = iw - len(label) - 2
        self._safe(scr, row, cx, h + " ", self._box_attr)
        self._safe(scr, row, cx + 2, label, self._box_attr)
        self._safe(scr, row, cx + 2 + len(label), " " + d * dashes + e, self._box_attr)

    def _box_top_centered(self, scr, row, cx, label, active=False, iw=None):
        if iw is None:
            iw = self._mixer_section_iw
        self._box_attr = curses.A_BOLD if active else curses.color_pair(C_WHITE) | curses.A_DIM
        self._box_active = active
        h, d = (BOX_TL_A, BOX_H_A) if active else (BOX_TL, BOX_H)
        e = BOX_TR_A if active else BOX_TR
        label = label[: iw - 2]
        inner = iw - len(label) - 2
        left_d = inner // 2
        self._safe(
            scr,
            row,
            cx,
            h + d * left_d + " " + label + " " + d * (inner - left_d) + e,
            self._box_attr,
        )

    def _box_side(self, scr, row, cx, iw=BOX_IW):
        v = BOX_V_A if self._box_active else BOX_V
        self._safe(scr, row, cx, v, self._box_attr)
        self._safe(scr, row, cx + iw + 1, v, self._box_attr)

    def _box_bot(self, scr, row, cx, iw=BOX_IW):
        bl = BOX_BL_A if self._box_active else BOX_BL
        d = BOX_H_A if self._box_active else BOX_H
        br = BOX_BR_A if self._box_active else BOX_BR
        self._safe(scr, row, cx, bl + d * iw + br, self._box_attr)

    def _box_bot_labeled(self, scr, row, cx, label, iw=BOX_IW):
        bl = BOX_BL_A if self._box_active else BOX_BL
        d = BOX_H_A if self._box_active else BOX_H
        br = BOX_BR_A if self._box_active else BOX_BR
        dashes = iw - len(label) - 3
        self._safe(scr, row, cx, bl + d * dashes + " " + label + " " + d + br, self._box_attr)

    def _hslider(self, scr, row, x, frac, muted=False, sel=False, color=C_GREEN, w=SLIDER_W):
        slots = w * 2
        filled_slots = max(0, min(slots, round(slots * frac)))
        full_chars = filled_slots // 2
        partial = filled_slots % 2
        fill_attr = curses.color_pair(C_RED if muted else color) | (
            curses.A_NORMAL if sel else curses.A_DIM
        )
        empty_attr = curses.color_pair(C_WHITE) | (curses.A_NORMAL if sel else curses.A_DIM)
        pos = x
        if full_chars:
            self._safe(scr, row, pos, SL_FULL * full_chars, fill_attr)
            pos += full_chars
        if partial:
            self._safe(scr, row, pos, BOX_H_A, fill_attr)
            pos += 1
        empty = w - full_chars - partial
        if empty:
            self._safe(scr, row, pos, BOX_H * empty, empty_attr)

    def _pan_slider(self, scr, row, x, frac, sel=False, color=C_GREEN, w=SLIDER_W):
        """Center-origin slider: fills outward from midpoint with half-block precision."""
        half = w // 2
        fill_attr = curses.color_pair(color) | (curses.A_NORMAL if sel else curses.A_DIM)
        empty_attr = curses.color_pair(C_WHITE) | (curses.A_NORMAL if sel else curses.A_DIM)
        self._safe(scr, row, x, BOX_H * w, empty_attr)

        left_slots = max(0, min(half * 2, round((1.0 - frac) * half * 2)))
        right_slots = half * 2 - left_slots
        left_full, left_partial = divmod(left_slots, 2)
        right_full, right_partial = divmod(right_slots, 2)

        if left_full:
            self._safe(scr, row, x + half - left_full, SL_FULL * left_full, fill_attr)
        if left_partial:
            self._safe(scr, row, x + half - left_full - 1, BOX_H_A, fill_attr)
        if right_full:
            self._safe(scr, row, x + half + 1, SL_FULL * right_full, fill_attr)
        if right_partial:
            self._safe(scr, row, x + half + 1 + right_full, BOX_H_A, fill_attr)
        self._safe(scr, row, x + half, BOX_V, curses.A_BOLD)

    def _mute_ind(self, scr, row, x, key):
        if self.state[key]["mute"]:
            self._safe(scr, row, x, "[M]", curses.A_BOLD | curses.color_pair(C_RED))
        else:
            self._safe(scr, row, x, "[m]", curses.A_DIM)

    def _phantom_ind(self, scr, row, x, key):
        if self.state[key]["phantom"]:
            self._safe(scr, row, x, "[48V]", curses.A_BOLD | curses.color_pair(C_YELLOW))
        else:
            self._safe(scr, row, x, "[48v]", curses.A_DIM)

    # -- tab bar --

    def _draw_tab_bar(self, scr, row, cx, section_w):
        ctrl_label = " CONTROLS "
        mix_label = " MIXER "
        dim = curses.color_pair(C_WHITE) | curses.A_DIM

        # Tabs left-aligned
        if self._window == "controls":
            ctrl_attr = curses.A_REVERSE | curses.A_BOLD
            mix_attr = dim
        else:
            ctrl_attr = dim
            mix_attr = curses.A_REVERSE | curses.A_BOLD
        self._safe(scr, row, cx + 1, ctrl_label, ctrl_attr)
        mix_x = cx + 1 + len(ctrl_label) + 1
        self._safe(scr, row, mix_x, mix_label, mix_attr)

        # Device name right-aligned and dimmed
        dev_name = self.spec.display_name
        name_x = cx + section_w - len(dev_name)
        self._safe(scr, row, name_x, dev_name, dim)

        # Underline rule across section width
        self._safe(scr, row + 1, cx, BOX_H * section_w, dim)

        # Erase under active tab (gives it a "connected" look)
        if self._window == "controls":
            active_x = cx + 1
            active_label_w = len(ctrl_label)
        else:
            active_x = mix_x
            active_label_w = len(mix_label)
        self._safe(scr, row + 1, active_x, " " * active_label_w, dim)

    # -- section drawing (controls) --

    def _draw_section(self, scr, row, cx, idx, sw=SLIDER_W, bw=BOX_IW, force_inactive=False):
        key, sub, label, color = self._active_elements()[idx]
        active = (self.cursor == idx) and not force_inactive
        val = self._val(idx)
        frac = self._frac(idx)
        muted = self._muted(idx)

        self._box_top(scr, row, cx, label, active, iw=bw)
        row += 1

        self._box_side(scr, row, cx, iw=bw)
        if sub is None:
            self._pan_slider(scr, row, cx + SLIDER_OFF, frac, active, color, w=sw)
        else:
            self._hslider(scr, row, cx + SLIDER_OFF, frac, muted, active, color, w=sw)
        self._slider_map.append((row, cx + SLIDER_OFF, sw, idx))
        row += 1

        self._box_side(scr, row, cx, iw=bw)
        lbl_attr = curses.A_BOLD if active else curses.A_DIM
        dial_active = bool(active and self.num_buf)
        if sub is None:
            self._safe(scr, row, cx + SLIDER_OFF, "IN", lbl_attr)
            pct = f"Mix: {val:3.0f}%"
            mid = cx + SLIDER_OFF + (sw - len(pct)) // 2
            pct_attr = curses.color_pair(C_YELLOW) | curses.A_BOLD if dial_active else lbl_attr
            self._safe(scr, row, mid, pct, pct_attr)
            self._safe(scr, row, cx + SLIDER_OFF + sw - 3, "OUT", lbl_attr)
        else:
            vlabel = "Vol:" if key.startswith("output") else "Gain:"
            val_str = f"{vlabel:5s} {val:+6.1f} dB"
            if dial_active:
                val_attr = curses.color_pair(C_YELLOW) | curses.A_BOLD
            elif muted:
                val_attr = curses.color_pair(C_RED)
            else:
                val_attr = lbl_attr
            self._safe(scr, row, cx + SLIDER_OFF, val_str, val_attr)
            if self._has_phantom(idx):
                self._phantom_ind(scr, row, cx + bw - 9, key)
            if self._has_mute(idx):
                self._mute_ind(scr, row, cx + bw - 3, key)
        row += 1

        self._box_bot(scr, row, cx, iw=bw)
        return row + 1

    # -- mixer section drawing --

    def _draw_mixer_section(self, scr, top_row, cx, sec_idx, compact=False):
        sections = self._flat_mixer_sections()
        key, label, color, sliders = sections[sec_idx]
        sel_sec = self._mixer_section == sec_idx
        pan_params = [(i, s) for i, s in enumerate(sliders) if s[0].startswith("pan")]
        vol_param_idx = next(i for i, s in enumerate(sliders) if s[0] == "volume")
        mstate = self._cur_mixer_state()

        vol_val = mstate[key]["volume"]
        connected = vol_val > _MIXER_DB_MIN
        if connected:
            box_attr = curses.color_pair(C_CYAN) | (curses.A_BOLD if sel_sec else curses.A_NORMAL)
        else:
            box_attr = None
        siw = self._mixer_section_iw
        self._box_top(scr, top_row, cx, label, sel_sec, iw=siw, attr=box_attr)
        row = top_row + 1

        for slot in range(len(pan_params) if compact else self._max_pan):
            self._box_side(scr, row, cx, siw)
            if slot < len(pan_params):
                pidx, (param, _, lo, hi, _) = pan_params[slot]
                val = mstate[key][param]
                sel = sel_sec and self._mixer_param == pidx
                self._pan_slider(
                    scr,
                    row,
                    cx + 2,
                    (val - lo) / (hi - lo),
                    sel,
                    color,
                    w=2 * self._mixer_pan_half + 1,
                )
            row += 1

            self._box_side(scr, row, cx, siw)
            if slot < len(pan_params):
                pidx, (param, plabel, lo, hi, _) = pan_params[slot]
                val = mstate[key][param]
                sel = sel_sec and self._mixer_param == pidx
                pan_val_attr = (
                    curses.color_pair(C_YELLOW) | curses.A_BOLD
                    if sel and self.num_buf
                    else curses.A_BOLD
                    if sel
                    else curses.A_DIM
                )
                self._safe(
                    scr,
                    row,
                    cx + 2,
                    f"{plabel + ':':<{siw - 8}} {val:+5.0f}",
                    pan_val_attr,
                )
            row += 1

        self._box_side(scr, row, cx, siw)
        row += 1

        vol_frac = max(0.0, min(1.0, (vol_val - _MIXER_DB_MIN) / (_MIXER_DB_MAX - _MIXER_DB_MIN)))
        vol_sel = sel_sec and self._mixer_param == vol_param_idx
        self._box_side(scr, row, cx, siw)
        self._hslider(scr, row, cx + 2, vol_frac, sel=vol_sel, color=color, w=siw - 2)
        row += 1

        self._box_side(scr, row, cx, siw)
        vol_val_attr = (
            curses.color_pair(C_YELLOW) | curses.A_BOLD
            if vol_sel and self.num_buf
            else curses.A_BOLD
            if vol_sel
            else curses.A_DIM
        )
        self._safe(
            scr,
            row,
            cx + 2,
            f"{'Vol:':<{siw - 12}} {vol_val:+6.1f} dB",
            vol_val_attr,
        )
        row += 1

        self._box_bot(scr, row, cx, siw)

    # -- file picker dialog --

    def _draw_file_picker(self, scr):
        scr.erase()
        h, w = scr.getmaxyx()
        cx = (w - (BOX_IW + 2)) // 2
        action = "SAVE" if self._mode == "save" else "LOAD"
        total_h = PICKER_LIST_H + 3 + (1 if self._mode == "save" else 0)
        row = max(0, (h - total_h) // 2)

        dim = curses.color_pair(C_WHITE) | curses.A_DIM
        self._box_attr = dim
        self._box_active = False

        # Top border with action + path (dim)
        path_str = str(self._config_dir) + "/"
        max_path = BOX_IW - len(action) - 5  # fixed overhead: "─ " + " " + " ─...─┐"
        if len(path_str) > max_path:
            path_str = "\u2026" + path_str[-(max_path - 1) :]
        title = f"{action} {path_str}"
        title_dashes = BOX_IW - len(title) - 3
        self._safe(scr, row, cx, BOX_TL + BOX_H + " ", dim)
        self._safe(scr, row, cx + 3, title, dim)
        self._safe(scr, row, cx + 3 + len(title), " " + BOX_H * title_dashes + BOX_TR, dim)
        row += 1

        # Empty line between top border and file list
        self._box_side(scr, row, cx)
        row += 1

        # File list
        for i in range(PICKER_LIST_H):
            self._box_side(scr, row, cx)
            abs_i = self._file_scroll + i
            if not self._file_list and i == 0:
                self._safe(scr, row, cx + SLIDER_OFF, "(no configs found)", dim)
            elif abs_i < len(self._file_list):
                f = self._file_list[abs_i]
                sel = abs_i == self._file_cursor
                pre = ARROW_R + " " if sel else "  "
                attr = curses.A_BOLD if sel else curses.A_DIM
                self._safe(scr, row, cx + SLIDER_OFF, f"{pre}{f.name}"[: BOX_IW - 2], attr)
            row += 1

        # File input (save mode only)
        if self._mode == "save":
            self._box_side(scr, row, cx)
            file_x = cx + SLIDER_OFF
            self._safe(scr, row, file_x, "File: ", dim)
            file_x += 6
            self._safe(scr, row, file_x, self._file_input, curses.A_BOLD)
            file_x += len(self._file_input)
            self._text_cursor_pos = (row, file_x)
            self._safe(scr, row, file_x, ".json", dim)
            row += 1

        # Bottom border with hints (right-aligned, same style as status bar)
        action = "save" if self._mode == "save" else "load"
        hints = [("Tab", f" {ARROW_D}{ARROW_U}"), ("\u21b5", f" {action}"), ("Esc", " cancel")]
        hints_content_w = sum(len(h[0]) + len(h[1]) for h in hints) + len(HSEP) * (len(hints) - 1)
        hints_w = 1 + hints_content_w + 2  # leading space + content + trailing " ─"
        bot_dashes = BOX_IW - hints_w
        self._safe(scr, row, cx, BOX_BL + BOX_H * bot_dashes, dim)
        col = cx + 1 + bot_dashes + 1  # BL + dashes + leading space
        for i, hint in enumerate(hints):
            key, desc = hint[0], hint[1]
            color = hint[2] if len(hint) > 2 else C_WHITE
            if i:
                self._safe(scr, row, col, HSEP, dim)
                col += len(HSEP)
            self._safe(scr, row, col, key, curses.color_pair(color) | curses.A_BOLD)
            col += len(key)
            self._safe(scr, row, col, desc, dim)
            col += len(desc)
        self._safe(scr, row, col, " " + BOX_H, dim)
        self._safe(scr, row, cx + BOX_IW + 1, BOX_BR, dim)

    # -- main draw --

    def _draw(self, scr):
        self._text_cursor_pos = None
        if self._mode in ("save", "load"):
            self._draw_file_picker(scr)
            return

        scr.erase()
        h, w = scr.getmaxyx()
        self._slider_map = []

        # Compute layout width - controls always matches mixer so both tabs are equal width
        max_row_len = max(len(row) for row in self._mixer_rows)
        mixer_w = max_row_len * (self._mixer_section_iw + 3) - 1
        cx = max(0, (w - mixer_w) // 2)

        self._total_h = 3 + self._controls_body_h + 5
        if h < self._total_h or w < mixer_w:
            self._safe(scr, 0, 0, f"Terminal too small ({w}x{h}, need {mixer_w}x{self._total_h})")
            return

        row = max(0, (h - self._total_h) // 2)
        self._draw_tab_bar(scr, row, cx, mixer_w)
        row += 3

        if self._window == "controls":
            row = self._draw_controls_body(scr, row, cx, mixer_w)
            help_args = self._build_controls_help()
        else:
            row = self._draw_mixer_body(scr, row, cx)
            help_args = self._build_mixer_help()

        row = self._draw_status_bar(scr, row, cx, mixer_w)
        self._draw_help_footer(scr, row + 1, cx, *help_args)

    def _draw_controls_body(self, scr, row, cx, mixer_w):
        if self._has_subsections:
            return self._draw_controls_twocol(scr, row, cx, mixer_w)

        bw = mixer_w - 2
        sw = bw - SLIDER_OFF
        active_elems = self._active_elements()
        for idx in range(len(active_elems)):
            row = self._draw_section(scr, row, cx, idx, sw=sw, bw=bw)
            if idx < len(active_elems) - 1:
                row += 1

        return row + 1

    def _draw_controls_twocol(self, scr, row, cx, mixer_w):
        """Draw two-column controls layout for EVO 8 (inputs left, outputs right)."""
        col_w = (mixer_w - COL_GAP) // 2
        col_bw = col_w - 2
        col_sw = col_bw - SLIDER_OFF
        right_cx = cx + col_w + COL_GAP

        left_elems = self._element_groups[0][1]
        right_elems = self._element_groups[1][1]

        # Draw left column (inputs)
        saved_sub = self._controls_subsection
        self._controls_subsection = 0
        left_row = row
        for idx in range(len(left_elems)):
            left_row = self._draw_section(
                scr,
                left_row,
                cx,
                idx,
                sw=col_sw,
                bw=col_bw,
                force_inactive=(saved_sub != 0),
            )
            if idx < len(left_elems) - 1:
                left_row += 1

        # Draw right column (outputs)
        self._controls_subsection = 1
        right_row = row
        for idx in range(len(right_elems)):
            right_row = self._draw_section(
                scr,
                right_row,
                right_cx,
                idx,
                sw=col_sw,
                bw=col_bw,
                force_inactive=(saved_sub != 1),
            )
            if idx < len(right_elems) - 1:
                right_row += 1

        self._controls_subsection = saved_sub
        row = max(left_row, right_row)

        return row + 1

    def _draw_bus_route(self, scr, row, cx, width):
        """Draw 3-line bus between input and output rows.
        EVO 4: static single bus ending with '▶ LOOP IN 1|2' label.
        EVO 8: interactive bus selector with two output pair labels.
        """
        sec_ow = self._mixer_section_iw + 3
        dim = curses.color_pair(C_WHITE) | curses.A_DIM
        bus_attr = curses.color_pair(C_CYAN) | curses.A_BOLD
        mstate = self._cur_mixer_state()

        wall_positions = set()
        for i, (key, _, _, _) in enumerate(self._mixer_rows[0]):
            if mstate.get(key, {}).get("volume", _MIXER_DB_MIN) > _MIXER_DB_MIN:
                wall_positions.add(i * sec_ow)

        output_wall_positions = set()
        for i, (key, _, _, _) in enumerate(self._mixer_rows[1]):
            if mstate.get(key, {}).get("volume", _MIXER_DB_MIN) > _MIXER_DB_MIN:
                output_wall_positions.add(i * sec_ow + self._mixer_section_iw + 1)

        # Compute label width to right-align bus switcher within the app
        evo4_label = " IN 3|4 (LOOP) "
        bus_labels_all = [
            label for key, label, _, _ in self._mixer_rows[1] if key.startswith("output_pair")
        ]
        if self.spec.num_output_pairs == 1:
            label_w = len(evo4_label) + 1  # +1 reserves one connector char at right end
        else:
            label_w = 3 + max(len(l) for l in bus_labels_all[:2]) if bus_labels_all else 0

        jx = cx + width - label_w  # right junction: labels end at cx + width - 1

        def _bus_chars(n=None):
            if n is None:
                n = jx - cx
            chars = []
            for p in range(n):
                up = p in wall_positions
                down = p in output_wall_positions
                if p == 0 and not up:
                    chars.append(" ")
                elif p == 0:
                    chars.append(BUS_J_START)
                elif up and down:
                    chars.append(BUS_J_CROSS)
                elif up:
                    chars.append(BUS_J_T_UP)
                elif down:
                    chars.append(BUS_J_T_DOWN)
                else:
                    chars.append(BUS_H)
            return "".join(chars)

        if self.spec.num_output_pairs == 1:
            # EVO 4: single static bus - row 1 has the line, rows 0 and 2 blank
            self._safe(scr, row + 1, cx, _bus_chars(width), bus_attr)
            self._safe(scr, row + 1, jx, evo4_label, bus_attr)
            return

        # EVO 8: interactive bus selector
        bus = self._mixer_bus
        bus_labels = bus_labels_all
        attr0 = (curses.A_BOLD | curses.color_pair(C_CYAN)) if bus == 0 else dim
        attr1 = (curses.A_BOLD | curses.color_pair(C_CYAN)) if bus == 1 else dim

        # Row 1: bus line + junction + OUT 1|2 label (same line as bus)
        # ╦ when OUT 1|2 active: line continues right AND branches down to OUT 3|4
        # ╗ when OUT 3|4 active: line terminates, drops straight down
        self._safe(scr, row + 1, cx, _bus_chars(), bus_attr)
        if bus_labels:
            pre0 = ARROW_R if bus == 0 else ARROW_R_EMPTY
            junc = BUS_H if bus == 0 else BUS_TR
            self._safe(scr, row + 1, jx, junc + pre0 + " " + bus_labels[0], attr0)

        # Row 2: ╚▶/╚▷ OUT 3|4 label
        if len(bus_labels) > 1:
            pre1 = ARROW_R if bus == 1 else ARROW_R_EMPTY
            self._safe(scr, row + 2, jx, BUS_BL + pre1 + " " + bus_labels[1], attr1)

    def _draw_mixer_body(self, scr, row, cx):
        sec_ow = self._mixer_section_iw + 3
        sections = self._flat_mixer_sections()

        if len(self._mixer_rows) == 1:
            # single row (unused currently)
            for sec_idx in range(len(sections)):
                self._draw_mixer_section(scr, row, cx + sec_idx * sec_ow, sec_idx, compact=True)
            row += self._mixer_section_h
        else:
            # Multi-row: row 0 = inputs (compact), row 1 = outputs
            flat_idx = 0
            row_sections = self._mixer_rows[0]
            for i in range(len(row_sections)):
                self._draw_mixer_section(scr, row, cx + i * sec_ow, flat_idx, compact=True)
                flat_idx += 1
            row += self._mixer_section_h - 2

            # Bus routing area between input and output rows
            max_row_len = max(len(r) for r in self._mixer_rows)
            route_w = max_row_len * sec_ow - 1
            self._draw_bus_route(scr, row, cx, route_w)
            row += 3

            row_sections = self._mixer_rows[1]
            for i in range(len(row_sections)):
                self._draw_mixer_section(scr, row, cx + i * sec_ow, flat_idx)
                flat_idx += 1
            row += self._mixer_section_h + 1

        return row

    def _draw_status_bar(self, scr, row, cx, section_w=BOX_IW + 2):
        dim = curses.color_pair(C_WHITE) | curses.A_DIM
        # Status / numeric entry line (no box, just text)
        if self.status_ticks > 0:
            self.status_ticks -= 1
        elif self.status:
            self.status = ""
        if self.num_buf:
            unit = self._current_unit()
            dial_attr = curses.color_pair(C_YELLOW)
            dial_prefix = f"= {self.num_buf}"
            self._safe(scr, row, cx + SLIDER_OFF, dial_prefix, dial_attr)
            self._safe(scr, row, cx + SLIDER_OFF + len(dial_prefix) + 1, f" {unit}", dial_attr)
            self._text_cursor_pos = (row, cx + SLIDER_OFF + len(dial_prefix))
        elif self.status:
            attr = (
                curses.color_pair(C_RED) | curses.A_BOLD
                if self.status_err
                else curses.color_pair(C_YELLOW)
            )
            self._safe(scr, row, cx + SLIDER_OFF, self.status, attr)
        row += 1
        # Border with hints — (key, desc[, color]) tuples
        hints: list = [("s", " save"), ("o", " load"), ("q", " quit")]
        if self.num_buf:
            hints = [("↵", ":set", C_YELLOW), ("Esc", ":cancel", C_YELLOW)] + hints
        # Compute width of hints block: " key desc · key desc … key desc "
        hints_w = 1 + sum(len(h[0]) + len(h[1]) for h in hints) + len(HSEP) * (len(hints) - 1) + 1
        dashes = section_w - 1 - hints_w
        # Draw dashes
        self._safe(scr, row, cx, BOX_H * dashes, dim)
        self._safe(scr, row, cx + section_w - 1, BOX_H, dim)
        # Draw hints right-aligned, keys highlighted
        col = cx + dashes + 1  # +1 for leading space
        for i, hint in enumerate(hints):
            key, desc = hint[0], hint[1]
            color = hint[2] if len(hint) > 2 else C_WHITE
            if i:
                self._safe(scr, row, col, HSEP, dim)
                col += len(HSEP)
            self._safe(scr, row, col, key, curses.color_pair(color) | curses.A_BOLD)
            col += len(key)
            self._safe(scr, row, col, desc, dim)
            col += len(desc)
        return row + 1

    # -- key handlers --

    def _handle_adjust(self, key, fn):
        """Handle [/]//{/} adjustment keys. Returns True if consumed."""
        if key == ord("]"):
            fn(1)
        elif key == ord("["):
            fn(-1)
        elif key == ord("}"):
            fn(5)
        elif key == ord("{"):
            fn(-5)
        else:
            return False
        return True

    def _controls_key(self, key):
        elems = self._active_elements()
        if key in (ord("j"), ord("J"), curses.KEY_DOWN):
            self.cursor = (self.cursor + 1) % len(elems)
        elif key in (ord("k"), ord("K"), curses.KEY_UP):
            self.cursor = (self.cursor - 1) % len(elems)
        elif key in (ord("l"), ord("L"), curses.KEY_RIGHT) and self._has_subsections:
            self._controls_subsection = (self._controls_subsection + 1) % len(self._element_groups)
            self.cursor = 0
        elif key in (ord("h"), ord("H"), curses.KEY_LEFT) and self._has_subsections:
            self._controls_subsection = (self._controls_subsection - 1) % len(self._element_groups)
            self.cursor = 0
        elif key == ord("m"):
            self._toggle_mute()
        elif key == ord("P"):
            self._toggle_phantom()
        else:
            self._handle_adjust(key, self._adjust)

    def _select_mixer_section(self, idx):
        """Set active mixer section and reset param to last (volume)."""
        self._mixer_section = idx
        self._mixer_param = len(self._all_mixer_sections[idx][3]) - 1

    def _mixer_key(self, key):
        n_params = len(self._all_mixer_sections[self._mixer_section][3])
        num_rows = len(self._mixer_rows)
        r, c = self._mixer_row_col()
        if key in (ord("l"), ord("L"), curses.KEY_RIGHT):
            new_sec = (
                self._mixer_section_at(r, c + 1)
                if c + 1 < len(self._mixer_rows[r])
                else self._mixer_section_at(r, 0)
            )
            self._select_mixer_section(new_sec)
        elif key in (ord("h"), ord("H"), curses.KEY_LEFT):
            new_sec = (
                self._mixer_section_at(r, c - 1)
                if c > 0
                else self._mixer_section_at(r, len(self._mixer_rows[r]) - 1)
            )
            self._select_mixer_section(new_sec)
        elif key in (ord("j"), curses.KEY_DOWN) and num_rows > 1:
            self._select_mixer_section(self._mixer_section_at((r + 1) % num_rows, c))
        elif key in (ord("k"), curses.KEY_UP) and num_rows > 1:
            self._select_mixer_section(self._mixer_section_at((r - 1) % num_rows, c))
        elif key == ord("m") and self.spec.num_output_pairs > 1:
            self._mixer_bus = (self._mixer_bus + 1) % self.spec.num_output_pairs
        elif key == ord(" "):
            self._mixer_param = (self._mixer_param + 1) % n_params
        else:
            self._handle_adjust(key, self._mixer_adjust)

    # -- event loop --

    def run(self, scr):
        curses.curs_set(0)
        curses.use_default_colors()
        for i, color in enumerate(
            [
                curses.COLOR_GREEN,
                curses.COLOR_RED,
                curses.COLOR_CYAN,
                curses.COLOR_YELLOW,
                curses.COLOR_WHITE,
                curses.COLOR_BLUE,
            ],
            1,
        ):
            curses.init_pair(i, color, -1)
        curses.set_escdelay(25)
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        scr.timeout(20)

        while True:
            self._sync()
            self._draw(scr)
            if self._text_cursor_pos:
                h, w = scr.getmaxyx()
                r, c = self._text_cursor_pos
                if 0 <= r < h and 0 <= c < w - 1:
                    curses.curs_set(1)
                    scr.move(r, c)
                else:
                    curses.curs_set(0)
            else:
                curses.curs_set(0)
            scr.refresh()
            key = scr.getch()

            if self._mode in ("save", "load"):
                self._picker_key(key)
                continue

            if key == ord("q"):
                break
            elif key == 27:  # Esc
                self.num_buf = ""
            elif key == ord("s"):
                self._enter_save_mode()
            elif key == ord("o"):
                self._enter_load_mode()
            elif key == 9:  # Tab
                self._window = "mixer" if self._window == "controls" else "controls"
                self.num_buf = ""
            elif key == curses.KEY_RESIZE:
                scr.clear()
            elif key == 10:  # Enter
                if self.num_buf:
                    try:
                        val = float(self.num_buf)
                        if self._window == "controls":
                            self._set_val(val)
                        else:
                            self._mixer_set_val(val)
                    except ValueError:
                        pass
                    self.num_buf = ""
            elif key in (curses.KEY_BACKSPACE, 127) and self.num_buf:
                self.num_buf = self.num_buf[:-1]
            elif key == ord("-") and not self.num_buf:
                self.num_buf = "-"
            elif key == ord(".") and "." not in self.num_buf and len(self.num_buf) < 8:
                self.num_buf += "."
            elif 48 <= key <= 57 and len(self.num_buf) < 8:  # 0-9
                self.num_buf += chr(key)
            elif self._window == "controls":
                self._controls_key(key)
            else:
                self._mixer_key(key)


class DemoController:
    """In-memory mock controller for TUI demo without hardware."""

    def __init__(self, spec: DeviceSpec):
        self.spec = spec
        self._state = {}
        # Init default state
        if spec.num_output_pairs == 1:
            self._state["output"] = {"volume": -10.0, "mute": False}
        else:
            for i in range(spec.num_output_pairs):
                self._state[f"output{i + 1}"] = {"volume": -10.0, "mute": False}
        for i in range(spec.num_inputs):
            self._state[f"input{i + 1}"] = {
                "gain": 20.0,
                "mute": False,
                "phantom": False,
            }
        if spec.has_monitor:
            self._state["monitor"] = 50

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_status_raw(self) -> bytes:
        return b""  # unused - decode_status is overridden

    def decode_status(self, _data: bytes) -> dict:
        import copy

        return copy.deepcopy(self._state)

    def set_volume(self, db: float, output_pair: int | None = None):
        db = max(self.spec.vol_db_min, min(self.spec.vol_db_max, db))
        if self.spec.num_output_pairs == 1:
            self._state["output"]["volume"] = db
        elif output_pair is not None:
            self._state[f"output{output_pair + 1}"]["volume"] = db
        else:
            for i in range(self.spec.num_output_pairs):
                self._state[f"output{i + 1}"]["volume"] = db
        return (0, db)

    def set_gain(self, target: str, db: float):
        db = max(self.spec.gain_db_min, min(self.spec.gain_db_max, db))
        self._state[target]["gain"] = db

    def set_monitor(self, val: int):
        self._state["monitor"] = max(0, min(100, val))

    def set_mute(self, target: str, on: bool):
        self._state[target]["mute"] = on

    def set_phantom(self, target: str, on: bool):
        self._state[target]["phantom"] = on

    def set_mixer_input(self, input_num, gain_db, pan=0.0, mix_bus=0):
        pass

    def set_mixer_output(self, volume_db, pan_l=-100.0, pan_r=100.0, output_pair=0, mix_bus=0):
        pass

    def set_mixer_loopback(self, volume_db, pan_l=-100.0, pan_r=100.0, mix_bus=0):
        pass

    def set_mixer_crosspoint(self, cn, db):
        pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="EVO TUI")
    parser.add_argument("--device", choices=list(DEVICES.keys()), help="Select device (evo4, evo8)")
    parser.add_argument(
        "--demo", action="store_true", help="Run without hardware (mock controller)"
    )
    args = parser.parse_args()

    if args.demo:
        spec = DEVICES[args.device] if args.device else DEVICES["evo8"]
        evo = DemoController(spec)
        with evo:
            curses.wrapper(EvoTUI(evo).run)
        return

    devices = detect_devices()
    if args.device:
        spec = DEVICES[args.device]
        if spec not in devices:
            print(f"error: {args.device} not found (check /dev/{args.device})", file=sys.stderr)
            sys.exit(1)
    elif not devices:
        print("error: no EVO device found (check /dev/evo*)", file=sys.stderr)
        sys.exit(1)
    elif len(devices) > 1:
        print("Multiple devices found. Use --device to select:", file=sys.stderr)
        for d in devices:
            print(f"  --device {d.name}", file=sys.stderr)
        sys.exit(1)
    else:
        spec = devices[0]

    try:
        evo = EVOController(spec)
        with evo:
            curses.wrapper(EvoTUI(evo).run)
    except (OSError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
