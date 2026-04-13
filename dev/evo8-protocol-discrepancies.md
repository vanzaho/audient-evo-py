# EVO 8 Protocol Discrepancies

Comparison between `dev/evo8-implementation.md`, the Arduino reference
(`hoskere/audient-evo8-rp2350-arduino`), and the actual implementation.

---

## 1. Gain access path — diverges, probably mirrors (low risk)

| | Entity | wIndex | wValue | Payload |
|---|---|---|---|---|
| Implementation | FU11 CS=2 | 0x0B00 | (2<<8)\|CN (1-4) | 2-byte Q8.8 |
| Arduino | EU58 CS=1 | 0x3A00 | 0x0100+ch (0-3) | 4-byte `{0x00, adj_gain, sign, sign}` |

For EVO 4, `DESIGN.md` says EU58 CS=1 mirrors FU11 CS=2 (read-only). The Arduino
writes to it on EVO 8. Both paths likely reach the same hardware register. The
encoding format also differs (our Q8.8 vs the Arduino's custom centering-on-8dB
formula). **Needs hardware verification; both likely work.**

---

## 2. Mute target ordering — internally contradictory in Arduino (uncertain, needs HW test)

Our implementation: inputs CN 0–3, outputs CN 4–5.

Arduino function comment says: `target = 0 (output 1+2), 1 (output 3+4), 2–5 (input ch1–4)`.

But Arduino `loop1()` call sites say the opposite:
```cpp
evo_set_mute(0, false);    // unmute input 1   ← contradicts function comment
evo_set_mute(1, false);    // unmute input 2
```

The Arduino source is self-contradictory. Additionally, the mute wIndex in the
Arduino is `0x03a0` (likely a typo for `0x3a00`) — suggesting the mute function
was never verified against hardware. **Needs hardware test to confirm ordering.**

---

## 3. Output volume entity — diverges, probably mirrors (low risk)

| | Entity | wIndex | wValue OUT1+2 | wValue OUT3+4 | Payload |
|---|---|---|---|---|---|
| Implementation | FU10 CS=2 | 0x0A00 | CN=1-2 | CN=3-4 | 2-byte Q8.8 |
| Arduino | EU59 CS=0 | 0x3B00 | 0x0000 | 0x0002 | 4-byte with custom encoding |

For EVO 4, `DESIGN.md` confirms EU59 CS=0 is a mirror of FU10. The EVO 8 likely
works the same way. Both paths reach the same register.

---

## 4. Mixer crosspoint dB encoding — Arduino likely wrong

| | Formula | dB=0 sends | dB=+6 sends |
|---|---|---|---|
| Implementation | `db * 256` (UAC2 Q8.8) | 0x0000 | 0x0600 |
| Arduino | `(db - 6.0) * 256` | 0xFA00 | 0x0000 |

Our encoding follows the UAC2 standard (confirmed in `DESIGN.md` for EVO 4 MU60).
The Arduino's mixer function contains `// ⚠️ UPDATE these once you verify with
Wireshark!` comments, indicating it was written without hardware verification. The
-6 dB offset in the Arduino appears to be a bug.

---

## 5. Mixer output assignment — "reserved" label was wrong (FIXED)

**This was the most significant discrepancy and has been corrected in the
implementation.**

The original doc labelled mixer out_idx 2 and 3 as "reserved / unused on stock
firmware." This was wrong.

The Arduino's `evo_set_input_pan_mix(channel, db, pan, output_num)` uses
`output_num=0` for "Main 1+2" routing and `output_num=1` for "Main 3+4" routing,
with the CN formula:

```
L: wValue = 0x0100 + (4 * input) + (2 * output_num)
R: wValue = 0x0101 + (4 * input) + (2 * output_num)
```

This means:
- `output_num=0` -> out_idx 0, 1 (mixer output for OUT1+2)
- `output_num=1` -> out_idx 2, 3 (mixer output for OUT3+4)

The EVO 8 mixer has **two independent stereo mixer outputs**: one feeding each output
pair's monitoring/loopback context. The high-level mixer methods accept a
`mix_output` parameter (0-based, default 0).

Additionally, the final USB output source pair had a latent stride bug for EVO 8:
it was writing to loopback_L × out_2 and loopback_L × out_3 instead of loopback_R ×
out_0 and loopback_R × out_1. Treating OUT5+6 as `set_mixer_output(...,
output_pair=2)` now uses the same CN formula as every other stereo output source.

### Correct mixer output layout (EVO 8)

| out_idx | Mix bus | Destination |
|---------|---------|-------------|
| 0 | Bus 0 L | Main 1+2 context (loopback / monitoring) |
| 1 | Bus 0 R | Main 1+2 context |
| 2 | Bus 1 L | Main 3+4 context |
| 3 | Bus 1 R | Main 3+4 context |

---

## Summary

| Area | Status |
|---|---|
| Gain path (EU58 vs FU11) | Unverified - both likely work |
| Mute ordering | Unverified - needs hardware test |
| Output volume (EU59 vs FU10) | Unverified - both likely work |
| Mixer dB encoding | Arduino likely wrong; our UAC2 encoding is correct |
| Mixer output assignment | **Fixed** - out_idx 2,3 are mixer output 1, not reserved |
| Final output source stride | **Fixed** - OUT5+6 now uses the same CN formula as other output sources |
