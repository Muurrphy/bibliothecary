# Monroe lips (梦露嘴唇)

The mouth every renderer in this project draws. It was designed for the
128×64 chest OLED of the Lilyput robot and is now the only mouth in the
package; the earlier generic dot-matrix geometry was removed.

## Shape

- Two sculpted upper lobes meet in a soft central notch with a natural
  tubercle. Opening and lateral pull flatten the tubercle and Cupid's bow;
  closure and rounding let them return.
- From each Cupid's-bow peak the outer shoulder pulls inward before returning
  to the corner: a subtle concave S-curve, not a straight diagonal.
- The lower lip is a wide cushion, fuller than the upper lip, whose rim rises
  toward both corners.
- Opening lifts the upper lip a little and drops the jaw a lot.
- Muscle antagonism: a mouth that opens farther must narrow, a mouth that
  stretches wider must close. No pose maximises both axes.
- Horizontal and side-pull families keep both corners connected; only narrow,
  vertically open poses may separate at the corners.

## Two outputs from one design

| Profile | Where | What it draws |
|---|---|---|
| `oled` | 128×64 one-bit OLED (firmware, preview) | The 44 designed frames: Monroe v1 (0–26) and the muscle-channel targets (27–43). Clean 2×2 cells with 1 px gutters, one frame per event. |
| `screen` | tablets, monitors | The same landmark contours rebuilt every frame at twice the resolution from blended muscle poses, drawn as flat pixel art: lip liner, upper and lower body, shadowed parting and hard highlight blocks. |

## Files

| File | Role |
|---|---|
| `tools/monroe/make_lips.py` | Original Monroe v1 generator (Pillow, NumPy). Kept verbatim. |
| `tools/monroe/make_v2.py` | Original muscle-channel generator (English v2). Kept verbatim except the path to `make_lips.py`. |
| `tools/monroe/build_bank.py` | Writes the 44-frame bank: `firmware/esp32_oled/monroe_frames.h` and `src/robot_lipsync/renderers/monroe_frames.js`. Byte-identical to the Lilyput chest header. |
| `src/robot_lipsync/monroe.py` | Muscle targets (English and Mandarin), viseme map, OLED frame rules, nearest-frame choice. Runtime, no dependencies. |
| `tools/monroe/build_tables.py` | Writes `firmware/esp32_oled/monroe_select.h` and `src/robot_lipsync/renderers/monroe_model.js` from `monroe.py`. |
| `src/robot_lipsync/renderers/dotmatrix.js` | Both profiles for the browser, plus `DotLips.track(events)`. |

Regenerate after changing the design:

```bash
pip install pillow numpy
python tools/monroe/build_bank.py
python tools/monroe/build_tables.py
pytest
```

## Motion

- OLED: like the chest board, one designed frame per event with no
  cross-fades; a gap of 90 ms or less holds the previous pose. English uses the
  readable profile (unstressed vowels stop at mid-range; only long strong
  accents reach the extreme frames) and drops ordinary changes closer than
  70 ms. Mandarin drops them under 55 ms. Closures, f/v, th, deep /a/ and the
  tight pucker always show.
- Screen: neighbouring muscle targets blend through smooth lead and release
  windows (105 ms lead for closures and rounded sounds, 75 ms otherwise). Jaw
  channels and lip channels blend separately so tongue-only consonants move the
  jaw without reshaping the lips. During b/p/m and f the pose is locked 85% to
  the closure. Mandarin `ai/ao/ei/ou` move from start to end target inside one
  event.

## Status

The OLED frames and the English readable profile were judged on the physical
chest board. The Mandarin rules and the `screen` profile are software-tested
only.
