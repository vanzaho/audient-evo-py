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

- [x] Does EVO 4 expose a status/interrupt endpoint for HW-change events?
      YES, but on **interface 0** (UAC2 audio control, owned by
      `snd-usb-audio`): `EP 0x83 IN, Interrupt, bInterval 8`. Interface 3
      (our bind) has **0 endpoints**. We cannot cleanly own the notification
      stream from Option B - see §9.
- [ ] Exact set of meter values and their GET request shape.
- [ ] Naming conventions for the kcontrols so PipeWire/WirePlumber route them
      sensibly (study Scarlett2 control names).
- [ ] Whether to keep `/dev/evo4` ioctl long-term or retire it once all
      controls are native (keep it for now - zero-risk fusion).

---

## 9. Findings (session 2026-06-22)

### Progress
- Steps 1-3 done and verified on hardware:
  1. `evo_ctrl()` helper extracted from `evo_ioctl` (the "fusion" - one shared
     locked transfer path). Python TUI unchanged.
  2. Empty control-only card registered (`snd_card_new` + `snd_card_register`
     in probe, `snd_card_free` in disconnect *before* taking `dev->lock`).
     Shows as a separate card in `/proc/asound/cards` (e.g. card 4 "Mixer").
  3. First control: `input1` phantom (`wValue 0x0000`, `wIndex 0x3A00`, 4-byte
     LE, `1`=on), served from a software cache, written via `evo_set_bool`.
     `.put` returns 1=changed / 0=unchanged / -errno. Verified vs LED + Python.

### Two-card situation (Option B reality)
- Out-of-tree module **cannot** add kcontrols to card 0 (EVO4) - only the
  card's owner (`snd-usb-audio`) can. So our controls live on a **second,
  control-only card** (no PCM).
- Downside: not auto-associated with the audio PCM; `alsamixer -c EVO4` stays
  empty; tools must target the Mixer card by **id** (not index - probe order
  varies). Upside: ships today, DKMS-clean, no kernel patching, audio
  undisturbed across `rmmod`/reload.
- Real fix to the split = Option A (controls land on card 0).

### HW-sync is the Option-A payoff (key conclusion)
- The interrupt endpoint (EP 0x83) lives on interface 0, already polled by
  `snd-usb-audio`. An interrupt-IN endpoint has one logical reader, so Option B
  cannot own it -> no clean interrupt-URB HW-sync.
- Option B: build **without** HW-sync. Cache stays correct as long as changes
  go *through* the driver; only stale case is the physical knob. Don't
  over-invest in a polling hack.
- Option A (quirk inside `snd-usb-audio`): already owns EP 0x83's notification
  path (Scarlett2 pattern) - the natural home for HW-sync.

### Migration sequence
```
B: steps 4-6 (gain, volume, monitor, matrix, meters)
B: step 8 (alsactl persistence; drop evo4-load-config.service)
   [skip interrupt HW-sync in B - see above]
-> Python/tests migrate to pyalsa, control by control (ioctl still present)
-> all green through ALSA   <-- validation gate; this IS the upstream evidence
-> (optional) retire /dev/evo4
-> (optional) port proven table into snd-usb-audio quirk for Option A
```
- `pyalsa` (`pyalsa.alsahcontrol`, Arch `python-pyalsa`) reads our kcontrols and
  can subscribe to `snd_ctl_notify` events. This is the Python migration target.

### Option A dev/test workflow
- **Rebuild the module, not the whole kernel.** Build `snd-usb-audio.ko`
  against source matching `uname -r` with the live `.config`
  (`zcat /proc/config.gz > .config; make olddefconfig; make modules_prepare;
  make M=sound/usb modules`), then `rmmod snd_usb_audio; insmod ...`. Vermagic
  must match or `insmod` rejects it. Requires nothing streaming the EVO.
- Files: new `sound/usb/mixer_evo.c` (port of the B control table, `.get/.put`
  call `snd_usb_ctl_msg()` instead of `evo_ctrl()`), hook in `mixer_quirks.c`
  `snd_usb_mixer_apply_create_quirk()` by VID/PID, add to `sound/usb/Makefile`.
- Full custom-kernel build only for a final clean-boot sanity check / upstream.

### Decoding interrupt notifications (for Option A step 7)
- Use **usbmon / Wireshark** on bus 3 (`usbmon3`, filter
  `usb.endpoint_address == 0x83`). usbmon sees the traffic even though
  `snd-usb-audio` owns the endpoint.
- Turn each physical control (smart knob, monitor encoder, front-panel) one at
  a time; map action -> notification bytes.
- Expect either the UAC2 6-byte status message (`bInfo, bAttribute, wValue,
  wIndex` -> then `GET_CUR` for the value) **or** a vendor bitmap (Scarlett2
  does this). Capture decides. Cross-check with Windows app if ambiguous.

---

## Reference

- Scarlett2 driver:
  `https://github.com/torvalds/linux/blob/master/sound/usb/mixer_scarlett2.c`
- Quirk hook: `sound/usb/mixer_quirks.c` -> `snd_usb_mixer_apply_create_quirk`
- Current code: `kmod/evo_raw.c`, `evo/kmod.py`, `evo/controller.py`
- Issue discussion: vanzaho/audient-evo-py#4
