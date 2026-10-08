# Mandarin and Spanish articulation profiles

Robot LipSync treats language support as a phonetic and timing problem, not a
translation problem. The lips, jaw, and facial anatomy are shared across
languages, but phoneme inventories, vowel systems, legal sound sequences, and
coarticulation differ. The implementation therefore reuses universal visible
landmarks such as bilabial closure while giving Mandarin and Spanish their own
text-to-phoneme front ends and vowel/rounding targets.

The numeric articulation targets in this repository are inspectable engineering
priors for a low-DOF mouth. They are not motion-capture ground truth and should
not be described as biologically exact.

## Mandarin (`zh`, `zh-CN`, or `cmn`)

Install the phrase-aware pinyin front end:

```bash
pip install -e ".[mandarin]"
robot-lipsync demo --text "你好，世界。" --language zh-CN \
  --output build/mandarin.html
```

The compiler merges two designs: the Lilyput Mandarin v1 spec (17 semantic
targets, written for the chest OLED) and a surface-phonetics pass. Nothing was
dropped from either.

1. Han phrases become tone-numbered pinyin with `pypinyin`; j/q/x/y + written
   `u` is read as `ü`.
2. Every character is one syllable: the initial takes 28% of it, the final
   72% (a stated prior, not acoustic truth). Inside the final the nucleus
   weighs 2.1, a medial or off-glide 0.9 and a nasal coda 0.8.
3. Seven initial classes: `ZH_BPM` b/p/m (closure), `ZH_F` f, `ZH_APICAL`
   d/t/n/l, `ZH_VELAR` g/k/h, `ZH_PALATAL` j/q/x, `ZH_DENTAL` z/c/s and
   `ZH_RETROFLEX` zh/ch/sh/r.
4. A non-closing initial already carries part of its final (CV co-onset):
   42% toward a rounded final, 30% toward a spread one, 20% toward /a/.
   b/p/m and f are landmarks and are never averaged away.
5. The initial keeps a 42 ms visual lead; the final takes over at its own
   acoustic onset, so a 180 ms "爸" still shows its closure for a frame.
6. Finals follow the surface pronunciation: `ian/üan/ie/üe` use the mid-open
   front vowel ê (`ZH_EH`), not /a/; `-n` closes the jaw (`ZH_N`) and `-ng`
   half-closes it (`ZH_NG`), so every character opens and closes; `ai/ao/ei/ou`
   are one moving target each (`ZH_AI` = a→i …), which reads better on a 20 fps
   OLED than two flashes, while the tablet renderer shows the motion.
7. The apical vowel of `zi/ci/si` (`ZH_IZ`) and `zhi/chi/shi/ri` (`ZH_IR`) is
   kept out of the wide /i/ class.
8. zh/ch/sh/r, u, ü and o pout forward and slightly evert the upper lip
   ("吃", "谱").
9. Tongue-only consonants move the jaw but leave the lip shape to the
   neighbouring vowels (JALI, Edwards et al. 2016); rounded sounds start early.
10. For the OLED, `robot_lipsync.mouth.oled_frame` maps the targets onto the
    chest frame bank, and changes closer than 55 ms keep the previous frame
    unless a landmark is involved.
11. While streaming, two trailing Han characters are withheld so polyphonic
    phrase readings can use right context without rewriting events already
    sent to hardware.

Status: software-tested only. The Mandarin rules have not yet been judged on
the physical chest OLED against the English profile, nor scored with native
speakers or video ground truth.

Tones are retained in event metadata. They are not turned into five different
mouth shapes because lexical tone is primarily an F0/prosody distinction. A
neutral fifth tone receives slightly lower motion intensity; the four lexical
tones otherwise share the same segmental mouth target.

If `pypinyin` is absent, Han text remains renderable with a low-confidence
neutral Mandarin vowel target (`confidence=0.25`). This is an explicit fallback,
not full Mandarin support.

## English and Spanish refinements (2026-10-06)

Built on what made Mandarin read well: every syllable reaches its own target,
and the targets differ where the mouth really differs.

