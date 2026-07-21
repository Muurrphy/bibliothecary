# Third-party systems and research boundary

Robot LipSync stands on existing speech animation and voice-agent work. Links below are references and possible adapters; their code, models, weights, datasets, and licenses are not bundled here.

## Lip sync and speech animation

- [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync): offline audio-file analysis and 6–9 discrete cartoon mouth cues. Excellent future offline provider; not designed as a causal physical-control runtime.
- [JALI](https://www.dgp.toronto.edu/~karan/jali/): expressive phonetic animation, coarticulation, prosody, and animator control. Robot LipSync does not claim to invent those concepts.
- [NVIDIA Audio2Face 3D SDK](https://github.com/NVIDIA/Audio2Face-3D-SDK): high-performance GPU facial animation. It can become a teacher or high-dimensional baseline, not an MCU backend.
- [Columbia Robot Lip Sync](https://www.creativemachineslab.com/lipsync.html): self-supervised learning on a dedicated 10-DoF silicone robot face with published data/code links. This establishes that learned physical lips and motor babbling are existing research.
- [Phoneme-to-Lip-14DOF](https://github.com/yuesheng21/Phoneme-to-Lip-14DOF): Chinese dynamic visemes and a 14-DoF robot data release. License must be confirmed before copying or redistribution.

## Voice-agent orchestration

- [Pipecat](https://github.com/pipecat-ai/pipecat), [LiveKit Agents](https://github.com/livekit/agents), and [TEN Framework](https://github.com/ten-framework/ten-framework) already provide broad real-time voice-agent pipelines.
- Robot LipSync should integrate with these ecosystems instead of building another telephony/WebRTC/orchestration framework.
- Its narrower contribution is causal Articulation IR, constrained hardware compilation, shared physical timing, and end-device audio-motion measurement.

## ElevenLabs

The optional provider uses the official [HTTP streaming-with-timestamps endpoint](https://elevenlabs.io/docs/api-reference/text-to-speech/stream-with-timestamps). ElevenLabs recommends streaming for low time-to-first-audio and distinguishes model inference latency from physical playback latency in its [latency guide](https://elevenlabs.io/docs/eleven-api/concepts/latency). ElevenLabs remains a service dependency governed by its own terms. It is an adapter, not the project identity. The core demo and tests require no account and make no paid calls.

## Claim policy

Do not claim:

- first real-time lip sync;
- first phoneme/viseme mapping;
- first coarticulation model;
- first learned silicone robot mouth;
- guaranteed sub-two-second speech;
- biologically exact muscle simulation;
- elimination of the uncanny valley.

Claims should name the exact configuration, metric, dataset, comparator, and confidence/limitations.
