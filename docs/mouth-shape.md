# Dot-matrix mouth

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
| `oled` | 128×64 one-bit OLED (firmware, preview) | The 44 designed frames: frame bank v1 (0–26) and the muscle-channel targets (27–43). Clean 2×2 cells with 1 px gutters, one frame per event. |
| `screen` | tablets, monitors | The same landmark contours rebuilt every frame on a 64x32 LED grid from blended muscle poses, drawn as a flat, saturated LED fill like the OLED: a quiet lip line, a dimmer parting and one small gloss mark. The Cupid's bow and tubercle are relaxed 60% toward the gentler tension outline. Gestures are bigger than on the OLED (wider jaw drop, narrower rounding, harder press, a squeezed kiss for u/ü/o), stronger syllables open further, and a mouth that would leave the panel is scaled to fit. |

## Files

| File | Role |
|---|---|
| `tools/mouth/make_lips.py` | Original frame generator (Pillow, NumPy). |
| `tools/mouth/make_v2.py` | Original muscle-channel generator (English v2). Uses the geometry in `make_lips.py`. |
| `tools/mouth/build_bank.py` | Writes the 44-frame bank: `firmware/esp32_oled/mouth_frames.h` and `src/robot_lipsync/renderers/mouth_frames.js`. Byte-identical to the Lilyput chest header. |
| `src/robot_lipsync/mouth.py` | Muscle targets (English and Mandarin), viseme map, OLED frame rules, nearest-frame choice. Runtime, no dependencies. |
| `tools/mouth/build_tables.py` | Writes `firmware/esp32_oled/mouth_select.h` and `src/robot_lipsync/renderers/mouth_model.js` from `mouth.py`. |
| `src/robot_lipsync/renderers/dotmatrix.js` | Both profiles for the browser, plus `DotLips.track(events)`. |

Regenerate after changing the design:

```bash
pip install pillow numpy
python tools/mouth/build_bank.py
python tools/mouth/build_tables.py
pytest
```

## Motion

- OLED: like the chest board, one designed frame per event with no
  cross-fades; a gap of 90 ms or less holds the previous pose. English uses the
  readable profile (unstressed vowels stop at mid-range; only long strong
  accents reach the extreme frames) and drops ordinary changes closer than
  70 ms. Mandarin drops them under 55 ms. Closures, f/v, th, deep /a/ and the
  tight pucker always show.
- Screen: every target peaks at the middle of its event with a flat-topped
  dominance window and hands over quickly to the next, so each syllable reaches
  its own shape instead of averaging with its neighbours. Jaw
  channels and lip channels blend separately so tongue-only consonants move the
  jaw without reshaping the lips. During b/p/m and f the pose is locked 85% to
  the closure. Mandarin `ai/ao/ei/ou` move from start to end target inside one
  event.

## Status

The OLED frames and the English readable profile were judged on the physical
chest board. The Mandarin rules and the `screen` profile are software-tested
only.

## Colours

Red is a toned-down Y2K lipstick rose (`255,40,108`); blue is the Aqua blue of
Mac OS X around 2000 (`56,152,255`). Pure saturated red and blue were dropped
because, glowing on black, they vibrated and were tiring to watch.