- English reduced vowels (`AH0`, `ER0`) use a small neutral schwa instead of
  the open /ʌ/; lax `IH` and `UH` sit between their tense neighbours and the
  neutral mouth.
- English diphthongs (`AY AW OY EY OW`) are one moving target each, like
  Mandarin `ai/ao`: the tablet shows the whole path even for a short "I" or
  "go", and the OLED shows a readable endpoint.
- `S Z` close the teeth and spread; `SH ZH CH JH` (and Spanish `ch`) pout
  forward; `L` is tongue-only and no longer shifts the lips sideways.
- Spanish gets default lexical stress (penultimate syllable for words ending
  in a vowel, `n` or `s`, otherwise the last; written accents win; weak `i/u`
  in a diphthong yield to the strong vowel). Spanish vowels are never reduced:
  unstressed vowels keep 84% of the stressed opening, while English unstressed
  vowels keep 70%.

## Word timing and Spanish pass (2026-10-06)

Spanish looked "detached from the voice", and kept moving after a phrase had
ended. Two causes, both in timing rather than in mouth shapes:

1. **Word-level alignments were glued into one word.** The compiler joined
   every consecutive Latin-script token into a single word. That is right for
   character-level aligners (ElevenLabs sends one letter per span), but
   word-level aligners (edge-tts, Azure, Whisper) send whole words. A whole
   phrase, pause included, became one "word" whose phones were spread evenly
   from its first word to its last: the mouth kept talking through the pause
   and drifted up to a second away from the voice. English was hit too (the
   glued string is not in CMUdict, so it fell back to spelling). Now only
   single-character tokens closer than 40 ms are joined; every word token keeps
   its own timestamp. Edge punctuation (`¿Qué`, `Lilith.`) is stripped.
2. **Some voices report words early.** `robot_lipsync.calibrate.estimate_offset_ms`
   compares where the alignment says someone speaks with where the audio is
   loud. The edge-tts Mandarin and English voices run about 60 ms early, the
   Spanish ones about 90 ms. The demos keep the 60 ms lead the Mandarin look
   was tuned with and remove only the extra, so all languages lead the voice by
   the same amount (Spanish syllables are short, so an extra 30 ms is a lot).

Measured on the demo lines (correlation between mouth opening and loudness,
higher is better): Spanish 0.37 / 0.40 / 0.15 → 0.63 / 0.47 / 0.64, English
0.16 / 0.31 / 0.22 → 0.49 / 0.33 / 0.54; Mandarin unchanged at 0.55.

Spanish articulation, in the same pass:

- Vowels land on their sound; only the consonant before them leads (as with
  Mandarin finals), and a consonant already shows its vowel's rounding or
  spreading (o/u 36%, i/e 26%, a 18%): Spanish is CV-timed.
- Own muscle targets for the five pure vowels: central /a/, a true mid /e/,
  /o/ and /u/ rounded more tightly than English.
- Syllable-timed allocation: every vowel keeps a full slot, the stressed one is
  about a quarter longer and opens widest; unaccented function words (`la`,
  `de`, `mi`, `que`, `un`…) carry no stress.
- Unstressed `i/u` next to a vowel is a glide (`bueno`, `quieres`, `hoy`), a
  quick pass rather than a syllable; accented `í/ú` stays a vowel (`día`).
- `b/v` is a full closure only after a pause or `m/n`; between sounds it is the
  approximant [β] (`la vida`, `Cuba`): lips nearly meet without sealing.
- Spanish `ch` rounds less than English `ch/sh`.

## Spanish (`es`, `es-419`, or `es-ES`)

Spanish support has no runtime dependency:

```bash
robot-lipsync demo --text "Hola, mundo." --language es \
  --output build/spanish.html
```

The deterministic orthographic front end covers the productive rules needed by
the lip planner, including `ch`, `ll`, `rr`, `ñ`, silent `h`, soft `c/g`,
`que/qui`, `gue/gui`, `güe/güi`, and final `y`. Spanish `b` and `v` both map to
the bilabial target rather than incorrectly using the English labiodental `/v/`
(a full closure after a pause or `m/n`, the approximant [β] elsewhere).
The five stable vowel targets `/a e i o u/` are distinct from the English CMU
vowel inventory, and adjacent vowels naturally create visible diphthong paths.

