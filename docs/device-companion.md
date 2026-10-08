# Device companion architecture

The project has two Python namespaces in one distribution:

- `margin`: lesson files, reader page, player, speech, question handling and the local server.
- `robot_lipsync`: speech alignment to mouth events, language rules, screen/OLED rendering and reusable tools.

The computer loads a lesson with article paragraphs and steps. A step can focus a sentence, mark words, add a note or figure, speak text, or emit an optional cue. The Kindle receives lightweight page changes over long polling; no microphone or jailbreak is needed on the e-reader.

For the ElevenLabs browser path, generated audio and timing become a clip. The phone fetches the clip and mouth events, plays audio with Web Audio and draws events against the audio clock. Its own microphone feeds a question through the computer to a realtime model, or through separate transcription and chat. The model returns validated lesson steps. Extra muted screens can follow the same clip.

Character timestamps are provided by the speech service when supported. Intra-character phoneme timing and language rules remain an approximation. The lower-level mouth module can still be used independently; see [its architecture](architecture.md).

The public source includes the current cache, timeout, playback-error, ordered-upload and device-owner handling already developed for this prototype. The consolidation changes packaging and documentation, not the listening algorithm. [Known issues](known-issues.md) record the real mobile failures that remain.

`cue` events can be consumed by another program. `examples/cue_opener.py` opens a configured page; no personal robot trajectory or head-control program is included.
