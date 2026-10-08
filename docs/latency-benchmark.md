# Physical response latency benchmark

The project optimizes **end of user speech → first audible physical sample**, while checking that visible mouth motion starts on the same clock and that audio remains clean.

## Why TTFB is insufficient

TTS time-to-first-byte excludes turn detection, LLM delay, phrase formation, player buffering, host scheduling, USB/serial transport, MCU buffering, and the loudspeaker path. A low TTFB can still produce a slow or broken robot.

LiveKit exposes useful end-of-utterance, LLM TTFT, and TTS TTFB metrics. Picovoice defines Voice Assistant Response Time as LLM TTFT plus first-token-to-speech. Robot LipSync keeps compatible stage concepts but extends observation to the physical device and first visible motion:

- [LiveKit observability and latency metrics](https://docs.livekit.io/deploy/observability/data/)
- [Picovoice text-to-speech benchmark](https://github.com/Picovoice/text-to-speech-benchmark)
- [ElevenLabs latency concepts](https://elevenlabs.io/docs/eleven-api/concepts/latency)

## Standard marks

| Mark | Definition |
| --- | --- |
| `end_of_user_speech` | last detected user speech sample |
| `turn_committed` | system accepts the turn as complete |
| `llm_first_token` | first usable model output token |
| `phrase_committed` | first text span safe enough for TTS |
| `tts_request_start` | provider request begins |
| `tts_response_headers` | streaming response is accepted |
| `tts_first_audio` | first decodable PCM/audio bytes arrive |
| `device_first_audio_chunk` | first chunk enters the physical device |
| `physical_audio_start` | device begins its playback sample clock |
| `first_visible_motion` | mouth backend begins the matching event |

`origin` should equal the monotonic timestamp of `end_of_user_speech` when that signal is trustworthy.

## Quality counters

At minimum, record:

- underrun count;
- maximum audio feed gap;
- dropped or late motion events;
- queue saturation;
- interrupted/cancelled turn state;
- user speech truncation rate;
- first-phrase grammatical/prosodic failure;
- provider errors and fallback path.

Latency purchased by making speech crackle is a failed optimization.

## Reporting protocol

1. Pin provider, model, voice, region, hardware, sample rate, buffer sizes, and code commit.
2. Separate cold start, first request after prewarm, and steady-state runs.
3. Use fixed prompts spanning short, long, punctuated, and unpunctuated output.
4. Report at least 100 turns before making a public distribution claim.
5. Publish P50, P95, P99, min, max, failures, and the raw JSONL.
6. Report both physical audio start and visible-motion offset.
7. Keep provider cost and voice-quality settings in the result metadata.

The executable harness, fixed English v1 suite, adapter protocol, checkpoint/resume behavior, and simulated CI adapter are documented in [`benchmarks/README.md`](../benchmarks/README.md). The simulated adapter validates the tool only; it is not a latency result.

## Reference result versus guarantee

The original Lilyput integration observed endpoint samples of 1.969, 1.966, 2.588, 2.247, 4.573, 1.908, 1.992, and 2.674 seconds during one real conversation run. This is a useful engineering record, not a controlled public benchmark: prompts differed, network conditions were not held constant, and the sample is small.

The correct current wording is:

> Near-two-second physical response on a reference prototype, with visible long-tail latency and no universal SLA.

## Stronger physical verification

Firmware timestamps prove when I2S starts, not when acoustic energy reaches the listener. A rigorous future fixture should record a line-out/microphone threshold and a display photodiode or camera trigger on the same acquisition clock. That creates a true end-of-turn → acoustic onset → visible onset measurement.

## Fault injection

The benchmark roadmap includes deterministic delay and loss injection at:

- LLM token delivery;
- phrase-release boundary;
- TTS response headers and audio chunks;
- host-to-device writes;
- renderer queue and acknowledgement;
- device feed gaps.

This distinguishes a robust real-time system from one that is fast only on a perfect network.
