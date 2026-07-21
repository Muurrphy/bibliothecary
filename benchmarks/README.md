# Controlled 100-turn benchmark

The default suite contains 20 fixed English cases repeated five times. It covers short and long replies, punctuation and timeout phrase release, normalization, prosody, and visible-speech landmarks.

## Measurement scopes must not be mixed

1. `transcript_commit_to_physical_output`: inject finalized user text at time zero. This isolates response generation, TTS, transport, speaker start, and mouth start.
2. `acoustic_eou_to_physical_output`: replay a fixed user WAV through the input path and start at detected acoustic end-of-utterance.
3. `external_sensor_physical_output`: additionally measure speaker energy and display light with a microphone/photodiode on one acquisition clock.

The included suite declares scope 1. Do not rename it as a full acoustic benchmark.

## Adapter protocol

The runner keeps one adapter process alive for the whole experiment, preserving provider connections and real steady-state behavior. Stdin and stdout are strict JSONL; diagnostic logs belong on stderr.

```json
{"type":"hello","protocol":1,"suite_id":"robot-lipsync-english-v1","run_id":"..."}
{"type":"ready","protocol":1,"adapter":"my-agent"}
{"type":"trial","trial_id":"short-greeting-r01","case_id":"short-greeting","user_text":"...","tags":["short"],"warmup":false}
{"type":"trace","trial_id":"short-greeting-r01","trace":{"schema":"robot-lipsync/latency-trace/v1","session_id":"...","milliseconds":{},"counters":{},"metadata":{}}}
```

The adapter owns the live voice stack and must mark real events. In particular, `physical_audio_start` must come from the playback device, not HTTP arrival. The reference OLED firmware supplies `LIP/EVENT VISIBLE_START` for `first_visible_motion`.

## Prove the runner without making a performance claim

```bash
robot-lipsync benchmark-run \
  --adapter-command "python benchmarks/stub_agent.py" \
  --output build/stub-100.jsonl

robot-lipsync benchmark-report build/stub-100.jsonl
```

The stub is deterministic and every record is labeled `simulated=true`. Its numbers only test scheduling, checkpointing, schemas, and reports; they are forbidden as README performance evidence.

## Run a real adapter

```bash
robot-lipsync benchmark-run \
  --adapter-command "python path/to/my_live_agent_adapter.py" \
  --output results/my-hardware-commit.jsonl \
  --warmups 3 --repeats 5 --timeout 45
```

The runner flushes every trace immediately and supports `--resume`. Publish the suite, raw JSONL, report, commit SHA, provider/model/voice, region, hardware, buffers, failures, and unedited video of representative trials.
