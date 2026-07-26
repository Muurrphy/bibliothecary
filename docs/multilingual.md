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

The compiler:

1. converts a Han phrase to tone-numbered pinyin with `pypinyin`;
2. separates each syllable into an initial and a visible final trajectory;
3. maps bilabial, labiodental, apical, velar, palatal, dental-sibilant, and
   retroflex initials separately;
4. preserves open, rounded, spread, tight-rounded, and front-rounded (`ü`)
   finals;
5. treats compound finals as motion paths rather than one neutral pose;
6. withholds two trailing Han characters while streaming so common polyphonic
   phrase readings can use right context without rewriting events already sent
   to hardware.

Tones are retained in event metadata. They are not turned into five different
mouth shapes because lexical tone is primarily an F0/prosody distinction. A
neutral fifth tone receives slightly lower motion intensity; the four lexical
tones otherwise share the same segmental mouth target.

If `pypinyin` is absent, Han text remains renderable with a low-confidence
neutral Mandarin vowel target (`confidence=0.25`). This is an explicit fallback,
not full Mandarin support.

## Spanish (`es`, `es-419`, or `es-ES`)

Spanish support has no runtime dependency:

```bash
robot-lipsync demo --text "Hola, mundo." --language es \
  --output build/spanish.html
```

The deterministic orthographic front end covers the productive rules needed by
the lip planner, including `ch`, `ll`, `rr`, `ñ`, silent `h`, soft `c/g`,
`que/qui`, `gue/gui`, `güe/güi`, and final `y`. Spanish `b` and `v` both map to
the bilabial target rather than incorrectly using the English labiodental `/v/`.
The five stable vowel targets `/a e i o u/` are distinct from the English CMU
vowel inventory, and adjacent vowels naturally create visible diphthong paths.

The generic `es` and `es-419` profiles use seseo. `es-ES` maps `z` and soft
`c` to a dental target for the Castilian distinction. Other regional allophones
remain outside the current low-DOF model unless they produce a dependable
external lip or jaw difference.

## Research basis and limits

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
