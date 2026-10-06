# Changelog

## 0.1.0 - Unreleased

- Extracted a renderer-independent articulation contract from the Lilyput dual-ESP32 prototype.
- Added causal incremental alignment compilation.
- Added English visible-speech targets, coarticulation, landmark protection, and width/open antagonism.
- Added dependency-free animated HTML demo and compact serial JSON backend.
- Added optional ElevenLabs same-stream audio/alignment provider.
- Added physical latency trace schema, report CLI, benchmark rules, and uncontrolled reference samples.
- Added a persistent 100-turn benchmark runner, fixed English v1 suite, checkpoint/resume, detailed stage report, and clearly labeled CI stub.
- Added reproducibly compiled ESP32-C3 OLED firmware, a namespaced bounded serial protocol, and a host timeline uploader.
- Added tests, CI, schemas, architecture, research boundaries, and LeRobot mouth-lab roadmap.
- Added language-tagged Spanish G2P with five-vowel articulation, seseo and
  `es-ES` dialect handling.
- Added optional phrase-aware Mandarin pinyin, initial/final articulation,
  compound-final paths, tone metadata, and a two-character streaming horizon.
- Added Mandarin and Spanish demos, fixtures, research notes, and tests.
- Replaced the generic dot-matrix mouth with the Monroe lips from the Lilyput
  chest OLED: the 44-frame bank in the firmware and the `oled` preview, and the
  same geometry rebuilt at 2x for the `screen` (tablet) preview.
- Added an optional Monroe frame hint to `LIP/EVENT`; older boards ignore it.
- Merged the Lilyput Mandarin v1 rules (17 semantic targets, CV co-onset,
  initial lead, OLED de-flicker) with surface finals (ê, nasal codas, glide
  timing), pouting rounded initials and JALI-style jaw/lip separation.
- Fixed word-level alignments (edge-tts, Azure, Whisper) being glued into one
  phrase-long word: each word now keeps its own timestamp, so pauses stay
  silent and Spanish/English no longer drift away from the voice.
- Added `robot_lipsync.calibrate` to measure a TTS voice's timestamp offset
  against its audio.
- Spanish pass: vowels land on their sound, CV anticipation, pure-vowel muscle
  targets, syllable-timed allocation, unstressed function words, glides, the
  [β] approximant and a lighter `ch`.
