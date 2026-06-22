# EVO 4 ALSA Mixer Driver - Implementation Plan

Goal: expose EVO 4 hardware controls (phantom, gain, volume, monitor, mixer
matrix, meters) as native ALSA controls in the kernel, instead of the current
userspace ioctl + Python approach. Fixes volume-change latency, gives free
persistence across reboots, and makes alsamixer / PipeWire / WirePlumber show
real controls.

This is a learn-by-doing plan. Build Option B first (out-of-tree, ships today),
then optionally port to Option A (upstream) once the control logic is proven.

---

## 0. Where we start

Current architecture (`kmod/evo_raw.c` + `evo/kmod.py` + `evo/controller.py`):

- `evo_raw` binds the **unused DFU interface 3** only to obtain the
  `usb_device` handle (it does not use interface 3 for anything).
- Exposes `/dev/evo4` with one ioctl `EVO_CTRL_TRANSFER` that forwards raw
  UAC2 control transfers to endpoint 0.
- `snd-usb-audio` independently owns interfaces 0-2 for audio streaming.
- They coexist because they bind *different interfaces* of the same device.
- All control *semantics* (which `wValue`/`wIndex` = phantom/gain/mixer) live
  in Python (`evo/controller.py`).

This is the ideal starting point: the protocol is already mapped, and we only
need to move the *control surface* into the kernel as ALSA `kcontrol`s.

ep0 contention is a non-issue: the USB core serialises control transfers, so
`snd-usb-audio` and our module hitting ep0 concurrently is safe.

---

## 1. Key fact that shapes everything: Scarlett2 is a *quirk inside snd-usb-audio*

`sound/usb/mixer_scarlett2.c` is **not a separate driver**. It is a mixer quirk
inside `snd-usb-audio`, hooked from `snd_usb_mixer_apply_create_quirk()` in
`sound/usb/mixer_quirks.c`, keyed by VID/PID. Because `snd-usb-audio` already
owns the device's audio-control interface, the quirk runs in that driver's
context, gets the existing `struct usb_mixer_interface` + `chip->dev`, and
registers `snd_kcontrol`s **on the same ALSA card as the PCM**. Each control's
`.get/.put` issues `snd_usb_ctl_msg()` (in-kernel `usb_control_msg`).

Consequence: **which card the controls live on** is the whole design decision.

- Controls on the **same card as the audio PCM** => must live *inside*
  `snd-usb-audio` (Option A / upstream).
- Controls from an **out-of-tree module** => can only live on a *separate*
  control-only card (Option B).

You cannot cleanly add `kcontrol`s to the existing EVO04 card from an
out-of-tree module: kcontrols must be added by the card's owner, during/after
its creation, under its lifetime + locking.

---

## 2. The two targets

### Option A - inside `snd-usb-audio` (the "correct" / Scarlett2 way)

- Add `mixer_evo.c` to `sound/usb/`, hook it in `mixer_quirks.c`
  (`snd_usb_mixer_apply_create_quirk`) by VID/PID.
- Controls land on the **EVO04 card itself**: `alsamixer -c EVO04` shows
  phantom/gain/monitor/matrix, WirePlumber sees them natively, and
  `alsactl store/restore` persists them at boot for free.
- Cost: modifying an in-tree module. Out-of-tree that means shipping a patched
  `snd-usb-audio.ko` via DKMS (tracks every kernel version, fragile). The
  realistic distribution form is **upstreaming** - slow, GPL, kernel coding
  style, needs a maintainer commitment and a stable protocol.

### Option B - our own control-only ALSA card (ships today)

- Keep binding interface 3 exactly as now. In addition to (or replacing) the
  ioctl, call `snd_card_new(&intf->dev, ...)` => register one `snd_kcontrol`
  per control => `snd_card_register()`.
- No PCM - `snd-usb-audio` keeps streaming. We get a **second card**
  (e.g. "EVO4 Mixer") whose controls are real ALSA controls driven by the same
  ep0 transfers.
- Cost: controls sit on a *different card* from the audio PCM. `alsamixer` on
  EVO04 won't show them; anything that auto-associates controls with the
  streaming card won't link them. But functionally complete and 100%
  out-of-tree / DKMS-friendly.

### The fusion (one module, two faces)

Evolve `evo_raw` into one module that keeps the existing ioctl (Python TUI/CLI
keep working unchanged) **and** registers an ALSA control card. One shared
`usb_device` handle, one shared control-transfer helper. The ioctl path and the
kcontrol `.get/.put` both call the same `evo_ctrl()` function. That is the
fusion, in code.

---

## 3. Control surface to port (from `evo/controller.py`)

Map each existing control to an ALSA `kcontrol` type:

| EVO control            | ALSA type                          | Notes |
|------------------------|------------------------------------|-------|
| Phantom 48V            | `BOOLEAN`                          | per target |
| Mute                   | `BOOLEAN`                          | per target |
| Gain (mic/line)        | `INTEGER` + dB TLV                 | step 1.0 dB (`_GAIN_DB_STEP`) |
| Output volume          | `INTEGER` + dB TLV                 | per output pair |
| Monitor mode/ratio     | `ENUMERATED` (or INTEGER ratio)    | EU56 wValue/wIndex |
| Mixer crosspoint/matrix| `INTEGER` + dB TLV (many)          | range -128..+6 dB (`_MIXER_DB_MIN/MAX`) |
| Level meters           | `INTEGER`, read-only (`VOLATILE`)  | updated from device |

Pull the exact `wValue` (`control_selector << 8 | channel`) and `wIndex`
(`EntityID << 8 | interface`) constants straight out of `controller.py` -
they're already correct. dB TLV uses `SNDRV_CTL_TLV_DB_MINMAX` /
`SNDRV_CTL_TLV_DB_SCALE` so alsamixer shows real dB.

