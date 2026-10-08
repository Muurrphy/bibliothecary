# Background references and adapters

These links provide background on speech animation and voice interaction, along with possible adapters. Check each upstream license before reusing code, models or data.

## Lip sync and speech animation

- [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync): offline audio-file analysis and 6–9 discrete cartoon mouth cues. Excellent future offline provider; not designed as a causal physical-control runtime.
- [JALI](https://www.dgp.toronto.edu/~karan/jali/): speech animation, coarticulation, prosody, and animator control.
- [NVIDIA Audio2Face 3D SDK](https://github.com/NVIDIA/Audio2Face-3D-SDK): high-performance GPU facial animation. It can become a teacher or high-dimensional baseline, not an MCU backend.
- [Columbia Robot Lip Sync](https://www.creativemachineslab.com/lipsync.html): self-supervised learning on a dedicated 10-DoF silicone robot face with published data/code links. This establishes that learned physical lips and motor babbling are existing research.
- [Phoneme-to-Lip-14DOF](https://github.com/yuesheng21/Phoneme-to-Lip-14DOF): Chinese dynamic visemes and a 14-DoF robot data release. License must be confirmed before copying or redistribution.
- [Mandarin dynamic-viseme paper](https://arxiv.org/abs/2604.01756): initial/final decomposition, Chinese visible categories, dynamic trajectories, and robot coarticulation. Robot LipSync references the published method but does not redistribute its trajectories.
- [Spanish G2P rules](https://aclanthology.org/W98-0804/) and [Mexican-Spanish constraint-based visual speech](https://doi.org/10.1155/2008/412056): research references for the Spanish front end and coarticulation boundary.

## Voice-agent orchestration

- [Pipecat](https://github.com/pipecat-ai/pipecat), [LiveKit Agents](https://github.com/livekit/agents), and [TEN Framework](https://github.com/ten-framework/ten-framework) already provide broad real-time voice-agent pipelines.
- Robot LipSync should integrate with these ecosystems instead of building another telephony/WebRTC/orchestration framework.
- Its narrower contribution is causal Articulation IR, constrained hardware compilation, shared physical timing, and end-device audio-motion measurement.

## ElevenLabs

The optional provider uses the official [HTTP streaming-with-timestamps endpoint](https://elevenlabs.io/docs/api-reference/text-to-speech/stream-with-timestamps). Its [latency guide](https://elevenlabs.io/docs/eleven-api/concepts/latency) describes service timing. The offline mouth preview and tests use local fixtures.
