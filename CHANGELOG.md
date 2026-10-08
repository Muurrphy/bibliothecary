# Changelog

## 0.2.1 — 2026-10-08

Smoothness fixes from the filming sessions (Kindle stopped moving, questions not heard, slow or
odd replies to simple commands):

- Kindle page: every request has a time limit, a drawing error triggers a full redraw, and a
  watchdog restarts the update loop, so the e-reader can no longer freeze after a Wi-Fi blink or
  sleep. Saying "刷新" redraws every screen.
- Speaker page: the device tapped last becomes the one that listens and speaks, so reopening the
  home-screen app no longer leaves it silent and deaf. The microphone is reopened after the
  screen was locked; audio interrupted by a call or Siri resumes by itself when it can.
- A line that fails to play is tried once more and then skipped; the reading only pauses when no
  speaker page is there at all (a reloading page gets 12 seconds to come back).
- Missing character timestamps no longer stop a line: the mouth uses an estimate for it.
- No fixed 0.7 s wait before every line on a single speaker.
- Spoken commands ("继续", "等一下", "从头讲", also in traditional characters) are carried out at
  once on the realtime path instead of waiting for a model answer.
- A realtime answer that has not started within 6 s is asked again through speech-to-text and
  the text model, and the stale connection is replaced. The apology line follows the lesson's
  language.

## 0.2.0 — 2026-10-08

- Consolidated the Kindle reading companion and multilingual mouth into Margin.
- Included both Python namespaces, CLI commands, language dependencies, screen renderers, fixtures, schemas and optional OLED tools in one distribution.
- Included the current reader reliability and explicit voice-profile changes already developed locally: cached speech, bounded waits, playback-error pause, ordered microphone uploads, primary-device handling and audio-clock mouth timing.
- Added original bumblebee-play and neutrino lesson examples.
- Added English and Chinese project descriptions, setup, data handling, known issues, contribution guidance and unified offline CI.
- Documented intermittent real phone capture. No new mobile-listening fix is part of the consolidation.

## Earlier mouth-module history

The original mouth project is retained at https://github.com/Muurrphy/robot-lipsync. Its MIT source was imported from commit `8b90e617de9af3bc5d8c33d94d40e19735abe951`; see [migration](docs/migration.md).