---

## 4. Three things Scarlett2 gets right that we must replicate

1. **Software cache.** Reading the device on every alsamixer redraw is slow -
   this is the current "delay" complaint. Read all values once at init into a
   cache; serve `.get` from cache; on `.put` send the transfer *and* update the
   cache. This alone fixes the latency.

2. **Hardware-initiated changes.** When the user turns the physical smart knob /
   monitor encoder or toggles something on the unit, we must reflect it or
   alsamixer goes stale. Submit an **interrupt URB** on the device's status
   endpoint, parse the notification, update the cache, then call
   `snd_ctl_notify(card, SNDRV_CTL_EVENT_MASK_VALUE, &kctl->id)`. This is what
   makes it feel "immediate" and is the bulk of Scarlett2's complexity.
   - PREREQUISITE: confirm the EVO 4 actually exposes a status/interrupt
     endpoint (`lsusb -v`). If it only answers GET_CUR polls, we fall back to
     polling (worse UX) or skip HW-sync for v1.

3. **Persistence.** Once they're real kcontrols, `alsa-restore.service` /
   `alsactl` save and restore them across reboots automatically. This
   **replaces** `kmod/evo4-load-config.service`.

---

## 5. Code sketch (Option B, inside the existing `evo_probe`)

After we have `dev->udev`:

```c
struct snd_card *card;
snd_card_new(&intf->dev, SNDRV_DEFAULT_IDX1, "EVO4Mix",
             THIS_MODULE, 0, &card);

static int phantom_get(struct snd_kcontrol *k, struct snd_ctl_elem_value *v) {
    struct evo_device *dev = snd_kcontrol_chip(k);
    v->value.integer.value[0] = dev->cache.phantom;   /* served from cache */
    return 0;
}
static int phantom_put(struct snd_kcontrol *k, struct snd_ctl_elem_value *v) {
    struct evo_device *dev = snd_kcontrol_chip(k);
    bool on = v->value.integer.value[0];
    if (on == dev->cache.phantom) return 0;
    evo_set_cur(dev, PHANTOM_WVALUE, PHANTOM_WINDEX, on); /* same ep0 xfer */
    dev->cache.phantom = on;
    return 1;   /* return 1 = value changed (notifies listeners) */
}
static const struct snd_kcontrol_new phantom_ctl = {
    .iface = SNDRV_CTL_ELEM_IFACE_MIXER,
    .name  = "Phantom Power 48V Switch",
    .info  = snd_ctl_boolean_mono_info,
    .get = phantom_get, .put = phantom_put,
};

snd_ctl_add(card, snd_ctl_new1(&phantom_ctl, dev));
/* ...one per control: gain, volume, monitor enum, 4x4 matrix... */
snd_card_register(card);
```

Refactor first: factor the `usb_control_msg` call out of `evo_ioctl` into a
shared `evo_ctrl()` helper so both the ioctl path and the kcontrol `.get/.put`
call it. That refactor *is* the fusion.

---

## 6. Build order (each step independently testable)

1. **Refactor.** Extract `evo_ctrl()` helper from `evo_ioctl`. No behaviour
   change. Verify Python TUI/CLI still works.
2. **Empty card.** Add `snd_card_new` + `snd_card_register` in `evo_probe`,
   teardown in `evo_disconnect`. Verify `aplay -l` / `cat /proc/asound/cards`
   shows the new card with no controls; verify hot-unplug is clean.
3. **First control (phantom).** Add the cache struct, init it once from the
   device, add `phantom_get/put`. Verify with `amixer -c EVO4Mix` and toggling
   in `alsamixer`; cross-check against the Python tool.
4. **Gain + volume with dB TLV.** Confirm alsamixer shows correct dB and range.
5. **Monitor enum + mixer matrix.** Port the rest of `controller.py`.
6. **Meters (read-only).**
7. **HW-sync interrupt URB** (if a status endpoint exists). Turn the physical
   knob, confirm alsamixer updates live via `snd_ctl_notify`.
8. **Persistence.** Drop `evo4-load-config.service`, confirm `alsactl
   store/restore` round-trips. Update `README.md` and `kmod/install.sh`.

---

## 7. Distribution / packaging notes

- Option B builds as DKMS exactly like the current module - update
  `kmod/Makefile` and `kmod/dkms.conf` to pull in ALSA symbols (already
  available; `snd`, `snd-usb-audio` are standard). No kernel patching.
- Keep `MODULE_LICENSE("GPL")` (required for ALSA symbols anyway).
- Once Option B is proven, the same `.info/.get/.put` table ports almost
  verbatim into a `mixer_evo.c` quirk for Option A / upstream submission. The
  already-reverse-engineered, stable protocol map is exactly what makes that
  submission viable.

---

## 8. Open questions to resolve before / during build

- [ ] Does EVO 4 expose a status/interrupt endpoint for HW-change events?
      (`lsusb -v`, look at interface 3 / any HID/interrupt EP).
- [ ] Exact set of meter values and their GET request shape.
- [ ] Naming conventions for the kcontrols so PipeWire/WirePlumber route them
      sensibly (study Scarlett2 control names).
- [ ] Whether to keep `/dev/evo4` ioctl long-term or retire it once all
      controls are native (keep it for now - zero-risk fusion).

---

## Reference

- Scarlett2 driver:
  `https://github.com/torvalds/linux/blob/master/sound/usb/mixer_scarlett2.c`
- Quirk hook: `sound/usb/mixer_quirks.c` -> `snd_usb_mixer_apply_create_quirk`
- Current code: `kmod/evo_raw.c`, `evo/kmod.py`, `evo/controller.py`
- Issue discussion: vanzaho/audient-evo-py#4