The generic `es` and `es-419` profiles use seseo. `es-ES` maps `z` and soft
`c` to a dental target for the Castilian distinction. Other regional allophones
remain outside the current low-DOF model unless they produce a dependable
external lip or jaw difference.

## Research basis and limits

- Edwards, Landreth, Fiume and Singh, [*JALI: an animator-centric viseme model
  for expressive lip synchronization*](https://dgp.toronto.edu/~elf/JALISIG16.pdf)
  (SIGGRAPH 2016): separate jaw and lip control, mandatory closures, and
  tongue-only consonants that leave the lips to the surrounding vowels.
- Cohen and Massaro (1993), dominance-function coarticulation, used by the
  tablet renderer to blend neighbouring targets.
- The Lilyput Mandarin v1 spec cites Tsinghua's text-to-visual-speech study
  (2002), the ISCSLP 2000 Standard Chinese viseme system, synchronised CV
  co-onset (Journal of Phonetics, 2022) and evidence that visual cues affect
  Mandarin vowels but not tones (Frontiers, 2023).

- Li, Huang, and Li, [*Realistic Lip Motion Generation Based on 3D Dynamic
  Viseme and Coarticulation Modeling for Human-Robot
  Interaction*](https://arxiv.org/abs/2604.01756) (2026), proposes a Mandarin
  initial/final decomposition, 14 visible categories, dynamic compound-final
  trajectories, and coarticulation for a 14-DoF robot mouth. Robot LipSync uses
  those architectural principles but does not copy their code, data, or
  high-dimensional trajectories.
- Bonaventura et al.,
  [*Grapheme-to-phoneme transcription rules for Spanish, with application to
  automatic speech recognition and synthesis*](https://aclanthology.org/W98-0804/)
  (1998), supports a rule-based Spanish orthographic front end and documents
  remaining difficulty around hiatuses, loanwords, and dialect variants.
- Martínez Lazalde, Maddock, and Meredith,
  [*A Constraint-Based Approach to Visual Speech for a Mexican-Spanish Talking
  Head*](https://doi.org/10.1155/2008/412056) (2008), demonstrates why Spanish
  visual speech still needs context-dependent coarticulation rather than simple
  pose concatenation.
- Fernandez-Lopez and Sukno,
  [*Optimizing Phoneme-to-Viseme Mapping for Continuous Lip-Reading in
  Spanish*](https://doi.org/10.1007/978-3-030-12209-6_15) (2019), finds strong
  visual ambiguities in continuous Spanish and reports that an intermediate
  many-to-one vocabulary outperformed a one-phone/one-viseme setup in their
  recognition experiments.
- Bear et al.,
  [*Which phoneme-to-viseme maps best improve visual-only computer
  lip-reading?*](https://arxiv.org/abs/1710.01093) (2017), shows that mapping
  quality varies across talkers and that viseme inventories should be evaluated
  rather than treated as universal truth.
- Taylor, Theobald, and Matthews,
  [*Comprehensive many-to-many phoneme-to-viseme mapping and its application for
  concatenative visual speech
  synthesis*](https://doi.org/10.1016/j.specom.2013.02.005) (2013), motivates
  context-sensitive mappings because a single phoneme can have different visual
  realizations under coarticulation.

## Validation still required

The profiles have deterministic unit and integration tests, but stronger claims
need recorded native-speaker and physical-robot data. A multilingual evaluation
should report at least:

- bilabial and labiodental landmark recall;
- Mandarin `u/ü`, retroflex, and compound-final trajectory errors;
- Spanish five-vowel and rounded-vowel errors;
- phrase-level append-only violations and added look-ahead latency;
- jaw/width constraint violations, jerk, and minimum readable dwell;
- native-speaker preference tests separated by language and Spanish dialect.
