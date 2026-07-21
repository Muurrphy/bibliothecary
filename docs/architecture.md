# Architecture

Robot LipSync separates speech timing, articulation, rendering, and transport so that no visual style or device becomes the data model.

## Layers

```text
Provider
  audio chunks + character/token alignment
          ↓
Phoneme alignment
  timed, language-tagged phonemes
          ↓
Planner
  coarticulation + visible speech landmarks + muscle constraints
          ↓
Articulation IR
  renderer-independent continuous events
          ↓
Constraint/backend layer
  display dwell, event budget, DOF projection, velocity and limits
          ↓
HTML · OLED · avatar · serial · soft mouth
```

## Why alignment is a provider concern

The planner should not care whether timing came from ElevenLabs, forced alignment, Rhubarb, a local TTS engine, or a prerecorded fixture. Providers normalize timing into `AlignmentSpan` and optionally provide audio chunks from the same generation.

When a TTS service can return audio and alignment together, that path is preferred: a second audio-analysis request adds latency and can drift away from the actual generated audio.

## Append-only streaming contract

Physical event queues cannot revise the past. `IncrementalArticulationCompiler` therefore:

1. appends character alignment as it arrives;
2. withholds an incomplete final English word;
3. compiles the stable prefix;
4. keeps one event as coarticulation look-ahead;
5. emits only events that were never emitted before;
6. flushes the final look-ahead event when the stream ends.

If a provider edits timestamps already declared stable, the provider is violating this contract. The compiler intentionally raises instead of silently rewriting hardware motion.

## Articulation IR v1

Every event has time, duration, viseme metadata, language, confidence, intensity, and eight continuous channels:

| Channel | Meaning |
| --- | --- |
| `jaw_open` | jaw-driven vertical opening |
| `lip_separation` | visible gap independent of jaw angle |
| `mouth_width` | horizontal corner retraction |
| `lip_round` | orbicular rounding |
| `lip_press` | bilabial compression |
| `lip_protrusion` | forward pucker/protrusion |
| `lower_lip_tuck` | lower lip movement toward the upper teeth |
| `asymmetry` | signed left/right bias |

This is not a claim that eight scalars fully describe human tissue. It is a compact, inspectable contract that can be projected to smaller displays and expanded by later schemas.

## Style versus articulation

Articulation answers what must be visible for speech. Style answers how a renderer depicts it. A neon blue lip, a monochrome pixel lip, and a silicone mouth may consume the same target but should not share hard-coded geometry.

The original Lilyput Monroe mouth is a reference style, not biological ground truth.

## Physical clock

Network arrival time is not playback time. A backend should anchor visible events to a playback event such as `physical_audio_start` or a device sample counter. This prevents mouth motion from following variable HTTP/USB arrival jitter.

## Threading rule

The only thread feeding live audio must never block on a renderer round-trip. A hardware backend may confirm setup before audio starts and validate counts after a phrase ends, but motion uploads during playback should be bounded and non-blocking.
